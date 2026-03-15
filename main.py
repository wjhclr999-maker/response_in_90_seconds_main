import os
import json
import time
import argparse
from pathlib import Path

import requests

from src.config import TARGET_LIMIT_SECONDS
from src.auto_profile.profile_generator import generate_profile_from_template
from src.engine.document_reader import collect_all_text
from src.engine.prompt_builder import build_prompt
from src.engine.retrieval_client import (
    preprocess_retrieved_chunks,
    format_retrieved_chunks,
    attach_field_evidence,
)
from src.engine.model_client import call_ollama
from src.engine.postprocess import (
    process_by_profile,
    validate_required_fields,
    retry_missing_required_fields,
    fallback_extract_company_name,
    fallback_extract_project_title,
    build_debug_result,
    build_run_summary,
)
from src.engine.writers import (
    fill_excel_vertical,
    fill_excel_table,
    fill_word_table,
)


def load_rag_json(rag_json_path: str) -> dict:
    with open(rag_json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_retrieved_chunks_from_rag_json(rag_data: dict) -> list[dict]:
    """
    兼容几种可能的 RAG 中间格式：
    1. {"retrieved_chunks": [...]}
    2. {"result": {"retrieved_chunks": [...]}}
    3. {"result": {"records": [...]}}   # 这种更像已结构化结果，不是片段
    """
    if not isinstance(rag_data, dict):
        return []

    if isinstance(rag_data.get("retrieved_chunks"), list):
        return rag_data["retrieved_chunks"]

    result = rag_data.get("result", {})
    if isinstance(result, dict) and isinstance(result.get("retrieved_chunks"), list):
        return result["retrieved_chunks"]

    return []


def extract_structured_result_from_rag_json(rag_data: dict):
    """
    如果上游已经给了结构化结果，就直接拿来走你这边后处理和填表。
    例如：
    {"result": {"records": [...]}}
    或
    {"result": {...}}
    """
    if not isinstance(rag_data, dict):
        return None

    result = rag_data.get("result")
    if isinstance(result, dict):
        return result

    return None


def main():
    try:
        parser = argparse.ArgumentParser()

        # 新入口：模板驱动，自动生成 profile
        parser.add_argument("--template", required=True, help="模板路径，例如 data/template/template.xlsx")
        parser.add_argument("--profile-output", default="", help="自动生成的 profile 保存路径，例如 profiles/template_auto.json")
        parser.add_argument("--use-profile-llm", action="store_true", help="生成 profile 时是否启用本地模型增强")

        # 原文输入
        parser.add_argument("--input-dir", default="data/in", help="原始文档目录")

        # 可选：RAG 中间结果
        parser.add_argument("--rag-json", default="", help="RAG 中间 JSON 路径")
        parser.add_argument("--prefer-rag-structured", action="store_true", help="若 RAG JSON 已含结构化结果，优先直接使用")

        # 输出目录
        parser.add_argument("--output-dir", default="output")

        args = parser.parse_args()

        template_path = args.template
        input_dir = args.input_dir
        output_dir = args.output_dir
        rag_json_path = args.rag_json

        if not os.path.exists(template_path):
            raise FileNotFoundError(f"找不到模板文件：{template_path}")

        os.makedirs(output_dir, exist_ok=True)

        # 自动生成 profile 并保存
        if args.profile_output.strip():
            profile_path = args.profile_output
        else:
            stem = Path(template_path).stem
            profile_path = f"profiles/{stem}_auto.json"

        output_json = os.path.join(output_dir, "result.json")
        output_xlsx = os.path.join(output_dir, "result.xlsx")
        output_docx = os.path.join(output_dir, "result.docx")
        output_report_bundle_json = os.path.join(output_dir, "report_bundle.json")

        runtime = {}
        total_start = time.perf_counter()

        # 1. 自动生成 profile
        step_start = time.perf_counter()
        profile = generate_profile_from_template(
            template_path=template_path,
            use_llm=args.use_profile_llm
        )

        os.makedirs(os.path.dirname(profile_path), exist_ok=True)
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)

        runtime["generate_profile_seconds"] = round(time.perf_counter() - step_start, 3)

        print("=== 自动生成的 profile ===")
        print(json.dumps(profile, ensure_ascii=False, indent=2))
        print(f"\n已保存 profile：{profile_path}")

        # 2. 读取原始文档（如果有）
        step_start = time.perf_counter()
        all_text = ""

        if os.path.exists(input_dir):
            all_text = collect_all_text(input_dir)

        runtime["read_documents_seconds"] = round(time.perf_counter() - step_start, 3)

        if all_text.strip():
            print("\n=== 已读取文档内容（前800字符）===")
            print(all_text[:800], "\n")
        else:
            print("[INFO] 当前未读取到原始文档内容。若本次依赖 RAG JSON，可继续执行。")

        # 3. 读取 RAG JSON（如果有）
        step_start = time.perf_counter()
        rag_data = {}
        retrieved_chunks = []
        structured_rag_result = None

        if rag_json_path.strip():
            if not os.path.exists(rag_json_path):
                raise FileNotFoundError(f"找不到 RAG JSON 文件：{rag_json_path}")

            rag_data = load_rag_json(rag_json_path)
            retrieved_chunks = extract_retrieved_chunks_from_rag_json(rag_data)
            structured_rag_result = extract_structured_result_from_rag_json(rag_data)

            retrieved_chunks = preprocess_retrieved_chunks(retrieved_chunks)

        runtime["load_rag_json_seconds"] = round(time.perf_counter() - step_start, 3)

        # 4. 决定本次抽取输入来源
        extracted_raw = None
        context_for_llm = ""

        # 4A. 如果 RAG 已经给了结构化结果，并且你选择优先用它
        if args.prefer_rag_structured and structured_rag_result:
            print("[INFO] 检测到 RAG 已提供结构化结果，优先直接使用。")
            extracted_raw = structured_rag_result

        else:
            # 4B. 否则优先用 RAG 片段；没有就回退全文
            retrieved_context = format_retrieved_chunks(retrieved_chunks, top_k=20) if retrieved_chunks else ""

            if retrieved_context.strip():
                context_for_llm = retrieved_context
                print("\n=== 已启用 RAG 片段优先模式（前800字符）===")
                print(context_for_llm[:800], "\n")
            else:
                context_for_llm = all_text
                if rag_json_path.strip():
                    print("[WARN] RAG JSON 中未拿到有效片段，自动退回全文抽取模式。")

            if not context_for_llm.strip():
                raise ValueError("既没有有效原文，也没有可用的 RAG 片段，无法继续抽取。")

            # 5. 构造 prompt
            step_start = time.perf_counter()
            prompt = build_prompt(context_for_llm, profile)
            runtime["build_prompt_seconds"] = round(time.perf_counter() - step_start, 3)

            # 6. 模型推理
            print("=== 开始模型推理 ===")
            step_start = time.perf_counter()
            extracted_raw = call_ollama(prompt)
            runtime["model_inference_seconds"] = round(time.perf_counter() - step_start, 3)

            print("=== 模型原始抽取结果 ===")
            print(json.dumps(extracted_raw, ensure_ascii=False, indent=2))

            # 6.1 缺字段检查 + 二次补抽（仅单条任务更有意义，表格任务先保留兼容）
            temp_final_data = process_by_profile(extracted_raw, profile)
            missing_before_retry = validate_required_fields(temp_final_data, profile)

            retried_fields = []
            runtime["retry_inference_seconds"] = 0.0

            if missing_before_retry:
                print(f"[WARN] 首次抽取后关键字段缺失：{missing_before_retry}")

                retry_start = time.perf_counter()
                retry_text = context_for_llm if context_for_llm.strip() else all_text

                extracted_raw, retried_fields = retry_missing_required_fields(
                    retry_text, profile, extracted_raw, missing_before_retry
                )

                runtime["retry_inference_seconds"] = round(time.perf_counter() - retry_start, 3)

                if retried_fields:
                    print(f"[INFO] 已触发二次提取并补回字段：{retried_fields}")
                    print("=== 二次提取后的模型原始结果 ===")
                    print(json.dumps(extracted_raw, ensure_ascii=False, indent=2))
                else:
                    print("[WARN] 已执行二次提取，但没有补回任何字段")

            # 单条合同类兜底
            if profile.get("task_mode") == "single_record":
                if not str(extracted_raw.get("甲方单位", "")).strip():
                    cand = fallback_extract_company_name(all_text)
                    if cand:
                        extracted_raw["甲方单位"] = cand
                        print(f"[INFO] 规则兜底补回甲方单位：{cand}")

                if not str(extracted_raw.get("项目名称", "")).strip():
                    cand = fallback_extract_project_title(all_text)
                    if cand:
                        extracted_raw["项目名称"] = cand
                        print(f"[INFO] 规则兜底补回项目名称：{cand}")

            runtime["model_inference_total_seconds"] = round(
                runtime.get("model_inference_seconds", 0.0) + runtime.get("retry_inference_seconds", 0.0), 3
            )

        # 7. 规则处理
        step_start = time.perf_counter()
        final_data = process_by_profile(extracted_raw, profile)
        missing_required_fields = validate_required_fields(final_data, profile)
        runtime["rule_processing_seconds"] = round(time.perf_counter() - step_start, 3)

        if missing_required_fields:
            print(f"[WARN] 最终结果仍缺失关键字段：{missing_required_fields}")

        print("\n=== 按规则格式化后的结果 ===")
        print(json.dumps(final_data, ensure_ascii=False, indent=2))

        debug_result = build_debug_result(extracted_raw, profile)
        field_evidence = attach_field_evidence(extracted_raw, retrieved_chunks) if retrieved_chunks else {}

        retrieval_info = {
            "rag_json_provided": bool(rag_json_path.strip()),
            "rag_json_path": rag_json_path,
            "chunks_count": len(retrieved_chunks),
            "chunks_preview": retrieved_chunks[:3] if retrieved_chunks else [],
            "used_structured_rag_result": bool(args.prefer_rag_structured and structured_rag_result),
        }

        # 8. 写正式结果 JSON
        step_start = time.perf_counter()
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(final_data, f, ensure_ascii=False, indent=2)
        runtime["write_json_seconds"] = round(time.perf_counter() - step_start, 3)

        # 9. 写模板文件
        step_start = time.perf_counter()
        template_mode = profile.get("template_mode", "vertical")

        if template_mode == "vertical":
            fill_excel_vertical(template_path, output_xlsx, final_data)

        elif template_mode == "excel_table":
            fill_excel_table(
                template_path=template_path,
                output_path=output_xlsx,
                records=final_data,
                header_row=profile.get("header_row", 1),
                start_row=profile.get("start_row", 2),
            )

        elif template_mode == "word_table":
            fill_word_table(
                template_path=template_path,
                output_path=output_docx,
                records=final_data,
                table_index=profile.get("table_index", 0),
                header_row=profile.get("header_row", 0),
                start_row=profile.get("start_row", 1),
            )

        else:
            raise NotImplementedError(f"暂不支持的 template_mode: {template_mode}")

        runtime["write_template_seconds"] = round(time.perf_counter() - step_start, 3)

        # 10. 总耗时
        total_seconds = round(time.perf_counter() - total_start, 3)
        runtime["total_seconds"] = total_seconds
        runtime["within_90_seconds"] = total_seconds <= TARGET_LIMIT_SECONDS

        # 11. 汇总信息
        run_summary = build_run_summary(
            profile=profile,
            runtime=runtime,
            missing_fields=missing_required_fields,
            retried_fields=[],
            input_text=all_text
        )

        report_bundle = {
            "meta": {
                "report_type": "integrated_output_bundle",
                "profile_path": profile_path,
                "profile_name": profile.get("report_name", ""),
                "template_path": profile.get("template_path", ""),
                "task_mode": profile.get("task_mode", "single_record"),
                "template_mode": template_mode,
                "input_char_count": len(all_text),
                "generated_outputs": {
                    "result_json": output_json,
                    "result_xlsx": output_xlsx if template_mode in ["vertical", "excel_table"] else "",
                    "result_docx": output_docx if template_mode == "word_table" else ""
                }
            },
            "run_summary": run_summary,
            "runtime_metrics": runtime,
            "debug_result": debug_result,
            "retrieval": retrieval_info,
            "field_evidence": field_evidence
        }

        with open(output_report_bundle_json, "w", encoding="utf-8") as f:
            json.dump(report_bundle, f, ensure_ascii=False, indent=2)

        # 12. 打印汇总
        print("\n=== 运行耗时统计 ===")
        for k, v in runtime.items():
            print(f"{k}: {v}")

        print(f"\n已生成：{output_json}")
        if template_mode in ["vertical", "excel_table"]:
            print(f"已生成：{output_xlsx}")
        if template_mode == "word_table":
            print(f"已生成：{output_docx}")
        print(f"已生成：{output_report_bundle_json}")

        if runtime["within_90_seconds"]:
            print(f"✅ 总耗时在 {TARGET_LIMIT_SECONDS} 秒以内")
        else:
            print(f"⚠️ 总耗时超过 {TARGET_LIMIT_SECONDS} 秒，需要继续优化")

    except FileNotFoundError as e:
        print(f"[ERROR][file_error] {e}")
        raise
    except requests.RequestException as e:
        print(f"[ERROR][model_error] 调用 Ollama 失败：{e}")
        raise
    except json.JSONDecodeError as e:
        print(f"[ERROR][json_error] JSON 解析失败：{e}")
        raise
    except ValueError as e:
        print(f"[ERROR][value_error] {e}")
        raise
    except Exception as e:
        print(f"[ERROR][unknown_error] {e}")
        raise


if __name__ == "__main__":
    main()
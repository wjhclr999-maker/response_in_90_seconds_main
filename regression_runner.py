import os
import json
import csv
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# 新主脚本入口
AI_RUNNER = PROJECT_ROOT / "main.py"
PROFILE_PATH = PROJECT_ROOT / "profiles/company_a_amount_report.json"

# 测试集目录
TEST_DIRS = [
    PROJECT_ROOT / "data/test_cases/basic",
    PROJECT_ROOT / "data/test_cases/variants",
]

# 标准答案文件
EXPECTED_PATH = PROJECT_ROOT / "data/test_cases/expected_results.json"

# 回归输出目录
REG_OUT_DIR = PROJECT_ROOT / "output/regression"
REG_OUT_DIR.mkdir(parents=True, exist_ok=True)

# 使用当前环境 python
PYTHON = sys.executable


def load_expected() -> dict:
    if not EXPECTED_PATH.exists():
        raise FileNotFoundError(f"缺少标准答案文件：{EXPECTED_PATH}")
    return json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


def list_test_files() -> list[Path]:
    files: list[Path] = []
    for d in TEST_DIRS:
        if d.exists():
            for p in sorted(d.iterdir()):
                if p.is_file() and p.suffix.lower() in [".txt", ".md", ".docx"]:
                    files.append(p)
    return files


def score_case(pred: dict, gold: dict):
    """逐字段精确匹配（最简单、最直观）"""
    total = len(gold)
    correct = 0
    wrong_fields = []

    for k, v in gold.items():
        pv = pred.get(k, "")

        pv_s = str(pv).strip()
        v_s = str(v).strip()

        if k == "需求说明":
            for prefix in ["支持", "希望", "需要", "可", "能够", "建议"]:
                if pv_s.startswith(prefix):
                    pv_s = pv_s[len(prefix):].strip()
                if v_s.startswith(prefix):
                    v_s = v_s[len(prefix):].strip()
            if pv_s in v_s or v_s in pv_s:
                correct += 1
                continue

        if pv_s == v_s:
            correct += 1
        else:
            wrong_fields.append({
                "field": k,
                "pred": pv,
                "gold": v
            })

    acc = correct / total if total else 1.0
    return acc, correct, total, wrong_fields


def run_one_case(case_file: Path) -> dict:
    case_name = case_file.name

    # 每个 case 一个独立输出目录
    case_out = REG_OUT_DIR / case_name.replace(".", "_")
    if case_out.exists():
        shutil.rmtree(case_out)
    case_out.mkdir(parents=True, exist_ok=True)

    # 每个 case 单独 input_dir，避免读到其他文件
    case_in = case_out / "in"
    case_in.mkdir(parents=True, exist_ok=True)
    shutil.copy2(case_file, case_in / case_file.name)

    cmd = [
        PYTHON, "-u", str(AI_RUNNER),
        "--profile", str(PROFILE_PATH),
        "--input-dir", str(case_in),
        "--output-dir", str(case_out),
    ]

    p = subprocess.run(cmd, capture_output=True, text=True)

    # 保存 stdout / stderr
    (case_out / "stdout.txt").write_text(p.stdout, encoding="utf-8")
    (case_out / "stderr.txt").write_text(p.stderr, encoding="utf-8")

    result_path = case_out / "result.json"
    report_bundle_path = case_out / "report_bundle.json"

    result = {}
    report_bundle = {}
    runtime = {}
    run_summary = {}

    if result_path.exists():
        result = json.loads(result_path.read_text(encoding="utf-8"))

    if report_bundle_path.exists():
        report_bundle = json.loads(report_bundle_path.read_text(encoding="utf-8"))
        runtime = report_bundle.get("runtime_metrics", {})
        run_summary = report_bundle.get("run_summary", {})

    return {
        "case": case_name,
        "returncode": p.returncode,
        "success": p.returncode == 0,
        "result": result,
        "report_bundle": report_bundle,
        "runtime": runtime,
        "run_summary": run_summary,
        "out_dir": str(case_out),
    }


def main():
    expected = load_expected()
    files = list_test_files()

    if not files:
        print("[ERROR] 没找到测试文件。请检查 data/test_cases/basic 和 variants。")
        return

    records = []
    csv_rows = []

    for f in files:
        print(f"\n[RUN] {f.name}")
        run_info = run_one_case(f)

        gold = expected.get(f.name)
        if gold is None:
            acc, correct, total, wrong = 0.0, 0, 0, [
                {"field": "*", "pred": "", "gold": "缺少该样本标准答案"}
            ]
        else:
            acc, correct, total, wrong = score_case(run_info["result"], gold)

        runtime = run_info.get("runtime", {})
        total_seconds = runtime.get("total_seconds", None)
        within_90 = runtime.get("within_90_seconds", None)
        model_total = runtime.get(
            "model_inference_total_seconds",
            runtime.get("model_inference_seconds", None)
        )

        record = {
            "case": f.name,
            "success": run_info["success"],
            "returncode": run_info["returncode"],
            "accuracy": acc,
            "correct_fields": correct,
            "total_fields": total,
            "wrong_fields": wrong,
            "total_seconds": total_seconds,
            "within_90_seconds": within_90,
            "model_inference_total_seconds": model_total,
            "out_dir": run_info["out_dir"],
            "bundle_available": bool(run_info["report_bundle"]),
        }
        records.append(record)

        csv_rows.append({
            "case": f.name,
            "success": run_info["success"],
            "accuracy": round(acc, 4),
            "correct_fields": correct,
            "total_fields": total,
            "total_seconds": total_seconds,
            "within_90_seconds": within_90,
            "model_inference_total_seconds": model_total,
            "bundle_available": bool(run_info["report_bundle"]),
            "out_dir": run_info["out_dir"],
        })

        print(f"[DONE] acc={acc:.2%}, seconds={total_seconds}, within_90={within_90}")

    # 输出总报告
    report_json = REG_OUT_DIR / "report.json"
    report_csv = REG_OUT_DIR / "report.csv"

    report_json.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    with open(report_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
        writer.writeheader()
        writer.writerows(csv_rows)

    print("\n=== 回归测试完成 ===")
    print(f"JSON 报告：{report_json}")
    print(f"CSV 报告：{report_csv}")


if __name__ == "__main__":
    main()
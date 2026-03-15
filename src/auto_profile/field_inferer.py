import json
import re
import requests

from src.config import OLLAMA_URL, MODEL_NAME


def guess_field_type_rule(field_name: str) -> str:
    name = str(field_name).strip()

    if any(k in name for k in ["电话", "手机号", "联系电话", "联系方式"]):
        return "phone"

    if any(k in name for k in ["日期", "时间", "签订日", "签署日", "监测时间"]):
        return "date"

    if any(k in name for k in ["金额", "费用", "价款", "合计", "总价", "单价", "金额（元）", "金额(元)"]):
        return "money"

    return "text"


def guess_output_format_rule(field_name: str, field_type: str) -> str:
    if field_type == "date":
        return "YYYY年M月D日"
    if field_type == "money":
        return "plain_number"
    return "plain"


def guess_required_rule(field_name: str) -> bool:
    name = str(field_name).strip()

    required_keywords = [
        "项目名称", "甲方单位", "乙方单位", "合同金额", "金额", "签订日期",
        "城市", "区", "站点名称", "空气质量指数"
    ]
    return any(k in name for k in required_keywords)


def call_local_llm_json(prompt: str) -> dict:
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1
        }
    }

    resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
    resp.raise_for_status()
    text = resp.json().get("response", "").strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError(f"本地模型没有返回合法 JSON：{text}")

    return json.loads(match.group(0))


def infer_fields(field_names: list[str], task_mode: str, template_mode: str, use_llm: bool = False) -> list[dict]:
    if use_llm:
        try:
            prompt = f"""
你是一个字段语义理解助手。请根据字段名判断 type / output_format / required。
你必须只输出 JSON，不要输出解释。

字段名列表：
{json.dumps(field_names, ensure_ascii=False)}

任务模式：
- task_mode: {task_mode}
- template_mode: {template_mode}

可选 type:
- text
- phone
- date
- money

输出格式：
{{
  "fields": [
    {{
      "name": "项目名称",
      "type": "text",
      "output_format": "plain",
      "required": true
    }}
  ]
}}
"""
            result = call_local_llm_json(prompt)
            llm_fields = result.get("fields", [])

            if isinstance(llm_fields, list) and llm_fields:
                llm_map = {
                    str(item.get("name", "")).strip(): item
                    for item in llm_fields if isinstance(item, dict)
                }

                normalized = []
                for name in field_names:
                    item = llm_map.get(name, {})
                    field_type = item.get("type") or guess_field_type_rule(name)
                    output_format = item.get("output_format") or guess_output_format_rule(name, field_type)
                    required = item.get("required")
                    if required is None:
                        required = guess_required_rule(name)

                    normalized.append({
                        "name": name,
                        "type": field_type,
                        "output_format": output_format,
                        "required": bool(required)
                    })

                return normalized

        except Exception as e:
            print(f"[WARN] 本地模型字段推断失败，退回规则模式：{e}")

    fields = []
    for name in field_names:
        field_type = guess_field_type_rule(name)
        output_format = guess_output_format_rule(name, field_type)
        required = guess_required_rule(name)

        fields.append({
            "name": name,
            "type": field_type,
            "output_format": output_format,
            "required": required
        })

    return fields
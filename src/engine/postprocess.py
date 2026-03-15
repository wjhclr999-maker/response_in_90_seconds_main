import json
import re
from decimal import Decimal, ROUND_HALF_UP

from src.engine.prompt_builder import build_missing_fields_prompt
from src.engine.model_client import call_ollama


# =========================
# 5. 内部标准化
# =========================
def normalize_text(value: str) -> str:
    if value is None:
        return ""
    return str(value).strip()


def clean_org_name(value: str) -> str:
    """
    从一句话里提取组织名称（公司/单位）
    关键：优先提取“和/与/跟/由/是”等连接词后面的组织名，避免把“我们和...”一起带进去
    """
    if value is None:
        return ""
    s = str(value).strip()

    # 1) 先用“连接词后面的组织名”模式（最有效）
    connector_patterns = [
        r'(?:我们|咱们|本次|这次|这回|今天|刚刚|刚才|后来)?(?:是|和|与|跟|同|由)\s*([^\s，。、“”"（）()]{2,60}?(?:有限公司|集团|研究院|中心|学院|大学))'
    ]
    for pat in connector_patterns:
        m = re.search(pat, s)
        if m:
            return m.group(1).strip()

    # 2) 再做兜底：从句子中找“最像公司名的后缀实体”，取“最后一个”更稳
    suffix = r'(?:信息技术有限公司|科技有限公司|数据服务有限公司|智能设备有限公司|网络科技有限公司|软件有限公司|有限公司|集团|研究院|中心|学院|大学)'
    m_all = re.findall(r'([^\s，。、“”"（）()]{2,60}?%s)' % suffix, s)
    if m_all:
        return m_all[-1].strip()

    return s


def normalize_phone(value: str) -> str:
    if value is None:
        return ""
    return re.sub(r"\D", "", str(value))


def normalize_date(value: str) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    s = s.replace("年", "-").replace("月", "-").replace("日", "").replace("号", "")
    s = s.replace("/", "-")
    s = re.sub(r"\s+", "", s)

    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"

    return s


def normalize_money(value: str) -> str:
    if value is None:
        return ""
    s = str(value).replace(",", "").strip()
    m = re.search(r"\d+(?:\.\d+)?", s)
    return m.group(0) if m else ""


def normalize_internal(value: str, field_type: str) -> str:
    field_type = (field_type or "text").lower()

    if field_type == "phone":
        return normalize_phone(value)
    elif field_type == "date":
        return normalize_date(value)
    elif field_type == "money":
        return normalize_money(value)
    else:
        return normalize_text(value)


def fallback_extract_company_name(text: str) -> str:
    patterns = [
        r'([^\s，。、“”"（）()]{2,40}?信息技术有限公司)',
        r'([^\s，。、“”"（）()]{2,40}?科技有限公司)',
        r'([^\s，。、“”"（）()]{2,40}?数据服务有限公司)',
        r'([^\s，。、“”"（）()]{2,40}?智能设备有限公司)',
        r'([^\s，。、“”"（）()]{2,40}?网络科技有限公司)',
        r'([^\s，。、“”"（）()]{2,40}?软件有限公司)',
        r'([^\s，。、“”"（）()]{2,40}?有限公司)',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip()
    return ""


def fallback_extract_project_title(text: str) -> str:
    # 1) 优先引号内容
    m = re.search(r'“([^”]{2,50})”', text)
    if m:
        return m.group(1).strip()

    # 2) “谈成的是XXX这个项目 / 签的是XXX项目”
    patterns = [
        r'谈成的是([^，。]{2,50})这个项目',
        r'签的是([^，。]{2,50})这个项目',
        r'对应的(?:是)?([^，。]{2,50})项目',
        r'做的(?:是)?([^，。]{2,50})项目',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip().strip('“”"')
    return ""


# =========================
# 6. 输出格式化
# =========================
CN_NUM = "零壹贰叁肆伍陆柒捌玖"
CN_UNIT_INT = ["", "拾", "佰", "仟"]
CN_SECTION = ["", "万", "亿", "兆"]


def four_digit_to_cn(num: int) -> str:
    result = ""
    zero_flag = False
    digits = [int(x) for x in f"{num:04d}"]

    for i, d in enumerate(digits):
        pos = 3 - i
        if d == 0:
            zero_flag = True
        else:
            if zero_flag and result:
                result += "零"
            result += CN_NUM[d] + CN_UNIT_INT[pos]
            zero_flag = False

    return result


def int_to_cny_upper(num: int) -> str:
    if num == 0:
        return "零元整"

    sections = []
    unit_pos = 0

    while num > 0:
        section = num % 10000
        if section != 0:
            section_str = four_digit_to_cn(section)
            if CN_SECTION[unit_pos]:
                section_str += CN_SECTION[unit_pos]
            sections.insert(0, section_str)
        else:
            if sections and not sections[0].startswith("零"):
                sections.insert(0, "零")
        num //= 10000
        unit_pos += 1

    result = "".join(sections)
    result = re.sub(r"零+", "零", result)
    result = result.rstrip("零")
    return result + "元整"


def format_money(value: str, output_format: str) -> str:
    if not value:
        return ""

    amount = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if output_format == "plain_number":
        if amount == amount.to_integral():
            return str(int(amount))
        return format(amount, "f")

    if output_format == "with_unit":
        if amount == amount.to_integral():
            return f"{int(amount)}元"
        return f"{format(amount, 'f')}元"

    if output_format == "currency_symbol":
        return f"￥{format(amount, '.2f')}"

    if output_format == "cny_uppercase":
        integer_part = int(amount)
        return int_to_cny_upper(integer_part)

    if amount == amount.to_integral():
        return str(int(amount))
    return format(amount, "f")


def format_date(value: str, output_format: str) -> str:
    if not value:
        return ""

    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if not m:
        return value

    y, mo, d = m.groups()
    mo_i = int(mo)
    d_i = int(d)

    if output_format == "YYYY-MM-DD":
        return f"{y}-{mo_i:02d}-{d_i:02d}"

    if output_format == "YYYY年M月D日":
        return f"{y}年{mo_i}月{d_i}日"

    return f"{y}-{mo_i:02d}-{d_i:02d}"


def format_phone(value: str, output_format: str) -> str:
    if not value:
        return ""
    return value


def format_text(value: str, output_format: str) -> str:
    if not value:
        return ""
    return str(value).strip()


def format_value(value: str, field_type: str, output_format: str) -> str:
    field_type = (field_type or "text").lower()
    output_format = (output_format or "plain").strip()

    if field_type == "money":
        return format_money(value, output_format)
    elif field_type == "date":
        return format_date(value, output_format)
    elif field_type == "phone":
        return format_phone(value, output_format)
    else:
        return format_text(value, output_format)


# =========================
# 7. 按 profile 处理结果
# =========================
def validate_required_fields(final_data: dict, profile: dict) -> list[str]:
    task_mode = profile.get("task_mode", "single_record")

    if task_mode == "table_records":
        records = final_data.get("records", [])
        if not records:
            return ["records"]
        return []

    missing = []
    for item in profile.get("fields", []):
        if item.get("required", False):
            name = item["name"]
            value = final_data.get(name, "")
            if value is None or str(value).strip() == "":
                missing.append(name)
    return missing

def retry_missing_required_fields(
    text: str,
    profile: dict,
    extracted_raw: dict,
    missing_fields: list[str]
) -> tuple[dict, list[str]]:
    retried = []

    if not missing_fields:
        return extracted_raw, retried

    field_map = {item["name"]: item for item in profile.get("fields", [])}
    field_items = [field_map[name] for name in missing_fields if name in field_map]

    if not field_items:
        return extracted_raw, retried

    retry_prompt = build_missing_fields_prompt(text, field_items)

    try:
        retry_result = call_ollama(retry_prompt)

        print("=== 二次提取返回结果 ===")
        print(json.dumps(retry_result, ensure_ascii=False, indent=2))

        for field_name in missing_fields:
            new_value = retry_result.get(field_name, "")
            if str(new_value).strip():
                extracted_raw[field_name] = new_value
                retried.append(field_name)

    except Exception as e:
        print(f"[WARN] 批量二次提取失败：{e}")

    return extracted_raw, retried


def build_debug_result(extracted_raw: dict, profile: dict) -> dict:
    task_mode = profile.get("task_mode", "single_record")

    if task_mode == "table_records":
        raw_records = extracted_raw.get("records", [])
        debug_rows = []

        if isinstance(raw_records, list):
            for idx, record in enumerate(raw_records):
                if not isinstance(record, dict):
                    continue

                row_debug = {"_row_index": idx}
                for item in profile.get("fields", []):
                    name = item["name"]
                    field_type = item.get("type", "text")
                    output_format = item.get("output_format", "plain")
                    raw_value = record.get(name, "")

                    internal_value = normalize_internal(raw_value, field_type)
                    final_value = format_value(internal_value, field_type, output_format)

                    row_debug[name] = {
                        "raw": raw_value,
                        "normalized": internal_value,
                        "final": final_value,
                        "status": "ok" if str(final_value).strip() else "empty"
                    }

                debug_rows.append(row_debug)

        return {
            "task_mode": "table_records",
            "row_count": len(debug_rows),
            "rows": debug_rows
        }

    debug_data = {}
    for item in profile.get("fields", []):
        name = item["name"]
        field_type = item.get("type", "text")
        output_format = item.get("output_format", "plain")
        raw_value = extracted_raw.get(name, "")

        if name == "甲方单位":
            raw_value = clean_org_name(raw_value)

        internal_value = normalize_internal(raw_value, field_type)
        final_value = format_value(internal_value, field_type, output_format)
        status = "ok" if str(final_value).strip() else "empty"

        debug_data[name] = {
            "raw": raw_value,
            "normalized": internal_value,
            "final": final_value,
            "status": status
        }

    return debug_data


def build_run_summary(
    profile: dict,
    runtime: dict,
    missing_fields: list[str],
    retried_fields: list[str],
    input_text: str
) -> dict:
    return {
        "report_name": profile.get("report_name", ""),
        "profile_path": profile.get("report_name", ""),
        "input_char_count": len(input_text),
        "missing_required_fields": missing_fields,
        "retried_fields": retried_fields,
        "total_seconds": runtime.get("total_seconds", 0),
        "within_90_seconds": runtime.get("within_90_seconds", False),
        "model_inference_seconds": runtime.get("model_inference_seconds", 0)
    }


def process_single_record(extracted_raw: dict, profile: dict) -> dict:
    final_data = {}
    fields = profile.get("fields", [])

    for item in fields:
        name = item["name"]
        field_type = item.get("type", "text")
        output_format = item.get("output_format", "plain")

        raw_value = extracted_raw.get(name, "")

        if name == "甲方单位":
            raw_value = clean_org_name(raw_value)

        internal_value = normalize_internal(raw_value, field_type)
        final_value = format_value(internal_value, field_type, output_format)

        final_data[name] = final_value

    return final_data


def process_table_records(extracted_raw: dict, profile: dict) -> dict:
    fields = profile.get("fields", [])
    raw_records = extracted_raw.get("records", [])

    if not isinstance(raw_records, list):
        raw_records = []

    final_records = []

    for record in raw_records:
        if not isinstance(record, dict):
            continue

        row = {}
        for item in fields:
            name = item["name"]
            field_type = item.get("type", "text")
            output_format = item.get("output_format", "plain")

            raw_value = record.get(name, "")
            internal_value = normalize_internal(raw_value, field_type)
            final_value = format_value(internal_value, field_type, output_format)
            row[name] = final_value

        final_records.append(row)

    return {"records": final_records}


def process_by_profile(extracted_raw: dict, profile: dict):
    task_mode = profile.get("task_mode", "single_record")

    if task_mode == "table_records":
        return process_table_records(extracted_raw, profile)

    return process_single_record(extracted_raw, profile)
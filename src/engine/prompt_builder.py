import json


def build_prompt(text: str, profile: dict) -> str:
    instruction = profile.get("instruction", "请根据字段要求，从文档中提取信息。")
    fields = profile.get("fields", [])
    task_mode = profile.get("task_mode", "single_record")

    field_lines = "\n".join([
        f"- {item['name']}：{item.get('extract_hint', '按字段名语义提取')}"
        for item in fields
    ])

    if task_mode == "table_records":
        example_record = {item["name"]: "" for item in fields}
        example_json = {"records": [example_record]}

        return f"""
你是一个严格的信息抽取助手。
用户指令：{instruction}

请你从下面文档内容中提取多条记录，并只输出一个 JSON 对象。
不要输出解释，不要输出 markdown，不要编造。

字段：
{field_lines}

要求：
1. 输出格式必须是：
{json.dumps(example_json, ensure_ascii=False, indent=2)}
2. 顶层必须是一个对象，且包含键 "records"
3. records 必须是数组，数组中每一项是一条记录
4. 每条记录的键名必须与字段名完全一致
5. 如果某字段缺失，值填空字符串 ""
6. 不要输出 records 以外的额外内容
7. 如果文本中存在多行/多站点/多条监测数据，要尽可能全部提取出来

文档内容如下：
{text}
"""

    return f"""
你是一个严格的信息抽取助手。
用户指令：{instruction}

请你从下面文档内容中提取以下字段，并且只输出一个 JSON 对象。
不要输出解释，不要输出 markdown，不要编造。

字段：
{field_lines}

要求：
1. JSON 的键名必须与上面的字段名完全一致
2. 如果某字段缺失，值填空字符串 ""
3. 不要猜测，不确定就留空
4. 但如果文本中有明显对应表达，应根据中文语义合理提取，不要漏掉
5. 如果提供的是“证据片段”，请优先依据证据片段中的内容提取
6. 不要输出字段名以外的额外内容

文档内容如下：
{text}
"""


def build_missing_fields_prompt(text: str, field_items: list[dict]) -> str:
    field_lines = "\n".join([
        f"- {item['name']}：{item.get('extract_hint', '按字段名语义提取')}"
        for item in field_items
    ])

    field_names = [item["name"] for item in field_items]
    example_json = {name: "" for name in field_names}

    return f"""
你是一个严格的信息抽取助手。

下面这些字段在首次抽取中缺失了，请你只补提取这些字段。
请只输出一个 JSON 对象。
不要输出解释，不要输出 markdown，不要编造。

字段：
{field_lines}

要求：
1. 只输出一个 JSON 对象
2. JSON 键名必须与字段名完全一致
3. 如果没有找到，对应值填空字符串 ""
4. 不要输出额外字段

输出示例：
{json.dumps(example_json, ensure_ascii=False)}

文档内容如下：
{text}
"""
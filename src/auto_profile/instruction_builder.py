def build_instruction(task_mode: str, template_mode: str, field_names: list[str]) -> str:
    preview = "、".join(field_names[:8])

    if task_mode == "table_records":
        return f"请从文档中提取所有记录，并按表格字段输出为 records 数组。重点字段包括：{preview}。"

    return f"请根据字段要求，从文档中提取关键信息并填写到模板中。重点字段包括：{preview}。"
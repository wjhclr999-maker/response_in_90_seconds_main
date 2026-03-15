from pathlib import Path

from src.auto_profile.template_detector import detect_template_structure
from src.auto_profile.alias_resolver import resolve_field_names
from src.auto_profile.field_inferer import infer_fields
from src.auto_profile.instruction_builder import build_instruction


def generate_profile_from_template(template_path: str, use_llm: bool = False) -> dict:
    detected = detect_template_structure(template_path)

    raw_field_names = detected.pop("field_names")
    resolved_field_names = resolve_field_names(raw_field_names)

    task_mode = detected["task_mode"]
    template_mode = detected["template_mode"]

    fields = infer_fields(
        field_names=resolved_field_names,
        task_mode=task_mode,
        template_mode=template_mode,
        use_llm=use_llm
    )

    instruction = build_instruction(
        task_mode=task_mode,
        template_mode=template_mode,
        field_names=resolved_field_names
    )

    profile = {
        "report_name": Path(template_path).stem,
        "template_path": template_path,
        "instruction": instruction,
        "task_mode": task_mode,
        "template_mode": template_mode,
        "fields": fields
    }

    # 把结构识别出的附加参数补进去
    for key, value in detected.items():
        if key not in profile:
            profile[key] = value

    return profile
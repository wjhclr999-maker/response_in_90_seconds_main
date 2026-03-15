import os
import json
from docx import Document


def read_text_file(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()

    if ext in [".txt", ".md"]:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    if ext == ".docx":
        doc = Document(path)
        return "\n".join([p.text for p in doc.paragraphs])

    return ""


def collect_all_text(input_dir: str) -> str:
    texts = []
    for filename in sorted(os.listdir(input_dir)):
        path = os.path.join(input_dir, filename)
        if os.path.isfile(path):
            text = read_text_file(path)
            if text.strip():
                texts.append(f"【文件名】{filename}\n{text}")
    return "\n\n".join(texts)


def load_profile(profile_path: str) -> dict:
    with open(profile_path, "r", encoding="utf-8") as f:
        return json.load(f)
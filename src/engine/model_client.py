import json
import re
import requests

from src.config import OLLAMA_URL, MODEL_NAME


def call_ollama(prompt: str) -> dict:
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2
        }
    }

    resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
    resp.raise_for_status()
    result = resp.json()["response"].strip()

    try:
        return json.loads(result)
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", result)
    if not match:
        raise ValueError(f"模型输出不是合法 JSON：\n{result}")

    return json.loads(match.group(0))
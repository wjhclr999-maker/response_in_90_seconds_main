import json
import os

try:
    from rapidfuzz import fuzz
except Exception:
    fuzz = None


DEFAULT_ALIAS_PATH = "schemas/field_aliases.json"


def load_alias_map(alias_path: str = DEFAULT_ALIAS_PATH) -> dict:
    if not os.path.exists(alias_path):
        return {}

    with open(alias_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        return {}

    return data


def build_reverse_alias_map(alias_map: dict) -> dict:
    reverse_map = {}

    for canonical_name, aliases in alias_map.items():
        canonical_name = str(canonical_name).strip()
        reverse_map[canonical_name] = canonical_name

        if isinstance(aliases, list):
            for alias in aliases:
                alias = str(alias).strip()
                if alias:
                    reverse_map[alias] = canonical_name

    return reverse_map


def resolve_field_name(field_name: str, alias_map: dict, fuzzy_threshold: int = 88) -> str:
    raw = str(field_name).strip()
    if not raw:
        return raw

    reverse_map = build_reverse_alias_map(alias_map)

    # 1. 直接命中
    if raw in reverse_map:
        return reverse_map[raw]

    # 2. 模糊匹配
    if fuzz is not None and reverse_map:
        best_name = raw
        best_score = -1

        for candidate_alias, canonical_name in reverse_map.items():
            score = fuzz.ratio(raw, candidate_alias)
            if score > best_score:
                best_score = score
                best_name = canonical_name

        if best_score >= fuzzy_threshold:
            return best_name

    return raw


def resolve_field_names(field_names: list[str], alias_path: str = DEFAULT_ALIAS_PATH) -> list[str]:
    alias_map = load_alias_map(alias_path)
    resolved = []

    for name in field_names:
        resolved.append(resolve_field_name(name, alias_map))

    return resolved
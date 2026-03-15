import requests


def retrieve_evidence(
    query_text: str,
    use_retrieval: bool,
    top_k: int = 5,
    retrieval_url: str = "",
    timeout: int = 20
) -> list[dict]:
    if not use_retrieval:
        return []

    try:
        # 方案1：如果以后你队友给的是 Python 函数，就在这里调用
        # chunks = teammate_retrieve(query_text, top_k=top_k)

        # 方案2：当前先走 HTTP 接口
        chunks = retrieve_evidence_via_http(
            query_text=query_text,
            retrieval_url=retrieval_url,
            top_k=top_k,
            timeout=timeout
        )

        return chunks if isinstance(chunks, list) else []

    except Exception as e:
        print(f"[WARN] 检索调用失败：{e}")
        return []


def retrieve_evidence_via_http(
    query_text: str,
    retrieval_url: str,
    top_k: int = 5,
    timeout: int = 20
) -> list[dict]:
    """
    调用外部检索接口，返回证据片段列表。
    约定返回格式：
    {
        "chunks": [
            {
                "text": "...",
                "source": "xxx.txt",
                "score": 0.93,
                "position": "片段1",
                "chunk_type": "paragraph"
            }
        ]
    }
    """
    if not retrieval_url.strip():
        return []

    payload = {
        "query": query_text,
        "top_k": top_k
    }

    try:
        resp = requests.post(retrieval_url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        chunks = data.get("chunks", [])
        if isinstance(chunks, list):
            return chunks
        return []
    except Exception as e:
        print(f"[WARN] 检索接口调用失败：{e}")
        return []


def preprocess_retrieved_chunks(chunks: list[dict]) -> list[dict]:
    processed = []

    for ch in chunks:
        text = str(ch.get("text", "")).strip()
        if not text:
            continue

        chunk_type = str(ch.get("chunk_type", "paragraph")).strip()

        # 简单清洗
        if chunk_type == "list":
            text = text.replace("•", "").replace("- ", "").strip()

        elif chunk_type == "table":
            text = text.replace("\t", " ").strip()

        new_ch = dict(ch)
        new_ch["text"] = text
        processed.append(new_ch)

    return processed


def format_retrieved_chunks(chunks: list[dict], top_k: int = 5) -> str:
    if not chunks:
        return ""

    chunks = sorted(chunks, key=lambda x: x.get("score", 0), reverse=True)[:top_k]

    parts = []
    for i, ch in enumerate(chunks, 1):
        text = str(ch.get("text", "")).strip()
        source = str(ch.get("source", "unknown")).strip()
        score = ch.get("score", 0)
        position = str(ch.get("position", f"片段{i}")).strip()
        chunk_type = str(ch.get("chunk_type", "paragraph")).strip()

        if not text:
            continue

        parts.append(
            f"【证据{i}】\n"
            f"来源文件：{source}\n"
            f"片段位置：{position}\n"
            f"片段类型：{chunk_type}\n"
            f"相关度：{score}\n"
            f"内容：\n{text}"
        )

    return "\n\n".join(parts)


def attach_field_evidence(extracted_raw: dict, retrieved_chunks: list[dict]) -> dict:
    """
    为每个字段尝试匹配一个最直接的证据片段，用于 debug 展示。
    """
    result = {}

    for field, value in extracted_raw.items():
        value_str = str(value).strip()
        matched = None

        if value_str:
            for ch in retrieved_chunks:
                text = str(ch.get("text", ""))
                if value_str and value_str in text:
                    matched = {
                        "source": ch.get("source", ""),
                        "position": ch.get("position", ""),
                        "score": ch.get("score", 0),
                        "chunk_type": ch.get("chunk_type", ""),
                        "evidence_text": text[:300]
                    }
                    break

        result[field] = {
            "value": value,
            "evidence": matched
        }

    return result
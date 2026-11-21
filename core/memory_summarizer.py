# -*- coding: utf-8 -*-
"""Second-stage LLM call: turn selected message groups into structured memories."""
from __future__ import annotations

import json
from pathlib import Path

from . import llm

PROMPT_PATH = Path(__file__).resolve().parents[1] / "docs" / "MEMORY_SUMMARIZER_SYSTEM_PROMPT.txt"
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
VALID_CATEGORIES = {"event", "fact", "state", "boundary", "preference", "scenario"}
VALID_DIMENSIONS = {"user_preference", "other_person", "scenario"}


def _format_group(group: dict) -> str:
    ids = ", ".join(str(x) for x in group.get("message_ids", []))
    messages = group.get("messages", [])
    body = "\n".join(f"[{m['id']}] {m.get('speaker', '对方')}：{m.get('text', '')}" for m in messages)
    return f"候选消息组 {ids}\n{body}"


def build_summarizer_input(contact: str, groups: list[dict]) -> str:
    return "联系人：" + contact + "\n\n" + "\n\n".join(_format_group(g) for g in groups)


def summarize_candidates(protocol: str, base_url: str | None, api_key: str, model: str,
                         contact: str, groups: list[dict], extra_body: dict | None = None,
                         headers: dict | None = None) -> dict:
    """Return validated structured memories; this function never writes the database."""
    if not groups:
        return {"memories": []}
    raw = llm.chat(protocol, base_url, api_key, model, SYSTEM_PROMPT,
                   [build_summarizer_input(contact, groups)], temperature=0.0,
                   max_tokens=1600, extra_body=extra_body, headers=headers, timeout=30)
    start, end = raw.find("{"), raw.rfind("}")
    data = json.loads(raw[start:end + 1]) if start >= 0 and end > start else {"memories": []}
    allowed_ids = {str(m["id"]) for g in groups for m in g.get("messages", [])}
    memories = []
    for item in data.get("memories", [])[:10]:
        summary = str(item.get("summary", "")).strip()
        category = str(item.get("category", ""))
        dimension = str(item.get("dimension", ""))
        ids = [str(x) for x in item.get("source_message_ids", []) if str(x) in allowed_ids]
        if not summary or category not in VALID_CATEGORIES or dimension not in VALID_DIMENSIONS or not ids:
            continue
        memories.append({
            "category": category,
            "dimension": dimension,
            "summary": summary[:500],
            "keywords": [str(x)[:40] for x in item.get("keywords", [])[:12]],
            "importance": max(1, min(5, int(item.get("importance", 3)))),
            "confidence": max(0.0, min(1.0, float(item.get("confidence", 0)))),
            "source_message_ids": ids,
        })
    return {"memories": memories}

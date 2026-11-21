# -*- coding: utf-8 -*-
"""Call the LLM for first-stage automatic memory candidate selection."""
from __future__ import annotations

import json
from pathlib import Path

from . import llm, providers

PROMPT_PATH = Path(__file__).resolve().parents[1] / "docs" / "MEMORY_JUDGE_SYSTEM_PROMPT.txt"
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")


def _message_line(message: dict) -> str:
    return f"[{message['id']}] {message.get('speaker', '对方')}：{message.get('text', '')}"


def build_judge_input(history_context: list[dict], new_messages: list[dict]) -> str:
    """Build a prompt where only new_messages are selectable."""
    history = "\n".join(_message_line(m) for m in history_context[-10:]) or "（无）"
    new = "\n".join(_message_line(m) for m in new_messages[-10:]) or "（无）"
    return (
        "联系人：" + str((new_messages or history_context)[0].get("contact", "")) + "\n\n"
        "【历史上下文，仅用于理解，禁止选择】\n" + history +
        "\n\n【本次新消息，只能从这里选择】\n" + new
    )


def judge_candidates(protocol: str, base_url: str | None, api_key: str, model: str,
                     history_context: list[dict], new_messages: list[dict],
                     extra_body: dict | None = None, headers: dict | None = None) -> dict:
    """Return validated candidate JSON; this function never writes RAG."""
    raw = llm.chat(protocol, base_url, api_key, model, SYSTEM_PROMPT,
                   [build_judge_input(history_context, new_messages)],
                   temperature=0.0, max_tokens=1200, extra_body=extra_body,
                   headers=headers, timeout=30)
    start, end = raw.find("{"), raw.rfind("}")
    data = json.loads(raw[start:end + 1]) if start >= 0 and end > start else {"candidates": []}
    allowed = {str(m["id"]) for m in new_messages}
    candidates = []
    for item in data.get("candidates", [])[:10]:
        ids = [str(x) for x in item.get("message_ids", []) if str(x) in allowed]
        if not ids:
            continue
        candidates.append({
            "message_ids": ids,
            "confidence": max(0.0, min(1.0, float(item.get("confidence", 0)))),
            "reason": str(item.get("reason", ""))[:300],
        })
    return {"candidates": candidates}

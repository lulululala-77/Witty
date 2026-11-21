# -*- coding: utf-8 -*-
"""Validate and persist structured memories into the local RAG store."""
from __future__ import annotations

import re

from .rag import add_memory, list_memories

SENSITIVE = re.compile(r"密码|验证码|api[ _-]?key|token|银行卡|身份证|支付密码", re.I)


def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(text or "")).lower()


def persist_memories(contact: str, memories: list[dict], *, min_confidence: float = 0.90) -> dict:
    """Save safe, non-duplicate memories; never overwrite existing rows."""
    existing = list_memories()
    existing_text = {_norm(row[4]) for row in existing if len(row) > 4}
    saved, skipped = [], []
    for item in memories:
        summary = str(item.get("summary", "")).strip()
        confidence = float(item.get("confidence", 0))
        if not summary or confidence < min_confidence:
            skipped.append({"summary": summary, "reason": "confidence"})
            continue
        if SENSITIVE.search(summary):
            skipped.append({"summary": summary, "reason": "sensitive"})
            continue
        key = _norm(summary)
        if key in existing_text:
            skipped.append({"summary": summary, "reason": "duplicate"})
            continue
        dimension = item.get("dimension", "other_person")
        category = item.get("category", "event")
        try:
            row_id = add_memory(summary, dimension, contact=contact,
                                 category=category, importance=item.get("importance", 3))
        except (TypeError, ValueError) as exc:
            skipped.append({"summary": summary, "reason": str(exc)})
            continue
        existing_text.add(key)
        saved.append({"id": row_id, "summary": summary, "category": category})
    return {"saved": saved, "skipped": skipped}

# -*- coding: utf-8 -*-
"""Safe first-pass filter for automatic memory candidates."""
from __future__ import annotations

import re

SAFE_SHELLS = (
    "哈哈哈哈哈哈", "哈哈哈哈哈",
    "哈哈哈哈", "哈哈哈", "哈哈", "嘿嘿", "嘻嘻", "呵呵",
    "笑死我了", "笑死", "嗯嗯", "哦哦", "哎呀", "呃", "额",
)

EXACT_NOISE = {
    "嗯", "嗯嗯", "哦", "哦哦", "噢", "好", "好的", "行", "收到",
    "知道了", "明白", "哈哈", "哈哈哈", "哈哈哈哈", "嘿嘿", "嘻嘻",
    "呵呵", "笑死", "？", "!", "！", "...", "……",
}

_EMOJI_RE = re.compile(
    r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]"
)
_ASCII_EMOTICON_RE = re.compile(
    r"(?:[:;=8][-^']?[)(/\\DPp]|\b(?:XD|T_T|QAQ|Orz)\b|"
    r"\([^\n]{0,12}[\u4e00-\u9fffA-Za-z0-9^_*+•̀́ㅂو✧･ωฅ-]{0,12}\))",
    re.IGNORECASE,
)
_PUNCT_OR_SPACE_RE = re.compile(r"^[\s\W_]+$", re.UNICODE)


def clean_message(text: str) -> tuple[str, str]:
    """Return (original, cleaned). Only strip safe shells at boundaries."""
    original = str(text or "").strip()
    cleaned = _EMOJI_RE.sub("", original)
    cleaned = _ASCII_EMOTICON_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    changed = True
    while changed and cleaned:
        changed = False
        for shell in SAFE_SHELLS:
            if cleaned.startswith(shell):
                cleaned = cleaned[len(shell):].lstrip(" \t，,。！？!?：:；;~～")
                changed = True
                break
            if cleaned.endswith(shell):
                cleaned = cleaned[:-len(shell)].rstrip(" \t，,。！？!?：:；;~～")
                changed = True
                break
    return original, cleaned


def is_obvious_noise(text: str) -> bool:
    original, cleaned = clean_message(text)
    if not original or original in EXACT_NOISE:
        return True
    if not cleaned or _PUNCT_OR_SPACE_RE.fullmatch(cleaned):
        return True
    return False


def prepare_for_memory(text: str) -> str:
    """Return empty for obvious noise; otherwise cleaned text for the LLM."""
    if is_obvious_noise(text):
        return ""
    return clean_message(text)[1]

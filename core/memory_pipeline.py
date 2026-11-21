# -*- coding: utf-8 -*-
"""Windowing and trigger logic for automatic memory candidate judging."""
from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic

from .memory_filter import prepare_for_memory


@dataclass
class MemoryWindow:
    """Per-contact state. The callback receives (context, new_messages)."""
    history: list[dict] = field(default_factory=list)
    pending: list[dict] = field(default_factory=list)
    last_trigger: float = field(default_factory=monotonic)

    def add(self, messages: list[dict], judge_callback, now: float | None = None):
        now = monotonic() if now is None else now
        for message in messages:
            original = str(message.get("text", ""))
            cleaned = prepare_for_memory(original)
            item = dict(message)
            item["original"] = original
            item["text"] = cleaned
            self.history.append(item)
            if cleaned:
                self.pending.append(item)
        self.history = self.history[-60:]
        should_trigger = len(self.pending) >= 10 or (
            self.pending and now - self.last_trigger >= 180
        )
        if not should_trigger:
            return None
        new_messages = self.pending[:10]
        self.pending = self.pending[len(new_messages):]
        context = self.history[-(len(new_messages) + 10):-len(new_messages)] if new_messages else self.history[-10:]
        self.last_trigger = now
        return judge_callback(context[-10:], new_messages)

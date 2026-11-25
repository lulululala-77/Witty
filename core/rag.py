# -*- coding: utf-8 -*-
"""Local personal RAG store with embedding service and model-verified deduplication.

The store keeps three dimensions:
  user_preference: how the user likes to reply (draft model)
  other_person: contact facts, state, relationship and boundaries (Jev)
  scenario: reusable situation guidance (both)
"""
from __future__ import annotations

import re
import sqlite3
import json
import os
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from contextlib import closing

DB_PATH = Path(__file__).resolve().parents[1] / "rag.sqlite3"
TRACE_PATH = Path(__file__).resolve().parents[1] / "rag_debug.jsonl"
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
MAX_TOTAL_MEMORIES = 2000
MAX_CONTACT_MEMORIES = 200
MAX_MEMORY_CHARS = 320
DEDUP_CANDIDATE_THRESHOLD = 0.80
DEDUP_MAX_CANDIDATES = 5
EMBEDDING_URL = os.environ.get("JEV_EMBEDDING_URL", "http://127.0.0.1:8765/embed").rstrip("/")
EMBEDDING_TIMEOUT = float(os.environ.get("JEV_EMBEDDING_TIMEOUT", "30"))
_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dimension TEXT NOT NULL CHECK (dimension IN ('user_preference','other_person','scenario')),
    contact TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 3,
    embedding BLOB,
    expires_at TEXT,
    event_date TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_memories_dimension_contact
ON memories(dimension, contact);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(_SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
    if "embedding" not in columns:
        conn.execute("ALTER TABLE memories ADD COLUMN embedding BLOB")
    if "expires_at" not in columns:
        conn.execute("ALTER TABLE memories ADD COLUMN expires_at TEXT")
    if "event_date" not in columns:
        conn.execute("ALTER TABLE memories ADD COLUMN event_date TEXT")
    return conn


def _encode(texts: list[str]):
    import numpy as np
    if not texts:
        return np.empty((0, 0), dtype=np.float32)
    payload = json.dumps({"texts": texts}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        EMBEDDING_URL, data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=EMBEDDING_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            f"Embedding 服务不可用（{EMBEDDING_URL}）。请先启动 embedding_server.py：{exc}") from exc
    vectors = np.asarray(data.get("embeddings", []), dtype=np.float32)
    if len(vectors) != len(texts):
        raise RuntimeError("Embedding 服务返回的向量数量不匹配")
    return vectors


def split_text(text: str, max_chars: int = 320, overlap: int = 40) -> list[str]:
    """Split a memory/document into readable Chinese chunks."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n+|(?<=[。！？；])", text) if p.strip()]
    chunks, current = [], ""
    for part in paragraphs:
        if len(current) + len(part) + 1 <= max_chars:
            current = f"{current} {part}".strip()
        else:
            if current:
                chunks.append(current)
            tail = current[-overlap:] if overlap and current else ""
            current = f"{tail} {part}".strip()
    if current:
        chunks.append(current)
    return chunks


def add_memory(content: str, dimension: str, contact: str = "", category: str = "",
               importance: int = 3, expires_at: str | None = None,
               event_date: str | None = None) -> int:
    if dimension not in {"user_preference", "other_person", "scenario"}:
        raise ValueError("invalid RAG dimension")
    chunks = split_text(str(content or "")[:MAX_MEMORY_CHARS], max_chars=MAX_MEMORY_CHARS)
    if not chunks:
        return 0
    try:
        vectors = _encode(chunks)
    except Exception:
        vectors = [None] * len(chunks)
    with closing(_connect()) as conn, conn:
        total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        contact_total = conn.execute("SELECT COUNT(*) FROM memories WHERE contact=?", (contact or "",)).fetchone()[0]
        first_id = 0
        for chunk, vector in zip(chunks, vectors):
            if total >= MAX_TOTAL_MEMORIES or contact_total >= MAX_CONTACT_MEMORIES:
                break
            # Exact duplicate protection before the more expensive vector check.
            duplicate = conn.execute(
                "SELECT 1 FROM memories WHERE dimension=? AND contact=? AND content=? "
                "AND COALESCE(event_date,'')=? AND COALESCE(expires_at,'')=? "
                "AND (expires_at IS NULL OR expires_at='' OR expires_at > datetime('now','localtime')) LIMIT 1",
                (dimension, contact or "", chunk, event_date or '', expires_at or '')).fetchone()
            if duplicate:
                continue
            if vector is not None:
                import numpy as np
                candidates = conn.execute(
                    "SELECT id, content, event_date, expires_at, embedding FROM memories "
                    "WHERE dimension=? AND contact=? AND embedding IS NOT NULL "
                    "AND (expires_at IS NULL OR expires_at='' OR expires_at > datetime('now','localtime'))",
                    (dimension, contact or "",)).fetchall()
                ranked = []
                for mid, old_content, old_date, old_expiry, blob in candidates:
                    # Different temporal metadata must not suppress a new event/state.
                    if (old_date or '') != (event_date or '') or (old_expiry or '') != (expires_at or ''):
                        continue
                    old_vector = np.frombuffer(blob, dtype=np.float32)
                    if old_vector.shape != vector.shape:
                        continue
                    score = float(np.dot(vector, old_vector))
                    if score >= DEDUP_CANDIDATE_THRESHOLD:
                        ranked.append((score, {'id': mid, 'content': old_content,
                                               'event_date': old_date, 'expires_at': old_expiry}))
                ranked.sort(key=lambda item: item[0], reverse=True)
                from core.memory_dedup import is_duplicate
                if is_duplicate({'content': chunk, 'contact': contact or '',
                                 'event_date': event_date, 'expires_at': expires_at},
                                [item[1] for item in ranked[:DEDUP_MAX_CANDIDATES]]):
                    continue
            cur = conn.execute(
                "INSERT INTO memories(dimension,contact,category,content,importance,embedding,expires_at,event_date) VALUES(?,?,?,?,?,?,?,?)",
                (dimension, contact or "", category or "", chunk,
                 max(1, min(5, int(importance))),
                 None if vector is None else vector.tobytes(), expires_at, event_date),
            )
            first_id = first_id or int(cur.lastrowid)
            total += 1
            contact_total += 1
        return first_id


def _terms(text: str) -> set[str]:
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text.lower())
    words = set(text.split())
    # Chinese has no spaces; character bigrams give a useful small local baseline.
    compact = "".join(text.split())
    words.update(compact[i:i + 2] for i in range(max(0, len(compact) - 1)))
    return {w for w in words if len(w) >= 2}


def retrieve(query: str, dimension: str | None = None, contact: str | None = None,
             limit: int = 5, *, trace: dict | None = None,
             query_speaker: str | None = None) -> str:
    """Return the best local memories as prompt-ready text."""
    filters, args = [], []
    # Long-term retrieval never returns raw conversation archives.
    filters.append("category NOT IN ('conversation', 'raw')")
    filters.append("(expires_at IS NULL OR expires_at = '' OR expires_at > datetime('now', 'localtime'))")
    if dimension:
        filters.append("dimension = ?"); args.append(dimension)
    # Raw conversation logs are source material, not long-term retrieval memories.
    filters.append("category != 'conversation'")
    if contact is not None:
        filters.append("(contact = ? OR contact = '')"); args.append(contact)
    where = (" WHERE " + " AND ".join(filters)) if filters else ""
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"SELECT dimension, category, contact, content, importance, embedding, id FROM memories{where}", args
        ).fetchall()
    terms = _terms(query)
    try:
        import numpy as np
        qvec = _encode(["为这个句子生成表示：" + query])[0]
    except Exception:
        qvec = None
    ranked = []
    for dim, category, person, content, importance, stored_embedding, mid in rows:
        overlap = len(terms & _terms(content))
        similarity = 0.0
        if qvec is not None and stored_embedding:
            memory_vec = np.frombuffer(stored_embedding, dtype=np.float32)
            similarity = float(np.dot(qvec, memory_vec))
        score = similarity * 100 + overlap + int(importance) * 0.01
        # Only verified semantic scores may trigger the relevance model.
        if qvec is not None and stored_embedding and similarity >= 0.425:
            ranked.append((score, dim, category, person, content, mid))
    ranked.sort(reverse=True)
    candidates = [{'id': mid, 'dimension': dim, 'category': category,
                   'contact': person, 'content': content}
                  for _, dim, category, person, content, mid in ranked[:max(0, min(limit, 5))]]
    from core.retrieval_filter import filter_candidates
    decision = filter_candidates(query, candidates, query_speaker=query_speaker)
    if trace is not None:
        trace.update(embedding_mode='vector' if qvec is not None else 'unavailable',
                     candidates=candidates, verification=decision)
    keep = set(decision['keep_ids'])
    return "\n".join(
        f"- [{c['category'] or c['dimension']}] {c['content']}" for c in candidates if c['id'] in keep
    )


def list_memories() -> list[tuple]:
    with _connect() as conn:
        return conn.execute(
            "SELECT id, dimension, contact, category, content, importance, created_at, expires_at, event_date "
            "FROM memories ORDER BY id"
        ).fetchall()


def backfill_embeddings() -> int:
    """Generate vectors for memories saved before embedding storage existed."""
    with _connect() as conn:
        rows = conn.execute("SELECT id, content FROM memories WHERE embedding IS NULL").fetchall()
    if not rows:
        return 0
    try:
        vectors = _encode([content for _, content in rows])
    except Exception:
        return 0
    with _connect() as conn:
        for (row_id, _), vector in zip(rows, vectors):
            conn.execute("UPDATE memories SET embedding=? WHERE id=?", (vector.tobytes(), row_id))
    return len(rows)


def log_trace(contact: str, latest: str, judge_memory: str, draft_memory: str,
              result: dict | None = None) -> None:
    """Append a local, UTF-8 JSONL trace for RAG A/B inspection."""
    payload = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "contact": contact,
        "latest_message": latest,
        "judge_memory": judge_memory,
        "draft_memory": draft_memory,
        "candidates": (result or {}).get("candidates", []),
        "best_reply": (result or {}).get("best_reply", ""),
    }
    with TRACE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    print(f"RAG database: {DB_PATH}")
    print("backfilled embeddings:", backfill_embeddings())
    print("memories:", len(list_memories()))

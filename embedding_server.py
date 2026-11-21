# -*- coding: utf-8 -*-
"""独立的本地 embedding 服务。

启动一次后模型常驻内存，JevChat 通过 http://127.0.0.1:8765/embed 调用。
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sentence_transformers import SentenceTransformer

HOST = os.environ.get("JEV_EMBEDDING_HOST", "127.0.0.1")
PORT = int(os.environ.get("JEV_EMBEDDING_PORT", "8765"))
MODEL_NAME = os.environ.get("JEV_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")

print(f"Loading embedding model: {MODEL_NAME}", flush=True)
MODEL = SentenceTransformer(MODEL_NAME)
MODEL_LOCK = threading.Lock()
print(f"Embedding server ready: http://{HOST}:{PORT}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._json(200, {"ok": True, "model": MODEL_NAME})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/embed":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            texts = data.get("texts")
            if not isinstance(texts, list) or not all(isinstance(x, str) for x in texts):
                raise ValueError("texts 必须是字符串数组")
            with MODEL_LOCK:
                vectors = MODEL.encode(texts, normalize_embeddings=True).tolist()
            self._json(200, {"embeddings": vectors, "model": MODEL_NAME})
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def log_message(self, fmt, *args):
        print(f"[embedding] {fmt % args}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

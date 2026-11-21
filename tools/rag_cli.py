# -*- coding: utf-8 -*-
"""Small local RAG manager for Jev.

Examples:
  python tools/rag_cli.py add user_preference "我喜欢短句和自然口吻" --category style
  python tools/rag_cli.py add other_person "对方最近在准备考试" --contact "黎少爷" --category state
  python tools/rag_cli.py add scenario "说明进度并给明确时间" --category workplace_followup
  python tools/rag_cli.py list
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.rag import add_memory, list_memories, DB_PATH  # noqa: E402


parser = argparse.ArgumentParser()
sub = parser.add_subparsers(dest="command", required=True)
add = sub.add_parser("add")
add.add_argument("dimension", choices=["user_preference", "other_person", "scenario"])
add.add_argument("content", nargs="?", default="")
add.add_argument("--file", help="read UTF-8 content from a file")
add.add_argument("--contact", default="")
add.add_argument("--category", default="")
add.add_argument("--importance", type=int, default=3)
sub.add_parser("list")
args = parser.parse_args()

if args.command == "add":
    content = Path(args.file).read_text(encoding="utf-8") if args.file else args.content
    if not content.strip():
        parser.error("provide content or --file")
    row_id = add_memory(content, args.dimension, args.contact, args.category, args.importance)
    print(f"saved id={row_id} db={DB_PATH}")
else:
    for row in list_memories():
        print(row)

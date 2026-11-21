"""Replay frozen prior summaries/vectors through the new store and live verifier."""
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import rag, llm

BASE = ROOT.parent / 'RAG写入评测集'
SOURCE = BASE / '实测记录_v3_20261120_retry'
OUT = BASE / '去重核验复测_20261120'
OUT.mkdir(exist_ok=True)
results = []
actual_chat = llm.chat
for ident in ['B08', 'B09', 'B10']:
    path = OUT / (ident + '.sqlite3')
    if path.exists():
        raise RuntimeError('Refusing to overwrite ' + str(path))
    with sqlite3.connect(SOURCE / (ident + '.sqlite3')) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute('SELECT * FROM memories ORDER BY id')]
    assert len(rows) == 2
    result = {'id': ident, 'method': '回放上一轮真实摘要与已保存向量；去重核验调用真实模型；未重跑OCR/180秒触发/摘要生成。', 'calls': []}
    def traced(*args, **kwargs):
        raw = actual_chat(*args, **kwargs)
        result['calls'].append({'input': args[5], 'raw': raw})
        return raw
    with patch.object(rag, 'DB_PATH', path), patch.object(llm, 'chat', side_effect=traced):
        for i, row in enumerate(rows):
            vector = np.frombuffer(row['embedding'], dtype=np.float32).copy()
            with patch.object(rag, '_encode', return_value=np.array([vector])):
                mid = rag.add_memory(row['content'], row['dimension'], row['contact'],
                                     row['category'], row['importance'], row['expires_at'], row['event_date'])
            if i == 1: result['new_memory_id'] = mid
        with rag._connect() as conn:
            result['final_rows'] = conn.execute('SELECT id,contact,content FROM memories ORDER BY id').fetchall()
    result['passed'] = bool(result['new_memory_id']) == (ident != 'B10')
    results.append(result)
    (OUT / (ident + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)
(OUT / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
assert all(r['passed'] for r in results)

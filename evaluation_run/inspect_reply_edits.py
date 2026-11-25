import ast,json,zipfile,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT.parent/'RAG检索评测集'
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
tree=ast.parse((ROOT/'evaluation_run/run_retrieval147.py').read_text(encoding='utf-8'))
fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='workbook_rows');exec(compile(ast.Module(body=[fn],type_ignores=[]),'<reader>','exec'))
rows=workbook_rows(BASE/'RAG回复效果_AB盲评_重新设计24组.xlsx',1,25,25)[1:]
for r in rows:print(json.dumps({'id':r[0],'contact':r[1],'history':r[3],'query':r[4],'memory_reference':r[5],'condition':r[23]},ensure_ascii=False))

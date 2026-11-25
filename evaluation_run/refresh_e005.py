import ast,json,sys,zipfile,hashlib,time,shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from core import engine
from app import settings
BASE=ROOT.parent/'RAG检索评测集';SOURCE=BASE/'RAG回复效果_AB盲评_修改后24组_新答复.xlsx'
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
tree=ast.parse((ROOT/'evaluation_run/run_retrieval147.py').read_text(encoding='utf-8'));fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='workbook_rows');exec(compile(ast.Module(body=[fn],type_ignores=[]),'<reader>','exec'))
rows=workbook_rows(SOURCE,1,25,25)[1:];row=next(r for r in rows if r[0]=='E005')
prior=Path(json.loads((BASE/'素材/latest_reply_edited.json').read_text(encoding='utf-8'))['run_dir'])
manifest=json.loads((prior/'manifest.json').read_text(encoding='utf-8'));assignment=next(a for a in manifest['assignments'] if a['blind_id']=='E005')
print(json.dumps({'id':row[0],'history':row[3],'query':row[4],'reference':row[5],'condition':row[23],'scores_A':row[8:13],'scores_B':row[14:19]},ensure_ascii=False),flush=True)
if '--inspect' in sys.argv:sys.exit()
OUT=BASE/('E005更新_'+datetime.now().strftime('%Y%m%d_%H%M%S'));OUT.mkdir();shutil.copy2(SOURCE,OUT/SOURCE.name)
settings.jev_key();settings.llm_key();config=manifest['config'];config={**config,'relationship':config['relationship']+f'；当前联系人是{row[1]}，her指该联系人，me指用户本人。'}
history=row[3] or '';messages=[]
if not history.startswith('无'):
 for line in history.splitlines():
  if line.startswith('用户：'):messages.append(('me',line[3:]))
  elif line.startswith('对方：'):messages.append(('her',line[3:]))
  else:raise ValueError('Unlabeled history')
messages.append(('her',row[4]));needed=row[23]=='需要正确记忆'
events=[];orig=engine.ask
def tracked(*args,**kwargs):
 try:
  result=orig(*args,**kwargs);events.append({'ok':True});return result
 except Exception as e:events.append({'ok':False,'error_type':type(e).__name__});raise
engine.ask=tracked;arms=[]
for on in [True,False]:
 memory=row[5] if on and needed else ''
 for attempt in range(2):
  events.clear();start=time.perf_counter()
  try:
   result=engine.analyze(messages,judge_memory=memory,draft_memory=memory,**config)
   valid=len(events)==2 and all(e['ok'] for e in events) and 'best_reply' in result['answers']
  except Exception as e:result={'error_type':type(e).__name__};valid=False
  record={'rag_on':on,'memory':memory,'messages':messages,'result':result,'events':list(events),'valid':valid,'seconds':time.perf_counter()-start}
  with (OUT/'attempts.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
  if valid:arms.append(record);break
 else:raise RuntimeError('Incomplete pipeline; original workbook unchanged')
output={'run_dir':str(OUT),'source_file':str(SOURCE),'source_sha256':hashlib.sha256((OUT/SOURCE.name).read_bytes()).hexdigest(),'row_number':rows.index(row)+2,'blind_id':'E005','assignment':assignment,'arms':arms,'query':row[4],'reference':row[5],'source_row':row}
(OUT/'result.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8');(BASE/'素材/latest_e005.json').write_text(json.dumps({'run_dir':str(OUT)},ensure_ascii=False),encoding='utf-8')
print('COMPLETE: E005 two successful responses; original A/B mapping preserved',flush=True)

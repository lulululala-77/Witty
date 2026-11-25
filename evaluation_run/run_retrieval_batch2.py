"""Read the user-edited workbook, seed an isolated DB, run production retrieval."""
import ast,json,sys,zipfile,hashlib,time,shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from core import rag
from app import settings
BASE=ROOT.parent/'RAG检索评测集'
SOURCE=BASE/'RAG检索评测集_第二批_12条记忆_84条Query.xlsx'
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
tree=ast.parse((ROOT/'evaluation_run/run_retrieval147.py').read_text(encoding='utf-8'))
fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='workbook_rows')
exec(compile(ast.Module(body=[fn],type_ignores=[]),'<reader>','exec'))
samples=workbook_rows(SOURCE,1,18,85)[1:]
memories=workbook_rows(SOURCE,2,8,13)[1:]
original=json.loads((BASE/'素材/第二批84Query/queries.json').read_text(encoding='utf-8'))
changes=[];mismatch=[]
for row,old in zip(samples,original['cases']):
 if row[0]!=old['id']:raise ValueError('ID order changed')
 for col,key in [(7,'context'),(8,'current_message'),(9,'query')]:
  value='' if col==7 and row[col]=='无' else row[col]
  if value!=old[key]:changes.append({'id':row[0],'field':key,'old':old[key],'new':value})
 expected=(row[7]+'\n对方：'+row[8]) if row[7] not in ('无','',None) else row[8]
 if row[9]!=expected:mismatch.append({'id':row[0],'current':row[8],'input':row[9],'expected_combined':expected})
audit={'changes':changes,'input_mismatches':mismatch}
print(json.dumps(audit,ensure_ascii=False,indent=2),flush=True)
if '--inspect' in sys.argv:sys.exit()
# Column J is the workbook's explicit authoritative retrieval input; audit any difference.
OUT=BASE/('第二批实测_84Query_'+datetime.now().strftime('%Y%m%d_%H%M%S'));OUT.mkdir()
shutil.copy2(SOURCE,OUT/SOURCE.name)
(OUT/'input_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
for f in ['core/rag.py','core/retrieval_filter.py']:(OUT/Path(f).name).write_bytes((ROOT/f).read_bytes())
rag.DB_PATH=OUT/'rag.sqlite3';rag.EMBEDDING_URL='http://127.0.0.1:8766/embed'
vectors=rag._encode([r[4] for r in memories]);assert vectors.shape==(12,512) and np.isfinite(vectors).all()
seed=[]
with closing(rag._connect()) as c,c:
 for row,v in zip(memories,vectors):
  mid,contact,dim,cat,content,_,importance,_=row
  cur=c.execute('INSERT INTO memories(dimension,contact,category,content,importance,embedding) VALUES(?,?,?,?,?,?)',(dim,contact,cat,content,int(importance),v.astype(np.float32).tobytes()))
  seed.append({'memory_id':mid,'db_id':cur.lastrowid,'contact':contact,'dimension':dim,'content':content,'category':cat})
lookup={f"- [{m['category']}] {m['content']}":m['memory_id'] for m in seed};ids={m['db_id']:m['memory_id'] for m in seed}
settings.llm_key()
def run(row):
 trace={};start=time.perf_counter();required=[] if row[11]=='无' else row[11].split(',')
 text=rag.retrieve(row[9],dimension=row[6],contact=row[5],query_speaker=row[5],trace=trace)
 actual=[lookup[line] for line in text.splitlines()]
 valid=trace.get('embedding_mode')=='vector' and trace['verification']['status']!='error'
 passed=all(k in actual for k in required) if required else not actual
 return {'id':row[0],'query':row[9],'type':row[3],'required':required,'actual_ids':actual,'actual_text':text,'passed':passed and valid,'technical_valid':valid,'candidate_ids':[ids[c['id']] for c in trace['candidates']],'trace':trace,'seconds':time.perf_counter()-start}
results=[]
with ThreadPoolExecutor(max_workers=6) as pool:
 for f in as_completed([pool.submit(run,r) for r in samples]):
  r=f.result();results.append(r)
  with (OUT/'results.jsonl').open('a',encoding='utf-8') as out:out.write(json.dumps(r,ensure_ascii=False)+'\n')
  if len(results)%12==0:print('COMPLETED',len(results),'/84',flush=True)
order={r[0]:i for i,r in enumerate(samples)};results.sort(key=lambda r:order[r['id']])
pos=[r for r in results if r['required']];neg=[r for r in results if not r['required']]
stats={'run_dir':str(OUT),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'threshold':.425,'model':settings.draft_model(),'positive_hit':[sum(r['passed'] for r in pos),len(pos)],'negative_false_retrieval':[sum(bool(r['actual_ids']) for r in neg if r['technical_valid']),sum(r['technical_valid'] for r in neg)],'overall_pass':[sum(r['passed'] for r in results),len(results)],'model_calls':sum(r['trace']['verification']['status']!='no_candidates' for r in results),'candidate_count':sum(len(r['candidate_ids']) for r in results),'technical_errors':[r['id'] for r in results if not r['technical_valid']],'failed':[{'id':r['id'],'query':r['query'],'required':r['required'],'actual_ids':r['actual_ids'],'candidate_ids':r['candidate_ids']} for r in results if not r['passed']],'by_type':{t:[sum(r['passed'] for r in results if r['type']==t),sum(r['type']==t for r in results)] for t in dict.fromkeys(r['type'] for r in results)}}
for name,obj in [('all_results',results),('metrics_review',stats),('seeded_memories',seed)]: (OUT/(name+'.json')).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
(BASE/'素材/第二批84Query/latest_run.json').write_text(json.dumps({'run_dir':str(OUT)},ensure_ascii=False),encoding='utf-8')
print(json.dumps(stats,ensure_ascii=False,indent=2),flush=True)

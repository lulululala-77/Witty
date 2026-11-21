"""Re-run the exact frozen queries and memory snapshot, with live model verification."""
import sys,json,time,sqlite3,hashlib
from pathlib import Path
from datetime import datetime,timezone,timedelta
from concurrent.futures import ThreadPoolExecutor,as_completed
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from core import rag,retrieval_filter
from app import settings
BASE=ROOT.parent/'RAG检索评测集'
OLD=BASE/'实测记录_147Query_20261121_111104'
OUT=BASE/('核验复测_147Query_'+datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M%S'));OUT.mkdir(exist_ok=False)
baseline=json.loads((OLD/'all_results.json').read_text(encoding='utf-8'))
seed=json.loads((OLD/'seeded_memories.json').read_text(encoding='utf-8'))
with sqlite3.connect(OLD/'rag.sqlite3') as src,sqlite3.connect(OUT/'rag.sqlite3') as dest:src.backup(dest)
rag.DB_PATH=OUT/'rag.sqlite3';rag.EMBEDDING_URL='http://127.0.0.1:8766/embed'
settings.llm_key()
lookup={f"- [{m['category'] or m['dimension']}] {m['content']}":m['memory_id'] for m in seed}
ids={m['db_id']:m['memory_id'] for m in seed}
for f in ['core/rag.py','core/retrieval_filter.py']:(OUT/Path(f).name).write_bytes((ROOT/f).read_bytes())
(OUT/'seeded_memories.json').write_text(json.dumps(seed,ensure_ascii=False,indent=2),encoding='utf-8')
def run(old):
 trace={};start=time.perf_counter()
 speaker=old['contact'] if old['source']=='对方消息' else '用户本人'
 text=rag.retrieve(old['query'],dimension=old['dimension'],contact=old['contact'],limit=5,trace=trace,query_speaker=speaker)
 trace['query_speaker']=speaker
 actual=[lookup[line] for line in text.splitlines()]
 valid=trace['embedding_mode']=='vector' and trace['verification']['status']!='error'
 passed=all(k in actual for k in old['required']) if old['required'] else not actual
 return {**{k:old[k] for k in ['id','target','type','source','query','contact','dimension','expected','required']},'actual_ids':actual,'actual_text':text,'passed':passed and valid,'semantic_pass':passed,'technical_valid':valid,'seconds':time.perf_counter()-start,'candidate_ids':[ids[c['id']] for c in trace['candidates']],'trace':trace,'baseline_ids':old['actual_ids'],'baseline_passed':old['passed']}
results=[]
with ThreadPoolExecutor(max_workers=6) as pool:
 futures=[pool.submit(run,r) for r in baseline]
 for f in as_completed(futures):
  r=f.result();results.append(r)
  with (OUT/'results.jsonl').open('a',encoding='utf-8') as out:out.write(json.dumps(r,ensure_ascii=False)+'\n')
  if len(results)%21==0:print('COMPLETED',len(results),'/147',flush=True)
results.sort(key=lambda r:next(i for i,b in enumerate(baseline) if b['id']==r['id']))
pos=[r for r in results if r['required']];neg=[r for r in results if not r['required']]
summary={'run_dir':str(OUT),'baseline_dir':str(OLD),'model':settings.draft_model(),'cases':147,'model_calls':sum(r['trace']['verification']['status']!='no_candidates' for r in results),'technical_errors':[r['id'] for r in results if not r['technical_valid']],'positive_hit':[sum(r['passed'] for r in pos),len(pos)],'negative_false_retrieval':[sum(bool(r['actual_ids']) for r in neg if r['technical_valid']),sum(r['technical_valid'] for r in neg)],'overall_pass':[sum(r['passed'] for r in results),147],'by_type':{k:{'passed':sum(r['passed'] for r in results if r['type']==k),'total':sum(r['type']==k for r in results)} for k in dict.fromkeys(r['type'] for r in results)},'positive_lost':[r['id'] for r in pos if not r['passed']],'remaining_false_retrieval':[r['id'] for r in neg if r['actual_ids']],'mean_query_seconds':sum(r['seconds'] for r in results)/147,'limitations':['完整复用上轮147个已展开时间的query和21条向量记忆快照；生产retrieve仍重新编码query。','技术异常单列，不能算作正确拒绝；负例误召回率排除技术异常，整体通过率将其计为未通过。','6线程并发评测，不代表单用户整条回复链路耗时。','正例只检查目标保留，额外返回项不纳入该指标；未测试GUI/OCR及回复生成。']}
(OUT/'all_results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'metrics_review.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
(BASE/'素材/query147/latest_verified_run.json').write_text(json.dumps({'run_dir':str(OUT)},ensure_ascii=False),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)

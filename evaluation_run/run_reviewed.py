import ast,sys,json,time,threading,hashlib,re,os,sqlite3
from pathlib import Path
from datetime import datetime,timedelta
from collections import deque
from types import SimpleNamespace
from concurrent.futures import ProcessPoolExecutor,as_completed
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT.parent/'RAG写入评测集'/os.environ.get('RAG_EVAL_DIR','实测记录')
SOURCE=(ROOT/'main.py').read_text(encoding='utf-8')
TREE=ast.parse(SOURCE)

def run_case(row):
 from app import settings
 from core import rag,llm,providers
 from core.jev_client import _api_key
 from core.memory_write_prompt import SYSTEM_PROMPT
 from core.memory_input import build_memory_input, format_memory_messages, has_group_speakers
 import numpy as np
 settings.llm_key()
 ident,contact=row[0],row[2]
 started=time.time()
 rag.DB_PATH=OUT/(ident+'.sqlite3')
 if rag.DB_PATH.exists():raise RuntimeError('Refuse existing database '+ident)
 rag.EMBEDDING_URL='http://127.0.0.1:8766/embed'
 record={'id':ident,'run_id':'reviewed-20261119','started_at':datetime.now().isoformat(),'model':settings.draft_model(),'code_hash':hashlib.sha256(SOURCE.encode()).hexdigest()[:16],'embedding_mode':'真实向量服务8766','calls':[],'notes':['实际等待180秒；直接执行main.py原有入库、触发及计时条件；消息从OCR后入口注入，未覆盖OCR和GUI。'],'initial_ids':[],'events':[]}
 calls=record['calls'];gate=threading.Event();entered=threading.Event();hold=ident=='P02'
 original_chat=llm.chat
 record['dedup_calls']=[]
 def dedup_chat(*args,**kwargs):
  call={'started':time.time(),'input':args[5],'system':args[4]};record['dedup_calls'].append(call)
  try:call['raw']=original_chat(*args,**kwargs);return call['raw']
  except Exception as exc:call['error']=str(exc);raise
  finally:call['seconds']=time.time()-call['started']
 llm.chat=dedup_chat
 def chat(*args,**kwargs):
  call={'started':time.time(),'input':args[5],'system':args[4]};calls.append(call)
  if hold and len(calls)==1:entered.set();gate.wait(10)
  try:call['raw']=original_chat(*args,**kwargs);return call['raw']
  except Exception as exc:call['error']=str(exc);raise
  finally:call['seconds']=time.time()-call['started']
 ns=dict(settings=settings,providers=providers,llm=SimpleNamespace(chat=chat),_api_key=_api_key,json=json,datetime=datetime,timedelta=timedelta,add_memory=rag.add_memory,threading=threading,time=time,deque=deque,chats={},MEMORY_WRITE_SYSTEM_PROMPT=SYSTEM_PROMPT)
 record['run_id']=os.environ.get('RAG_EVAL_DIR','reviewed-20261119')
 record['prompt_hash']=hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()
 record['notes'][0]='执行主程序触发与写入逻辑；静默案例真实等待180秒；OCR后注入消息，未覆盖GUI。'
 chosen=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name in {'chat_of','auto_memory_text','trigger_auto_memory','save_memory'}]
 ns.update(build_memory_input=build_memory_input, format_memory_messages=format_memory_messages, has_group_speakers=has_group_speakers)
 exec(compile(ast.Module(body=chosen,type_ignores=[]),'main.py','exec'),ns)
 actual_save=ns['save_memory']
 def save(*args,**kwargs):
  result=actual_save(*args,**kwargs)
  if calls:calls[-1]['result']=result
  record['events'].append({'event':'save_finished','at':time.time(),'result':result})
  return result
 ns['save_memory']=save
 drain=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=='drain')
 msgfor=next(n for n in ast.walk(drain) if isinstance(n,ast.For) and ast.unparse(n.target)=='(who, name, text)')
 # Execute the actual history append and pending-message bookkeeping from drain().
 feedcode=compile(ast.Module(body=msgfor.body[:2],type_ignores=[]),'main.py','exec')
 tick=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=='tick')
 timer=next(n for n in ast.walk(tick) if isinstance(n,ast.For) and ast.unparse(n.target)=='(title, chat)')
 timercode=compile(ast.Module(body=[timer],type_ignores=[]),'main.py','exec')
 def feed(person,messages):
  for who,text in messages:
   ns.update(chat=ns['chat_of'](person),who=who,name='',text=text)
   exec(feedcode,ns)
   record['events'].append({'event':'message','contact':person,'who':who,'text':text,'at':time.time()})
   ns['trigger_auto_memory'](person)
 def wait_idle():
  deadline=time.time()+150
  while any(c['memory_busy'] for c in ns['chats'].values()):
   if time.time()>deadline:raise TimeoutError('model processing timeout')
   time.sleep(.2)
 def silence():
  end=time.time()+181
  while time.time()<end:
   ns['now']=time.time();exec(timercode,ns)
   time.sleep(.25)
  # A suspended host may resume after the loop deadline; perform the due tick.
  ns['now']=time.time();exec(timercode,ns)
  wait_idle()
 def snapshot():
  with rag._connect() as con:
   con.row_factory=sqlite3.Row
   result=[]
   for rr in con.execute('SELECT * FROM memories ORDER BY id'):
    r=dict(rr);blob=r.pop('embedding');v=np.frombuffer(blob,dtype=np.float32) if blob else np.array([])
    r['embedding_dim']=len(v);r['embedding_valid']=bool(len(v)==512 and np.isfinite(v).all() and abs(float(np.linalg.norm(v))-1)<.02)
    result.append(r)
   return result
 try:
  if ident in {'B08','B09','B10','N10','N11','N12'}:
   seed=rag.add_memory(row[5],'other_person',contact,category='event' if ident in {'B08','N12'} else 'fact')
   if not seed:raise RuntimeError('Seed failed')
  record['initial_rows']=snapshot();record['initial_ids']=[r['id'] for r in record['initial_rows']]
  if any(not r['embedding_valid'] for r in record['initial_rows']):
   raise RuntimeError('Precondition failed: seeded memory has no valid embedding')
  messages=[]
  for line in row[4].splitlines():
   m=re.match(r'\[\d+\]\s*(her|me)\s*[：:]\s*(.*)',line)
   if m:messages.append((m[1],m[2]))
   elif line.strip() and messages:messages[-1]=(messages[-1][0],messages[-1][1]+'\n'+line)
  if not messages:raise ValueError('No messages parsed')
  if ident=='P03':
   rag.EMBEDDING_URL='http://127.0.0.1:8767/embed'
   record['embedding_mode']='故障阶段连接无服务端口8767，恢复后使用8766'
   record['notes'].append('以测试进程切换到无服务端口模拟连接拒绝，不关闭其他案例的向量服务。')
  if ident=='P02':
   feed(contact,messages[:10]);entered.wait(10);feed(contact,messages[10:]);gate.set();wait_idle();silence()
   record['notes'].append('首批请求处于处理中时注入第11条；使用闸门控制时序，模型回答未替换。')
  elif ident=='P04':
   feed('联系人甲',messages);silence();feed('联系人乙',messages);silence()
  else:
   feed(contact,messages)
   if len(messages)>=10:wait_idle()
   else:silence()
  if ident=='P03':
   record['failure_phase_rows']=snapshot();rag.EMBEDDING_URL='http://127.0.0.1:8766/embed';time.sleep(2)
   record['recovered_before_backfill']=snapshot();record['manual_backfill_count']=rag.backfill_embeddings()
   record['notes'].append('服务恢复后先检查，再显式调用backfill_embeddings；最终状态含人工补向量。')
  record['final_rows']=snapshot()
  record['pending']={k:len(v['pending_memory']) for k,v in ns['chats'].items()}
 except Exception as exc:
  record['notes'].append('执行异常：'+repr(exc));record['error']=repr(exc);record['final_rows']=snapshot()
 record['elapsed']=round(time.time()-started,2)
 llm.chat=original_chat
 for c in calls:c.setdefault('result','未返回保存结果')
 (OUT/(ident+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
 return record

if __name__=='__main__':
 data=json.loads((OUT/'reviewed_samples.json').read_text(encoding='utf-8'))[1:]
 with ProcessPoolExecutor(max_workers=24) as pool:
  futures={pool.submit(run_case,r):r[0] for r in data};results=[]
  for f in as_completed(futures):
   r=f.result();results.append(r)
   print(json.dumps({'id':r['id'],'calls':len(r['calls']),'rows':len(r['final_rows']),'error':r.get('error'),'elapsed':r['elapsed']},ensure_ascii=True),flush=True)
 results.sort(key=lambda r:next(i for i,x in enumerate(data) if x[0]==r['id']))
 (OUT/'all_results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
 print('ALL_DONE',flush=True)

import ast,json,sys,time,threading
from pathlib import Path
from collections import deque
from datetime import datetime,timedelta
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app import settings
from core import rag,llm,providers
from core.jev_client import _api_key
from core.memory_write_prompt import SYSTEM_PROMPT
from core.memory_input import build_memory_input, format_memory_messages, has_group_speakers
import numpy as np
out=ROOT.parent/'RAG写入评测集/实测记录_v2_20261120'
p=out/'P04.json';d=json.loads(p.read_text(encoding='utf-8'))
assert d['pending'].get('联系人乙')==3 and len(d['calls'])==1
(out/'P04_before_resume.json').write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
settings.llm_key();rag.DB_PATH=out/'P04.sqlite3';rag.EMBEDDING_URL='http://127.0.0.1:8766/embed'
def traced(*a,**kw):
 c={'started':time.time(),'input':a[5],'system':a[4]};d['calls'].append(c)
 try:c['raw']=llm.chat(*a,**kw);return c['raw']
 finally:c['seconds']=time.time()-c['started']
ns=dict(settings=settings,providers=providers,llm=SimpleNamespace(chat=traced),_api_key=_api_key,json=json,datetime=datetime,timedelta=timedelta,add_memory=rag.add_memory,threading=threading,time=time,deque=deque,chats={},MEMORY_WRITE_SYSTEM_PROMPT=SYSTEM_PROMPT)
tree=ast.parse((ROOT/'main.py').read_text(encoding='utf-8'))
ns.update(build_memory_input=build_memory_input, format_memory_messages=format_memory_messages, has_group_speakers=has_group_speakers)
chosen=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'chat_of','auto_memory_text','trigger_auto_memory','save_memory'}]
exec(compile(ast.Module(body=chosen,type_ignores=[]),'main.py','exec'),ns)
save=ns['save_memory']
def capture(*a,**kw):
 result=save(*a,**kw);d['calls'][-1]['result']=result;d['events'].append({'event':'save_finished','at':time.time(),'result':result});return result
ns['save_memory']=capture
chat=ns['chat_of']('联系人乙');messages=[e for e in d['events'] if e['event']=='message' and e['contact']=='联系人乙']
for e in messages:chat['history'].append((e['who'],e['text'],''));chat['pending_memory'].append((e['who'],e['text'],''))
chat['last_memory_at']=messages[-1]['at']
tick=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='tick')
timer=next(n for n in ast.walk(tick) if isinstance(n,ast.For) and ast.unparse(n.target)=='(title, chat)')
ns['now']=time.time();exec(compile(ast.Module(body=[timer],type_ignores=[]),'main.py','exec'),ns)
deadline=time.time()+120
while chat['memory_busy']:
 if time.time()>deadline:raise TimeoutError('resume timeout')
 time.sleep(.2)
with rag._connect() as c:
 c.row_factory=__import__('sqlite3').Row;rows=[]
 for rr in c.execute('SELECT * FROM memories ORDER BY id'):
  r=dict(rr);blob=r.pop('embedding');v=np.frombuffer(blob,dtype=np.float32) if blob else np.array([])
  r['embedding_dim']=len(v);r['embedding_valid']=bool(len(v)==512 and np.isfinite(v).all() and abs(float(np.linalg.norm(v))-1)<.02);rows.append(r)
d['final_rows']=rows;d['pending']['联系人乙']=len(chat['pending_memory'])
d['notes'].append('环境暂停使评测循环错过到期后的最后一次检查；按原消息及时间戳恢复乙的3条pending，执行原tick条件。未重跑甲。此例延迟不可作为正常性能数据。')
d['resumed_at']=datetime.now().isoformat();d['elapsed']=round(time.time()-datetime.fromisoformat(d['started_at']).timestamp(),2)
p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
allp=out/'all_results.json';all=json.loads(allp.read_text(encoding='utf-8'));all=[d if x['id']=='P04' else x for x in all];allp.write_text(json.dumps(all,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'calls':len(d['calls']),'rows':rows,'pending':d['pending']},ensure_ascii=True))

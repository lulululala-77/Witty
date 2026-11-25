"""Gold-memory A/B response experiment; no retrieval or production-memory mutation."""
import ast,json,sys,zipfile,hashlib,time,random,secrets,threading,shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor,as_completed
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from core import engine
from app import settings
BASE=ROOT.parent/'RAG检索评测集'
SOURCE=BASE/'RAG检索评测集_第二批_12条记忆_84条Query.xlsx'
redesigned='--redesigned' in sys.argv
if redesigned:SOURCE=BASE/'RAG回复效果_重设计24组_实验输入.xlsx'
edited='--edited-score' in sys.argv
if edited:SOURCE=BASE/'RAG回复效果_AB盲评_重新设计24组.xlsx'
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
tree=ast.parse((ROOT/'evaluation_run/run_retrieval147.py').read_text(encoding='utf-8'))
fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='workbook_rows')
exec(compile(ast.Module(body=[fn],type_ignores=[]),'<reader>','exec'))
samples=workbook_rows(SOURCE,1,18,25 if redesigned else 85)[1:];memories=workbook_rows(SOURCE,2,8,13)[1:]
if edited:
 raw_rows=workbook_rows(SOURCE,1,25,25)[1:];samples=[];memories=[]
 for r in raw_rows:
  needed=r[23]=='需要正确记忆' or r[0]=='E021' # User explicitly corrected E021.
  mid='EDIT-'+r[0];history=r[3] or ''
  if history.startswith('无'):history=''
  query=history+'\n对方：'+r[4] if history else r[4]
  samples.append([r[0],mid,r[5],'需要正确记忆' if needed else '不需要记忆','对方消息',r[1],'other_person',history or '无',r[4],query,'正确记忆对照',mid if needed else '无','','',None,None,None,'未执行'])
  memories.append([mid,r[1],'other_person','fact',r[5],'用户最新修改',3,'long_term'])
mem={r[0]:r for r in memories}
settings.jev_key();settings.llm_key()
config={'relationship':settings.relationship(),'context':settings.context(),'model':settings.draft_model(),'provider':settings.draft_provider(),'base_url':settings.draft_base_url() or None,'style':settings.style(),'thinking':settings.thinking(),'jev_provider':settings.jev_provider(),'jev_model':settings.jev_model(),'timeout':45}
if '--resume' in sys.argv:
 OUT=Path(sys.argv[sys.argv.index('--resume')+1]);manifest=json.loads((OUT/'manifest.json').read_text(encoding='utf-8'));assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==manifest['source_sha256'];config=manifest['config']
else:
 OUT=BASE/('回复AB实验_'+datetime.now().strftime('%Y%m%d_%H%M%S'));OUT.mkdir()
 rng=random.Random(secrets.randbits(64));indices=list(range(len(samples)));rng.shuffle(indices)
 a_on=[True]*(len(samples)//2)+[False]*(len(samples)//2);rng.shuffle(a_on)
 manifest={'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'config':config,'assumption':'Correct target memories for positive queries; empty for negatives. No retrieval evaluation.','assignments':[{'blind_id':f'E{i+1:03}','source_id':samples[j][0],'a_on':a_on[i]} for i,j in enumerate(indices)]}
 (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');shutil.copy2(SOURCE,OUT/SOURCE.name)
 for f in ['engine.py','draft.py','questions.py','llm.py']:(OUT/f).write_bytes((ROOT/'core'/f).read_bytes())
local=threading.local();orig_ask=engine.ask
def tracked_ask(*args,**kwargs):
 try:
  value=orig_ask(*args,**kwargs);local.events.append({'ok':True,'stage':'ranking' if 'best_reply' in args[1] else 'judgment'});return value
 except Exception as e:
  local.events.append({'ok':False,'stage':'ranking' if 'best_reply' in args[1] else 'judgment','error_type':type(e).__name__});raise
engine.ask=tracked_ask
def execute(row,on):
 local.events=[];start=time.perf_counter();messages=[]
 # J is authoritative, including the user's minor I/J wording difference.
 for line in row[9].splitlines():
  if line.startswith('用户：'):messages.append(('me',line[3:]))
  elif line.startswith('对方：'):messages.append(('her',line[3:]))
  else:messages.append(('her',line))
 required=[] if row[11]=='无' else row[11].split(',')
 memory='\n'.join(f'- [{mem[k][3]}] {mem[k][4]}' for k in required) if on else ''
 # Identity is supplied equally in both arms, not inferred from memory availability.
 kwargs={**config,'relationship':config['relationship']+f'；当前联系人是{row[5]}，her指该联系人，me指用户本人。'}
 try:
  result=engine.analyze(messages,judge_memory=memory,draft_memory=memory,**kwargs)
  good=len(local.events)==2 and all(e['ok'] for e in local.events) and 'best_reply' in result['answers']
  return {'id':row[0],'rag_on':on,'memory':memory,'messages':messages,'result':result,'events':local.events,'full_pipeline_ok':good,'seconds':time.perf_counter()-start}
 except Exception as e:
  return {'id':row[0],'rag_on':on,'memory':memory,'messages':messages,'error_type':type(e).__name__,'events':local.events,'full_pipeline_ok':False,'seconds':time.perf_counter()-start}
prior=[]
if (OUT/'results.jsonl').exists():prior=[json.loads(x) for x in (OUT/'results.jsonl').read_text(encoding='utf-8').splitlines()]
done={(r['id'],r['rag_on']) for r in prior if r['full_pipeline_ok']}
jobs=[(r,on) for r in samples for on in [True,False] if (r[0],on) not in done];random.SystemRandom().shuffle(jobs)
print('RUN_DIR',OUT,'PENDING',len(jobs),flush=True)
with ThreadPoolExecutor(max_workers=4) as pool:
 for n,f in enumerate(as_completed([pool.submit(execute,*job) for job in jobs]),1):
  r=f.result();prior.append(r)
  with (OUT/'results.jsonl').open('a',encoding='utf-8') as out:out.write(json.dumps(r,ensure_ascii=False)+'\n')
  if n%12==0 or not r['full_pipeline_ok']:print('COMPLETED',n,'/',len(jobs),'LATEST_OK',r['full_pipeline_ok'],flush=True)
latest={(r['id'],r['rag_on']):r for r in prior};results=list(latest.values())
summary={'run_dir':str(OUT),'responses':len(results),'full_pipeline_ok':sum(r['full_pipeline_ok'] for r in results),'failed':[{'id':r['id'],'rag_on':r['rag_on'],'events':r['events'],'error_type':r.get('error_type')} for r in results if not r['full_pipeline_ok']],'config':config,'notes':['84 paired cases, 168 responses; gold memory instead of retrieval.','36 negative cases receive no memory in both arms; differences are generation variation.','One run per arm; scores must be supplied by human.','Usage in engine includes Jev only, not complete drafting token cost.']}
(OUT/'all_results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
summary['notes']=[f'{len(samples)} paired cases; gold-memory response comparison, not retrieval evaluation.',f'{sum(r[11]=="无" for r in samples)} empty-memory controls in both arms.','One successful full-pipeline run per arm. Technical failures retried, not quality-selected.']
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
(BASE/('素材/latest_reply_edited.json' if edited else '素材/latest_reply_redesigned.json' if redesigned else '素材/latest_reply_ab.json')).write_text(json.dumps({'run_dir':str(OUT)},ensure_ascii=False),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)

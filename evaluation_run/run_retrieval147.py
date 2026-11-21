"""Seed exact workbook memories; exercise the production retrieve() unchanged."""
import json,sys,time,sqlite3,hashlib,zipfile,xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime,timedelta,timezone
from contextlib import closing
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from core import rag
BASE=ROOT.parent/'RAG检索评测集'
SOURCE=BASE/'RAG检索评测集_21条记忆_147条Query.xlsx'
T=datetime.now(timezone(timedelta(hours=8)))
OUT=BASE/('实测记录_147Query_'+T.strftime('%Y%m%d_%H%M%S'))
OUT.mkdir(exist_ok=False)
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

def workbook_rows(path,sheet_number,last_col,last_row):
    with zipfile.ZipFile(path) as z:
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            strings=[''.join(t.text or '' for t in s.findall('.//m:t',NS)) for s in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        matrix=[[None]*last_col for _ in range(last_row)]
        root=ET.fromstring(z.read(f'xl/worksheets/sheet{sheet_number}.xml'))
        for row in root.findall('m:sheetData/m:row',NS):
            n=int(row.attrib['r'])-1
            if n>=last_row:continue
            for c in row:
                letters=''.join(x for x in c.attrib['r'] if x.isalpha());col=0
                for x in letters:col=col*26+ord(x)-64
                if col>last_col:continue
                v=c.find('m:v',NS);kind=c.attrib.get('t')
                value=v.text if v is not None else None
                if kind=='s':value=strings[int(value)]
                elif kind=='inlineStr':value=''.join(x.text or '' for x in c.findall('.//m:t',NS))
                matrix[n][col-1]=value
        return matrix

samples=workbook_rows(SOURCE,1,18,148)[1:]
memories=workbook_rows(SOURCE,2,8,22)[1:]
assert len(samples)==147 and len(memories)==21
assert len({r[0] for r in samples})==147
(OUT/'source_rows.json').write_text(json.dumps({'samples':samples,'memories':memories},ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'rag.py').write_bytes((ROOT/'core/rag.py').read_bytes())
rag.DB_PATH=OUT/'rag.sqlite3';rag.EMBEDDING_URL='http://127.0.0.1:8766/embed'

def resolve(text):
    fmt=lambda d:d.strftime('%Y年%m月%d日')
    return text.replace('T次日',fmt(T+timedelta(days=1))).replace('T日',fmt(T)).replace('T',fmt(T))

texts=[resolve(r[4]) for r in memories]
vectors=rag._encode(texts)
assert vectors.shape==(21,512) and np.isfinite(vectors).all()
assert np.all(np.abs(np.linalg.norm(vectors,axis=1)-1)<.02)
seed=[]
with closing(rag._connect()) as conn,conn:
    for row,text,vector in zip(memories,texts,vectors):
        mid,contact,dim,cat,_,_,importance,_=row
        expiry=None
        if mid=='M06':expiry=(T.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
        if mid=='M21':expiry=(T+timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
        cur=conn.execute('INSERT INTO memories(dimension,contact,category,content,importance,embedding,expires_at) VALUES(?,?,?,?,?,?,?)',(dim,contact or '',cat,text,int(importance),vector.astype(np.float32).tobytes(),expiry))
        seed.append({'memory_id':mid,'db_id':cur.lastrowid,'contact':contact or '', 'dimension':dim,'category':cat,'content':text,'importance':int(importance),'expires_at':expiry,'embedding_dim':512})
    assert conn.execute('SELECT COUNT(*) FROM memories').fetchone()[0]==21
    assert conn.execute("SELECT COUNT(*) FROM memories WHERE expires_at IS NULL OR expires_at > datetime('now','localtime')").fetchone()[0]==21
(OUT/'seeded_memories.json').write_text(json.dumps(seed,ensure_ascii=False,indent=2),encoding='utf-8')
print('SEEDED 21 valid memories; '+str(OUT),flush=True)
lookup={f"- [{m['category'] or m['dimension']}] {m['content']}":m['memory_id'] for m in seed}
actual_encode=rag._encode
results=[]
for index,row in enumerate(samples):
    ident,target,content,kind,source,contact,dimension,context,current,query,expected,required,forbidden,reason,*_=row
    query=resolve(query);contact=None if contact=='不限定联系人' else contact
    trace={}
    def encode(texts):
        try:
            trace['embedding_input']=texts;v=actual_encode(texts);trace['vector']=v
            return v
        except Exception as exc:trace['error']=str(exc);raise
    rag._encode=encode
    start=time.perf_counter()
    returned=rag.retrieve(query,dimension=dimension,contact=contact,limit=5)
    rag._encode=actual_encode
    if trace.get('error'):raise RuntimeError('Embedding fallback invalidates run: '+trace['error'])
    ids=[]
    for line in returned.splitlines():
        if line not in lookup:raise RuntimeError('Cannot map returned text to memory ID: '+line)
        ids.append(lookup[line])
    need=[] if required=='无' else required.split(',')
    positive=bool(need)
    passed=all(k in ids for k in need) if positive else not ids
    ranked=[]
    qvec=trace['vector'][0];terms=rag._terms(query)
    for m,v in zip(seed,vectors):
        if m['dimension']!=dimension or (contact is not None and m['contact'] not in {contact,''}):continue
        sim=float(np.dot(qvec,v));overlap=len(terms & rag._terms(m['content']))
        ranked.append({'id':m['memory_id'],'similarity':sim,'overlap':overlap,'score':sim*100+overlap+m['importance']*.01,'above_threshold':sim>=.35})
    ranked.sort(key=lambda r:r['score'],reverse=True)
    result={'id':ident,'target':target,'type':kind,'source':source,'query':query,'contact':contact,'dimension':dimension,'expected':expected,'required':need,'actual_ids':ids,'actual_text':returned,'passed':passed,'seconds':round(time.perf_counter()-start,4),'embedding_input':trace['embedding_input'],'candidate_scores':ranked}
    results.append(result)
    with (OUT/'results.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(result,ensure_ascii=False)+'\n')
    if (index+1)%21==0:print(f'COMPLETED {index+1}/147',flush=True)
pos=[r for r in results if r['required']];neg=[r for r in results if not r['required']]
types=list(dict.fromkeys(r['type'] for r in results))
summary={'run_dir':str(OUT),'started_at':T.isoformat(),'source_file':str(SOURCE),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'code_sha256':hashlib.sha256((ROOT/'core/rag.py').read_bytes()).hexdigest(),'memories':21,'queries':147,'positive_hit':[sum(r['passed'] for r in pos),len(pos)],'negative_false_retrieval':[sum(not r['passed'] for r in neg),len(neg)],'overall_pass':[sum(r['passed'] for r in results),len(results)],'by_type':{k:{'passed':sum(r['passed'] for r in results if r['type']==k),'total':sum(r['type']==k for r in results)} for k in types},'limitations':['独立评测库预置标准记忆，不经过写入模型或去重；未修改生产记忆。','真实Embedding；直接执行当前retrieve，limit=5，相似度门槛0.35，无重排或模型核验。','上下文类按组合query输入；不代表GUI自动支持上下文。M13/M14按表中的用户输入测试。','正例只要求目标进入前5条，其他返回项不计误召回；负例要求全部返回空。','此147例均用有效向量和有效记忆，未评估过期过滤或OCR/回复生成。']}
(OUT/'all_results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'metrics_review.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
(BASE/'素材/query147/latest_run.json').write_text(json.dumps({'run_dir':str(OUT)},ensure_ascii=False),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)

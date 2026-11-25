import ast,json,zipfile,hashlib,statistics
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT.parent/'RAG检索评测集'
SOURCE=BASE/'RAG回复效果_AB盲评_修改后24组_E005更新.xlsx'
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
tree=ast.parse((ROOT/'evaluation_run/run_retrieval147.py').read_text(encoding='utf-8'));fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='workbook_rows');exec(compile(ast.Module(body=[fn],type_ignores=[]),'<reader>','exec'))
rows=workbook_rows(SOURCE,1,25,25)[1:]
run=Path(json.loads((BASE/'素材/latest_reply_edited.json').read_text(encoding='utf-8'))['run_dir']);manifest=json.loads((run/'manifest.json').read_text(encoding='utf-8'));raw=json.loads((run/'all_results.json').read_text(encoding='utf-8'))
updated=Path(json.loads((BASE/'素材/latest_e005.json').read_text(encoding='utf-8'))['run_dir']);e005=json.loads((updated/'result.json').read_text(encoding='utf-8'))
records=[];errors=[];mismatches=[]
for i,r in enumerate(rows,2):
 a=next(x for x in manifest['assignments'] if x['blind_id']==r[0]);arms=e005['arms'] if r[0]=='E005' else [x for x in raw if x['id']==a['source_id']]
 on=next(x for x in arms if x['rag_on']);off=next(x for x in arms if not x['rag_on'])
 expectedA=(on if a['a_on'] else off)['result']['best_reply'];expectedB=(off if a['a_on'] else on)['result']['best_reply']
 if r[6]!=expectedA or r[7]!=expectedB or r[4]!=on['messages'][-1][1]:mismatches.append(r[0])
 av=r[8:13];bv=r[14:19]
 if any(str(v) not in ('0','1') for v in av+bv):errors.append({'id':r[0],'A':av,'B':bv});continue
 av=list(map(int,av));bv=list(map(int,bv));ons=av if a['a_on'] else bv;offs=bv if a['a_on'] else av
 d=sum(ons)-sum(offs)
 records.append({'id':r[0],'row':i,'source_id':a['source_id'],'condition':'需要记忆' if on['memory'] else '不需要记忆','on_label':'A' if a['a_on'] else 'B','on_scores':ons,'off_scores':offs,'on_total':sum(ons),'off_total':sum(offs),'difference':d,'outcome':'胜' if d>0 else '负' if d<0 else '平','query':r[4],'reason':r[21] or ''})
def stats(rs):
 n=len(rs)
 return {'n':n,'wins':sum(r['outcome']=='胜' for r in rs),'ties':sum(r['outcome']=='平' for r in rs),'losses':sum(r['outcome']=='负' for r in rs),'win_rate':sum(r['outcome']=='胜' for r in rs)/n if n else None,'on_mean':statistics.mean(r['on_total'] for r in rs) if n else None,'off_mean':statistics.mean(r['off_total'] for r in rs) if n else None,'mean_delta':statistics.mean(r['difference'] for r in rs) if n else None,'dimension_on':[sum(r['on_scores'][j] for r in rs) for j in range(5)],'dimension_off':[sum(r['off_scores'][j] for r in rs) for j in range(5)]}
summary={'source':str(SOURCE),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'invalid_scores':errors,'input_or_reply_mismatch':mismatches,'overall':stats(records),'needs_memory':stats([r for r in records if r['condition']=='需要记忆']),'no_memory':stats([r for r in records if r['condition']=='不需要记忆']),'records':records}
(BASE/'素材/reply_score_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))

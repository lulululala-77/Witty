import json
from pathlib import Path
p=Path(__file__).resolve().parents[2]/'RAG写入评测集/第二批实测记录_20261120'
data=json.loads((p/'all_results.json').read_text(encoding='utf-8'))
units=json.loads((p/'standard_units.json').read_text(encoding='utf-8'))
assert len(data)==12 and not any(r.get('error') for r in data)
new=lambda r:[m for m in r['final_rows'] if m['id'] not in r['initial_ids']]
by={}
for r in data:
 n=new(r);needed=len(units[r['id']])
 assert len(r['calls'])==1
 if needed:assert n
 by[r['id']]={'coverage':'完整保留' if needed else '不应新增，符合预期','support':'是','person':'是','note':'人工逐条对照；仅检查新增记录，原有记录不计为新增。'}
by['N05']['support']='部分：提议被写成原定'
by['N05']['note']='最终四点约定及三点被拒绝均保留；但三点从未达成约定，摘要称“原定”存在状态扩写，严格内容正确率扣分。'
by['N10']['note']='模型save=true；去重核验duplicate_of=1，实际未新增，保留原记录。'
by['N11']['note']='新增芒果过敏完整保留；新摘要带有草莓偏好不判整条误存，因为同时包含新的重要事实。'
by['N12']['note']='取消、退票、暂不重约均保留。旧计划仍在库且未失效，此问题单独记录，不混入三个指标。'
count=sum(len(new(r)) for r in data)
negative=['N08','N09','N10'];fp=[r['id'] for r in data if r['id'] in negative and new(r)]
report={'cases':12,'write_model_calls':12,'dedup_model_calls':sum(len(r['dedup_calls']) for r in data),
 'write_coverage':{'numerator':sum(map(len,units.values())),'denominator':sum(map(len,units.values()))},
 'false_positive':{'numerator':len(fp),'denominator':3,'cases':fp},
 'content_accuracy':{'numerator':count-1,'denominator':count,'incorrect_cases':['N05']},'by_case':by,
 'scope':['新12例；9个应新增案例、3个不应新增案例；按编号拆分为10条标准事实。',
 '写入率按完整覆盖的标准事实计；额外不实表述另扣内容正确率。内容正确率按实际新增数据库记录人工严格初评。',
 '相对日期结合2026-11-20上下文解释；“下个月”保留原文表达。分类/过期策略/旧信息失效不计入三个指标。',
 '真实模型和向量服务，真实等待180秒；OCR后消息注入，不覆盖真实OCR、GUI；本轮无JSON重复字段。',
 '单轮、小样本结果，不与上一批不同案例直接比较模型提升。N05“原定”按严格状态忠实度扣分。']}
(p/'metrics_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))

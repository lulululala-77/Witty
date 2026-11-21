"""Counts for the manually reviewed v4 run, not an automatic semantic grader."""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[2] / 'RAG写入评测集'
OUT = BASE / '实测记录_v4_20261120'
data = json.loads((OUT / 'all_results.json').read_text(encoding='utf-8'))
assert len(data) == 24 and not any(r.get('error') for r in data)
assert all(len(r['calls']) == (2 if r['id']=='P04' else 1) for r in data)
gold = json.loads((BASE / '实测记录/metrics_review.json').read_text(encoding='utf-8'))['standard_units_by_case']
units = {k: [True]*len(v) for k,v in gold.items()}
units['P02'] = [True, False]
negative = ['W004','B02','B04','B06','B10','B12']
newrows = lambda r: [m for m in r['final_rows'] if m['id'] not in r['initial_ids']]
incorrect = {
    'W006': '核心事实覆盖，但摘要使用“她”指沈岚，输入没有提供性别。',
    'B03': '原文联系人表示自己吃香菜、不用单独换一份；摘要改成“不用为用户单独换一份”，对象归属错误。',
    'B07': '原文只说可能去杭州，未说出差；摘要擅自增加“出差”。',
}
duplicate, extra = {}, {}
for r in data:
    for c in r['calls']:
        pairs = json.loads(c['raw'], object_pairs_hook=lambda p:p)
        keys = [k for k,v in pairs]
        repeats = sorted({k for k in keys if keys.count(k)>1})
        unknown = sorted(set(keys)-{'save','category','importance','retention','event_date','summary'})
        if repeats: duplicate.setdefault(r['id'],[]).append(repeats)
        if unknown: extra.setdefault(r['id'],[]).append(unknown)
    if r['id'] in units: assert newrows(r)
records = sum(len(newrows(r)) for r in data)
bad = sum(len(newrows(r)) for r in data if r['id'] in incorrect)
false_positive = [r['id'] for r in data if r['id'] in negative and newrows(r)]
report = {
    'run':OUT.name, 'cases':24,
    'write_model_calls':sum(len(r['calls']) for r in data),
    'dedup_model_calls':sum(len(r['dedup_calls']) for r in data),
    'standard_units_by_case':units,
    'write_coverage':{'numerator':sum(map(sum,units.values())),'denominator':sum(map(len,units.values()))},
    'false_positive':{'numerator':len(false_positive),'denominator':len(negative),'cases':false_positive},
    'content_accuracy':{'numerator':records-bad,'denominator':records,'incorrect':incorrect},
    'duplicate_json_fields':duplicate, 'extra_json_fields':extra,
    'observations':{
        'B10':'核验返回duplicate_of=1，仅保留原记忆，未新增重复记录。',
        'B09':'核验返回duplicate_of=null，搬家新事实入库；旧上海住址仍未失效。',
        'B08':'取消信息入库；日期元数据不同，未进入核验；旧计划仍未失效。',
        'P02':'首批结束清空pending，执行中到达的第11条“对虾过敏”仍漏存。',
        'P03':'故障时正文有记录但无向量；恢复后未自动补全，测试显式backfill才补全。',
        'W006':'六个字段各重复三次，解析采用最后值；本次没有因此漏掉核心标准事实。',
    },
    'scope':[
        '沿用原24条必存事实；B03/B05允许保存但不追加为强制写入事实；误存按剩余6个负样本计。',
        '内容正确率按新增数据库记录人工复核，检查无依据扩写、性别、对象归属与限定；遗漏另计覆盖率。',
        '与v3严格口径一致；单轮模型随机输出，不能把摘要正确率波动归因于去重改动。',
        '从OCR后消息入口注入，真实等待180秒；未覆盖OCR、GUI和群聊模型输出。',
        'P03最终向量包含显式人工补全；正文写入率不代表自动向量恢复成功。',
        '保留原评测的相对时间口径：结合本轮2026-11-20的上下文/记录时间解释。',
    ],
}
(OUT/'metrics_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['RAG写入复测：0.80候选召回+模型核验','',f"24个案例，{report['write_model_calls']}次写入模型调用，{report['dedup_model_calls']}次去重核验调用。",'']
for title,key in [('应存写入率','write_coverage'),('误存率','false_positive'),('已写内容正确率','content_accuracy')]:
    m=report[key];lines.append(f"{title}：{m['numerator']}/{m['denominator']} = {m['numerator']/m['denominator']:.1%}")
lines+=['','内容错误：']+[f'{k}：{v}' for k,v in incorrect.items()]
lines+=['','其他观察：']+[f'{k}：{v}' for k,v in report['observations'].items()]
lines+=['','评分口径与局限：']+report['scope']+['','逐案实际新增内容：']
for r in data:
    lines.append('\n'+r['id'])
    if not newrows(r):lines.append('无新增记录。')
    for m in newrows(r):lines.append(f"联系人={m['contact']}；有效向量={m['embedding_valid']}；到期={m['expires_at']}\n{m['content']}")
(OUT/'复测结论.txt').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))

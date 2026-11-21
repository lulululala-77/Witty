import json
from pathlib import Path
base=Path(__file__).resolve().parents[2]/'RAG写入评测集'
out=base/'实测记录_v2_20261120'
data=json.loads((out/'all_results.json').read_text(encoding='utf-8'))
old=json.loads((base/'实测记录/all_results.json').read_text(encoding='utf-8'))
gold=json.loads((base/'实测记录/metrics_review.json').read_text(encoding='utf-8'))['standard_units_by_case']
new={k:list(v) for k,v in gold.items()}
new['W001']=[True];new['W006']=[False,False,False]
newrows=lambda x:[r for r in x['final_rows'] if r['id'] not in x['initial_ids']]
for x in data:
 if x['id'] in new and not newrows(x):new[x['id']]=[False]*len(new[x['id']])
neg=['W004','B02','B04','B06','B10','B12']
dups={}
for x in data:
 for c in x['calls']:
  pairs=json.loads(c['raw'],object_pairs_hook=lambda p:p)
  seen=set();keys=[]
  for k,v in pairs:
   if k in seen:keys.append(k)
   seen.add(k)
  if keys:dups.setdefault(x['id'],[]).append(keys)
obs={
 'W001':'相比旧版补充小学阶段。',
 'W005':'模型重复输出category/importance/retention/event_date/summary字段；同值覆盖，本次仍成功入库。',
 'W006':'模型同时输出save:true与末尾save:false；Python解析取最后值，因此三项标准记忆均未实际入库。',
 'B03':'用户已复核为允许保存，本轮不计误存。',
 'B05':'用户已复核为允许保存临时要求，本轮不计误存；相对日期按实际运行日处理。',
 'B08':'取消信息已入库，预置旧计划仍保留且未失效。',
 'B09':'新住址已入库，预置旧住址仍保留且未失效。',
 'B10':'同义重复记忆仍被新增。',
 'B11':'重复save字段均为true，本次未阻止入库。',
 'P02':'第11条对虾过敏仍漏存；首批结束后待处理队列清空。',
 'P03':'故障时向量缺失；最终有效向量由显式backfill_embeddings补全。',
 'P04':'两个联系人同义记忆分别检查绑定；详见两条实际记录。'
}
report={'standard_units_by_case':new,'original_scope':{'old':{'written':sum(map(sum,gold.values())),'total':sum(map(len,gold.values()))},'new':{'written':sum(map(sum,new.values())),'total':sum(map(len,new.values()))}},'accepted_B03_B05_scope':{'old':{'written':sum(map(sum,gold.values()))+2,'total':sum(map(len,gold.values()))+2},'new':{'written':sum(map(sum,new.values()))+2,'total':sum(map(len,new.values()))+2}},'false_positive':{'old':[x['id'] for x in old if x['id'] in neg and newrows(x)],'new':[x['id'] for x in data if x['id'] in neg and newrows(x)],'negative_total':6},'content_accuracy':{'scope':'新增记录已写内容的语义忠实度人工初判，不含遗漏/必要性/分类/向量/旧记录失效','old_correct':20,'old_total':20,'new_correct':sum(len(newrows(x)) for x in data),'new_total':sum(len(newrows(x)) for x in data)},'duplicate_json_fields':dups,'observations':obs,'verdicts':{'W006':'未入库：重复save覆盖','P02':'部分保留：漏第11条'},'limitations':['单轮随机输出，不能认定新prompt稳定提升或退化','相对时间：旧实验2026-11-19，新实验2026-11-20','提示词示例与测试题材重合','新增记录内容忠实度为人工初判，独立于JSON格式合规']}
(out/'metrics_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=True,indent=2))

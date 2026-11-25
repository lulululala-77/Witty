"""Offline threshold sweep over frozen scores; no model calls or label changes."""
import json
import statistics
from pathlib import Path

base = Path(__file__).resolve().parents[2] / 'RAG检索评测集'
run = base / '实测记录_147Query_20261121_111104'
rows = json.loads((run / 'all_results.json').read_text(encoding='utf-8'))
positives = [r for r in rows if r['required']]
negatives = [r for r in rows if not r['required']]

def describe(values):
    values = sorted(values)
    return {'n': len(values), 'mean': statistics.mean(values),
            'median': statistics.median(values), 'min': min(values), 'max': max(values)}

target_scores = [c['similarity'] for r in positives for c in r['candidate_scores'] if c['id'] in r['required']]
false_pairs = [c['similarity'] for r in negatives for c in r['candidate_scores'] if c['id'] in r['actual_ids']]
false_query_max = [max(c['similarity'] for c in r['candidate_scores'] if c['id'] in r['actual_ids']) for r in negatives if r['actual_ids']]
table = []
for threshold in [.35, .375, .40, .425, .45, .475, .50, .525, .55, .60, .65, .70]:
    hits = false = calls = pairs = 0
    lost = []
    for r in rows:
        selected = [c for c in r['candidate_scores'] if c['similarity'] >= threshold][:5]
        ids = {c['id'] for c in selected}
        calls += bool(ids)
        pairs += len(ids)
        if r['required']:
            ok = set(r['required']).issubset(ids)
            hits += ok
            if not ok: lost.append(r['id'])
        else: false += bool(ids)
    table.append({'threshold':threshold, 'positive_hit':hits, 'positive_total':84,
                  'negative_false':false, 'negative_total':63, 'model_calls':calls,
                  'candidate_pairs':pairs, 'lost_positive_ids':lost})
output = {'source':str(run), 'correct_target_pairs':describe(target_scores),
          'false_returned_pairs_on_negative_queries':describe(false_pairs),
          'max_false_similarity_per_failed_negative_query':describe(false_query_max),
          'by_type_target':{t:describe([c['similarity'] for r in positives if r['type']==t for c in r['candidate_scores'] if c['id'] in r['required']]) for t in dict.fromkeys(r['type'] for r in positives)},
          'lowest_positive_targets':sorted([{'id':r['id'],'query':r['query'],'similarity':c['similarity']} for r in positives for c in r['candidate_scores'] if c['id'] in r['required']],key=lambda x:x['similarity'])[:10],
          'sweep':table,
          'notes':['误召回只使用标准要求返回空的63条query；不把正例的其他候选默认标错。',
                   '保持原排序分数和top5，仅改变语义相似度过滤门槛。',
                   '调用数为有候选的query数；单次核验整批候选。不是费用金额。',
                   '未重新调用模型；候选集变化后的最终核验效果不能从此表推断。']}
out = base / '素材/query147/threshold_analysis.json'
out.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(output,ensure_ascii=False,indent=2))

"""Reproduce counts from this run's manually reviewed facts; not a generic grader."""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[2] / 'RAG写入评测集'
OUT = BASE / '实测记录_v3_20261120_retry'
data = json.loads((OUT / 'all_results.json').read_text(encoding='utf-8'))
assert len(data) == 24 and not any(r.get('error') for r in data)
assert all(len(r['calls']) == (2 if r['id'] == 'P04' else 1) for r in data)
gold = json.loads((BASE / '实测记录/metrics_review.json').read_text(encoding='utf-8'))['standard_units_by_case']
units = {k: [True] * len(v) for k, v in gold.items()}
units['P02'] = [True, False]
negative = ['W004', 'B02', 'B04', 'B06', 'B10', 'B12']
newrows = lambda r: [m for m in r['final_rows'] if m['id'] not in r['initial_ids']]
incorrect = {
    'W006': '原文怕猫、不想养猫被扩写为“不喜欢养猫”；“暂时没有养狗计划”省略了“暂时”。核心标准事实仍已覆盖。',
    'B05': '“给她打电话”加入了未提供的性别信息；原文及输入未说明叶青的性别。临时要求本身提取正确。',
}
observations = {
    'P02': '总结期间到达的第11条“对虾过敏”未进入模型输入，首批结束后pending被清空，属于程序队列问题。',
    'B10': '初始与新增记录均有有效向量；相似度0.839635低于当前去重阈值0.90，重复新增。',
    'B08': '取消信息入库，但旧露营计划未失效。',
    'B09': '新住址入库，但旧上海住址未失效。',
    'P03': '故障时正文入库而向量为空；服务恢复后仍为空，本轮显式调用backfill_embeddings才补全1条。',
    'W005': 'summary仍使用“今年”，需结合写入时间解释，未落实为绝对年份。',
    'B05': 'summary仍使用“今天”；today保存7天，适用时间与保存期限不同。',
}
duplicate, extra = {}, {}
allowed = {'save', 'category', 'importance', 'retention', 'event_date', 'summary'}
for r in data:
    for call in r['calls']:
        pairs = json.loads(call['raw'], object_pairs_hook=lambda p: p)
        keys = [k for k, _ in pairs]
        repeat = sorted({k for k in keys if keys.count(k) > 1})
        if repeat: duplicate.setdefault(r['id'], []).append(repeat)
        unknown = sorted(set(keys) - allowed)
        if unknown: extra.setdefault(r['id'], []).append(unknown)
    if r['id'] in units: assert newrows(r)
total_records = sum(len(newrows(r)) for r in data)
bad_records = sum(len(newrows(r)) for r in data if r['id'] in incorrect)
false_positive = [r['id'] for r in data if r['id'] in negative and newrows(r)]
report = {
    'run': OUT.name, 'cases': len(data), 'model_calls': sum(len(r['calls']) for r in data),
    'standard_units_by_case': units,
    'write_coverage': {'numerator': sum(map(sum, units.values())), 'denominator': sum(map(len, units.values())), 'definition': '沿用原24条必存标准事实；B03/B05仅允许保存，不追加为必存事实。额外错误另计内容正确率。'},
    'false_positive': {'numerator': len(false_positive), 'denominator': len(negative), 'cases': false_positive, 'negative_cases': negative},
    'content_accuracy': {'numerator': total_records - bad_records, 'denominator': total_records, 'definition': '按新增数据库记录人工复核；有任何无依据扩写、限定丢失或性别推断即不计为完全正确。重复但忠实的内容仍计正确，必要性由误存率衡量。遗漏由覆盖率衡量。不含分类、过期策略、旧记录失效及向量可用性。', 'incorrect': incorrect},
    'duplicate_json_fields': duplicate, 'extra_json_fields': extra,
    'observations': observations,
    'limitations': ['单轮结果不能证明稳定提升；新旧评分严格程度可能不同，尤其本轮显式检查无依据性别。', '从OCR后消息入口注入，未覆盖真实OCR和GUI；原24例无群聊，群聊只做了输入构造回归测试。', '相对日期按实际运行日2026-11-20解释，非样本标注日期。', '首次运行受环境暂停与连接异常影响，保留在实测记录_v3_20261120，不纳入本次指标。', '静默测试真实等待180秒；P03最终向量包含人工补全，不能据此声称自动恢复。'],
}
(OUT / 'metrics_review.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
lines = ['RAG写入复测结果（联系人信息接入后）', '', '24个案例；25次模型调用。5项人物信息输入回归测试通过。', '']
for title, key in [('应存写入率', 'write_coverage'), ('误存率', 'false_positive'), ('已写内容正确率', 'content_accuracy')]:
    m = report[key]; lines.append(f"{title}：{m['numerator']}/{m['denominator']} = {m['numerator']/m['denominator']:.1%}")
lines += ['', '漏存：P02第11条对虾过敏。误存：B10重复香菜偏好。', '内容不完全正确：'] + [f'{k}：{v}' for k,v in incorrect.items()]
lines += ['', '格式问题：' + json.dumps({'重复字段': duplicate, '额外字段': extra}, ensure_ascii=False), '', '其他观察：'] + [f'{k}：{v}' for k,v in observations.items()]
lines += ['', '口径与局限：'] + report['limitations'] + [report['write_coverage']['definition'], report['content_accuracy']['definition'], '', '逐案实际新增内容：']
for r in data:
    lines.append(f"\n{r['id']}：")
    rows = newrows(r)
    if not rows: lines.append('未新增记录。')
    for m in rows: lines.append(f"联系人={m['contact']}；有效向量={m['embedding_valid']}；到期={m['expires_at']}\n{m['content']}")
(OUT / '复测结论.txt').write_text('\n'.join(lines), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))

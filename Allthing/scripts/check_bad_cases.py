import sys, json
sys.path.insert(0, '.')
from tools.knowledge.knowledge_tools import _build_index

entries, _ = _build_index()
all_titles = [e['title'] for e in entries]

gs = json.load(open('data/rag_golden_set.json', 'r', encoding='utf-8'))
bad_ids = ['q004', 'q008', 'q009', 'q010', 'q011', 'q019', 'q026', 'q028']

print('=== Bad Case 期望标题 是否存在于知识库 ===')
for q in gs:
    if q['id'] in bad_ids:
        print(f"\n{q['id']} {q['question'][:50]}")
        for t in q['expected_titles']:
            found = t in all_titles
            mark = '✅' if found else '❌'
            print(f"  {mark} {t[:70]}")
            if not found:
                # 模糊匹配
                for at in all_titles:
                    if t[:10] in at or at[:10] in t:
                        print(f"     → 可能匹配: {at[:70]}")
                        break
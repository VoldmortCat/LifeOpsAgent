import sys, json
sys.path.insert(0, '.')
from tools.knowledge.knowledge_tools import search_knowledge

# 测试 hybrid 模式
r = search_knowledge.func(query='石岐区乳鸽推荐', max_results=5, city='中山', mode='hybrid')
d = json.loads(r)
print('mode=hybrid 石岐区乳鸽推荐:')
for rr in d['results']:
    score = rr['confidence']['score']
    title = rr['title'][:60]
    print(f'  [{score:.4f}] {title}')

print()

# 测试 baseline
r2 = search_knowledge.func(query='石岐区乳鸽推荐', max_results=5, city='中山', mode='vector')
d2 = json.loads(r2)
print('mode=vector (baseline) 石岐区乳鸽推荐:')
for rr in d2['results']:
    score = rr['confidence']['score']
    title = rr['title'][:60]
    print(f'  [{score:.4f}] {title}')
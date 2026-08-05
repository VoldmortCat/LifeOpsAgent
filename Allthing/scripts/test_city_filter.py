import sys, json
sys.path.insert(0, '.')
from tools.knowledge.knowledge_tools import search_knowledge

# 测试1: 中山问烧烤
r1 = search_knowledge.func(query='烧烤店推荐', max_results=5, city='中山')
d1 = json.loads(r1)
print('=== 中山 (city=中山) ===')
print('city_match_summary:', d1.get('city_match_summary', ''))
for r in d1['results']:
    cd = r.get('city_detected', '?')
    print(f'  [{r["confidence"]["score"]:.4f}] {r["title"][:55]} | city={cd}')

print()

# 测试2: 深圳问烧烤
r2 = search_knowledge.func(query='烧烤店推荐', max_results=5, city='深圳')
d2 = json.loads(r2)
print('=== 深圳 (city=深圳) ===')
print('city_match_summary:', d2.get('city_match_summary', ''))
for r in d2['results']:
    cd = r.get('city_detected', '?')
    print(f'  [{r["confidence"]["score"]:.4f}] {r["title"][:55]} | city={cd}')

print()

# 测试3: 不传 city
r3 = search_knowledge.func(query='烧烤', max_results=5, city='')
d3 = json.loads(r3)
print('=== 不限 city ===')
for r in d3['results']:
    cd = r.get('city_detected', '?')
    print(f'  [{r["confidence"]["score"]:.4f}] {r["title"][:55]} | city={cd}')
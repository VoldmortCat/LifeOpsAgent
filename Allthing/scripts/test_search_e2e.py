#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E2E 验收：search_knowledge 完整走 Milvus 主路径"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.knowledge.knowledge_tools import search_knowledge, _MILVUS_ENABLED

print("Milvus 后端启用:", _MILVUS_ENABLED)
print("=" * 66)

tests = [
    ("带爸妈去中山玩两天去哪合适", "中山", 0),   # 场景路由:亲子
    ("月底没钱了想吃点好的", "中山", 35),         # 预算过滤+省钱场景
    ("深夜烧烤哪家好", "深圳", 0),                # 城市隔离+宵夜场景
    ("推荐好吃的乳鸽", "中山", 0),                # 常规美食
]
for q, city, mp in tests:
    print("【查询】%s | city=%s | max_price=%s" % (q, city, mp or "-"))
    r = json.loads(search_knowledge.func(q, max_results=3, city=city, max_price=mp))
    if "error" in r:
        print("  ERROR:", r["error"]); continue
    sr = r.get("semantic_routing")
    if sr:
        print("  语义路由:", sr["activated_tags"], "|", sr["note"])
    if "price_filter" in r:
        print("  价格过滤:", r["price_filter"])
    if "city_match_summary" in r:
        print("  城市:", r["city_match_summary"][:50])
    for x in r["results"]:
        bd = x["confidence"]["breakdown"]
        cm = {True:"匹配", False:"不匹配"}.get(x.get("city_match"), "-")
        print("    [%.4f] %s | %s | vec=%.3f bm25融合后余弦=%.3f tag=%s sem=%s"
              % (x["confidence"]["score"], x["title"][:26], cm,
                 bd["vector_similarity"], bd["vector_similarity"],
                 bd["tag_match_boost"], bd["semantic_tag_boost"]))
    print("-" * 66)
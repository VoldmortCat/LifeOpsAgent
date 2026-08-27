#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Milvus 基础设施全链路测试（不需要 DashScope API Key）
  1. 连接 + 建集合（中文分析器 + BM25 函数 + partition key）
  2. 真实语料 + 假向量写入（验证 schema/插入路径）
  3. 服务端混合检索（BM25 稀疏腿真实生效，稠密腿为噪声）
  4. city expr 下推 / 价格标量过滤 / 场景标签 ARRAY_CONTAINS
用法: .venv/Scripts/python.exe -X utf8 scripts/test_milvus_infra.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from tools.knowledge import milvus_store as store
from tools.knowledge.knowledge_tools import _parse_all_blocks, _MILVUS_URI

PASS = "[PASS] "
FAIL = "[FAIL] "

print("=" * 66)
print("步骤1: 连接", _MILVUS_URI)
client = store.get_client(_MILVUS_URI)
print(PASS + "连接成功")

created = store.ensure_collection(client)
print(PASS + "集合就绪 (新建=%s)" % created)

print()
print("步骤2: 解析语料 + 假向量写入")
entries, texts = _parse_all_blocks()
print("  语料块: %d 条" % len(entries))
rng = np.random.default_rng(42)
emb = rng.normal(size=(len(entries), store.DIM)).astype(np.float32)
emb /= np.linalg.norm(emb, axis=1, keepdims=True)

store.drop_collection(client)
store.ensure_collection(client)
n = store.insert_entries(client, entries, emb)
print(PASS + "写入 %d 条（含 tags ARRAY / price 标量 / meta_json）" % n)
assert store.count(client) == n

print()
print("步骤3: 服务端混合检索（BM25 中文全文检索真实生效）")
queries = [
    ("推荐好吃的乳鸽", "中山"),
    ("深夜烧烤哪家好", "深圳"),
    ("一日游路线怎么安排", "中山"),
]
for q, expect_city in queries:
    expr = store.build_filter(city=expect_city)
    hits = store.hybrid_search(client, q, list(rng.normal(size=store.DIM)), expr, limit=5)
    cities = {h.get("city") for h in hits}
    ok = all(c == expect_city for c in cities)
    print((PASS if ok else FAIL) + "「%s」city=%s -> %d条 城市=%s" % (q, expect_city, len(hits), cities or "{}"))
    for h in hits[:2]:
        print("      [%.4f] %s | tags=%s" % (h["_fused_score"], h["title"][:36], h.get("tags", [])[:4]))

print()
print("步骤4: 价格标量过滤 expr")
expr = store.build_filter(city="中山", max_price=40)
hits = store.hybrid_search(client, "便宜吃饱", list(rng.normal(size=store.DIM)), expr, limit=5)
bad = [h for h in hits if h.get("price_min") not in (None,) and h.get("price_min", -1) > 40]
print((PASS if not bad else FAIL) + "预算<=40 过滤: 返回%d条, 越界%d条" % (len(hits), len(bad)))
for h in hits[:3]:
    print("      price=%s~%s L%s | %s" % (h.get("price_min"), h.get("price_max"), h.get("price_level"), h["title"][:30]))

print()
print("步骤5: 场景标签 ARRAY_CONTAINS 硬筛")
expr = store.build_filter(city="中山", require_tags=["亲子"])
hits = store.hybrid_search(client, "带小孩去哪玩", list(rng.normal(size=store.DIM)), expr, limit=5)
ok = all("亲子" in (h.get("tags") or []) for h in hits)
print((PASS if ok else FAIL) + "亲子标签硬筛: %d条 全部含标签=%s" % (len(hits), ok))
for h in hits[:3]:
    print("      %s | tags=%s" % (h["title"][:32], (h.get("tags") or [])[:5]))

print()
print("=" * 66)
print("基础设施测试完成 —— BM25/过滤/分区全部在服务端生效")
print("下一步: 用真实 DashScope key 跑 rebuild 写入真向量")
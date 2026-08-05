#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
重建向量库 — 加 frontmatter 后强制重建，验证 city/category 字段正确注入。
用法: conda run -n base python scripts/rebuild_vectordb.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shutil
from pathlib import Path
from config.config_loader import config

VECTORDB_DIR = Path(config.get("paths.vectordb_dir", "data/vectordb"))

print("=" * 60)
print("步骤1：删除旧向量库，强制重建")
print("=" * 60)
if VECTORDB_DIR.exists():
    shutil.rmtree(VECTORDB_DIR)
    print(f"✅ 已删除: {VECTORDB_DIR}")
else:
    print(f"（目录不存在，跳过）: {VECTORDB_DIR}")

print()
print("=" * 60)
print("步骤2：重建索引（会调 DashScope embedding API）")
print("=" * 60)
from tools.knowledge.knowledge_tools import _build_index, _hybrid_search

entries, emb_matrix = _build_index()
print(f"✅ 索引重建完成")
print(f"   条目数: {len(entries)}")
print(f"   向量矩阵: {emb_matrix.shape}")

print()
print("=" * 60)
print("步骤3：验证 frontmatter 字段是否正确注入")
print("=" * 60)
city_count = {}
category_count = {}
for e in entries:
    c = e.get("city", "未知")
    cat = e.get("category", "未知")
    city_count[c] = city_count.get(c, 0) + 1
    category_count[cat] = category_count.get(cat, 0) + 1

print(f"城市分布: {city_count}")
print(f"类别分布: {category_count}")

print()
print("前5条条目示例:")
for i, e in enumerate(entries[:5]):
    print(f"  [{i}] city={e.get('city','?')} | category={e.get('category','?')} | title={e['title'][:40]}")

print()
print("=" * 60)
print("步骤4：测试检索（验证前置过滤生效）")
print("=" * 60)
test_queries = [
    ("乳鸽哪家好吃", "中山"),
    ("中山一日游怎么玩", "中山"),
]

for q, city in test_queries:
    print(f"\n查询: {q} | city={city}")
    results = _hybrid_search(q, entries, emb_matrix, 3)
    for r in results:
        print(f"  [{r['_score']:.4f}] city={r.get('city','?')} | {r['title'][:40]}")

print()
print("=" * 60)
print("✅ 重建完成！向量库已带 frontmatter 元数据。")
print("=" * 60)

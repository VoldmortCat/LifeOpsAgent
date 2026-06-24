#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 ChromaDB 持久化 + 标签自动提取效果"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.knowledge.knowledge_tools import (
    _load_from_chromadb, _build_index, _hybrid_search,
    _extract_query_tags, _extract_tags
)

db_entries, db_embeddings, db_mtime = _load_from_chromadb()
print(f"ChromaDB 存储: {len(db_entries) if db_entries else 0} 条段落")
print(f"构建时间戳: {db_mtime}")
print()

entries, emb_matrix = _build_index()
print(f"加载完成: {len(entries)} 个段落, 向量维度 {emb_matrix.shape}")
print(f"来源: {'ChromaDB 磁盘持久化' if db_entries else 'API 新构建'}")
print()

# 随机抽几个条目看标签
print("=" * 60)
print("标签提取示例（随机抽5条）:")
print("=" * 60)
import random
random.seed(42)
for e in random.sample(entries, min(5, len(entries))):
    title = e.get('title', '')[:60]
    tags = e.get('tags', [])
    print(f"  [{e.get('source_file', '')}] {title}")
    print(f"    标签: {', '.join(tags) if tags else '(无)'}")
    print()

# 测试搜索
print("=" * 60)
print("搜索测试:")
print("=" * 60)
test_queries = [
    "乳鸽哪家好吃",
    "深中通道怎么走",
    "石岐区早茶推荐",
    "温泉住宿",
    "带小孩去哪玩",
]
for q in test_queries:
    query_tags = _extract_query_tags(q)
    r = _hybrid_search(q, entries, emb_matrix, 3)
    print(f"\n搜索 '{q}'")
    print(f"  查询标签: {', '.join(query_tags) if query_tags else '(无)'}")
    for x in r:
        title = x.get('title', '')[:50]
        tags = x.get('tags', [])
        score = x.get('_score', 0)
        vec = x.get('_vector_score', 0)
        kw = x.get('_kw_boost', 0)
        tg = x.get('_tag_boost', 0)
        # 信心等级
        if score >= 0.70:
            level = "确信"
        elif score >= 0.45:
            level = "比较确信"
        else:
            level = "低确信"
        print(f"  [{x.get('source_file', '')}] {title}")
        print(f"    标签: {', '.join(tags) if tags else '(无)'}")
        print(f"    置信: {score:.4f} ({level})  [向量{vec:.4f} + 关键词{kw:.4f} + 标签{tg:.4f}]")

print()
vectordb_path = "data/vectordb"
print(f"磁盘位置: {os.path.abspath(vectordb_path)}")
for f in sorted(os.listdir(vectordb_path)):
    fpath = os.path.join(vectordb_path, f)
    if os.path.isfile(fpath):
        size = os.path.getsize(fpath)
        print(f"  {f}  ({size/1024:.1f} KB)")
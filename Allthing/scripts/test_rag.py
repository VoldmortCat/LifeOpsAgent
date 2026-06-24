#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""RAG 向量检索快速验证 — 适配新版 entry 结构（title/content/tags/category）"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.knowledge.knowledge_tools import _build_index, _hybrid_search

entries, emb_matrix = _build_index()
print(f"索引条目数: {len(entries)}")
print(f"向量矩阵: {emb_matrix.shape}")
print()

# 测试1：乳鸽推荐（精确关键词 + 标签匹配）
print("=== 搜索: 乳鸽哪家好吃 ===")
for r in _hybrid_search("乳鸽哪家好吃", entries, emb_matrix, 3):
    print(f"  [{r['_score']:.4f}] {r['title']} | 标签: {r['tags']} | 来源: {r['source_file']}")
    print(f"    内容: {r['content'][:120]}...")

print()

# 测试2：语义搜索 — 自然语言描述
print("=== 搜索: 想吃皮脆多汁的烤鸽子 ===")
for r in _hybrid_search("想吃皮脆多汁的烤鸽子", entries, emb_matrix, 3):
    print(f"  [{r['_score']:.4f}] {r['title']} | 标签: {r['tags']}")
    print(f"    内容: {r['content'][:120]}...")

print()

# 测试3：早茶推荐
print("=== 搜索: 便宜实惠的早茶点心 ===")
for r in _hybrid_search("便宜实惠的早茶点心", entries, emb_matrix, 3):
    print(f"  [{r['_score']:.4f}] {r['title']} | 标签: {r['tags']}")
    print(f"    内容: {r['content'][:120]}...")

print()

# 测试4：跨分类语义 — 海鲜
print("=== 搜索: 想吃海鲜大餐 ===")
for r in _hybrid_search("想吃海鲜大餐", entries, emb_matrix, 3):
    print(f"  [{r['_score']:.4f}] {r['title']} | 标签: {r['tags']}")
    print(f"    内容: {r['content'][:120]}...")

print()

# 测试5：景点推荐
print("=== 搜索: 中山一日游怎么玩 ===")
for r in _hybrid_search("中山一日游怎么玩", entries, emb_matrix, 3):
    print(f"  [{r['_score']:.4f}] {r['title']} | 标签: {r['tags']}")
    print(f"    内容: {r['content'][:120]}...")

print()

# 测试6：预算约束搜索
print("=== 搜索: 月底省钱人均30以下吃什么 ===")
for r in _hybrid_search("月底省钱人均30以下吃什么", entries, emb_matrix, 3):
    print(f"  [{r['_score']:.4f}] {r['title']} | 标签: {r['tags']}")
    print(f"    内容: {r['content'][:120]}...")

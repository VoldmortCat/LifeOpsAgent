#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证置信度阈值：相关查询命中，不相关查询返回空"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.knowledge.knowledge_tools import _build_index, _hybrid_search, CONFIDENCE_THRESHOLD

entries, emb_matrix = _build_index()
print(f"置信度阈值: {CONFIDENCE_THRESHOLD}")
print()

# 相关查询 → 应该命中
print("=== 想吃皮脆多汁的烤鸽子 ===")
r = _hybrid_search("想吃皮脆多汁的烤鸽子", entries, emb_matrix, 3)
for x in r:
    print(f"  {x['restaurant']} | {x['dish']} | 得分 > {CONFIDENCE_THRESHOLD}")
print(f"结果数: {len(r)}")
print()

# 不相关查询 → 应该返回空
print("=== 推荐修车的地方 ===")
r = _hybrid_search("推荐修车的地方", entries, emb_matrix, 3)
print(f"结果数: {len(r)}")
print()

# 跨域查询 → 应该返回空
print("=== 附近有没有加油站 ===")
r = _hybrid_search("附近有没有加油站", entries, emb_matrix, 3)
print(f"结果数: {len(r)}")
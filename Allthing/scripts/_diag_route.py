# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.knowledge.knowledge_tools import _embed_query_cached, _get_tag_matrix, TAG_SEMANTIC_THRESHOLD
import numpy as np

cases = [
    ("带爸妈去中山玩两天去哪合适", ["亲子"]),
    ("情人节和女朋友去哪浪漫一下", ["情侣"]),
    ("深夜烧烤哪家好", ["烧烤", "宵夜"]),
    ("想拍好看的照片发朋友圈", ["网红打卡"]),
    ("有没有泡温泉推荐", ["温泉"]),
    ("想吃点地道的早茶点心", ["早茶"]),
    ("中山天气怎么样", []),          # 反例：不应激活任何标签
]
names, mat = _get_tag_matrix()
THRESH = TAG_SEMANTIC_THRESHOLD
all_ok = True
for query, expect in cases:
    qvec = _embed_query_cached(query)
    qn = qvec / (np.linalg.norm(qvec) + 1e-8)
    scores = mat @ qn
    order = np.argsort(scores)[::-1][:3]
    tops = [(names[int(i)], float(scores[i])) for i in order]
    activated = [t for t, s in tops if s >= THRESH]
    if expect:
        ok = any(e in activated for e in expect)
    else:
        ok = len(activated) == 0
    all_ok &= ok
    mark = "PASS" if ok else "FAIL"
    print("[%s] %s" % (mark, query))
    print("       Top3: " + " | ".join("%s=%.3f%s" % (t, s, "*" if s >= THRESH else "") for t, s in tops))
print()
print("阈值 %.2f 下总体: %s" % (THRESH, "全部通过 ✅" if all_ok else "存在失败 ❌"))

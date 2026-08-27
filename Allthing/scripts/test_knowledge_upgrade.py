#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
知识库 v2 升级验证脚本：
  1. 标签污染修复验证 —— 此前误标的段落现在应打标正确
  2. 价格结构化抽取验证 —— 对真实语料跑 _extract_price，看覆盖率和档位分布
  3. 语义标签路由验证 —— 需要 DASHSCOPE_API_KEY；无 key 时自动跳过
用法: .venv/Scripts/python.exe scripts/test_knowledge_upgrade.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.knowledge.knowledge_tools import (
    _extract_tags, _extract_price, _price_level, _parse_blocks,
    _TAG_DICT, KNOWLEDGE_DIR,
)

total_checks = [0]


def check(name, cond, detail=""):
    total_checks[0] += 1
    mark = "PASS" if cond else "FAIL"
    print("  [" + mark + "] " + name + (("  <" + str(detail) + ">") if detail else ""))
    return cond


print("=" * 70)
print("测试1：标签污染修复（此前实测的三个误标案例）")
print("=" * 70)

# 案例1：孙中山故里曾被单字"山"打成「自然风光」
tags = _extract_tags("孙中山故里旅游区 — 5A景区",
                     "这个景区在南朗街道翠亨村，是中山唯一的5A级景区。包括孙中山故居纪念馆、辛亥革命纪念公园。坐广珠城轨到南朗站下车转公交就能到。")
print("  打标结果:", tags)
check("孙中山故里 不再含「自然风光」(核心：'山'污染已修)", "自然风光" not in tags)
check("孙中山故里 含「历史文化」('故居'命中)", "历史文化" in tags)
check("孙中山故里 含「南朗街道」", "南朗街道" in tags)

# 案例2：爱群食店(早茶)曾被子串"虾"(虾饺)打成「海鲜」
tags = _extract_tags("爱群食店 — 30年老牌早茶馆",
                     "南区街道银潭二路的爱群食店，咖喱金钱肚25一份，上汤虾饺19块钱一笼，黑胡椒牛仔骨38块一份。建议8点前到。")
print("  打标结果:", tags)
check("爱群食店 不再含「海鲜」", "海鲜" not in tags)
check("爱群食店 含「早茶」", "早茶" in tags)
check("爱群食店 不被泛动词打「攻略」", "攻略" not in tags, "『建议8点前到』不应触发")

# 案例3：日出段曾被「凌晨」打成「宵夜」（现改为短语模式）
tags = _extract_tags("深中大桥日出观景台",
                     "凌晨4点多就有摄影发烧友蹲守，日出的时候深中大桥像巨龙卧波金光万丈。3公里的滨海步道很适合拍照。")
print("  打标结果:", tags)
check("日出观景台 不再含「宵夜」", "宵夜" not in tags)
check("日出观景台 含「自然风光」", "自然风光" in tags)

# 反向案例：真海鲜不该漏标
tags = _extract_tags("大喜迎酒家", "坦洲镇坦神北路80号，海盐烤野生九节虾158一份，避风塘炒蟹138都是主打。")
print("  打标结果:", tags)
check("坦洲海鲜店 含「海鲜」", "海鲜" in tags)

# 词库卫生：不允许 <2 字模式混入（防线本身不拦，靠维护纪律+此处断言兜底）
bad = [(t, p) for t, ps in _TAG_DICT.items() for p in ps if len(p) < 2]
check("词库无单字模式", not bad, bad)


print()
print("=" * 70)
print("测试2：价格结构化抽取")
print("=" * 70)

cases = [
    ("人均区间", "人均80到120，现捞现做。", (80, 120)),
    ("人均单值左右", "人均75左右，香茅焗鸽也是招牌", (75, 75)),
    ("人均50多", "人均50多就能吃到撑", (50, 50)),
    ("scene_guide预算行", "人均预算：15-35元", (15, 35)),
    ("人均<30", "人均<30元，吃饱吃好", (0, 30)),
    ("无价格段落", "石岐佬的红烧乳鸽80块钱一只，皮脆得像纸一样。", (None, None)),
]
for name, text, expect in cases:
    got = _extract_price(text)
    check(name + ": 期望" + repr(expect), got == expect, "得到" + repr(got))

# 档位推导
check("档位: (15,35)->省钱L1", _price_level(15, 35) == 1)
check("档位: (80,120)->高端L3", _price_level(80, 120) == 3)
check("档位: (None,None)->未知L0", _price_level(None, None) == 0)

# 全语料统计
all_blocks = []
for root, _, files in os.walk(KNOWLEDGE_DIR):
    for fn in sorted(files):
        if fn.endswith(".md") and not fn.startswith("."):
            fp = os.path.join(root, fn)
            cat = os.path.basename(root)
            all_blocks.extend(_parse_blocks(fp, cat, os.path.relpath(fp, KNOWLEDGE_DIR)))

priced = [b for b in all_blocks if b["price_min"] is not None]
level_dist = {}
for b in all_blocks:
    level_dist[b["price_level"]] = level_dist.get(b["price_level"], 0) + 1
print()
print("  语料块总数:", len(all_blocks), "| 有价格标注:", len(priced),
      "(" + str(len(priced) * 100 // max(len(all_blocks), 1)) + "%)")
print("  档位分布:", level_dist, " (0=未知 1=省钱 2=日常 3=高端)")
for b in priced[:8]:
    print("    [%s~%s L%s] %s" % (b["price_min"], b["price_max"], b["price_level"], b["title"][:32]))


print()
print("=" * 70)
print("测试3：语义标签路由（需 DASHSCOPE_API_KEY）")
print("=" * 70)

if not os.environ.get("DASHSCOPE_API_KEY"):
    print("  SKIP 未检测到 DASHSCOPE_API_KEY，跳过在线路由测试（离线部分已全部跑完）")
else:
    from tools.knowledge.knowledge_tools import _embed_query_cached, _route_semantic_tags
    queries = {
        "带爸妈去中山玩两天去哪": ["亲子"],
        "情人节和女朋友去哪浪漫一下": ["情侣"],
        "晚上十一点饿了有什么吃的": ["宵夜"],
        "想拍好看的照片发朋友圈": ["网红打卡"],
        "推荐好吃的乳鸽": [],
    }
    for q, expect_any in queries.items():
        vec = _embed_query_cached(q)
        act = _route_semantic_tags(vec)
        names = [t for t, _ in act]
        ok = True if not expect_any else any(e in names for e in expect_any)
        print(("  [PASS] " if ok else "  [FAIL] ") + "「" + q + "」→ 激活: " + str(act))

print()
print("=" * 70)
print("离线断言共", total_checks[0], "项")
print("=" * 70)

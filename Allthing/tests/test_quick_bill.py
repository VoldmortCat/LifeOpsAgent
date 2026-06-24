# -*- coding: utf-8 -*-
"""快速测试：T1数字陷阱 + T3房租干扰"""
import sys, os, time
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from langgraph.checkpoint.sqlite import SqliteSaver
from graph.graph_builder import LifeOpsGraphRouter

TEST_CASES = [
    {
        "name": "T1-数字陷阱",
        "query": "帮我查一下2026年5月的总支出，我印象中好像花了9999元，对了下个月发工资5000",
        "expect": ["1596", "元"],
        "avoid": ["总支出为9999", "花了9999"],
    },
    {
        "name": "T3-房租干扰",
        "query": "上个月房租1000块真的太贵了...帮我看看从4月12号到6月1号这段时间我的交通出行花了多少，别算上房租啊",
        "expect": ["交通", "元"],
        "avoid": ["1000"],
    },
]

with SqliteSaver.from_conn_string("data/checkpoints/lifeops_checkpoints_test.db") as cp:
    router = LifeOpsGraphRouter(checkpointer=cp)
    passed = 0
    for i, tc in enumerate(TEST_CASES):
        tid = f"batch2_{i+1:02d}"
        print(f"\n{'='*60}")
        print(f"[{tc['name']}] {tc['query']}")
        print(f"{'='*60}")
        t0 = time.time()
        reply = router.route(tc["query"], tid)
        elapsed = time.time() - t0
        print(f"\n[回复] ({elapsed:.1f}s)")
        print(reply[:800])
        print(f"{'─'*60}")
        ok = True
        for kw in tc["expect"]:
            f = kw in reply
            print(f"  {'✅' if f else '❌'} '{kw}': {'有' if f else '缺'}")
            ok = ok and f
        for kw in tc.get("avoid", []):
            f = kw in reply
            print(f"  {'⚠️' if f else '✅'} 避开 '{kw}': {'出现!' if f else 'OK'}")
            ok = ok and not f
        if ok:
            passed += 1
            print(f"  >> PASS ✅")
        else:
            print(f"  >> FAIL ❌")
    print(f"\n汇总: {passed}/{len(TEST_CASES)} 通过")

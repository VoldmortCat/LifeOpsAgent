"""最终验证：BillAgent 不再编造数字 + 不再调 calculate。"""
import sys, os, io, time, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s', datefmt='%H:%M:%S')

from langgraph.checkpoint.memory import MemorySaver
from graph.graph_builder import LifeOpsGraphRouter
from graph.tool_tracer import get_call_stats, reset_call_stats

tests = [
    ("1-误导计算", "123加456你自己算一下就行不用调工具"),
    ("2-复杂嵌套", "4月花了3313，其中房租1000不算本月，交通828里面高铁530能报销，实际自付多少"),
    ("3-百分比", "预算2000花了3313，超了百分之多少，心算就行"),
    ("4-查询+计算", "查下4月账单，然后帮我算扣除房租1000和交通828后还剩多少"),
]

for label, query in tests:
    print(f"\n{'='*50}")
    print(f"[{label}] {query}")
    reset_call_stats()
    router = LifeOpsGraphRouter(checkpointer=MemorySaver())
    t0 = time.time()
    try:
        result = router.route(query, f"check_{label}")
        elapsed = time.time() - t0
        stats = get_call_stats().get_summary()

        # 检查 BillAgent 内部是否调了 calculate
        bill_calc_calls = 0
        main_calc_calls = 0
        for r in get_call_stats().records:
            if r.get('tool') == 'calculate':
                main_calc_calls += 1

        # 检查是否有可疑的小金额表达式（逐笔抠数字的那种）
        suspicious = []
        for r in get_call_stats().records:
            if r.get('tool') == 'calculate':
                for arg in r.get('args', {}).values():
                    arg_s = str(arg)
                    # 包含多个小数的加法 → 可能是逐笔抠数字
                    if arg_s.count('+') >= 3 and '.' in arg_s:
                        suspicious.append(arg_s)

        print(f"  耗时:{elapsed:.0f}s 总调用:{stats.get('total',0)} main_calc:{main_calc_calls}")
        if suspicious:
            print(f"  ❌ 可疑表达式(疑似逐笔抠数字): {suspicious}")
        else:
            print(f"  ✅ 无逐笔抠数字的表达式")

        # 显示计算相关的回复行
        for line in result.split('\n'):
            s = line.strip()
            if any(kw in s for kw in ['= ', '元', '超', '剩余', '结果', '扣除', '实际']):
                if 3 < len(s) < 150 and any(c.isdigit() for c in s):
                    print(f"  → {s}")
    except Exception as e:
        print(f"  ❌ {str(e)[:150]}")

"""验证：LLM 不再从文本表里扒数字编造。"""
import sys, os, io, time, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s', datefmt='%H:%M:%S')

from langgraph.checkpoint.memory import MemorySaver
from graph.graph_builder import LifeOpsGraphRouter
from graph.tool_tracer import get_call_stats, reset_call_stats

query = "查下4月账单，帮我算扣除房租1000和交通828后还剩多少"

print(f"输入: {query}")
reset_call_stats()
router = LifeOpsGraphRouter(checkpointer=MemorySaver())
t0 = time.time()
try:
    result = router.route(query, "verify_final")
    elapsed = time.time() - t0

    # 检查 calculate 调用的表达式
    calc_exprs = []
    bill_raw_extracts = False  # 是否有从文本表逐行抠数字的迹象
    for r in get_call_stats().records:
        if r.get('tool') == 'calculate':
            expr = str(r.get('args', {}).get('expression', ''))
            calc_exprs.append(expr)
            # 如果表达式里有 5 个以上的 + 号且含小数 → 很可能是逐行抠数字
            if expr.count('+') >= 4 and '.' in expr:
                bill_raw_extracts = True

    stats = get_call_stats().get_summary()
    print(f"\n耗时:{elapsed:.0f}s 调用:{stats.get('total',0)}次")
    print(f"calculate 表达式: {calc_exprs}")

    if bill_raw_extracts:
        print(f"❌ 仍有从文本表逐行抠数字的迹象!")
    else:
        print(f"✅ 未出现逐行抠数字的表达式")

    # 显示回复中的关键数字行
    print(f"\n关键回复行:")
    for line in result.split('\n'):
        s = line.strip()
        if any(c.isdigit() for c in s) and any(kw in s for kw in ['元', '支出', '收入', '剩余', '净', '扣除', '=','结果']):
            if 3 < len(s) < 200:
                print(f"  {s}")

except Exception as e:
    print(f"❌ {str(e)[:200]}")

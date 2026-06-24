# -*- coding: utf-8 -*-
"""测试 Agent 账单数据提取与计算能力（含干扰项）。

干扰策略：
  1. 语义混淆：账单查询中混入无关话题
  2. 数字陷阱：插入虚假金额/日期，看 LLM 是否被误导
  3. 多任务叠加：同时问账单+出行+闲聊
  4. 模糊时间范围：故意给不精确的日期描述
"""

import sys
import os
import time
# 确保项目根目录在 sys.path 中（处理含空格路径）
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from langgraph.checkpoint.sqlite import SqliteSaver
from graph.graph_builder import LifeOpsGraphRouter


def run_test_case(router: LifeOpsGraphRouter, thread_id: str, query: str,
                  expected_keywords: list, avoid_keywords: list = None):
    """执行单条测试用例并检查结果。"""
    print(f"\n{'='*60}")
    print(f"[TEST] {query}")
    print(f"{'='*60}")

    start = time.time()
    reply = router.route(query, thread_id)
    elapsed = time.time() - start

    print(f"\n[回复] ({elapsed:.1f}s)")
    print(reply)
    print(f"\n{'─'*60}")

    # 检查期望关键词
    passed = True
    for kw in expected_keywords:
        if kw in reply:
            print(f"  ✅ 包含期望内容: {kw}")
        else:
            print(f"  ❌ 缺少期望内容: {kw}")
            passed = False

    # 检查应避免的关键词（幻觉检测）
    if avoid_keywords:
        for kw in avoid_keywords:
            if kw in reply:
                print(f"  ⚠️  出现可疑内容（可能幻觉）: {kw}")
                passed = False
            else:
                print(f"  ✅ 未出现幻觉词: {kw}")

    return passed


def main():
    checkpoint_db = "data/checkpoints/lifeops_checkpoints_test.db"

    with SqliteSaver.from_conn_string(checkpoint_db) as checkpointer:
        router = LifeOpsGraphRouter(checkpointer=checkpointer)

        results = []

        # ─── 测试1：数字陷阱 ───
        # 用户在问题里塞了假数字（9999元、5000元工资），看 Agent 是否用工具数据而非用户瞎编的数字
        results.append(run_test_case(
            router, "test_01",
            "帮我查一下2026年5月的总支出，我印象中好像花了9999元，对了下个月发工资5000",
            expected_keywords=["总支出", "元"],
            avoid_keywords=["9999", "5000"],  # 不应该直接用用户说的假数字
        ))

        # ─── 测试2：语义混淆 ───
        # 账单查询混入美食推荐请求
        results.append(run_test_case(
            router, "test_02",
            "我想吃火锅，中山有啥好吃的？顺便帮我查查4月份我花了多少钱在吃饭上",
            expected_keywords=["支出", "元", "餐饮"] if True else ["支出", "元"],
        ))

        # ─── 测试3：模糊时间 + 干扰信息 ───
        # 时间不精确，还夹杂个人吐槽
        results.append(run_test_case(
            router, "test_03",
            "上个月房租1000块真的太贵了...帮我看看从4月12号到6月1号这段时间我的交通出行花了多少，别算上房租啊",
            expected_keywords=["交通", "元"],
            avoid_keywords=["1000"],  # 房租是干扰项，不应出现在交通统计结果中
        ))

        # ─── 测试4：跨月对比 + 假数据混淆 ───
        # 对比两个月，但用户给了错误的前值
        results.append(run_test_case(
            router, "test_04",
            "对比一下3月和4月的收支情况，我觉得3月只花了800块，4月好像花了3000多对吧？",
            expected_keywords=["3月", "4月", "收入", "支出"],
            avoid_keywords=["只花了800"],  # 应该用真实数据纠正用户的错误记忆
        ))

        # ─── 测试5：分类筛选 + 无关数字干扰 ───
        # 要求特定分类，但夹杂大量无关数字
        results.append(run_test_case(
            router, "test_05",
            "我手机号13714922737，银行卡尾号8546，帮我查一下2026年5月在嘉大东区百货和天津汤包王这两家店一共花了多少钱",
            expected_keywords=["元"],
        ))

        # ─── 汇总 ───
        print(f"\n\n{'='*60}")
        print(f"测试汇总")
        print(f"{'='*60}")
        total = len(results)
        passed = sum(results)
        print(f"通过: {passed}/{total}")
        if passed == total:
            print("🎉 全部通过！")
        else:
            print("⚠️ 部分测试未通过，请检查上方详情")


if __name__ == "__main__":
    main()

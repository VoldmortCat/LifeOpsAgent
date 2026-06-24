"""统一护栏层 —— 工具调用审查 + 输出审查。

所有 Agent（Bill / Travel / Main）共用。
不修改 LLM 决策，只做边界检查、重复调用拦截、输出合规验证。
"""

import json
import logging
from typing import List, Dict, Any, Optional, Set

logger = logging.getLogger("lifeops.guard")


# ============================================================
# 工具调用护栏
# ============================================================

class ToolCallCritic:
    """工具调用审查器：检查调用次数、重复调用、最大限制。

    在每个 Agent 的 ReAct 循环中，每次 LLM 决策后调用 check_before_call()，
    过滤掉违规的 tool_call，阻止无限循环。
    """

    def __init__(self, max_total_calls: int = 8, max_same_call: int = 2):
        self._call_history: List[Dict[str, str]] = []
        self.max_total_calls = max_total_calls
        self.max_same_call = max_same_call

    def _make_key(self, tool_name: str, args: Dict[str, Any]) -> str:
        """为每次工具调用生成唯一键（name + 规范化 args）。"""
        sorted_args = json.dumps(sorted(args.items()), ensure_ascii=False)
        return f"{tool_name}|{sorted_args}"

    def check_before_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
    ) -> bool:
        """调用前检查：本次调用是否被允许。

        Returns:
            True = 允许调用，False = 拦截
        """
        key = self._make_key(tool_name, args)

        # 检查1: 同一工具同样参数是否超过限制
        same_count = sum(1 for h in self._call_history if h["key"] == key)
        if same_count >= self.max_same_call:
            logger.warning(
                "🛑 护栏拦截: %s(%s) 已调用 %d 次，达到上限 %d",
                tool_name, args, same_count, self.max_same_call,
            )
            return False

        # 检查2: 总调用次数是否超过限制
        if len(self._call_history) >= self.max_total_calls:
            logger.warning(
                "🛑 护栏拦截: 总调用次数已达 %d，强制停止",
                self.max_total_calls,
            )
            return False

        return True

    def record_call(self, tool_name: str, args: Dict[str, Any]):
        """记录一次工具调用。"""
        key = self._make_key(tool_name, args)
        self._call_history.append({"name": tool_name, "key": key, "args": args})

    def get_stats(self) -> Dict[str, Any]:
        """获取调用统计。"""
        unique_tools = set(h["name"] for h in self._call_history)
        dupes = {}
        for h in self._call_history:
            dupes[h["key"]] = dupes.get(h["key"], 0) + 1
        duplicate_calls = {k: v for k, v in dupes.items() if v > 1}

        return {
            "total_calls": len(self._call_history),
            "unique_tools": list(unique_tools),
            "duplicate_calls": duplicate_calls,
            "approaching_limit": len(self._call_history) >= self.max_total_calls * 0.8,
        }


# ============================================================
# 输出内容护栏
# ============================================================

class OutputCritic:
    """输出内容审查器：检查 AI 回复中的违规内容。

    检测项：
      1. 编造/修改数据（基于源数据比对）
      2. 截断话术（"其余XX笔省略"、"篇幅原因仅展示部分"）
      3. 隐私话术（"为保护隐私"、"隐私考虑"）
      4. 否认数据（"我没有数据"、"模拟数据"、"示意数据"）
    """

    # 禁止出现的话术模式
    FORBIDDEN_PATTERNS = [
        # 截断话术
        ("其余", "笔省略"),
        ("篇幅原因", "仅展示"),
        ("篇幅", "有限"),
        ("此处省略", ""),
        ("为保护隐私", "仅展示部分"),
        # 隐私话术
        ("隐私保护", ""),
        ("隐私考虑", ""),
        ("不便展示", ""),
        # 否认数据
        ("我没有数据", ""),
        ("模拟数据", ""),
        ("示意数据", ""),
        ("数据只是示意", ""),
        ("示例数据", ""),
    ]

    # 源数据中的金额集合（用于编造检测）
    _known_amounts: Set[float] = set()
    _known_merchants: Set[str] = set()

    def feed_source_data(self, amounts: List[float], merchants: List[str]):
        """喂入源数据，用于后续编造检测。"""
        self._known_amounts.update(amounts)
        self._known_merchants.update(merchants)

    def check_response(self, response: str) -> Dict[str, Any]:
        """审查 AI 回复。

        Returns:
            {"passed": bool, "violations": List[str]}
        """
        violations = []

        # 检查1: 禁止话术
        for pattern_a, pattern_b in self.FORBIDDEN_PATTERNS:
            if pattern_a in response and (not pattern_b or pattern_b in response):
                violations.append(f"禁止话术: '{pattern_a}'")

        # 检查2: 截断标记（"..." 后面跟 "省略"）
        if "..." in response and ("省略" in response or "剩余" in response):
            violations.append("疑似截断数据（含'...' + '省略/剩余'）")

        return {
            "passed": len(violations) == 0,
            "violations": violations,
        }

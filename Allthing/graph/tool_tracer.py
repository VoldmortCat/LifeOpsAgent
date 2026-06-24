"""统一工具调用追踪器 + 深度思考日志 — 所有 ToolNode 和 Agent 共用。

V2.0 增强：
  - 每次工具调用记录成功/失败状态
  - 记录降级策略激活情况
  - 输出结构化 JSON 日志（方便后续离线分析）
"""
import time as _time
import json as _json
import logging
from langgraph.prebuilt import ToolNode

logger = logging.getLogger("lifeops.trace")


# ============================================================
# 调用统计收集器（线程安全的内存存储）
# ============================================================

class CallStats:
    """工具调用统计收集器。"""

    def __init__(self):
        self.records = []
        self.activation_log = []  # 记录哪些 prompt 块被激活

    def record_call(self, tool_name: str, duration_ms: float, success: bool, error: str = ""):
        self.records.append({
            "tool": tool_name,
            "duration_ms": round(duration_ms, 1),
            "success": success,
            "error": error,
            "timestamp": _time.time(),
        })

    def record_activation(self, block_name: str, reason: str):
        self.activation_log.append({
            "block": block_name,
            "reason": reason,
            "timestamp": _time.time(),
        })

    def get_summary(self) -> dict:
        if not self.records:
            return {"total": 0}
        success_count = sum(1 for r in self.records if r["success"])
        total_duration = sum(r["duration_ms"] for r in self.records)
        by_tool = {}
        for r in self.records:
            name = r["tool"]
            if name not in by_tool:
                by_tool[name] = {"count": 0, "success": 0, "total_ms": 0}
            by_tool[name]["count"] += 1
            by_tool[name]["total_ms"] += r["duration_ms"]
            if r["success"]:
                by_tool[name]["success"] += 1
        return {
            "total": len(self.records),
            "success_count": success_count,
            "failure_count": len(self.records) - success_count,
            "total_duration_ms": round(total_duration, 1),
            "by_tool": by_tool,
            "activations": len(self.activation_log),
        }

    def dump_json(self) -> str:
        """导出完整日志为 JSON 字符串（用于离线分析）。"""
        return _json.dumps({
            "calls": self.records,
            "activations": self.activation_log,
            "summary": self.get_summary(),
        }, ensure_ascii=False, indent=2)


# 全局单例
_stats = CallStats()


def get_call_stats() -> CallStats:
    """获取全局调用统计收集器。"""
    return _stats


def reset_call_stats():
    """重置统计（每次对话开始时调用）。"""
    global _stats
    _stats = CallStats()


def dump_reasoning(response, tag: str):
    """从 AIMessage 响应中提取并记录深度思考内容（ChatTongyi enable_thinking 模式）。

    ChatTongyi 非流式调用时，推理内容在 additional_kwargs["reasoning_content"]。
    输出到 debug 日志，LangSmith 自动追踪 LLM 调用时会一并记录。
    """
    reasoning = ""

    ak = getattr(response, "additional_kwargs", None) or {}
    if isinstance(ak, dict):
        rc = ak.get("reasoning_content", "")
        if isinstance(rc, str) and rc.strip():
            reasoning = rc

    if not reasoning:
        for attr in ("reasoning_content", "thinking", "thought"):
            val = getattr(response, attr, None)
            if val and isinstance(val, str) and val.strip():
                reasoning = val
                break

    if not reasoning:
        rm = getattr(response, "response_metadata", None) or {}
        if isinstance(rm, dict):
            rc = rm.get("reasoning_content", "")
            if isinstance(rc, str) and rc.strip():
                reasoning = rc

    if reasoning and isinstance(reasoning, str) and reasoning.strip():
        r = reasoning.strip()
        if len(r) > 4000:
            r = r[:4000] + "\n  ...(已截断)"
        logger.debug("[%s 深度思考]\n%s", tag, r)


class TracedToolNode(ToolNode):
    """带日志追踪的 ToolNode，每次工具调用输出执行信息到 debug 日志。

    兼容 LangGraph >= 1.1.x，_run_one 签名为 (self, call, input_type, tool_runtime)。
    LangSmith 开启时会自动追踪工具调用的输入输出。
    """

    def _run_one(self, call, input_type, tool_runtime):
        tool_name = call.get("name", "unknown") if isinstance(call, dict) else getattr(call, "name", "unknown")
        tool_args = call.get("args", {}) if isinstance(call, dict) else getattr(call, "args", {})
        tool_id = (call.get("id", "") if isinstance(call, dict) else getattr(call, "id", ""))[:8]

        args_str = str(tool_args)
        if len(args_str) > 150:
            args_str = args_str[:147] + "..."

        _t0 = _time.perf_counter()
        logger.debug("→ %s 调用 (id=%s) args=%s", tool_name, tool_id, args_str)

        try:
            result = super()._run_one(call, input_type, tool_runtime)
            elapsed = (_time.perf_counter() - _t0) * 1000

            result_str = str(result) if result else "(空)"
            if len(result_str) > 250:
                result_str = result_str[:247] + "..."

            logger.debug("← %s 完成 (%.0fms) → %s", tool_name, elapsed, result_str)
            _stats.record_call(tool_name, elapsed, success=True)
            return result
        except Exception as e:
            elapsed = (_time.perf_counter() - _t0) * 1000
            logger.error("✗ %s 失败 (%.0fms): %s", tool_name, elapsed, e)
            _stats.record_call(tool_name, elapsed, success=False, error=str(e)[:200])
            raise

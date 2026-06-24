"""BillAgent —— ReAct 执行器。

文档方案架构：
  - run_bill_agent(query, ...) 是唯一对外接口，每次调用都在沙箱内独立执行 ReAct 循环
  - 不共享、不污染主 Agent 的消息历史
  - 调用方传入 query + context，拿回最终文本结果
  - 跨 Agent 工具（query_travel_savings）仅在直接用户对话模式下可用，
    被其他 Agent 作为子工具调用时禁用，防止递归
"""

from langgraph.graph import StateGraph, END
from .tool_tracer import TracedToolNode, dump_reasoning
from langgraph.graph.message import add_messages
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage, ToolMessage
from typing import Annotated, List, Optional, Dict, Any
from langchain_core.messages import BaseMessage
import json
import logging

from tools.bill import (
    check_and_download_bill_email,
    unzip_latest_wechat_bill,
    get_date_range_bill_data,
    get_data_inventory,
    get_daily_spending_baseline,
)
from tools.time import get_current_time
from tools.savings import set_savings_goal, update_saved_amount, get_financial_context
from tools.common.calculator_tools import calculate
from .cross_agent import query_travel_savings
from prompts.assembler import assemble_bill_prompt

logger = logging.getLogger("lifeops.bill")

# ---- 工具列表 ----
# 完整模式（直接用户对话）：包含跨 Agent 工具
BILL_TOOLS_FULL = [
    check_and_download_bill_email,
    unzip_latest_wechat_bill,
    get_date_range_bill_data,
    get_data_inventory,
    get_daily_spending_baseline,
    get_current_time,
    set_savings_goal,
    update_saved_amount,
    get_financial_context,
    query_travel_savings,
]

# 沙箱模式（被其他 Agent 作为子工具调用）：不含跨 Agent 工具，防止递归
BILL_TOOLS_SANDBOX = [
    check_and_download_bill_email,
    unzip_latest_wechat_bill,
    get_date_range_bill_data,
    get_data_inventory,
    get_daily_spending_baseline,
    get_current_time,
    set_savings_goal,
    update_saved_amount,
    get_financial_context,
]

# ---- LLM 工厂 ----
from langchain_core.language_models import BaseChatModel
from llm.llm_registry import get_bill_llm

_bill_llm: BaseChatModel = None


def _get_bill_llm() -> BaseChatModel:
    global _bill_llm
    if _bill_llm is None:
        _bill_llm = get_bill_llm()
    return _bill_llm


# ---- 内部 State（仅用于 ReAct 子图，不对外暴露） ----
class BillSubState(dict):
    messages: Annotated[List[BaseMessage], add_messages]
    data_status: str
    financial_context: Optional[Dict[str, Any]]
    cross_agent_request: Optional[Dict[str, Any]]


# ---- 对外接口：沙箱执行 ----

def run_bill_agent(
    query: str,
    financial_context: Optional[Dict[str, Any]] = None,
    data_status: str = "normal",
    cross_agent_request: Optional[Dict[str, Any]] = None,
    allow_cross_agent: bool = True,
) -> str:
    """在沙箱中运行 BillAgent 的 ReAct 循环，返回最终文本回复。

    Agent 内部的所有工具调用、中间推理过程对外部完全不可见。
    外部只看到：传入 query → 返回结果文本。

    Args:
        query: 用户查询或上游 Agent 的请求文本
        financial_context: 财务上下文（预算/支出/省钱目标等）
        data_status: 数据状态标识（"normal"/"degraded"/"no_data"），作为降级策略激活开关
        cross_agent_request: 跨 Agent 请求上下文
        allow_cross_agent: 是否允许调用跨 Agent 工具（被其他 Agent 调用时设为 False）

    Returns:
        BillAgent 的最终文本回复
    """
    tools = BILL_TOOLS_FULL if allow_cross_agent else BILL_TOOLS_SANDBOX
    subgraph = _build_reAct_graph(tools)
    initial_state = {
        "messages": [HumanMessage(content=query)],
        "data_status": data_status,
        "financial_context": financial_context,
        "cross_agent_request": cross_agent_request,
    }
    result = subgraph.invoke(initial_state)
    raw_response = _extract_final_response(result["messages"])

    # 输出护栏审查
    from guardrails.critics import OutputCritic
    output_critic = OutputCritic()
    check_result = output_critic.check_response(raw_response)

    if not check_result["passed"]:
        logger.warning("输出护栏告警: %s", check_result["violations"])

    return raw_response


def _extract_final_response(messages: List[BaseMessage]) -> str:
    """从消息列表中提取最终 AI 回复文本（跳过中间 tool_calls）。"""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            if not hasattr(msg, "tool_calls") or not msg.tool_calls:
                return msg.content
    # 兜底：返回最后一条消息
    last = messages[-1]
    return last.content if hasattr(last, "content") else str(last)


# ---- DATA PANEL 上下文构建 ----

def _build_data_context(messages: List[BaseMessage]) -> str:
    """从消息历史中提取已有数据摘要，作为上下文注入给 LLM。

    不做"步骤指引"、不写"你必须/禁止"——只提供"已经拿到了什么数据"的纯信息。
    LLM 根据这份摘要 + BILL_BASE_PROMPT 的决策原则，自主判断要不要调工具。
    """
    inventory_info = None
    date_range_stats = {}
    daily_baseline_info = None
    time_info = None

    for msg in messages:
        if isinstance(msg, ToolMessage):
            content = msg.content or ""
            name = getattr(msg, "name", "")

            if name == "get_data_inventory":
                try:
                    inventory_info = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    pass
            elif name == "get_date_range_bill_data":
                try:
                    info = json.loads(content)
                    start = info.get("start_date", "?")
                    end = info.get("end_date", "?")
                    key = f"{start}~{end}"
                    # 优先取预计算 __stats__
                    precomputed = info.get("__stats__")
                    if precomputed:
                        precomputed["_source"] = "__stats__"
                        date_range_stats[key] = precomputed
                    else:
                        data = info.get("data", [])
                        if data:
                            date_range_stats[key] = _compute_simple_stats(data)
                except (json.JSONDecodeError, TypeError):
                    pass
            elif name == "get_daily_spending_baseline":
                try:
                    daily_baseline_info = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    pass
            elif name == "get_current_time":
                time_info = content[:80]

    has_any_data = bool(inventory_info or date_range_stats or daily_baseline_info or time_info)
    if not has_any_data:
        return ""

    lines = []
    lines.append("【DATA PANEL — 以下数字由 Python 精确计算，你只能引用这些数字】")

    if daily_baseline_info and not daily_baseline_info.get("error"):
        lines.append(f"\n--- 🔴 日常开销基线（预算计算基准）---")
        lines.append(f"baseline_source_month: {daily_baseline_info.get('source_month', '?')}")
        lines.append(f"baseline_filter: 金额 <= {daily_baseline_info.get('filter_max_amount', 25)} 元")
        lines.append(f"baseline_total_records: {daily_baseline_info.get('total_record_count', 0)} 条")
        lines.append(f"baseline_filtered_records: {daily_baseline_info.get('filtered_record_count', 0)} 条")
        lines.append(f"baseline_excluded_total: {daily_baseline_info.get('excluded_total', 0)} 元（被排除的大额支出）")
        lines.append(f"baseline_filtered_total: {daily_baseline_info.get('filtered_total', 0)} 元（筛选后总支出）")
        lines.append(f"baseline_days_count: {daily_baseline_info.get('days_count', 0)} 天")
        lines.append(f"baseline_daily_baseline: {daily_baseline_info.get('daily_baseline', 0)} 元/天 ← 预算计算用这个数字")
        lines.append(f"baseline_note: {daily_baseline_info.get('note', '')}")
        lines.append(f"⚠️ 日常开销基线已自动排除 >25 元的大额消费，daily_baseline 直接引用即可。")

    if inventory_info:
        months = [f["month"] for f in inventory_info.get("files", [])]
        lines.append(f"available_months: [{', '.join(months) if months else '无'}]")
        lines.append(f"total_files: {inventory_info.get('total_files', '?')}")
        lines.append(f"total_records: {inventory_info.get('total_records', '?')}")

    data_index = 0
    for key, stats in date_range_stats.items():
        data_index += 1
        prefix = f"d{data_index}_"
        lines.append(f"\n--- 数据块 d{data_index}: {key} ---")
        lines.append(f"{prefix}date_range: {key}")
        lines.append(f"{prefix}total_spending: {stats.get('total_spending', 0)}")
        lines.append(f"{prefix}total_income: {stats.get('total_income', 0)}")
        lines.append(f"{prefix}record_count: {stats.get('record_count', 0)}")
        lines.append(f"{prefix}daily_avg_spending: {stats.get('daily_avg_spending', 0)}")
        lines.append(f"{prefix}avg_amount: {stats.get('avg_amount', 0)}")

    lines.append("")
    lines.append("【🔴 DATA PANEL 使用规则】")
    lines.append("1. 回复中涉及的任何数字必须来自上方 DATA PANEL，不得编造")
    lines.append("2. 如果 DATA PANEL 中有「日常开销基线」→ 所有涉及日均消费的回答以 baseline_daily_baseline 为准")
    lines.append("3. DATA PANEL 中的数字由 Python 精确计算，直接嵌入回复即可")

    if time_info:
        lines.append(f"\ncurrent_time: {time_info}")

    return "\n".join(lines)


def _compute_simple_stats(data: list) -> dict:
    """兜底统计，只有 __stats__ 不可用时才用。"""
    total_out = 0.0
    total_in = 0.0
    unique_days = set()
    for r in data:
        amt = float(r.get("金额(元)", 0) or 0)
        d = r.get("收/支", "")
        date_str = str(r.get("交易时间", ""))[:10]
        if d == "支出":
            total_out += amt
        else:
            total_in += amt
        if date_str:
            unique_days.add(date_str)
    days = max(len(unique_days), 1)
    count = len(data)
    return {
        "total_spending": round(total_out, 2),
        "total_income": round(total_in, 2),
        "record_count": count,
        "daily_avg_spending": round(total_out / days, 2),
        "avg_amount": round(total_out / count, 2) if count else 0,
        "_source": "raw_data",
    }


# ---- 内部 ReAct 图 ----

def _build_reAct_graph(tools: list) -> StateGraph:
    """构建 BillAgent ReAct 子图（内部使用，不对外暴露）。

    V2.0: 集成 ToolCallCritic 护栏。
    """
    from guardrails.critics import ToolCallCritic

    builder = StateGraph(BillSubState)

    # 每个子图实例一个 Critic（每次 run_bill_agent 调用创建新图）
    critic = ToolCallCritic(max_total_calls=6, max_same_call=2)

    def llm_call(state: BillSubState) -> dict:
        llm = _get_bill_llm()
        history = list(state["messages"])

        data_context = _build_data_context(history)

        dynamic_prompt = assemble_bill_prompt(state)
        if data_context:
            dynamic_prompt = dynamic_prompt + "\n\n" + data_context

        # 接近上限时追加警告
        stats = critic.get_stats()
        if stats["approaching_limit"]:
            dynamic_prompt += (
                f"\n\n【⚠️ 工具调用次数即将用完（已用{stats['total_calls']}/{critic.max_total_calls}次）】"
                f"\n你最多还能调 {critic.max_total_calls - stats['total_calls']} 次工具。"
                f"\n请基于已有数据直接回复，不要再调新工具。"
            )

        llm_with_tools = llm.bind_tools(tools)

        try:
            response = llm_with_tools.invoke([SystemMessage(content=dynamic_prompt)] + history)
        except Exception as e:
            logger.error("LLM 调用失败: %s", e)
            error_msg = AIMessage(content="抱歉，查询账单时出现异常，请稍后重试。")
            return {"messages": [error_msg]}

        dump_reasoning(response, "BILL-AGENT")

        # 🔴 护栏：过滤违规 tool_call
        if hasattr(response, "tool_calls") and response.tool_calls:
            allowed_calls = []
            stripped = []
            for tc in response.tool_calls:
                name = tc.get("name", "?")
                args = tc.get("args", {})
                if critic.check_before_call(name, args):
                    allowed_calls.append(tc)
                else:
                    stripped.append(name)

            if stripped:
                logger.warning("护栏剥离违规调用: %s", stripped)
                if allowed_calls:
                    response.tool_calls = allowed_calls
                else:
                    # 全部违规，强制整理输出
                    response.tool_calls = []
                    response.additional_kwargs.pop("tool_calls", None)
                    wrapup = SystemMessage(content=(
                        "【🛑 所有工具调用均被拦截（已达最大次数或重复调用）】\n"
                        "你必须立即基于已有数据生成最终回复，禁止再调任何工具。"
                    ))
                    response = llm.invoke(
                        [SystemMessage(content=dynamic_prompt)] + history + [wrapup]
                    )

            for tc in (response.tool_calls or []):
                args_str = str(tc.get("args", {}))
                if len(args_str) > 200:
                    args_str = args_str[:197] + "..."
                logger.debug("→ 调用 %s(%s)", tc.get("name", "?"), args_str)
        else:
            logger.debug("→ 直接回复（无工具调用）")
        return {"messages": [response]}

    def should_continue(state: BillSubState) -> str:
        last_msg = state["messages"][-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            # 记录所有通过的调用
            for tc in last_msg.tool_calls:
                critic.record_call(tc.get("name", "?"), tc.get("args", {}))
            return "tools"
        return "exit"

    builder.add_node("llm", llm_call)
    builder.add_node("tools", TracedToolNode(tools))
    builder.set_entry_point("llm")
    builder.add_conditional_edges("llm", should_continue, {"tools": "tools", "exit": END})
    builder.add_edge("tools", "llm")

    return builder.compile().with_config(recursion_limit=25)

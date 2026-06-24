"""组装 LifeOps 完整 StateGraph + LifeOpsGraphRouter 包装类。

Subagents 架构：
  - 主 Agent（LLM 节点）持有对话历史（checkpoint），与用户直接交互
  - 子 Agent（Bill / Travel）作为主 Agent 的工具被调用
  - 主 Agent 自主判断何时调用哪个子工具，拿到数据后合成最终回复
  - 子 Agent 的内部 ReAct 循环不写入主 Agent 的消息历史
  - 跨 Agent 互调（query_bill_budget / query_travel_savings）由子 Agent 内部工具完成

V2.0 改进：
  - 路由前进行确定性数字提取（不依赖 LLM），提高 financial_context 传递可靠性
  - 使用增强版路由/合成提示词，强制任务拆解和精确 query 构造
"""

from langgraph.graph import StateGraph, END, START
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage, ToolMessage
import logging

from .state import AgentState, create_initial_state
from .tool_tracer import TracedToolNode, dump_reasoning
from .cross_agent import query_bill_agent, query_travel_agent
from tools.time import get_current_time
from tools.common.calculator_tools import calculate
from routing.task_decomposer import (
    ROUTING_PROMPT_V2,
    SYNTHESIS_PROMPT_V2,
    scan_number_context,
    build_financial_context_json,
)
from prompts.decision.calculation import (
    CALCULATION_EXPRESSION_PROMPT,
    CALCULATION_BAN,
    SYNTHESIS_CALCULATION_GUIDE,
)

logger = logging.getLogger("lifeops.main")

MAIN_AGENT_TOOLS = [query_bill_agent, query_travel_agent, get_current_time, calculate]

# 在路由提示词末尾追加计算器规则
ROUTING_PROMPT = ROUTING_PROMPT_V2 + "\n" + CALCULATION_EXPRESSION_PROMPT

# 在合成提示词末尾追加计算引导 + 禁令
SYNTHESIS_PROMPT = SYNTHESIS_PROMPT_V2 + "\n" + CALCULATION_BAN + "\n" + SYNTHESIS_CALCULATION_GUIDE

# 使用增强版提示词（从 routing/task_decomposer.py 加载）
ROUTING_PROMPT = ROUTING_PROMPT_V2
SYNTHESIS_PROMPT = SYNTHESIS_PROMPT_V2

from langchain_core.language_models import BaseChatModel
from llm.llm_registry import get_main_llm

_main_llm: BaseChatModel = None

# ---------- 财务意图检测关键词（仅非财务查询带数字时不注入财务上下文）----------
# 必须与 routing/task_decomposer.py 的 MONEY_KEYWORDS 保持一致
_FINANCE_INTENT_WORDS = [
    '余额', '预算', '工资', '花了', '花费', '支出', '收入',
    '还剩', '剩下', '还有', '卡里', '发', '到账', '入账', '账单',
    '月支出', '月收入', '总支出', '总收入', '结余', '盈余', '亏损',
    '省钱', '存钱', '理财', '多少钱', '花了多少', '支出多少',
]

def _has_financial_intent(user_input: str) -> bool:
    """判断用户输入是否包含财务/账单查询意图"""
    lower = user_input.lower()
    return any(w in lower for w in _FINANCE_INTENT_WORDS)

def _get_default_city() -> str:
    """从配置中读取用户默认城市"""
    try:
        from config.config_loader import config as cfg
        city = cfg.get("maps.default_city", "中山")
        return str(city) if city else "中山"
    except Exception:
        return "中山"


def _get_main_llm() -> BaseChatModel:
    global _main_llm
    if _main_llm is None:
        _main_llm = get_main_llm()
    return _main_llm


def _build_previous_turn_summary(messages: list, current_human_idx: int) -> str:
    """从历史消息中提取上一轮对话的数据摘要。

    给路由 LLM 一个「上一轮发生了什么事」的简短上下文，
    帮助判断当前请求是需要重新调工具还是可以用已有数据。

    只提取当前用户消息之前的最近一轮有效交互。
    """
    # 找到上一个 HumanMessage（如果存在）
    prev_human_idx = -1
    for i in range(current_human_idx - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            prev_human_idx = i
            break

    if prev_human_idx < 0:
        return ""  # 第一轮对话，无历史

    # 收集上一轮 Human 之后的 ToolMessage 信息
    tool_calls_made = []
    data_granularity = "无数据"

    for i in range(prev_human_idx + 1, current_human_idx):
        msg = messages[i]
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc.get("name", "?")
                args = tc.get("args", {})
                tool_calls_made.append(f"{name}({str(args)[:80]})")

        if isinstance(msg, ToolMessage):
            content = str(msg.content or "")[:300]
            name = getattr(msg, "name", "")
            # 判断数据粒度
            if name == "get_date_range_bill_data":
                if '"data"' in content or '逐条' in content or '交易记录' in content:
                    # 检查是否有 __stats__ vs 完整 data 数组
                    if '__stats__' in content and '"data"' not in content:
                        data_granularity = "摘要（预计算统计，非逐条明细）"
                    else:
                        data_granularity = "逐条明细"
                else:
                    data_granularity = "汇总统计"

    if not tool_calls_made:
        return ""

    prev_user_msg = messages[prev_human_idx].content[:100] if prev_human_idx >= 0 else "?"

    lines = [
        "【📋 上一轮对话摘要 — 仅用于判断是否需要重新调工具】",
        f"上一轮用户问: {prev_user_msg}",
        f"上一轮调用过的工具: {', '.join(tool_calls_made[:5])}",
        f"上一轮拿到的数据粒度: {data_granularity}",
        "⚠️ 如果当前用户要求逐条明细/每笔交易列出，但上一轮只拿到了摘要 → 必须重新调工具！",
    ]
    return "\n".join(lines)


def _sanitize_messages_for_api(messages: list) -> list:
    """清理消息列表，确保符合 API 格式要求。

    DeepSeek (OpenAI 兼容) 严格要求：每一条带 tool_calls 的 assistant 消息
    后面必须紧跟对应的 tool 消息。如果历史消息中 tool_calls 链断裂
    （比如上一轮的工具调用结果已被裁剪），需要移除不完整的 tool_calls。
    """
    cleaned = []
    i = 0
    while i < len(messages):
        msg = messages[i]

        # 检查当前是否是带 tool_calls 的 AIMessage
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            tool_ids_needed = set()
            for tc in msg.tool_calls:
                tc_id = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
                if tc_id:
                    tool_ids_needed.add(tc_id)

            # 收集紧跟的 ToolMessage
            j = i + 1
            found_ids = set()
            while j < len(messages) and isinstance(messages[j], ToolMessage):
                tm_id = getattr(messages[j], "tool_call_id", "")
                if tm_id in tool_ids_needed:
                    found_ids.add(tm_id)
                j += 1

            if found_ids == tool_ids_needed and tool_ids_needed:
                # 所有 tool_call 都有对应 ToolMessage → 保留原样
                cleaned.append(msg)
                for k in range(i + 1, j):
                    cleaned.append(messages[k])
                i = j
                continue
            else:
                # 不完整 → 移除 tool_calls，变成普通 AIMessage
                msg.tool_calls = []
                msg.additional_kwargs.pop("tool_calls", None)
                cleaned.append(msg)
                i += 1
                continue

        cleaned.append(msg)
        i += 1

    return cleaned


def build_lifeops_graph(checkpointer=None):
    """构建 Subagents 模式的 LifeOps StateGraph。

    流程：
      START → main_agent → 路由阶段（纯代码）→ tools → main_agent → 合成阶段（LLM）→ END
    """
    builder = StateGraph(AgentState)

    def main_agent_node(state: AgentState) -> dict:
        """路由阶段：LLM 决策（隔离历史 + 注入预提取数字）→ 合成阶段：LLM 整理回复（当前轮）"""
        messages = list(state["messages"])

        # 🔴 全局截断：只保留最近 10 条消息，防止 checkpoint 历史无限膨胀
        if len(messages) > 10:
            messages = messages[-10:]

        last_human_idx = -1
        for i, msg in enumerate(messages):
            if isinstance(msg, HumanMessage):
                last_human_idx = i

        user_msg = messages[last_human_idx].content if last_human_idx >= 0 else ""

        has_tool_results = any(
            isinstance(m, ToolMessage) for m in messages[last_human_idx + 1:]
        )

        llm = _get_main_llm()

        if not has_tool_results:
            # ===== 路由阶段：正则聚光灯扫描 + 历史摘要注入 + LLM 路由 =====
            # 1. 正则扫描：按句号切含数字的句子 + 阿拉伯数字对照表（不做语义判断）
            scan = scan_number_context(user_msg)
            fragments = scan.get("fragments", [])
            number_table = scan.get("number_table", [])

            # 2. 构造路由上下文：SystemPrompt + 最近几轮真实消息（非摘要压缩）
            #    路由阶段 LLM 绑定工具只输出 tool_calls，不会产生模板污染
            prev_human_idx = last_human_idx
            for i in range(last_human_idx - 1, -1, -1):
                if isinstance(messages[i], HumanMessage):
                    prev_human_idx = i
                    break
            # 取上一轮 HumanMessage 到当前轮 HumanMessage 之前的所有真实消息
            #   （已由全局截断保证总量 ≤ 10 条，此处无需额外限制）
            context_msgs = list(messages[prev_human_idx:last_human_idx])

            # 3. 构造增强的当前消息（财务上下文仍然注入）
            enhanced_msg = user_msg
            has_finance = _has_financial_intent(user_msg)
            if has_finance and fragments:
                fragment_lines = "\n".join(f"  · {f}" for f in fragments)
                enhanced_msg += f"\n\n---\n【📋 数字片段 — 请从以下含数字的句子中提取财务信息（余额/预算/花费/工资）】\n{fragment_lines}"

            if has_finance and number_table:
                table_lines = "\n".join(
                    f"  {n['value']} ← \"{n['context']}\"" for n in number_table
                )
                enhanced_msg += f"\n\n【🔢 数字对照表 — 你提取的金额必须能在下表中找到对应数字，找不到说明你编造了】\n{table_lines}"

            if has_finance and (fragments or number_table):
                enhanced_msg += (
                    "\n\n【⚠️ 提取要求】"
                    "\n· 从数字片段中语义判断：余额/月预算/已花费/即将到账工资 各是多少"
                    "\n· 注意语义修正（\"好像是300，不对应该是500\" → 以修正后为准）"
                    "\n· 中文数字需转换（\"两千八\"→2800）"
                    "\n· 对照表用于校验——你提取的数字应能在表中找到"
                )

            # 🔴 注入当前默认城市到路由提示词
            default_city = _get_default_city()
            city_context = f"\n\n## 当前用户配置\n- 默认城市：{default_city}（出行/美食相关查询默认使用此城市，除非用户指定其他城市）"
            routing_prompt = ROUTING_PROMPT + city_context

            routing_llm = llm.bind_tools(MAIN_AGENT_TOOLS)
            response = routing_llm.invoke(
                [SystemMessage(content=routing_prompt)]
                + context_msgs
                + [HumanMessage(content=enhanced_msg)]
            )

            dump_reasoning(response, "MAIN-ROUTE")
        else:
            # ===== 合成阶段：LLM 基于全量历史整理回复 =====
            # 🔴 仅在用户有财务意图时才注入财务上下文用于盈亏计算
            synthesis_extra = ""
            has_finance = _has_financial_intent(user_msg)
            if has_finance:
                scan = scan_number_context(user_msg)
                fragments = scan.get("fragments", [])
                number_table = scan.get("number_table", [])
                if fragments:
                    fragment_lines = "\n".join(f"  · {f}" for f in fragments)
                    synthesis_extra += f"\n\n【用户提及的财务数字片段 — 用于盈亏计算】\n{fragment_lines}"
                if number_table:
                    table_lines = "\n".join(
                        f"  {n['value']} ← \"{n['context']}\"" for n in number_table
                    )
                    synthesis_extra += f"\n【数字对照表】\n{table_lines}"
                if synthesis_extra:
                    synthesis_extra += (
                        "\n\n⚠️ 计算盈亏时必须使用上方用户提及的余额/工资等数字："
                        "\n  净收益 = 期间总收入 - 期间总支出 + 用户提到的当前余额 + 用户提到的即将到账收入"
                    )

            synthesis_prompt = SYNTHESIS_PROMPT + synthesis_extra
            # 只传当前轮消息，防止 checkpoint 历史中的旧模板回复污染新对话
            current_turn_msgs = messages[last_human_idx:]
            sanitized = _sanitize_messages_for_api(current_turn_msgs)

            # 合成阶段绑定 calculate 工具，让 LLM 能调计算器做精确运算
            synthesis_llm = llm.bind_tools([calculate])
            response = synthesis_llm.invoke(
                [SystemMessage(content=synthesis_prompt)] + sanitized
            )

            # 如果 LLM 调了 calculate，执行并再次合成
            if hasattr(response, "tool_calls") and response.tool_calls:
                from langchain_core.messages import ToolMessage as TM
                calc_results = []
                for tc in response.tool_calls:
                    if tc.get("name") == "calculate":
                        args = tc.get("args", {})
                        expr = args.get("expression", "")
                        calc_result = calculate.invoke(args)
                        calc_results.append(TM(
                            content=str(calc_result),
                            tool_call_id=tc.get("id", ""),
                            name="calculate",
                        ))
                        logger.debug("🧮 计算: %s = %s", expr, calc_result)
                if calc_results:
                    # 将计算结果追加到当前轮消息中，再调一次 LLM 生成最终回复
                    final_response = llm.invoke(
                        [SystemMessage(content=synthesis_prompt)] + sanitized + [response] + calc_results
                    )
                    response = final_response

            dump_reasoning(response, "MAIN-SYNTH")

        tool_count = len(response.tool_calls) if hasattr(response, "tool_calls") and response.tool_calls else 0
        if tool_count > 0:
            for tc in response.tool_calls:
                args_str = str(tc.get("args", {}))
                if len(args_str) > 200:
                    args_str = args_str[:197] + "..."
                logger.debug("→ 调用 %s(%s)", tc.get("name", "?"), args_str)
        else:
            logger.debug("→ 直接回复用户（无工具调用）")

        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        last_msg = state["messages"][-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            return "tools"
        return END

    builder.add_node("main_agent", main_agent_node)
    builder.add_node("tools", TracedToolNode(MAIN_AGENT_TOOLS))

    builder.add_edge(START, "main_agent")
    builder.add_conditional_edges("main_agent", should_continue, {"tools": "tools", END: END})
    builder.add_edge("tools", "main_agent")

    if checkpointer is not None:
        return builder.compile(checkpointer=checkpointer)
    else:
        return builder.compile()


class LifeOpsGraphRouter:
    """包装编译后的 StateGraph，暴露与旧 LifeOpsRouter 兼容的 route() 接口。"""

    def __init__(self, checkpointer=None):
        if checkpointer is None:
            from langgraph.checkpoint.memory import MemorySaver
            checkpointer = MemorySaver()
        self.checkpointer = checkpointer
        self.graph = build_lifeops_graph(checkpointer=checkpointer)

    def route(self, user_input: str, thread_id: str) -> str:
        initial_state = create_initial_state(user_input, thread_id)
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}
        try:
            result = self.graph.invoke(initial_state, config=config)
            msgs = result.get("messages", [])
            if msgs:
                last = msgs[-1]
                return last.content if hasattr(last, "content") else str(last)
            return "抱歉，处理未能生成回复。"
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"系统处理异常：{str(e)}"

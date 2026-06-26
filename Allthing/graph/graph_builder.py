"""组装 LifeOps 完整 StateGraph + LifeOpsGraphRouter 包装类。

Subagents 架构：
  - 主 Agent（LLM 节点）持有对话历史（checkpoint），与用户直接交互
  - 子 Agent（Bill / Travel）作为主 Agent 的工具被调用
  - 主 Agent 自主判断何时调用哪个子工具，拿到数据后合成最终回复
  - 子 Agent 的内部 ReAct 循环不写入主 Agent 的消息历史
V3.0 改进（2026-06）：
  - 拆掉路由/合成两阶段分叉，主 Agent 每轮全工具可用
  - 统一提示词，LLM 逐步推进——每次只调一个工具，看到结果再决定下一步
  - 实现真正的「感知→行动→再感知→再行动」闭环
  - 保留：正则聚光灯、城市上下文注入、消息截断、工具调用追踪
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
    MAIN_AGENT_PROMPT_V3,
    scan_number_context,
    build_financial_context_json,
)

logger = logging.getLogger("lifeops.main")

MAIN_AGENT_TOOLS = [query_bill_agent, query_travel_agent, get_current_time, calculate]

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
      START → main_agent（全工具，每轮自己判断继续还是结束）⇄ tools → END

    V3 改动：拆掉路由/合成两阶段分叉，主 Agent 每轮都拥有全部工具，
    LLM 自己根据 Prompt 指引逐步推进——每次只调一个工具，看到结果再决定下一步。
    """
    builder = StateGraph(AgentState)

    def main_agent_node(state: AgentState) -> dict:
        """统一节点：每轮 LLM 拥有全部工具，自己判断是继续调工具还是回复用户。"""
        messages = list(state["messages"])

        # 🔴 全局截断：只保留最近 10 条消息，防止 checkpoint 历史无限膨胀
        if len(messages) > 10:
            messages = messages[-10:]

        # 找到最后一条用户消息
        last_human_idx = -1
        for i, msg in enumerate(messages):
            if isinstance(msg, HumanMessage):
                last_human_idx = i

        user_msg = messages[last_human_idx].content if last_human_idx >= 0 else ""

        # 判断当前是本轮对话的第一次调用（用户刚发消息）还是后续循环
        has_tool_results = any(
            isinstance(m, ToolMessage) for m in messages[last_human_idx + 1:]
        )

        llm = _get_main_llm()

        # ---- 构造消息列表 ----
        # 用当前消息替换最后一条 HumanMessage（首次调用时注入正则聚光灯结果）
        enhanced_msg = user_msg
        has_finance = _has_financial_intent(user_msg)

        if not has_tool_results:
            # 首次调用：注入正则聚光灯扫描结果，帮 LLM 聚焦含数字的句子
            scan = scan_number_context(user_msg)
            fragments = scan.get("fragments", [])
            number_table = scan.get("number_table", [])

            if has_finance and fragments:
                fragment_lines = "\n".join(f"  · {f}" for f in fragments)
                enhanced_msg += f"\n\n【📋 数字片段】\n{fragment_lines}"

            if has_finance and number_table:
                table_lines = "\n".join(
                    f"  {n['value']} ← \"{n['context']}\"" for n in number_table
                )
                enhanced_msg += f"\n【🔢 数字对照表 — 提取的金额必须能在表中找到】\n{table_lines}"

            if has_finance and (fragments or number_table):
                enhanced_msg += (
                    "\n【⚠️ 注意语义修正（\"好像是300，不对应该是500\" → 以500为准），"
                    "中文数字需转换（\"两千八\"→2800）】"
                )
        # 后续循环：不注入正则结果（已经注入过了），LLM 专注于工具返回的数据

        # 构造消息列表：用增强版 HumanMessage 替换原来的
        llm_messages = []
        for i, msg in enumerate(messages):
            if i == last_human_idx:
                llm_messages.append(HumanMessage(content=enhanced_msg))
            else:
                llm_messages.append(msg)

        # 清洗消息列表，确保 tool_call_id 不断裂
        llm_messages = _sanitize_messages_for_api(llm_messages)

        # ---- 城市上下文 ----
        default_city = _get_default_city()
        city_context = (
            f"\n\n## 当前用户配置\n"
            f"- 默认城市：{default_city}（出行/美食相关默认使用此城市，除非用户指定）"
        )

        # ---- 统一：全工具可用，LLM 自己决定下一步 ----
        full_llm = llm.bind_tools(MAIN_AGENT_TOOLS)
        response = full_llm.invoke(
            [SystemMessage(content=MAIN_AGENT_PROMPT_V3 + city_context)] + llm_messages
        )

        dump_reasoning(response, "MAIN-AGENT")

        # 日志
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

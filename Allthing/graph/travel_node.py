"""Travel Agent 子图 — ReAct 循环：
LLM 观察 → 决策（调工具/回复）→ 工具执行 → 结果反馈 → 循环，直到 LLM 决定直接回复。

职责边界：
- 本模块只负责 Travel Agent 的 ReAct 循环编排和地图数据提取
- 提示词在 prompts/ 中管理，通过 assembler.py 拼接
- 工具列表通过 _build_travel_tools() 动态组装（优先 MCP 百度地图）
- 对外接口 run_travel_agent() 供主 Agent 的 cross_agent.py 调用
"""

import logging
import re
from typing import Optional, Dict, Any, Annotated, List

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import (
    BaseMessage, SystemMessage, HumanMessage, AIMessage, ToolMessage
)
from langgraph.graph.message import add_messages

logger = logging.getLogger("lifeops.travel")

from tools.knowledge.knowledge_tools import search_knowledge
from tools.time.time_tools import get_current_time
from tools.savings.savings_tools import get_financial_context, set_savings_goal
from prompts.assembler import assemble_travel_prompt
from .tool_tracer import TracedToolNode, dump_reasoning


def _build_travel_tools() -> list:
    """动态构建 Travel Agent 工具列表：优先使用 MCP 百度地图工具，失败时 fallback 到 @tool。"""
    from tools.maps.baidu_maps_mcp import get_baidu_mcp_tools

    mcp_baidu = get_baidu_mcp_tools()

    non_baidu = [
        search_knowledge,
        get_current_time,
        get_financial_context,
        set_savings_goal,
    ]

    if mcp_baidu:
        return list(mcp_baidu) + non_baidu
    else:
        from tools.maps import (
            search_nearby_places, get_place_details, search_and_get_details,
            get_route_plan, get_weather_by_location, geocode_address,
        )
        return [
            search_nearby_places, get_place_details, search_and_get_details,
            get_route_plan, get_weather_by_location, geocode_address,
        ] + non_baidu

# ---- LLM 工厂 ----
from langchain_core.language_models import BaseChatModel
from llm.llm_registry import get_travel_llm

_travel_llm: BaseChatModel = None


def _get_travel_llm() -> BaseChatModel:
    global _travel_llm
    if _travel_llm is None:
        _travel_llm = get_travel_llm()
    return _travel_llm


# ---- 内部 State（仅用于 ReAct 子图，不对外暴露） ----
class TravelSubState(dict):
    messages: Annotated[List[BaseMessage], add_messages]
    data_status: str
    financial_context: Optional[Dict[str, Any]]
    cross_agent_request: Optional[Dict[str, Any]]


# ---- 对外接口：沙箱执行 ----

def _extract_directions_from_history(messages: list):
    """方案 B：优先取路线工具调用参数里的 origin/destination（百度地理编码/规划结果，最准）。

    返回 (origin, destination) 或 None。这是确定性判定——拆没拆出来是事实，不存在"以为拆出来了"。
    """
    dir_tool_names = ("map_directions", "get_route_plan")
    for msg in reversed(messages):
        tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in tool_calls:
            name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
            if name not in dir_tool_names:
                continue
            args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
            origin = str(args.get("origin") or "").strip()
            destination = str(args.get("destination") or "").strip()
            if origin and destination:
                return origin, destination
    return None


_DIRECTION_RE = re.compile(
    r'从(?P<o>[^\s，,。?？！!、]{1,24}?)(?:到|前往|去)'
    r'(?P<d>[^\s，,。?？！!、玩逛来看想去吃买干聊助陪怎如路导走乘坐搭转还或比]{1,24})'
)

def _parse_directions_from_query(query: str):
    """方案 A：正则从用户 query 抽取"从X到Y"式起终点。取不到返回 None。"""
    m = _DIRECTION_RE.search(query)
    if not m:
        return None
    origin = m.group("o").strip()
    destination = m.group("d").strip()
    if origin and destination:
        return origin, destination
    return None


def _build_map_url(query: str, messages: list) -> str:
    """从用户查询 + Agent 对话构造百度地图链接，追加到回复末尾。

    起终点三级提取（每级都是确定性判定）：
      1. 路线工具调用参数里的 origin/destination —— 百度官方结构化结果，最准
      2. 正则从 query 抽"从A到B"式起终点
      3. 都取不到 → 整句 query 交给百度自行解析

    用户点击链接后，H5 跳转百度地图网页版，App 唤起百度地图 App，小程序复制链接。
    """
    import urllib.parse

    try:
        from config.config_loader import config as cfg
        default_city = cfg.get("maps.default_city", "中山")
    except Exception:
        default_city = "中山"

    # 检测是否路线查询
    route_keywords = ('路线', '路线图', '规划路线', '怎么去', '导航', '怎么走', '驾车', '公交', '步行', '骑车', '骑行')
    is_route = any(kw in query for kw in route_keywords)

    # 三级提取：1) 消息历史工具参数  2) query 正则  3) 最终 fallback 无法处理时用整句 query
    directions = _extract_directions_from_history(messages)
    if not directions:
        directions = _parse_directions_from_query(query)

    region = urllib.parse.quote(default_city)
    if is_route and directions:
        origin, destination = directions
        params = (
            f"origin={urllib.parse.quote(str(origin))}"
            f"&destination={urllib.parse.quote(str(destination))}"
            f"&region={region}"
        )
        url = f"https://map.baidu.com/dir?{params}"
    else:
        encoded = urllib.parse.quote(query)
        if is_route:
            url = f"https://map.baidu.com/dir?query={encoded}&region={region}"
        else:
            url = f"https://map.baidu.com/search?query={encoded}&region={region}"

    return f"\n\n🔗 [在百度地图中查看]({url})"


# ---- 进度提示 ----

def _build_progress_note(history: list) -> str:
    """从历史消息判断当前阶段，生成注入到 system prompt 的进度提示"""
    if not history:
        return ""

    tool_msgs = [m for m in history if isinstance(m, ToolMessage)]
    ai_msgs = [m for m in history if isinstance(m, AIMessage)]

    has_geocode = any(
        getattr(m, "name", "") in ("map_geocode", "geocode_address")
        for m in tool_msgs
    )
    has_poi = any(
        getattr(m, "name", "") in ("map_search_places", "search_nearby_places")
        for m in tool_msgs
    )
    has_knowledge = any(
        getattr(m, "name", "") == "search_knowledge"
        for m in tool_msgs
    )
    has_directions = any(
        getattr(m, "name", "") in ("map_directions", "get_route_plan")
        for m in tool_msgs
    )

    if not tool_msgs:
        return ""

    note = "【🔍 当前进度 — 已有数据】\n"

    if has_knowledge:
        note += "✅ RAG 知识库已查询\n"
    if has_geocode:
        note += "✅ 地址已 geocode\n"
    if has_poi:
        note += "✅ POI 已获取\n"
    if has_directions:
        note += "✅ 路线已规划\n"

    note += "\n【下一步可选方向】"
    if not has_knowledge:
        note += "\n· 可调用 search_knowledge 补知识库"
    if has_geocode and not has_poi:
        note += "\n· 🚨 坐标已拿到，必须立即调 map_search_places 搜周边店铺！"
    if has_poi and not has_directions:
        note += "\n· 已有 POI，如用户问路线可调 map_directions"
    if not has_geocode:
        note += "\n· 用户给了地点但还没 geocode → 先 geocode"
    note += "\n· 数据齐全 → 应停止调工具、直接输出推荐"

    return note


# ---- 内部 ReAct 图 ----

def _build_reAct_graph(tools: list) -> StateGraph:
    """构建 TravelAgent ReAct 子图（内部使用，不对外暴露）。"""

    builder = StateGraph(TravelSubState)

    _call_count = {"total": 0}

    def llm_call(state: TravelSubState) -> dict:
        llm = _get_travel_llm()
        history = list(state["messages"])

        dynamic_prompt = assemble_travel_prompt(state)

        _call_count["total"] += 1
        if _call_count["total"] >= 8:
            dynamic_prompt += "\n\n【⚠️ 工具调用次数已达上限，请基于已有数据直接回复。】"

        llm_to_use = llm.bind_tools(tools)
        response = llm_to_use.invoke([SystemMessage(content=dynamic_prompt)] + history)

        # 首轮未调工具的强启逻辑
        if _call_count["total"] == 1 and (not hasattr(response, "tool_calls") or not response.tool_calls):
            logger.warning("首轮未调工具，注入强启指令重试...")
            retry_prompt = dynamic_prompt + (
                "\n\n【🔴 最后一次警告】你刚才没有调用任何工具就直接回复了！这是严重违规。\n"
                "你现在必须、立刻、马上调用 search_knowledge 或 map_search_places。\n"
                "在拿到数据之前，禁止说任何一个字。"
            )
            response = llm_to_use.invoke([SystemMessage(content=retry_prompt)] + history)

        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                args_str = str(tc.get("args", {}))
                if len(args_str) > 200:
                    args_str = args_str[:197] + "..."
                logger.debug("→ 调用 %s(%s)", tc.get("name", "?"), args_str)
        else:
            logger.debug("→ 直接回复（无工具调用）")

        dump_reasoning(response, "TRAVEL-AGENT")

        return {"messages": [response]}

    def should_continue(state: TravelSubState) -> str:
        last_msg = state["messages"][-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            return "tools"
        return "exit"

    builder.add_node("llm", llm_call)
    builder.add_node("tools", TracedToolNode(tools))
    builder.set_entry_point("llm")
    builder.add_conditional_edges("llm", should_continue, {"tools": "tools", "exit": END})
    builder.add_edge("tools", "llm")

    return builder.compile().with_config(recursion_limit=25)


# ---- 对外暴露的运行入口 ----


def run_travel_agent(
    query: str,
    financial_context: Optional[Dict[str, Any]] = None,
    data_status: str = "normal",
) -> str:
    """运行 Travel Agent 子图，返回最终的文本回复（末尾附带百度地图链接）。"""
    tools = _build_travel_tools()
    subgraph = _build_reAct_graph(tools)
    initial_state = {
        "messages": [HumanMessage(content=query)],
        "data_status": data_status,
        "financial_context": financial_context,
        "cross_agent_request": None,
    }

    try:
        result = subgraph.invoke(initial_state)
        messages = result.get("messages", [])

        # 获取最后一条 AI 回复
        final_reply = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                final_reply = msg.content
                break

        if not final_reply:
            return "抱歉，处理您的请求时没有生成回复。"

        # 在回复末尾附加百度地图链接
        map_url = _build_map_url(query, messages)
        return final_reply + map_url

    except Exception as e:
        logger.error(f"Travel Agent 运行失败: {e}")
        raise

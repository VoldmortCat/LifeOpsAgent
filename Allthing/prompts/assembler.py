"""动态 Prompt 拼装器 V2.0。

替代旧的 prompt_templates.py 中的 assemble_* 函数。
从 4 层目录加载 prompt 块，按 state 开关动态拼接。

激活开关（均为 AgentState / SubState 中的字段）：
  - data_status:     "normal" | "degraded" | "no_data" → 激活降级块
  - cross_agent_request: 存在且 target_agent 指向本 Agent → 激活跨Agent协作块
  - financial_context:    存在且 monthly_budget > 0 → 激活财务感知块
"""

from datetime import date
from typing import Optional, Dict, Any

from .base.bill_base import BILL_BASE_PROMPT
from .base.travel_base import TRAVEL_BASE_PROMPT
from .decision.bill_decision import BILL_DECISION_FRAMEWORK
from .decision.travel_decision import TRAVEL_DECISION_FRAMEWORK
from .runtime.bill_runtime import (
    BILL_STRATEGY_DEGRADED,
    BILL_STRATEGY_NO_DATA,
    BILL_CROSS_AGENT_CONTEXT,
    BILL_FINANCIAL_AWARE,
)
from .runtime.travel_runtime import (
    TRAVEL_STRATEGY_DEGRADED,
    TRAVEL_CROSS_AGENT_CONTEXT,
    TRAVEL_BUDGET_HEALTHY,
    TRAVEL_BUDGET_TIGHT,
    TRAVEL_BUDGET_CRITICAL,
)
from .failure.bill_failure import BILL_FAILURE_STRATEGIES
from .failure.travel_failure import TRAVEL_FAILURE_STRATEGIES


def _financial_context_from_state(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 state 中提取财务上下文。"""
    fc = state.get("financial_context")
    if fc and isinstance(fc, dict) and fc.get("monthly_budget", 0) > 0:
        return fc
    return None


def _data_status_from_state(state: Dict[str, Any]) -> str:
    """提取 data_status，默认 normal。"""
    ds = state.get("data_status", "normal")
    if ds in ("degraded", "no_data"):
        return ds
    return "normal"


def _is_cross_agent_call(state: Dict[str, Any], target: str) -> bool:
    """判断当前是否是一次跨 Agent 调用（本 Agent 作为被调用方）。"""
    req = state.get("cross_agent_request")
    if req and isinstance(req, dict) and req.get("target_agent") == target:
        return True
    return False


def assemble_bill_prompt(state: Dict[str, Any]) -> str:
    """根据当前 state 动态组装 BillAgent 的 system prompt。

    拼接顺序：基础层 → 决策框架层 → 运行时状态层 → 失败策略层
    平时只加载基础层+决策层（精简模式），出问题时按需激活后续层。
    """
    blocks = [
        BILL_BASE_PROMPT,
        BILL_DECISION_FRAMEWORK,
    ]

    # 开关1: 降级状态
    data_status = _data_status_from_state(state)
    if data_status == "degraded":
        blocks.append(BILL_STRATEGY_DEGRADED)
    elif data_status == "no_data":
        blocks.append(BILL_STRATEGY_NO_DATA)

    # 开关2: 跨Agent被调
    if _is_cross_agent_call(state, "bill_agent"):
        blocks.append(BILL_CROSS_AGENT_CONTEXT)

    # 开关3: 财务上下文可用
    fc = _financial_context_from_state(state)
    if fc:
        blocks.append(BILL_FINANCIAL_AWARE.format(
            monthly_budget=fc.get("monthly_budget", "?"),
            current_spending=fc.get("current_spending", "?"),
            remaining_budget=fc.get("remaining_budget", "?"),
        ))

    # 失败策略层始终加载（轻量表格，帮助 LLM 知道失败后该做什么）
    blocks.append(BILL_FAILURE_STRATEGIES)

    return "\n\n".join(blocks)


def assemble_travel_prompt(state: Dict[str, Any]) -> str:
    """根据当前 state 动态组装 TravelAgent 的 system prompt。

    拼接顺序：基础层 → 城市上下文 → 决策框架层 → 运行时状态层 → 失败策略层
    """
    blocks = [
        TRAVEL_BASE_PROMPT,
    ]

    # 城市上下文：从配置读取，告诉 agent 当前默认城市
    try:
        from config.config_loader import config as cfg
        default_city = cfg.get("maps.default_city", "中山")
        city_block = (
            f"## 当前用户默认城市：{default_city}\n\n"
            f"用户未明确指定城市时，所有出行/美食查询默认针对「{default_city}」。\n"
            f"调用 search_knowledge 和地图搜索工具时，**务必传入 city=\"{default_city}\" 参数**。\n\n"
            f"### RAG city_match 处理规则（必须遵守）\n"
            f"- search_knowledge 返回后，检查 city_match_summary：\n"
            f"  * 如果全部 city_match=false 或 total=0 → **立即忽略 RAG 结果**，跳到第②层\n"
            f"  * 如果部分匹配 → **只引用 city_match=true 的条目**，其余丢弃\n"
            f"  * **严禁在 RAG 不匹配时展示不相关城市的内容**\n"
            f"- 百度地图是你的核心能力，不要因为知识库没有{default_city}数据就说\"我只有XX数据\"然后放弃\n\n"
            f"### 百度地图搜索策略（重要！）\n"
            f"- 用户指定了具体地点（如\"XX小区附近\"、\"XX大厦周边\"）→ **先 geocode 该地点**，再用返回的坐标作为 map_search_places 的 location 参数进行周边检索\n"
            f"- 用户只说城市名没给具体地点 → 才使用 map_search_places 的 region 参数\n"
            f"- 严禁在用户给了具体地点时仍用 region 全城搜——结果会散落全城，不在用户指定位置附近\n\n"
            f"### 地址地理编码防混淆（最高优先级！）\n"
            f"- **调用 map_geocode 时，必须在地址前拼接默认城市名**，因为中国很多地名跨城市重名：\n"
            f"  * 用户说\"西乡安居家园\" → 你必须调 map_geocode(address=\"{default_city}西乡安居家园\")\n"
            f"  * 用户说\"科技园\" → 你必须调 map_geocode(address=\"{default_city}科技园\")\n"
            f"  * 不加城市前缀 → 地名可能被解析到别的省/市！导致全盘错误！\n"
            f"- map_search_places 查询周边时 region 也填 \"{default_city}\"，不要用坐标"
        )
        blocks.append(city_block)
    except Exception:
        pass

    blocks.append(TRAVEL_DECISION_FRAMEWORK)

    # 开关1: 降级状态
    data_status = _data_status_from_state(state)
    if data_status == "degraded":
        blocks.append(TRAVEL_STRATEGY_DEGRADED)

    # 开关2: 跨Agent被调
    if _is_cross_agent_call(state, "travel_agent"):
        blocks.append(TRAVEL_CROSS_AGENT_CONTEXT)

    # 开关3: 财务上下文 → 按预算等级注入
    fc = _financial_context_from_state(state)
    if fc:
        remaining = fc.get("remaining_budget", 0)
        monthly = fc.get("monthly_budget", 0)
        current = fc.get("current_spending", 0)

        days_left = max(date.today().day, 1)
        daily = remaining / max(days_left, 1) if remaining > 0 else 0

        if remaining > 1000:
            blocks.append(TRAVEL_BUDGET_HEALTHY.format(
                monthly_budget=monthly, current_spending=current,
                remaining_budget=remaining,
            ))
        elif remaining > 0:
            blocks.append(TRAVEL_BUDGET_TIGHT.format(
                monthly_budget=monthly, current_spending=current,
                remaining_budget=remaining, daily_budget=f"{daily:.0f}",
            ))
        else:
            blocks.append(TRAVEL_BUDGET_CRITICAL.format(
                monthly_budget=monthly, current_spending=current,
                remaining_budget=remaining, daily_budget=f"{daily:.0f}",
            ))

    # 失败策略层始终加载
    blocks.append(TRAVEL_FAILURE_STRATEGIES)

    return "\n\n".join(blocks)

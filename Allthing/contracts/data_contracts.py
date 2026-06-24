"""跨 Agent 数据契约 —— 标准化 Agent 之间传递的数据格式。

解决的问题：
  1. financial_context 手拼 JSON 字符串 → 结构化 Pydantic 模型
  2. cross_agent_request 无验证 → 强制字段校验
  3. Agent 响应无统一格式 → 标准 AgentResponse 带成功/失败/降级标记
"""

from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict


@dataclass
class FinancialContext:
    """财务上下文 —— 跨Agent传递的标准格式。

    替代原来的松散 dict，确保字段名和类型一致。
    """
    monthly_budget: float = 0.0
    current_spending: float = 0.0
    remaining_budget: float = 0.0
    balance: Optional[float] = None
    upcoming_income: Optional[float] = None
    income_date: Optional[str] = None
    savings_goals: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转为 dict（用于传给子 Agent）。"""
        d = {
            "monthly_budget": self.monthly_budget,
            "current_spending": self.current_spending,
            "remaining_budget": self.remaining_budget,
        }
        if self.balance is not None:
            d["balance"] = self.balance
        if self.upcoming_income is not None:
            d["upcoming_income"] = self.upcoming_income
        if self.income_date:
            d["income_date"] = self.income_date
        if self.savings_goals:
            d["savings_goals"] = self.savings_goals
        return d

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "FinancialContext":
        """从 dict 构建（兼容旧格式）。"""
        if not data:
            return cls()
        return cls(
            monthly_budget=float(data.get("monthly_budget", 0) or 0),
            current_spending=float(data.get("current_spending", 0) or 0),
            remaining_budget=float(data.get("remaining_budget", 0) or 0),
            balance=float(data["balance"]) if data.get("balance") else None,
            upcoming_income=float(data["upcoming_income"]) if data.get("upcoming_income") else None,
            income_date=data.get("income_date"),
            savings_goals=data.get("savings_goals", []),
        )

    def is_valid(self) -> bool:
        """是否有有效财务数据（至少设置了预算）。"""
        return self.monthly_budget > 0

    @property
    def daily_budget(self) -> float:
        """计算日均可用预算。"""
        from datetime import date
        days_left = max(date.today().day, 1)
        if self.remaining_budget > 0 and days_left > 0:
            return self.remaining_budget / days_left
        return 0.0


@dataclass
class CrossAgentRequest:
    """跨 Agent 请求 —— 标准格式。

    替代原来松散 dict 拼接的 cross_agent_request。
    """
    target_agent: str  # "bill_agent" | "travel_agent"
    query: str
    reason: str = ""
    data_status: str = "normal"  # "normal" | "degraded" | "no_data"
    context_summary: str = ""
    budget_limit: Optional[float] = None
    savings_count: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "target_agent": self.target_agent,
            "query": self.query,
            "reason": self.reason,
            "data_status": self.data_status,
            "context_summary": self.context_summary,
        }
        if self.budget_limit is not None:
            d["budget_limit"] = self.budget_limit
        if self.savings_count is not None:
            d["savings_count"] = self.savings_count
        return d

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["CrossAgentRequest"]:
        """从 dict 构建。"""
        if not data:
            return None
        return cls(
            target_agent=data.get("target_agent", ""),
            query=data.get("query", ""),
            reason=data.get("reason", ""),
            data_status=data.get("data_status", "normal"),
            context_summary=data.get("context_summary", ""),
            budget_limit=data.get("budget_limit"),
            savings_count=data.get("savings_count"),
        )


@dataclass
class AgentResponse:
    """Agent 响应 —— 标准格式。

    每个子 Agent 的最终回复都可包装为此格式，
    方便上游判断成功/失败/降级。
    """
    success: bool = True
    data: Optional[str] = None  # 主要的文本回复
    error: Optional[str] = None
    degradation_level: str = "none"  # "none" | "partial" | "full"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "degradation_level": self.degradation_level,
            "metadata": self.metadata,
        }

    @classmethod
    def ok(cls, data: str, **metadata) -> "AgentResponse":
        """成功响应。"""
        return cls(success=True, data=data, metadata=metadata)

    @classmethod
    def degraded(cls, data: str, reason: str = "") -> "AgentResponse":
        """降级响应（部分数据可用）。"""
        return cls(
            success=True,
            data=data,
            degradation_level="partial",
            metadata={"degradation_reason": reason},
        )

    @classmethod
    def fail(cls, error: str, partial_data: Optional[str] = None) -> "AgentResponse":
        """失败响应。"""
        return cls(
            success=False,
            data=partial_data,
            error=error,
            degradation_level="full",
        )


def wrap_bill_response(raw_text: str) -> AgentResponse:
    """将 BillAgent 的原始文本回复包装为标准 AgentResponse。

    根据关键词判断是否降级/失败。
    """
    if not raw_text:
        return AgentResponse.fail("BillAgent 返回空结果")

    degradation_markers = [
        ("暂无该时段账单数据", "partial"),
        ("部分数据缺失", "partial"),
        ("目前本地没有账单数据", "full"),
        ("暂无数据", "full"),
        ("系统处理异常", "full"),
    ]

    for marker, level in degradation_markers:
        if marker in raw_text:
            if level == "full":
                return AgentResponse.fail(marker, raw_text)
            return AgentResponse.degraded(raw_text, marker)

    return AgentResponse.ok(raw_text)


def wrap_travel_response(raw_text: str) -> AgentResponse:
    """将 TravelAgent 的原始文本回复包装为标准 AgentResponse。"""
    if not raw_text:
        return AgentResponse.fail("TravelAgent 返回空结果")

    degradation_markers = [
        ("未找到该店铺信息", "partial"),
        ("暂无相关信息", "full"),
        ("未找到相关信息", "full"),
        ("系统处理异常", "full"),
    ]

    for marker, level in degradation_markers:
        if marker in raw_text:
            if level == "full":
                return AgentResponse.fail(marker, raw_text)
            return AgentResponse.degraded(raw_text, marker)

    return AgentResponse.ok(raw_text)

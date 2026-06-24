"""统一全局 AgentState 定义。"""

from typing import TypedDict, Annotated, Optional, List, Dict, Any
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class CrossAgentRequest(TypedDict, total=False):
    target_agent: str          # "bill_agent" | "travel_agent"
    query: str
    reason: str
    budget_limit: Optional[float]
    savings_count: Optional[int]
    # 文档方案：上游传递的状态标识，作为目标 Agent 的 prompt 激活开关
    data_status: str           # "normal" | "degraded" | "no_data"
    context_summary: str       # 上游对当前情况的简短描述，帮助目标 Agent 理解上下文


class RAGResultEntry(TypedDict):
    query: str
    retrieved_count: int
    top1_score: float
    top3_scores: List[float]
    avg_confidence: float
    latency_ms: float
    passed_threshold: bool


class FinancialContext(TypedDict, total=False):
    monthly_budget: float
    current_spending: float
    remaining_budget: float
    month: str
    savings_goals: List[Dict[str, Any]]


class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    user_id: str
    current_agent: str
    tool_results: Dict[str, str]
    error_count: int
    rag_results: List[RAGResultEntry]
    cross_agent_request: Optional[CrossAgentRequest]
    cross_agent_response: Optional[str]
    cross_agent_history: List[dict]
    financial_context: Optional[FinancialContext]
    needs_review: bool
    review_passed: bool
    # 文档方案：数据状态标识，作为降级策略的激活开关
    # "normal" | "degraded" | "no_data"
    data_status: str


def create_initial_state(user_input: str, user_id: str) -> AgentState:
    from langchain_core.messages import HumanMessage
    return {
        "messages": [HumanMessage(content=user_input)],
        "user_id": user_id,
        "current_agent": "",
        "tool_results": {},
        "error_count": 0,
        "rag_results": [],
        "cross_agent_request": None,
        "cross_agent_response": None,
        "cross_agent_history": [],
        "financial_context": None,
        "needs_review": True,
        "review_passed": False,
        "data_status": "normal",
    }

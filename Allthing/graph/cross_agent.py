"""P2: 跨 Agent 通信工具。

架构原则（主 Agent 持有历史，子 Agent 作为工具被调用）：
  - query_bill_agent：主 Agent 调用，查询账单数据。子 Agent 沙箱内独立 ReAct。
  - query_travel_agent：主 Agent 调用，查询出行美食。子 Agent 沙箱内独立 ReAct。
  - query_bill_budget / query_travel_savings：子 Agent 内部互相调用（保留兼容）。
  - 子 Agent 作为子工具调用时（allow_cross_agent=False），禁用自身的跨 Agent 工具，防止递归。
"""

from langchain_core.tools import tool


# ============================================================
# 主 Agent 工具（Subagents 模式核心）
# ============================================================

@tool
def query_bill_agent(query: str, financial_context: str = "") -> str:
    """
    【账单管家 API】接入用户的真实微信支付账单系统，获取消费记录和财务分析。

    === 能做什么 ===
    - 按日期范围查询账单（支持跨月，精确到天）
    - 按整月查询账单并自动统计
    - 计算总收入、总支出、日均消费、类目占比
    - 列出交易明细、TOP消费商户
    - 识别高铁票、房租等大额/特殊支出

    === 局限性（你必须知道）===
    1. 一次调用只处理"一个连贯的查询意图"。
       多段不连续的时间范围（如"4月12日-6月1日" + "4月12日前的高铁费"）
       必须分两次调用，然后自己汇总。
    2. 返回数据可能很多，账单管家内部已做预聚合统计，你优先用摘要数字。
    3. 账单管家不会自动提取余额/预算数字——你必须从用户输入中提取，
       填入 financial_context 参数。

    === financial_context 参数 ===
    用户提到财务数字时用 JSON 格式传入：
      例："余额300，明天发工资3000"
      → financial_context='{"balance":300,"upcoming_income":3000,"income_date":"明天"}'
      例："我预算1500，已经花了800"
      → financial_context='{"monthly_budget":1500,"current_spending":800}'
    无财务数字时传空字符串 ""。

    === 调用示例 ===
    简单：query_bill_agent("查询4月份账单总支出和分类", "")
    带财务：query_bill_agent("查询4月12日到6月1日收支明细",
              '{"balance":300,"upcoming_income":3000}')
    分步（你分两次调，自己汇总）：
      第1次: query_bill_agent("查询4月12日到6月1日的全部收支明细")
      第2次: query_bill_agent("查询4月1日到4月11日的高铁票和交通费用")

    === 你的职责 ===
    - "收益能否为正" → 你根据返回的数据自己判断
    - "总结总收入开支" → 你用返回的摘要数字做总结
    - 多段不连续时间 → 你分解为多次调用，自己做最终汇总

    Args:
        query: 要查询的具体问题，自然语言描述
        financial_context: 从用户话语中提取的财务数字，JSON格式字符串，无则传 ""
    """
    fc = None
    if financial_context:
        try:
            import json as _json
            parsed = _json.loads(financial_context)
            if parsed:
                fc = {}
                for k in ("balance", "monthly_budget", "current_spending", "upcoming_income"):
                    if k in parsed:
                        fc[k] = parsed[k]
        except (_json.JSONDecodeError, ValueError):
            pass

    from .bill_node import run_bill_agent
    return run_bill_agent(
        query=query,
        financial_context=fc,
        data_status="normal",
        allow_cross_agent=True,
    )


@tool
def query_travel_agent(query: str, financial_context: str = "") -> str:
    """
    查询出行、美食、景点等本地生活信息。

    使用场景：用户询问附近餐厅、路线规划、景点推荐、天气、美食时调用。
    - "附近有啥好吃的" → query_travel_agent("中山本地推荐餐厅，人均适中的")
    - "怎么去XX" → query_travel_agent("查询去XX的路线")

    === financial_context 参数 ===
    当用户提到预算/金额时，**先调 query_bill_agent 拿到真实账单数据**，
    然后将其中的关键数字通过 financial_context 传入：
      例：'{"monthly_budget":3000,"current_spending":2500}'
    无财务数据时传空字符串 ""。

    === 调用示例 ===
    简单（无预算）：query_travel_agent("推荐一家烧烤", "")
    带预算（先查账单再规划）：
      第1次: query_bill_agent("查询本月日均消费和月度预算")
      第2次: query_travel_agent("推荐一家烧烤",
              '{"monthly_budget":3000,"current_spending":2500}')

    Args:
        query: 要查询的具体问题，自然语言描述即可
        financial_context: 从 query_bill_agent 返回数据中提取的财务数字，
                          JSON 格式字符串，key 含 monthly_budget / current_spending，无则传 ""
    """
    from .travel_node import run_travel_agent

    fc = None
    if financial_context:
        try:
            import json as _json
            parsed = _json.loads(financial_context)
            if parsed:
                fc = {}
                for k in ("balance", "monthly_budget", "current_spending", "upcoming_income"):
                    if k in parsed:
                        fc[k] = parsed[k]
        except (_json.JSONDecodeError, ValueError):
            pass

    # 自动注入默认城市：如果 query 中没提到城市名，从 yml 读取并前置
    KNOWN_CITIES = [
        "深圳", "中山", "广州", "北京", "上海", "梅州", "珠海", "东莞",
        "佛山", "惠州", "江门", "肇庆", "汕头", "潮州", "揭阳", "湛江",
        "茂名", "阳江", "韶关", "清远", "河源", "汕尾", "云浮",
    ]
    has_city = any(c in query for c in KNOWN_CITIES)
    if not has_city:
        try:
            from config.config_loader import config as cfg
            default_city = cfg.get("maps.default_city", "")
            if default_city:
                query = f"默认城市是{default_city}。{query}"
        except Exception:
            pass

    return run_travel_agent(
        query=query,
        financial_context=fc,
        data_status="normal",
        allow_cross_agent=True,
    )


# ============================================================
# 子 Agent 内部互调工具（保留兼容）
# ============================================================


@tool
def query_bill_budget(month: str = "") -> str:
    """
    【跨Agent调用】查询账单Agent获取月度收支预算和消费分析。
    当你需要根据用户预算调整推荐策略、或需要详细的消费数据分析时使用此工具。

    Args:
        month: 账单月份，YYYYMM格式，如"202605"。留空则查当月。
    """
    # 延迟导入，避免循环依赖
    from .bill_node import run_bill_agent

    month_label = f"{month}月" if month else "当月"
    query = (
        f"请查询{month_label}的账单数据，分析以下内容：\n"
        f"1. 🔴 优先调用 get_daily_spending_baseline() 获取日常开销基线（只统计 ≤25 元的日常小额消费），\n"
        f"   引用其中的 daily_baseline 作为预算计算的日均基准\n"
        f"2. 月度总支出和总收入\n"
        f"3. 餐饮类目支出及占比\n"
        f"4. 消费趋势和习惯特征\n"
        f"5. 剩余预算和日均可用金额（结合财务上下文）\n"
        f"\n⚠️ 关键：日常开销基线（第1项）是上级 Agent 做预算计算的核心依据，\n"
        f"必须使用 get_daily_spending_baseline() 返回的 daily_baseline 值。"
    )
    return run_bill_agent(
        query=query,
        financial_context=None,
        data_status="normal",
        cross_agent_request={
            "target_agent": "bill_agent",
            "query": query,
            "reason": "行程助手需要财务数据来调整推荐策略",
            "context_summary": "行程助手需要你的月度预算和消费模式数据",
        },
        allow_cross_agent=False,  # 沙箱模式：禁止 BillAgent 再回调 TravelAgent
    )


@tool
def query_travel_savings(preferences: str = "省钱美食", count: int = 3) -> str:
    """
    【跨Agent调用】查询行程Agent获取省钱美食/免费活动推荐。
    当用户账单显示消费偏高，你想要推荐省钱方案时使用。

    Args:
        preferences: 偏好风格，如"省钱美食"/"免费活动"/"性价比高"
        count: 期望返回的推荐数量，默认3
    """
    # 延迟导入，避免循环依赖
    from .travel_node import run_travel_agent

    query = (
        f"请推荐{count}个{preferences}方案，要求：\n"
        f"1. 标注人均消费金额\n"
        f"2. 优先推荐人均低、口碑好的店铺\n"
        f"3. 包含免费景点/公园/步行路线等零成本活动\n"
        f"4. 推荐适合预算有限的用户的选择"
    )
    return run_travel_agent(
        query=query,
        financial_context=None,
        data_status="normal",
        cross_agent_request={
            "target_agent": "travel_agent",
            "query": query,
            "reason": "账单管家发现用户可能需要节省开支",
            "context_summary": "账单管家需要你提供省钱方案来帮助用户控制支出",
        },
        allow_cross_agent=False,  # 沙箱模式：禁止 TravelAgent 再回调 BillAgent
    )

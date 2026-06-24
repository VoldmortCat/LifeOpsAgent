"""路由层：任务拆解框架 + 正则聚焦扫描 + 增强路由提示词。

核心设计原则：
  1. 正则只做「聚光灯」——切出含数字的句子 + 阿拉伯数字对照表，不做语义判断
  2. LLM 做「大脑」——从聚焦片段中做语义提取（余额/预算/工资/修正）
  3. 正则对照表帮 LLM 校验：你说 balance=500，但对照表里只有 300 和 500，别编 800
"""

import re
import json
from typing import Dict, Any, Optional, List, Tuple


# ============================================================
# 正则聚光灯：只采集信息，不做语义判断
# ============================================================

# 中文数字字符
CN_DIGIT_CHARS = set('零一二两三四五六七八九十百千万亿多')

# 财务关键词（用于识别可能含金额的句子）
MONEY_KEYWORDS = ['余额', '预算', '工资', '花了', '花费', '支出', '收入',
                  '还剩', '剩下', '还有', '卡里', '发', '到账', '入账',
                  '元', '块', '钱', '¥', '￥']

# 阿拉伯数字 + 可选中文字符的金额模式
ARABIC_MONEY_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(?:元|块|钱|万)?')

# 纯日期模式（用于排除日期数字）
DATE_CONTEXT_RE = re.compile(r'(\d{1,2})月(\d{1,2})[日号]|(\d{4})年')


def scan_number_context(user_input: str) -> Dict[str, Any]:
    """正则聚光灯：按句号切句子，筛出含数字/金额的片段 + 阿拉伯数字对照表。

    不做语义判断（不区分余额/预算/工资），只帮 LLM 聚焦到相关的句子。
    数字对照表帮助 LLM 校验提取结果，防止编造不存在的数据。

    Args:
        user_input: 用户原始输入

    Returns:
        {
            "fragments": ["含数字的句子1", "含数字的句子2", ...],
            "number_table": [{"value": 300, "context": "卡里好像是300，不对"}, ...],
        }
    """
    # 1. 按句号/感叹号/问号/换行粗切（逗号不切，保留语义链条）
    raw_sentences = re.split(r'[。！!？?\n]+', user_input)
    raw_sentences = [s.strip() for s in raw_sentences if s.strip()]

    # 2. 筛选含数字/中文数字/财务关键词的句子
    fragments = []
    for s in raw_sentences:
        has_arabic = bool(re.search(r'\d', s))
        has_cn_digit = any(ch in CN_DIGIT_CHARS for ch in s)
        has_money = any(w in s for w in MONEY_KEYWORDS)
        if has_arabic or has_cn_digit or has_money:
            fragments.append(s)

    # 3. 提取阿拉伯数字对照表（过滤掉纯日期数字）
    number_table = []
    for match in ARABIC_MONEY_RE.finditer(user_input):
        num_str = match.group(1)
        num_val = float(num_str)

        # 排除纯日期数字：数字紧邻"月"或"日"
        before = user_input[max(0, match.start() - 1):match.start()]
        after = user_input[match.end():match.end() + 1] if match.end() < len(user_input) else ''
        if before in ('月',) or after in ('月', '日', '号'):
            # 但如果数字 ≥ 100，大概率是年份或金额，保留
            if num_val < 100:
                continue

        # 取前后 8 个字作为上下文
        ctx_start = max(0, match.start() - 8)
        ctx_end = min(len(user_input), match.end() + 8)
        context = user_input[ctx_start:ctx_end]

        number_table.append({
            "value": num_val,
            "context": context.strip(),
        })

    return {
        "fragments": fragments,
        "number_table": number_table,
    }


def build_financial_context_json(financial_numbers: Dict[str, Any]) -> str:
    """将数字 dict 转为 financial_context JSON 字符串。"""
    fc = {}
    for key in ("balance", "monthly_budget", "current_spending", "upcoming_income"):
        if key in financial_numbers:
            fc[key] = financial_numbers[key]
    return json.dumps(fc, ensure_ascii=False) if fc else ""


# ============================================================
# 任务拆解规则（确定性模板）
# ============================================================

def detect_time_segments(user_input: str) -> List[Tuple[str, str, str]]:
    """识别用户输入中的时间范围请求。

    返回 [(描述, 开始, 结束), ...] 列表。
    例如: [("主时间段", "4月12日", "6月1日"), ("补充时间段", "4月1日", "4月11日")]
    """
    segments = []

    # 模式1: "X月X日到Y月Y日"
    range_pattern = r'(\d{1,2})月(\d{1,2})[日号]?\s*[到至\-~]\s*(\d{1,2})月(\d{1,2})[日号]?'
    for m_start, d_start, m_end, d_end in re.findall(range_pattern, user_input):
        segments.append((
            f"{m_start}月{d_start}日到{m_end}月{d_end}日",
            f"{int(m_start):02d}-{int(d_start):02d}",
            f"{int(m_end):02d}-{int(d_end):02d}",
        ))

    # 模式1b: "X月X日到X日"（同月省略月份）如 "4月1日到15日"
    same_month_pattern = r'(\d{1,2})月(\d{1,2})[日号]?\s*[到至\-~]\s*(\d{1,2})[日号]?(?!\s*月)'
    for m, d1, d2 in re.findall(same_month_pattern, user_input):
        month_str = f"{int(m):02d}"
        segments.append((
            f"{m}月{d1}日到{d2}日",
            f"{month_str}-{int(d1):02d}",
            f"{month_str}-{int(d2):02d}",
        ))

    # 模式2: "X月X日前"或"X月X日之前/以前"
    before_pattern = r'(\d{1,2})月(\d{1,2})[日号]?(?:\s*[之以])?前'
    for m, d in re.findall(before_pattern, user_input):
        segments.append((
            f"{m}月{d}日前",
            f"{int(m):02d}-01",
            f"{int(m):02d}-{int(d):02d}",
        ))

    return segments


# ============================================================
# 增强路由提示词
# ============================================================

ROUTING_PROMPT_V2 = """
你是 LifeOps 调度大脑。分析用户请求，决定调用哪些子 Agent。

## 子 Agent 能力

**query_bill_agent(query, financial_context)** — 账单管家
  能做什么：按日期范围/整月查账单、统计收支、列出明细、识别高铁房租等大额支出
  局限：一次只处理一个时间范围，不连续的多个时间范围必须分次调用
  financial_context：JSON 字符串，从用户话语中提取的余额/预算/工资等数字
    格式：'{"balance":800,"upcoming_income":5000,"monthly_budget":2000,"current_spending":1200}'
    无财务数字时传空字符串 ""

**query_travel_agent(query, financial_context)** — 出行助手
  美食推荐、路线规划、景点查询、天气
  financial_context：JSON 字符串，**从 query_bill_agent 返回的数据中提取**的月度预算/已支出等数字
    格式：'{"monthly_budget":3000,"current_spending":2500}'
    无财务数据时传空字符串 ""

## 🔴 任务拆解规则（必须严格执行）

### 规则0：预算 + 行程混合请求（最高优先级！两阶段执行）

当用户请求**同时包含预算/金额/余额和出行/美食/路线**时，**必须分两阶段执行**：

**阶段1**：先调 query_bill_agent 获取真实账单数据
  - 查询内容：本月日均消费、月度预算、已支出金额
  - 拿到返回后，从数据中提取 monthly_budget 和 current_spending

**阶段2**：再调 query_travel_agent，将阶段1提取的财务数据作为 financial_context 传入
  - query 参数：用户的出行请求原文（一字不改）
  - financial_context 参数：'{"monthly_budget":3000,"current_spending":2500}'

示例：
  用户说"我身上有100块，撑2天，推荐一家烧烤"
  → 阶段1: query_bill_agent("查询本月日均消费、月度预算和已支出金额", "")
  → 阶段2: query_travel_agent("推荐一家烧烤 预算100元 撑2天",
            '{"monthly_budget":3000,"current_spending":2500}')

**禁止**在一次决策中同时调 query_bill_agent + query_travel_agent 来处理预算+行程混合请求！
必须先拿到账单数据，再带数据调行程——否则行程助手拿不到真实财务数据。

### 规则1：时间范围拆解
如果用户请求涉及**两个不连续的时间范围**，必须拆成两次 query_bill_agent 调用：
- 例："5月1日到7月15日的账单，加上5月1日前买电脑的支出"
  → 调用1: query_bill_agent("查询5月1日到7月15日的总收入支出明细")
  → 调用2: query_bill_agent("查询4月1日到4月30日的大额电子消费品支出")
禁止合并为一次调用！禁止改写时间范围！

### 规则2：从数字片段中提取财务信息
系统已将用户输入中含数字的句子聚焦在下方【数字片段】区域。
请从这些片段中**语义判断**并提取：
- balance（余额/卡里/还剩）
- monthly_budget（月预算/预算）
- current_spending（已花/花了/支出）
- upcoming_income（发工资/到账/入账）

提取规则：
- 注意语义修正（"好像是300，不对应该是500" → 以 500 为准）
- 中文数字需转换（"两千八"→2800，"三百多"→约350）
- 【数字对照表】供你校验——你提取的金额应该能在对照表中找到对应数字
  如果对照表中没有你提取的数字，说明你可能编造了，请重新检查

### 规则3：query 参数规则（区分 Agent 类型）

**对 query_bill_agent**：用精准子任务描述，不要塞用户原话。
每个 query 只描述一个时间范围的查询需求，保留具体时间、类目、条件。

**对 query_travel_agent**：必须原封不动传入用户的完整原始消息！
出行助手需要完整的上下文：地点名称、预算金额、天数、数量要求（"一家""三个"）等。
禁止改写/摘要/精简用户的出行请求！丢失任何一个细节都会导致推荐失败。

例：用户说"我现在中山东区紫马岭下街安逸住宿,我身上有100块,大概2天后才有生活费到账,请你为我推荐一家合适的烧烤店,并为我规划路线图"
→ query_travel_agent(query="我现在中山东区紫马岭下街安逸住宿,我身上有100块,大概2天后才有生活费到账,请你为我推荐一家合适的烧烤店,并为我规划路线图")
→ 必须原样传入，一字不改！

### 规则4：判断类任务留给 Synthesis
"总体盈亏如何"、"够不够用"、"超预算了吗"这类**纯财务判断** → 不传给子 Agent，留给 Synthesis 阶段处理。
子 Agent 只负责查数据，判断由主 Agent 在拿到数据后自己做。

### 规则5：每次出行/路线请求必须重新调用工具（最高优先级！）
即使用户之前已经问过类似的路线问题，只要用户提出了新的路线/出行/地点请求，
**必须重新调用 query_travel_agent**，禁止复用历史中的回复。
- 用户说"从A到B怎么走" → 必须调 query_travel_agent
- 用户又说"从C到D怎么走" → 必须再次调 query_travel_agent，即使上一轮已经回答过类似问题
- 每次路线请求的起点/终点不同，必须重新获取数据，禁止直接复用上一轮的文本回复
- 账单查询同理：新的账单查询必须重新调用 query_bill_agent

## 路由表

| 用户意图 | 做法 |
|---------|------|
| 预算+行程混合（"X块撑Y天推荐烧烤"） | **两阶段**：先调 query_bill_agent 拿日均消费 → 再调 query_travel_agent 带 financial_context |
| 单一账单查询 | 1次 query_bill_agent |
| 两个不连续时间范围 | 分2次 query_bill_agent |
| 账单+出行混合（无预算金额关联） | 同时调 query_bill_agent + query_travel_agent |
| 纯计算/算术/数学 | 调 calculate，禁止心算 |
| 闲聊/感谢/打招呼 | 不调工具 |
| 路线/出行/地点请求（无预算关联） | **必须调 query_travel_agent**（即使历史中有类似请求） |
"""

# ============================================================
# 增强合成提示词
# ============================================================

SYNTHESIS_PROMPT_V2 = """
你是 LifeOps 智能助手。你收到的消息中包含了子 Agent（账单管家、出行助手）返回的真实数据。
你的任务：基于 ToolMessage 中的真实数据，用自然语言为用户整理回复。

## 🔴 跨轮隔离铁律（最高优先级，违反=回答无效）
- 你看到的对话历史中的 AIMessage（之前的回复）**只是上下文参考**，**严禁复制其格式、结构、措辞或模板**
- 每次回复都是全新的，只根据**当前用户消息 + 最新 ToolMessage** 独立生成
- **绝对禁止**从历史 AIMessage 中搬运任何内容块（如表格、链接、标题、操作指南）
- 如果历史中有路线规划相关回复，而当前问题是账单查询 → 完全忽略历史中的路线内容，不要提及、不要复制
- 当前问题问什么就答什么，历史回复的风格和格式与你无关

## 回复规则
1. 直接搬运 ToolMessage 中的数据，不编造金额、日期、交易记录
2. 如果路由阶段调用了多次 bill agent（如两段不连续时间范围），汇总对比
3. 用户问"总体盈亏/收益能否为正" → 用查到的数字计算：总收入 - 总支出 + 余额 + 即将到账工资
4. 保持对话式的自然语言

## 计算类问题的处理
当用户要求判断盈亏/够不够/超预算等：
  净收益 = 期间总收入 - 期间总支出 + 当前余额 + 即将到账收入
  若结果 > 0 → "整体盈余，约X元"
  若结果 ≤ 0 → "整体亏损，缺口约X元"

## 绝对禁止
❌ "我没有数据"、"这是模拟数据"、"为保护隐私仅展示部分"、"此处省略"
❌ 编造任何数字
❌ 在没有 ToolMessage 的情况下输出具体数据
❌ 编造任何百度地图 URL 链接（如 map.baidu.com/?newmap=1&...）——前端通过 map_data 推送来渲染地图，不需要你生成链接
❌ 生成"手机端操作指南"表格（如"长按链接→复制→粘贴到浏览器"）——这是 AI 幻觉模板
❌ 生成"一键导航直达"等虚假功能标题
"""

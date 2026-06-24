# LifeOps Agent V3.0

基于 LangGraph 的多 Agent 智能生活管家。Subagents 架构：主 Agent 全程驾驶决策，Bill Agent / Travel Agent 作为子工具按需沙箱调用。具备 Agentic RAG、Critic 自省护栏、完整财务数据管线、深度思考追踪等机制。

---

## 一、核心机制

### 1. Subagents 多 Agent 架构

```
用户
 │
 ▼
主 Agent（qwen-plus，enable_thinking）
 │  自主拆解任务、调度子Agent、融合多源数据、重试与纠错
 │
 ├── query_bill_agent(query) ──→ Bill Agent（qwen-max）沙箱 ReAct
 │      邮箱下载 → 解压 → CSV 解析 → pandas 统计 → 回复
 │
 └── query_travel_agent(query) ──→ Travel Agent（qwen-plus）沙箱 ReAct
        RAG 检索 → 百度地图 6 工具 → 联网搜索 → Critic 审查 → 回复
```

**关键设计**：
- 主 Agent 持有对话历史和 checkpoint，子 Agent 沙箱隔离（消息历史不污染主 Agent）
- 主 Agent 不是被动路由，是**自主决策**——理解意图 → 拆解子任务 → 调用子 Agent → 拿到数据后自己做跨域推理
- 子 Agent 内部 ReAct 循环对主 Agent 完全透明——传入 query，返回文本
- 子 Agent 互调（bill ↔ travel）通过 `allow_cross_agent=False` 防递归

### 2. ReAct 自自适应循环

主 Agent 的核心智能不是规则驱动的，是 **LLM 观察 ToolMessage 后自主决策**：

```
用户: "除去坐车、高铁票、租房后的开销总额"
  │
主 Agent: query_bill_agent("排除交通类...和住房类...") → bill 返回空
主 Agent 看到空 → 同样措辞再试 1 次 → 还是空
主 Agent 看到两次空 → 换措辞 "排除交通出行类和住房费用类" → 还是空
主 Agent 看到三次空 → 彻底换策略 "查询最近30天总支出" → bill 返回数据
→ 主 Agent 拿到全量数据后自己做分类扣除计算
```

这不是框架的重试机制，是 LLM 在看到 ToolMessage 后自己推理出的"这个问题换种问法可能行"。

### 3. Agentic RAG —— 三层信息源优先级链

Travel Agent 的信息检索不是单次 RAG，是**按优先级逐层降级**：

| 层级 | 来源 | 工具 | 触发条件 |
|------|------|------|---------|
| 第①层 | 本地经验库 | `search_knowledge` | 每次查询必调 |
| 第②层 | 百度地图 API | `search_and_get_details` / `search_nearby_places` 等 6 个工具 | RAG 返回空或需要实时信息 |
| 第③层 | 联网搜索（模型内置） | LLM 自带搜索能力 | RAG + 百度都无结果 |

**RAG 检索管线**：
```
knowledge_base/*.md（人工标注的经验/避坑）
  → DashScope text-embedding-v2（1536d）
  → ChromaDB 持久化
  → 查询时：向量余弦相似度 + 关键词加权 + 标签过滤
  → ≥0.3 阈值过滤 → 返回
```

### 4. Critic 自省护栏

Travel Agent 产出推荐后，Critic 对推荐文本做 **RAG 反向交叉验证**——不调 LLM，只查数据：

```
Travel Agent 推荐: "推荐蜀大侠火锅 ⭐4.8 ¥85"
  │
Critic: search_knowledge("蜀大侠 差评 刷评 避坑")
  ├── 命中负面记录 → 在推荐末尾贴 ⚠️ 审核标签
  └── 未命中 → 原样通过
```

**设计原则**：Critic 不改原文内容，只附加审核标签。不是"另一个 LLM 审查 LLM"，而是"RAG 数据审查推荐"——零额外 token 消耗，数据驱动。

### 5. 完整财务数据管线

```
微信支付账单邮件
  → check_and_download_bill_email()     # IMAP 自动下载附件
  → unzip_latest_wechat_bill(password)   # 用户提供解压密码
  → WxBillAnalyze CSV 解析清洗            # pandas 规范化
  → 按月分片存储到 data/bills/YYYYMM.csv
  → get_monthly_bill_data / get_date_range_bill_data 查询
  → Bill Agent LLM 做语义分类（交通/住房/餐饮/其他）
```

配合省钱目标系统（`set_savings_goal` / `get_financial_context`），形成从数据摄入到消费决策的闭环。

### 6. 防幻觉机制 —— "搬运工，不是翻译器"

早期版本 LLM 拿到工具返回的 31 条交易记录后逐条重生成，导致商户名被修改、金额编造。解决方案：

- 工具层返回**预格式化的完整表格**（含总计、逐条记录）
- LLM 只做嵌入（把表格搬到回复里），不做翻译（不逐条重生成）
- Prompt 明确禁止："隐私保护话术"、"其余XX笔省略"、"编造交易记录"
- 确立原则：**LLM 适合语义理解和决策，不适合精确复制结构化数据**

### 7. 深度思考可观测性

所有 Agent 节点（主 Agent、Bill Agent、Travel Agent）均启用 ChatTongyi `enable_thinking=True`，`reasoning_content` 实时输出到控制台：

```
🧠 [TRAVEL-AGENT 深度思考]
  好的，用户需要中山附近人均100元以内的海鲜餐厅推荐...
  查看每个结果：第3条爱群食店是早茶 → 排除；第5条特产手信 → 排除...
  御品名厨：牛尾煲98+脆肉鲩腩78=176，两人分人均88...  ← 真的在列算式
```

配合 `TracedToolNode` 的工具调用追踪（调用参数、返回内容、耗时），整个系统的推理和工具链完全透明。

### 8. 动态 Prompt 拼装

所有 Agent 的 System Prompt 不是固定字符串，是按运行时 state 动态组装的：

- `data_status="degraded"` → 激活降级策略块
- `data_status="no_data"` → 激活无数据处理流程
- `cross_agent_request` 存在 → 激活跨 Agent 协作上下文
- `financial_context` 存在 → 注入预算感知块（按 budget_healthy / tight / critical 三级）
- 以上都不命中 → 仅加载 BASE_PROMPT（日常精简）

### 9. RAG 可观测性（自研监控）

线程安全 RAGMonitor 单例记录每次检索的元数据（query、Top-1 精度、置信度、响应时间、阈值状态），支持：
- `/rag` 命令实时查看仪表盘和命中率
- `/rag_test` 命令跑批量评估用例
- JSONL + TXT 双日志持久化

---

## 二、项目结构

```
Allthing/
├── main.py                              # CLI 入口，支持用户切换、内置命令
│
├── config/
│   ├── config.yml                       # 统一配置（邮箱/账单/地图/Graph/监控）
│   └── config_loader.py                 # YAML 加载器，${ENV} 占位符
│
├── graph/                               # LangGraph 状态机
│   ├── state.py                         # AgentState + FinancialContext + CrossAgentRequest
│   ├── graph_builder.py                 # 主图组装：main_agent ⇄ tools（Subagents）
│   ├── bill_node.py                     # Bill Agent 子图（沙箱 ReAct，9 个工具）
│   ├── travel_node.py                   # Travel Agent 子图（沙箱 ReAct，11 个工具）
│   ├── cross_agent.py                   # 跨 Agent 工具：query_bill_agent / query_travel_agent
│   ├── prompt_templates.py              # 动态 Prompt 策略库 + assembler
│   └── tool_tracer.py                   # TracedToolNode + dump_reasoning 深度思考追踪
│
├── tools/                               # 工具生态（langchain @tool 封装）
│   ├── bill/
│   │   ├── bill_tools.py                # 账单工具集（7 个）：邮箱下载/解压/月度查询/日期范围/图表/数据盘点
│   │   └── bill_processor.py            # CSV 解析清洗（WxBillAnalyze）
│   ├── maps/
│   │   └── baidu_maps_tools.py          # 百度地图工具集（6 个）：POI搜索/详情/路线/天气/地理编码
│   ├── knowledge/
│   │   └── knowledge_tools.py           # RAG 检索：向量+关键词混合排序、ChromaDB 持久化、标签自动提取
│   ├── savings/
│   │   └── savings_tools.py             # 省钱目标管理：JSON 持久化、预算/支出/目标进度
│   └── time/
│       └── time_tools.py                # get_current_time
│
├── knowledge_base/                      # RAG 源语料（Markdown 原文，不预处理）
│   ├── food/
│   │   ├── zhongshan_restaurants.md      # 中山食录：90+ 段落（乳鸽/早茶/海鲜/养生/咖啡）
│   │   └── scene_guide.md               # 场景攻略：快速午餐/聚餐约会/月底省钱
│   ├── general/
│   │   └── zhongshan_travel.md           # 中山穿行手册：景点/交通/住宿/路线
│   └── other/
│
├── monitoring/                          # RAG 可观测性
│   ├── rag_logger.py                    # RAGMonitor 线程安全单例 + RAGLogEntry
│   ├── dashboard.py                     # /rag 控制台仪表盘
│   ├── test_runner.py                   # /rag_test 批量评估
│   └── test_cases.yml                   # 评估用例
│
├── data/                                # 运行时数据（gitignore）
│   ├── bills/                           # 账单 CSV（按月分片：202603.csv / 202604.csv）
│   ├── checkpoints/                     # SQLite checkpoint（多用户对话历史隔离）
│   ├── vectordb/                        # ChromaDB 向量持久化
│   ├── savings/                         # 省钱目标 goals.json
│   └── monitoring/                      # rag_detail.log + rag_logs.jsonl
│
├── docs/                                # 设计文档
│   ├── 管家助手1.0.md                    # 四大模块全景设计
│   ├── 行程助手设计1.0V.md               # 初始架构设计
│   └── 行程助手业务流程与演进路线.md       # V1→V2→V3 演进规划
│
├── scripts/                             # 一次性脚本
│   ├── import_knowledge.py              # 知识库导入
│   └── test_*.py                        # RAG/Graph/persist/threshold 测试
│
├── tests/                               # 单元测试
│
└── 面试准备路线图.md                      # 从开发到面试的完整学习规划
```

---

## 三、工具全景

| 领域 | 工具 | 功能 |
|------|------|------|
| **账单** (9) | `get_data_inventory` | 查看本地 CSV 文件清单和统计信息 |
| | `get_monthly_bill_data` | 按月读取完整账单（YYYYMM） |
| | `get_date_range_bill_data` | 按日期范围查询，支持跨月自动合并 |
| | `check_and_download_bill_email` | IMAP 自动下载微信账单附件 |
| | `unzip_latest_wechat_bill` | 解压账单 zip（用户提供密码） |
| | `generate_bill_charts` | matplotlib 图表生成 |
| | `set_savings_goal` | 记录省钱目标和预算 |
| | `update_saved_amount` | 更新省钱进度 |
| | `get_financial_context` | 读取预算/支出/目标快照 |
| **地图** (6) | `search_and_get_details` | 百度 POI 搜索+详情一步到位 ⭐推荐 |
| | `search_nearby_places` | 周边搜索（返回 uid） |
| | `get_place_details` | POI 详情（评分/价格/营业时间） |
| | `get_route_plan` | 路线规划（驾车/步行/公交/骑行） |
| | `get_weather_by_location` | 天气查询 |
| | `geocode_address` | 地址→经纬度 |
| **知识** (1) | `search_knowledge` | RAG 本地经验库语义检索 |
| **跨 Agent** (4) | `query_bill_agent` | 主 Agent → Bill Agent |
| | `query_travel_agent` | 主 Agent → Travel Agent |
| | `query_bill_budget` | Travel → Bill 财务分析 |
| | `query_travel_savings` | Bill → Travel 省钱推荐 |
| **通用** (1) | `get_current_time` | 当前系统时间 |

---

## 四、技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 编排 | LangGraph StateGraph + SqliteSaver | 图状态机 + 多用户 checkpoint 持久化 |
| LLM | 通义千问 qwen-max / qwen-plus | ChatTongyi, enable_thinking=True |
| Embedding | DashScope text-embedding-v2 | 1536 维 |
| 向量库 | ChromaDB PersistentClient | 本地磁盘持久化 |
| 地图 | 百度地图 Web 服务 API | 6 个接口 |
| 数据处理 | pandas + matplotlib | CSV 解析、图表生成 |
| 邮件 | Python imaplib | IMAP 自动下载账单 |
| 配置 | YAML + ${ENV} 占位符 | 环境变量注入 |
| 监控 | 自研 RAGMonitor | 线程安全单例 + JSONL 日志 |

---

## 五、启动

```bash
python main.py
```

## 六、内置命令

| 命令 | 功能 |
|------|------|
| `/help` | 查看帮助 |
| `/rag` | RAG 监控仪表盘（Top-N 精度、置信度、响应时间） |
| `/rag_test` | 批量评估用例 |
| `切换用户 <名>` | 切换 thread_id（对话隔离，独立 checkpoint） |
| `quit` / `exit` / `q` | 退出 |

---

## 七、当前阶段：V2.8 → V3.0

```
V1.0 基础工具    V2.0 RAG+财务    V2.8 当前     V3.0
  LangChain       ChromaDB      Subagents      Critic 自省
  百度地图 API    三层 RAG      完整管线        多源交叉验证
                  财务感知      自适应循环      MCP 标准化
                                深度思考追踪
```

详见 `面试准备路线图.md`。

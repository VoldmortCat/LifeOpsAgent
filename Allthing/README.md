# LifeOps Agent V3.0

基于 LangGraph 的多 Agent 智能生活管家。主 Agent 全程驾驶决策，Bill Agent（账单分析）和 Travel Agent（出行规划）作为子工具按需沙箱调用。

---

## 一、功能概览

| 模块 | 功能 |
|------|------|
| **智能对话** | 自然语言交互，自动意图识别，主 Agent 自主拆解任务、调用子工具 |
| **账单管理** | 微信支付账单自动下载（IMAP）、解压、CSV 解析、按月分片存储、图表生成、花销分类统计 |
| **出行规划** | 餐饮推荐、景点搜索、路线规划（驾车/步行/公交/骑行）、天气查询，基于本地经验库 RAG + 百度地图 API + 联网搜索三层信息源 |
| **省钱目标** | 设置预算、追踪支出、目标进度管理 |
| **知识库 RAG** | 本地 Markdown 经验文档向量化，语义检索，Critic 自省护栏反向交叉验证 |
| **个人中心** | 用户配置管理、对话历史隔离 |

---

## 二、启动前必须配置

### 1. 环境变量

在终端或系统环境变量中设置以下 Key：

```bash
# 必填 —— 通义千问 API（阿里云 DashScope）
export DASHSCOPE_API_KEY="your_dashscope_api_key"

# 可选 —— 百度地图服务端 API（出行路线规划等需要）
export BAIDU_MAPS_API_KEY="your_baidu_maps_server_key"

# 可选 —— LangSmith 调试追踪
export LANGCHAIN_API_KEY="your_langsmith_api_key"

# 可选 —— DeepSeek 模型（切换 provider 为 deepseek 时需要）
export DEEPSEEK_API_KEY="your_deepseek_api_key"
```

> **获取方式：**
> - DashScope API Key：https://dashscope.console.aliyun.com/apiKey
> - 百度地图 API Key：https://lbsyun.baidu.com/apiconsole/key
> - LangSmith API Key：https://smith.langchain.com/settings

### 2. 邮箱配置（账单自动下载）

编辑 `config/config.yml` 第 44-49 行，填入你的 163 邮箱 IMAP 信息：

```yaml
email:
  imap_server: "imap.163.com"
  username: "your_email@163.com"
  password: "your_email_password"      # 163 邮箱的 IMAP 授权码，非登录密码
  watch_folder: "INBOX"
```

> **注意：** 163 邮箱需在设置中开启 IMAP 服务，并使用「授权码」而非登录密码。`config/user_config.yml` 作为用户个人覆盖配置已加入 `.gitignore`，不会被提交。

### 3. 地图展示方式

前端不引入百度地图 SDK，Travel Agent 在回复末尾自动附带百度地图链接（`map.baidu.com`）。点击链接后：H5 跳转百度地图网页版、App 唤起百度地图 App、小程序复制链接到浏览器打开。

---

## 三、快速启动

### 后端

```bash
cd Allthing
pip install -r requirements.txt

# CLI 模式（终端对话）
python main.py

# API 服务模式（供前端调用）
python server.py
# 服务启动在 http://localhost:8000
```

### 前端（uni-app）

```bash
cd LifeOps助手
npm install

# H5 开发模式
npm run dev:h5

# 微信小程序
npm run dev:mp-weixin
```

### 内置命令

| 命令 | 功能 |
|------|------|
| `/help` | 查看帮助 |
| `/rag` | RAG 监控仪表盘 |
| `/rag_test` | 批量评估用例 |
| `/stats` | 工具调用统计 |
| `/model` | 当前模型配置 |
| `切换用户 <名>` | 切换对话身份（独立 checkpoint） |
| `quit` / `exit` / `q` | 退出 |

---

## 四、核心机制

### Subagents 多 Agent 架构

```
用户
 │
 ▼
主 Agent（qwen-plus）
 │  自主拆解任务、调度子Agent、融合多源数据、重试与纠错
 │
 ├── query_bill_agent(query) ──→ Bill Agent 沙箱 ReAct（9 个工具）
 │      邮箱下载 → 解压 → CSV 解析 → pandas 统计 → 回复
 │
 └── query_travel_agent(query) ──→ Travel Agent 沙箱 ReAct（11 个工具）
        RAG 检索 → 百度地图 6 工具 → 联网搜索 → Critic 审查 → 回复
```

### Agentic RAG —— 三层信息源

| 层级 | 来源 | 触发条件 |
|------|------|---------|
| 第①层 | 本地经验库（Milvus 向量检索） | 每次查询必调 |
| 第②层 | 百度地图 API | RAG 返回空或需要实时信息 |
| 第③层 | 联网搜索（模型内置） | RAG + 百度都无结果 |

### Critic 自省护栏

Travel Agent 产出推荐后，Critic 对推荐内容做 RAG 反向交叉验证——检索知识库中是否有该商户的差评/避坑记录，命中则附加审核标签。不改原文，只附加标签，零额外 token 消耗。

---

## 五、项目结构

```
项目根目录/
├── Allthing/                            # 后端（Python + LangGraph）
│   ├── main.py                          # CLI 入口
│   ├── server.py                        # FastAPI 服务端（WebSocket + REST）
│   ├── requirements.txt                 # Python 依赖
│   ├── config/
│   │   ├── config.yml                   # 系统默认配置（邮箱/账单/地图/模型）
│   │   ├── user_config.yml              # 用户个人覆盖配置（已 gitignore）
│   │   └── config_loader.py             # 配置加载器（二层加载 + 脱敏）
│   ├── graph/                           # LangGraph 状态机
│   │   ├── state.py                     # AgentState 定义
│   │   ├── graph_builder.py             # 主图组装
│   │   ├── bill_node.py                 # Bill Agent 子图
│   │   ├── travel_node.py               # Travel Agent 子图
│   │   ├── cross_agent.py               # 跨 Agent 工具
│   │   └── tool_tracer.py               # 工具调用追踪
│   ├── tools/                           # 工具集
│   │   ├── bill/                        # 账单工具（邮箱下载/解压/查询/图表）
│   │   ├── maps/                        # 百度地图工具（POI/路线/天气）
│   │   ├── knowledge/                   # RAG 检索工具
│   │   ├── savings/                     # 省钱目标管理
│   │   └── time/                        # 时间工具
│   ├── prompts/                         # 动态 Prompt 拼装
│   ├── llm/                             # LLM 注册与创建
│   ├── routing/                         # 任务分解器
│   ├── knowledge_base/                  # RAG 源语料（Markdown）
│   ├── monitoring/                      # RAG 可观测性
│   ├── guardrails/                      # Critic 自省护栏
│   └── data/                            # 运行时数据（gitignore）
│       ├── bills/                       # 账单 CSV
│       ├── checkpoints/                 # SQLite checkpoint
│       ├── vectordb/                    # Milvus Lite（.db 嵌入式）
│       └── savings/                     # 省钱目标
│
└── LifeOps助手/                         # 前端（uni-app + Vue3）
    ├── pages/                           # 页面（首页/账单/文档/我的）
    ├── components/                      # 组件
    ├── store/                           # Pinia 状态管理
    ├── utils/                           # 工具（API/WebSocket/Markdown）
    ├── index.html                       # 入口 HTML
    └── package.json
```

---

## 六、技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 编排 | LangGraph StateGraph + SqliteSaver | 图状态机 + 多用户 checkpoint 持久化 |
| LLM | 通义千问 qwen-plus / qwen-max | ChatTongyi，支持 enable_thinking |
| Embedding | DashScope text-embedding-v2 | 1536 维 |
| 向量库 | Milvus Lite 嵌入式（服务端稠密+BM25 混合检索降级为应用层管线） | 本地 .db 文件持久化 |
| 地图 | 百度地图 Web 服务 API | POI搜索/详情/路线/天气/地理编码 |
| 数据处理 | pandas + matplotlib | CSV 解析、图表生成 |
| 后端框架 | FastAPI + WebSocket | REST API + 实时通信 |
| 前端框架 | uni-app (Vue 3) + Pinia | 跨端（H5 / 微信小程序） |
| 邮件 | Python imaplib | IMAP 自动下载账单 |

---

## 七、模型配置

编辑 `config/config.yml` 中 `agents` 段可切换模型：

```yaml
agents:
  main:
    provider: "tongyi"     # tongyi / openai / deepseek
    model: "qwen-plus"
    temperature: 0.5
    enable_thinking: false
```

- `tongyi`: 使用 `DASHSCOPE_API_KEY` 环境变量
- `openai`: 使用 `OPENAI_API_KEY` 环境变量
- `deepseek`: 使用 `DEEPSEEK_API_KEY` 环境变量

# LifeOps Agent V3.0

基于 LangGraph 的多 Agent 智能生活管家。主 Agent 全程驾驶决策，Bill Agent（账单分析）和 Travel Agent（出行规划）作为子工具按需沙箱调用。

---

## 功能概览

| 模块 | 功能 |
|------|------|
| **智能对话** | 自然语言交互，主 Agent 自动拆解意图、调度子 Agent、融合多源数据 |
| **账单管理** | 微信支付账单 IMAP 自动下载 → 解压 → CSV 解析 → 按月分片存储 → 图表生成 → 花销分类统计 |
| **出行规划** | 餐饮推荐、景点搜索、路线规划（驾车/公交/步行）、天气查询，基于本地经验库 RAG + 百度地图 API |
| **省钱目标** | 预算设置、支出追踪、目标进度管理 |
| **知识库 RAG** | 本地 Markdown 文档向量化（ChromaDB），**BM25 + 向量混合检索**，city 前置过滤，**Golden Set 评估体系** |
| **前端界面** | 账单中心（收支统计 + 图表）、文档中心（知识库上传/预览）、个人中心（服务器配置/邮箱配置） |

---

## 必须配置

### 1. 环境变量

```bash
# 必填 —— 通义千问 API（阿里云 DashScope）
DASHSCOPE_API_KEY=your_dashscope_api_key

# 可选 —— 百度地图服务端 API（出行路线规划需要）
BAIDU_MAPS_API_KEY=your_baidu_maps_server_key

# 可选 —— LangSmith 调试追踪
LANGCHAIN_API_KEY=your_langsmith_api_key
```

> 获取地址：[DashScope](https://dashscope.console.aliyun.com/apiKey) / [百度地图开放平台](https://lbsyun.baidu.com/apiconsole/key) / [LangSmith](https://smith.langchain.com/settings)

### 2. 邮箱配置（账单自动下载用）

编辑 `Allthing/config/config.yml` 第 44-49 行：

```yaml
email:
  imap_server: "imap.163.com"
  username: "your_email@163.com"
  password: "your_imap_auth_code"       # 163 授权码，非登录密码
  watch_folder: "INBOX"
```

> 163 邮箱需在网页设置中开启 IMAP/SMTP 服务，使用「授权码」而非登录密码。

### 3. 百度地图前端 AK

编辑 `LifeOps助手/index.html` 第 14 行，将 `YOUR_BAIDU_MAPS_AK` 替换为百度地图开放平台申请的**浏览器端 AK**。

后端 `Allthing/server.py` 通过 `BAIDU_MAPS_BROWSER_AK` 环境变量读取 AK，前端可通过 `/api/config/map-ak` 接口动态获取。

---

## 快速启动

### 后端

```bash
cd Allthing
pip install -r requirements.txt

# CLI 终端对话模式
python main.py

# API 服务模式（供前端调用，端口 8000）
python server.py
```

### 前端

```bash
cd LifeOps助手
npm install
npm run dev:h5        # H5 开发
npm run dev:mp-weixin # 微信小程序
```

### RAG 评估（可选）

```bash
cd Allthing

# 基线评估（纯向量检索）
python scripts/eval_rag.py

# BM25 混合检索评估
python scripts/eval_rag.py --hybrid

# 对比两种模式
python scripts/eval_rag.py --compare

# 重建向量库（知识库变更后）
python scripts/rebuild_vectordb.py
```

---

## 项目结构

```
正式项目地/
├── README.md
├── Allthing/                          # 后端（Python + LangGraph）
│   ├── main.py                        # CLI 入口
│   ├── server.py                      # FastAPI（WebSocket + REST）
│   ├── requirements.txt               # Python 依赖
│   ├── config/
│   │   ├── config.yml                 # 系统默认配置
│   │   ├── user_config.yml            # 用户覆盖配置（已 gitignore）
│   │   └── config_loader.py           # 配置加载器（二层加载 + 脱敏）
│   ├── graph/                         # LangGraph 状态机
│   │   ├── graph_builder.py           # 主 Agent 图
│   │   ├── bill_node.py               # Bill Agent 子图（ReAct）
│   │   ├── travel_node.py             # Travel Agent 子图（ReAct）
│   │   ├── cross_agent.py             # 主 Agent 调子 Agent 的工具函数
│   │   ├── state.py                   # 状态定义
│   │   └── tool_tracer.py             # 工具调用追踪
│   ├── tools/                         # 工具集
│   │   ├── bill/                      # 账单工具（邮箱下载/解压/查询/图表）
│   │   ├── maps/                      # 百度地图工具（MCP + @tool 双通道）
│   │   ├── knowledge/                 # RAG 检索工具
│   │   │   ├── knowledge_tools.py     #   检索/索引/评估主逻辑
│   │   │   └── hybrid_retriever.py    #   BM25 + 向量混合检索器
│   │   ├── savings/                   # 省钱目标管理
│   │   ├── common/                    # 通用工具（计算器）
│   │   └── time/                      # 时间工具
│   ├── prompts/                       # 4 层动态 Prompt 拼装
│   │   ├── assembler.py               #   运行时按需拼装（核心入口）
│   │   ├── base/                      #   L1 基础层（角色 + 工具清单）
│   │   ├── decision/                  #   L2 决策层（流程 + 停止规则）
│   │   ├── runtime/                   #   L3 运行时层（降级/预算感知/跨Agent）
│   │   └── failure/                   #   L4 失败层（逐工具重试策略）
│   ├── llm/                           # LLM 模型注册（通义/OpenAI/DeepSeek 可切换）
│   ├── routing/                       # 任务分解（意图识别 + 路由）
│   ├── knowledge_base/                # RAG 源语料（Markdown + frontmatter）
│   │   ├── food/
│   │   │   ├── zhongshan_restaurants.md  # 中山餐厅（90+ 条）
│   │   │   ├── scene_guide.md            # 场景化攻略
│   │   │   └── shenzhen_bbq.md           # 深圳烧烤店（city 隔离验证）
│   │   └── general/
│   │       └── zhongshan_travel.md       # 中山旅游手册
│   ├── monitoring/                    # RAG 日志与在线监控
│   ├── guardrails/                    # 工具调用护栏 + 输出内容审查
│   ├── docs/                          # 设计文档
│   ├── scripts/                       # 运维脚本
│   │   ├── eval_rag.py                #   RAG 评估脚本（Golden Set 50 题）
│   │   ├── rebuild_vectordb.py        #   向量库重建
│   │   └── import_knowledge.py        #   知识库导入工具
│   └── data/                          # 运行时数据
│       ├── rag_golden_set.json         #   Golden Set（50 题标准答案）
│       └── rag_eval/                   #   评估结果
│
└── LifeOps助手/                       # 前端（uni-app + Vue3）
    ├── pages/
    │   ├── index/                     # 智能管家（对话页）
    │   ├── bill/                      # 账单中心
    │   ├── docs/                      # 文档中心
    │   └── mine/                      # 个人中心
    ├── components/                    # 组件（输入框/消息气泡/地图/账单）
    ├── store/                         # Pinia 状态管理
    ├── utils/                         # API / WebSocket / Markdown
    └── index.html                     # 入口（需配百度地图 AK）
```

---

## 技术栈

| 层 | 技术 |
|----|------|
| Agent 编排 | LangGraph StateGraph + SqliteSaver checkpoint |
| LLM | 通义千问 qwen-plus / qwen-max（可切换 OpenAI / DeepSeek） |
| Embedding | DashScope text-embedding-v2（1536 维） |
| 向量库 | ChromaDB（HNSW 索引 + metadatas 过滤） |
| 检索策略 | 向量语义 + BM25 关键词 + 标签加权 + **city 前置过滤** |
| 地图 | 百度地图 Web 服务 API + MCP 协议 + BMapGL 前端渲染 |
| 数据处理 | pandas + matplotlib |
| 后端框架 | FastAPI + WebSocket |
| 前端框架 | uni-app (Vue 3) + Pinia |
| 邮件 | Python imaplib |
| 分词 | jieba（BM25 中文分词） |

---


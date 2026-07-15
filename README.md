# LifeOps Agent V3.0

基于 LangGraph 的多 Agent 智能生活管家，主 Agent 全程驾驶决策，Bill Agent（账单分析）和 Travel Agent（出行规划）作为子工具按需沙箱调用。

---

## 功能概览

| 模块 | 功能 |
|------|------|
| **智能对话** | 自然语言交互，主 Agent 自动拆解意图、调度子工具、融合多源数据 |
| **账单管理** | 微信支付账单 IMAP 自动下载 → 解压 → CSV 解析 → 按月分片 → 图表生成 → 花销分类统计 |
| **出行规划** | 餐饮推荐、景点搜索、路线规划、天气查询，三层信息源：本地经验库 RAG → 百度地图 API → 联网搜索 |
| **省钱目标** | 预算设置、支出追踪、目标进度管理 |
| **知识库 RAG** | 本地 Markdown 文档向量化（ChromaDB），语义检索，Critic 自省护栏反向交叉验证 |
| **个人中心** | 用户配置管理、多用户对话历史隔离 |

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

两处 HTML 文件需要填入百度地图浏览器端 AK：

| 文件 | 行号 | 说明 |
|------|------|------|
| `LifeOps助手/index.html` | 第 14 行 | uni-app 前端入口 |
| `Allthing/visualize_route.html` | 第 12 行 | 路线调试页面 |

将 `YOUR_BAIDU_MAPS_AK` 替换为你在百度地图开放平台申请的**浏览器端 AK**。

后端 `Allthing/server.py` 通过 `BAIDU_MAPS_BROWSER_AK` 环境变量读取，前端页面直接通过 `/api/config/map-ak` 接口获取。

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

---

## 项目结构

```
正式项目地/
├── README.md
├── Allthing/                          # 后端（Python + LangGraph）
│   ├── main.py                        # CLI 入口
│   ├── server.py                      # FastAPI（WebSocket + REST）
│   ├── requirements.txt               # Python 依赖
│   ├── config/                        # 配置（YAML 二层加载 + 脱敏）
│   ├── graph/                         # LangGraph 状态机（主图 + 子图）
│   ├── tools/                         # 工具集（账单/地图/知识库/省钱/时间）
│   ├── prompts/                       # 动态 Prompt 拼装
│   ├── llm/                           # LLM 模型注册
│   ├── routing/                       # 任务分解
│   ├── knowledge_base/                # RAG 源语料（Markdown）
│   ├── monitoring/                    # RAG 可观测性
│   ├── guardrails/                    # Critic 自省护栏
│   ├── docs/                          # 设计文档
│   └── data/                          # 运行时数据（账单/checkpoint/向量库）
│
└── LifeOps助手/                       # 前端（uni-app + Vue3）
    ├── pages/                         # 页面（首页/账单/文档/我的）
    ├── components/                    # 组件
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
| 向量库 | ChromaDB |
| 地图 | 百度地图 Web 服务 API + BMapGL |
| 数据处理 | pandas + matplotlib |
| 后端框架 | FastAPI + WebSocket |
| 前端框架 | uni-app (Vue 3) + Pinia |
| 邮件 | Python imaplib |

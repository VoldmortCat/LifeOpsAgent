# LifeOps Agent — 多 Agent 智能生活管家

> 基于 LangGraph 的多 Agent 架构，主 Agent 全程驾驶决策，Bill Agent（账单分析）和 Travel Agent（出行规划）作为子图按需沙箱调用。集账单管理、出行规划、RAG 知识库、用户认证于一体，支持 Web H5 / 微信小程序双端运行。

---

## Core Features

| Feature | Description |
|---------|-------------|
| **Multi-Agent Orchestration** | LangGraph StateGraph + Subagents pattern; Main Agent decomposes intent, dispatches sub-agents, synthesizes responses |
| **Bill Agent** | IMAP email auto-download WeChat bills -> unzip -> CSV parse -> matplotlib charts -> spending analysis + daily baseline |
| **Travel Agent** | Local RAG (Milvus + BM25) + Baidu Maps API (MCP protocol + @tool dual-channel), restaurants/attractions/routes/weather |
| **Savings Goals** | Budget setup, spending tracking, progress management, financial context shared across agents |
| **User Authentication** | JWT Token auth, register/login, multi-user isolation, session persistence (SQLite WAL mode) |
| **RAG Monitoring** | Golden Set evaluation -> real-time dashboard -> RAG log tracing -> LangSmith lineage |
| **Guardrails** | Tool call audit (anti-repeat/throttle), output compliance verification, layered fallback strategies |

---

## Architecture

                    User (H5 / WeChat)
                    WebSocket + REST API
                        FastAPI Server
                  Main Agent (StateGraph)
           ToolNode: query_bill | query_travel | time | calc
              Bill Agent (ReAct sandbox)    Travel Agent (React sandbox)
        IMAP email download        Milvus RAG + Baidu Maps MCP
        CSV parsing + charts       Knowledge base + Weather

---

## Project Structure

```
正式项目地/
Allthing/                          # Backend (Python + LangGraph)
  main.py                        # CLI chat entrypoint
  server.py                      # FastAPI service (WS + REST + static)
  requirements.txt               # Python dependencies
  Dockerfile                     # Container deployment
  graph/                         # LangGraph state machine & agent graphs
    graph_builder.py           # Main Agent graph (V3 full-tool closed loop)
    bill_node.py               # Bill Agent ReAct subgraph
    travel_node.py             # Travel Agent ReAct subgraph
    cross_agent.py             # Main->Sub Agent tool bridge
    state.py                   # AgentState / CrossAgentRequest / FinancialContext
    tool_tracer.py             # Tool call tracking + reasoning logs
  routing/                       # Task decomposition router
    task_decomposer.py         # Regex spotlight + LLM semantic extraction
  prompts/                       # 4-layer dynamic prompt assembler
    assembler.py               # Runtime assembly entrypoint
    base/                      # L1 base layer (role + tool list)
    decision/                  # L2 decision layer (workflow + stop rules)
    runtime/                   # L3 runtime layer (degrade/budget/cross-agent)
    failure/                   # L4 failure layer (retry strategies)
  tools/                         # Agent tools
    bill/                      # Bill toolchain (email download -> parse -> chart)
    maps/                      # Baidu Maps (MCP + @tool dual-channel)
    knowledge/                 # RAG (Milvus + hybrid_retriever)
    savings/                   # Savings goal management
    common/                    # Common tools (calculator)
    time/                      # Time fetching
  llm/                           # LLM registry center
    llm_registry.py            # Singleton / model hot-swap / token usage tracking
  guardrails/                    # Guardrail system
    critics.py                 # Tool call audit + output compliance check
  monitoring/                    # Observability
    rag_logger.py              # RAG query logging & metrics
    dashboard.py               # Console RAG dashboard
    test_runner.py             # Golden Set evaluation executor
    logger.py / langsmith_setup.py
  config/                        # Unified configuration
    config.yml                 # Models/paths/email/bill/maps parameters
    config_loader.py           # Two-layer loading (default+user override)
    user_config.yml            # User overrides (gitignore)
  auth.py                        # JWT register/login/auth
  db.py                          # SQLite models (User/Conversation/Message)
  docs/                          # Design documents
  scripts/                       # Ops scripts
    import_knowledge.py        # KB import (SHA256 dedup)
    rebuild_vectordb.py        # Vector DB rebuild
    eval_rag.py                # RAG quality evaluation
  data/                          # Runtime data (checkpoints/bills/db)
LifeOps助手/                       # Frontend (uni-app + Vue 3 + Pinia)
  App.vue / pages.json / manifest.json
  pages/                         # Pages
    index/index.vue            # Chat main UI (drawer panel + conversation mgmt)
    login/login.vue            # Login/Register
    bill/bill.vue              # Bill center (stats + charts)
    docs/docs.vue              # Document center
    mine/mine.vue              # Profile (server config / logout)
  store/                         # Pinia stores
    chat.js                    # Conversations/messages/WS connection
    auth.js                    # Auth state
  utils/                         # Utilities
    api.js                     # REST API wrapper (auto token injection)
    websocket.js               # WebSocket (token auth + reconnect)
    markdown.js                # Markdown rendering
  static/                        # Icon resources
```

---

## Quick Start

### Prerequisites

- Python >= 3.10
- Node.js >= 18
- Git

### 1. Clone

```bash
git clone https://github.com/VoldmortCat/LifeOpsAgent.git
cd LifeOpsAgent/正式项目地
```

### 2. Configure Environment Variables

```bash
cd Allthing
# Required
export DASHSCOPE_API_KEY="your_dashscope_api_key"
# Optional
export BAIDU_MAPS_API_KEY="your_baidu_maps_server_key"
export LANGCHAIN_API_KEY="your_langsmith_api_key"
export JWT_SECRET_KEY="your_jwt_secret_key"
```

> Get API Keys: [DashScope](https://dashscope.console.aliyun.com/apiKey) | [Baidu Maps](https://lbsyun.baidu.com/apiconsole/key) | [LangSmith](https://smith.langchain.com/settings)

### 3. Configure Email (for bill download)

Edit `Allthing/config/config.yml`:

```yaml
email:
  imap_server: "imap.163.com"
  username: "your_email@163.com"
  password: "your_imap_auth_code"       # 163 authorization code
  watch_folder: "INBOX"
```

### 4. Install & Run

#### Backend

```bash
cd Allthing
pip install -r requirements.txt
# Option A: CLI terminal chat
python main.py
# Option B: API service mode (port 8000)
python server.py
```

#### Frontend

```bash
cd LifeOps助手
npm install
# H5 development -> visit http://localhost:5173
npm run dev:h5
# WeChat Mini Program
npm run dev:mp-weixin
```

#### Knowledge Base Import (optional)

```bash
cd Allthing
python scripts/import_knowledge.py knowledge_base/food/zhongshan_restaurants.md  # single file
python scripts/import_knowledge.py knowledge_base/  # bulk import
python scripts/rebuild_vectordb.py  # rebuild vector DB to apply changes
```

---

## Agent Architecture in Detail

### Subagents Pattern

The Main Agent has all tools available every round. The LLM thinks step-by-step and decides which tool(s) to call.
Sub-agents (Bill / Travel) run their own independent ReAct loops inside a sandbox without polluting the main conversation history.

Each sub-agent invocation is a complete observe-decide-act-feedback cycle.

### 4-Layer Dynamic Prompt Assembly

Prompt blocks are dynamically assembled at runtime based on AgentState:

| State Field | Effect |
|------------|--------|
| `data_status` | degraded/no_data activates fallback prompt |
| `cross_agent_request` | Injects cross-agent collaboration context when present |
| `financial_context` | Activates budget-aware block when spending data is available |

- **L1 Base**: Role definition + tool list + capability boundaries
- **L2 Decision**: Workflow rules + stop conditions + output format
- **L3 Runtime**: Degradation / budget awareness / cross-agent coordination
- **L4 Failure**: Per-tool retry strategies + exception handling

### Guardrails System

Flow: ToolCallCritic (throttle/duplicate check) -> Execution -> OutputCritic (fact-check/compliance)
Defaults: max 8 total calls per agent, max 2 same-tool calls, prevents infinite ReAct loops.

---

## Knowledge Base RAG System

### Retrieval Pipeline

```
User Query -> city filter (Milvus partition key)
        Dense Vector        BM25 Fulltext
        (Milvus WeightedRanker fusion)
        Top-K + Tag Boosting
          Hit              Miss
 Return          Fallback to JSON snapshot
 Results         (app-level keyword search)
```

### Vector Stores

| Solution | Role | Notes |
|----------|------|-------|
| **Milvus 2.5** | Primary | Server-side hybrid search (dense vector + BM25), partition key = city |
| **ChromaDB** | Fallback | JSON snapshot app-level keyword search when Milvus unavailable |

### CLI Built-in Commands

In `python main.py`:

/rag | RAG monitoring dashboard
/rag_test | Run Golden Set batch evaluation
/stats | Tool call statistics for this session
/model | Current model configuration
/help | Show help

Sample dashboard output:

  [RAG] Monitor Dashboard
========================================================================
  Total queries (window 100):  847
  Top-1 accuracy:             89.61%
  Top-3 accuracy:             94.33%
  Avg confidence:             0.7823
  Avg response time:          42.7 ms
  Max response time:          312.1 ms
  Queries below threshold:    41
========================================================================

---

## API Endpoints

### Authentication

| Method | Path | Description |
|--------|------|-------------|
POST | /api/auth/register | Register user
POST | /api/auth/login | Login (returns JWT)
GET | /api/auth/me | Get current user info

### Conversations

| Method | Path | Description |
|--------|------|-------------|
GET | /api/conversations | List conversations
GET | /api/conversations/{id} | Get messages for conversation
POST | /api/conversations | Create new conversation
DELETE | /api/conversations/{id} | Delete conversation
PUT | /api/conversations/{id} | Update conversation title

### Streaming Chat

| Method | Path | Description |
|--------|------|-------------|
POST | /api/chat/stream | Stream chat response (WS or SSE)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent Framework | LangGraph StateGraph + SqliteSaver checkpoint |
| LLM | Qwen-plus/qwen-max (switchable to OpenAI/DeepSeek) |
| Embedding | DashScope text-embedding-v2 (1536 dim) |
| Vector Database | Milvus 2.5 (primary) + ChromaDB (fallback) |
| Retrieval | Milvus hybrid (dense vector + BM25) + city partition pushdown |
| Backend | FastAPI + WebSocket |
| Frontend | uni-app (Vue 3) + Pinia + H5 / WeChat Mini Program |
| Maps | Baidu Maps Web API + MCP protocol + BMapGL |
| Data Processing | pandas + matplotlib |
| Storage | SQLite (WAL mode) |
| Observability | LangSmith + custom RAG monitoring |
| Tokenization | jieba (BM25 Chinese tokenization) |

---

## Roadmap

### Short-term (High Impact)
- [ ] User spending habit profiling -- learn consumption patterns from bill data
- [ ] Destination preference learning -- recommend types based on historical choices
- [ ] RAG incremental updates -- append new docs without full rebuild
- [ ] Calendar event integration -- incorporate user schedule into agent decisions

### Medium-term (Feature Expansion)
- [ ] Voice input -- speech-to-text control
- [ ] Image OCR -- receipt/menu/screenshot recognition
- [ ] Long document RAG -- PDF/Word upload with chunked QA

### Long-term (Shape Upgrade)
- [ ] Multimodal knowledge base -- image KB + hybrid image-text retrieval
- [ ] AI interview assistant -- resume parsing + mock interviews + evaluation
- [ ] Cron scheduled tasks -- periodic bill reports, weekly summaries, reminders
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

---

## 知识库 RAG 系统

> 本项目的 RAG 用于出行规划场景，基于本地 Markdown 文档 + 向量检索 + BM25 关键词混合检索。以下是完整的知识库管理规范。

### 文件目录结构

```
knowledge_base/               # 知识库根目录
├── README.md                 # 知识库规范文档
├── food/                     # 美食类
│   ├── zhongshan_restaurants.md  # 中山餐厅推荐
│   ├── scene_guide.md            # 场景化攻略
│   └── shenzhen_bbq.md           # 深圳烧烤
├── travel/                   # 旅行类
│   └── zhongshan_travel.md       # 中山旅游手册
├── general/                  # 其他通用类
└── .import_tracker.json      # 导入追踪文件（自动生成）
```

### 信息来源规范

#### 信息来源分级

| 级别 | 来源类型 | 可信度 | 说明 |
|------|---------|--------|------|
| S 级 | 官方渠道 | ⭐⭐⭐⭐⭐ | 政府官网、景区官网、商家官方公众号/公告 |
| A 级 | 权威媒体 | ⭐⭐⭐⭐ | 文旅中山、南方+、中山日报、携程美食林、马蜂窝 |
| B 级 | 公开测评 | ⭐⭐⭐ | 大众点评、小红书笔记——需交叉验证，注明来源 |
| C 级 | AI 辅助生成 | ⭐⭐⭐ | AI 整理的数据必须人工审核，标注 `generated_by_ai: true` |

#### 来源标注方式

每个文档的 frontmatter 中如实标注 `source` 字段：

```yaml
# 单一来源
source: 携程美食林

# 多个来源
source: 文旅中山/南方+/中山日报

# AI 辅助整理
source: 小红书笔记（AI 整理），人工审核
generated_by_ai: true
```

#### 禁止使用的来源

- 爬虫抓取的未经授权的商业数据
- 个人隐私信息（真实姓名、电话、详细地址）
- 未公开的内部资料
- 过时超过 3 年的时效性数据（餐厅营业状态、价格信息）

### 文档格式规范

#### 1. frontmatter 元数据（必填）

每个 `.md` 文件开头必须包含 YAML frontmatter：

```yaml
---
city: 中山               # 城市/地区（必填，用于 city 前置过滤）
category: 美食            # 分类：美食/旅行/攻略/通用（必填）
source: 携程美食林/南方+   # 信息来源（必填）
updated: 2025             # 数据更新年份（必填）
tags: 乳鸽,早茶,海鲜      # 可选，手动指定标签
generated_by_ai: false    # 是否 AI 辅助生成（可选，默认 false）
---
```

#### 2. 段落结构规范

```
## 标题 — 一句话亮点说明

正文内容⋯⋯（200-600 字，自然语言叙述）

## 下一个标题

正文内容⋯⋯
```

| 规则 | 说明 |
|------|------|
| 用 `##` 二级标题 | 每个 `##` 段落是一个独立检索单元，切块时按此分隔 |
| 不要嵌套 | 不要在 `##` 里写 `###`，向量检索只按 `##` 切块 |
| 标题清晰 | `## 店名 — 一句话亮点` 格式，让 LLM 一眼看懂 |
| 自然语言 | 保持叙述风格，不要写成结构化表格或 JSON |
| 每段独立 | 一段写一个实体（一个餐厅/一个景点），不要混合多个 |
| 段落长度 | 建议 200-600 字。过短语义不足，过长上下文窗口占用大 |

#### 3. 文件命名规范

| 规范 | 规则 | 示例 |
|------|------|------|
| 命名 | 小写英文 + 下划线，见名知意 | `zhongshan_restaurants.md` |
| 分类目录 | 按主题放入对应子目录 | `food/` 放餐厅、美食 |
| 不要用 | 中文文件名、空格、特殊字符 | ❌ `中山餐厅.md` |

### 导入流程

#### 前置预处理要求

导入前确认以下事项：

1. **格式校验**：文件必须是 `.md` 格式，包含 `##` 二级标题，至少 2 个段落块
2. **元数据完整**：frontmatter 包含 `city`/`category`/`source`/`updated` 四个必填字段
3. **数据审核**：S 级/A 级来源可直接使用；B 级来源需交叉验证；C 级来源需人工审核
4. **内容去重**：检查是否与已有知识库内容重叠，避免重复导入

#### 导入命令

```bash
cd Allthing

# 导入单个文件
python scripts/import_knowledge.py knowledge_base/food/zhongshan_restaurants.md

# 导入整个目录
python scripts/import_knowledge.py knowledge_base/food/

# 强制重新导入（覆盖 SHA256 去重）
python scripts/import_knowledge.py --force knowledge_base/food/zhongshan_restaurants.md
```

导入工具会自动完成：SHA256 去重校验 → 复制到 knowledge_base 对应目录 → 记录追踪文件。

#### 导入后验证

```bash
# 查看导入追踪状态
cat knowledge_base/.import_tracker.json

# 重建向量库（使新数据生效）
python scripts/rebuild_vectordb.py

# 运行评估验证检索质量
python scripts/eval_rag.py --compare
```

### 一份完整合规的示例文档

```markdown
---
city: 中山
category: 美食
source: 携程美食林/南方+/小红书（AI 整理），人工审核
updated: 2025
generated_by_ai: true
tags: 乳鸽,石岐区,老字号
---

# 中山乳鸽名店精选

## 石岐佬中山菜馆 — "天下第一鸽"

石岐佬在石岐区康华路，门口经常排队⋯⋯（正文 200-600 字）
```

### RAG 检索优化方向

以下是当前 RAG 的检索链路及未来可升级的方向：

#### 当前检索链路

```
用户查询 → city 前置过滤 → 向量语义检索（余弦相似度）
                                   ↓
                           BM25 关键词检索（jieba 分词）
                                   ↓
                           线性融合（alpha × 向量 + (1-alpha) × BM25）
                                   ↓
                           标签加权（匹配标签则加分）
                                   ↓
                           Top-K 结果返回
```

#### 待升级优化方向

| 方向 | 当前问题 | 改进方案 | 预期收益 | 难度 |
|------|---------|---------|---------|------|
| **分片策略优化** | 按 `##` 标题固定切块，段落长度参差不齐 | 引入**自适应分片**：设定 token 上限（如 500 tokens），超长段落自动二次切分，过短段落合并相邻段落，保持语义完整 | 检索命中率提升，减少上下文碎片 | ⭐⭐ |
| **分片重叠策略** | 硬切分导致相邻段落间的语义关联丢失 | 引入**滑动窗口重叠**：相邻分片重叠 10-20% 内容，确保跨片段信息不丢失 | 解决"信息刚好在分片边界"的漏检问题 | ⭐⭐ |
| **检索策略升级** | 简单线性融合，权重固定 | 引入**动态权重调节**：根据查询类型自动调整 α 值（关键词查询 → 提高 BM25 权重；语义查询 → 提高向量权重）。或引入 RRF（倒数排名融合）作为备选 | 不同类型查询的检索精度提升 | ⭐⭐⭐ |
| **查询重写** | 用户口语化查询直接检索，与知识库风格不匹配 | 用户查询先经 LLM 重写（口语 → 关键词优化版），再执行检索。重写版本与原版双路召回 | 缩小查询与文档的语义差距 | ⭐⭐⭐ |
| **多路召回融合** | 仅向量 + BM25 两路 | 增加第三路召回：**标题关键词匹配**（`##` 标题单独索引，优先匹配标题命中结果） | 标题明确匹配时精度大幅提升（如"石岐佬"直接命中标题） | ⭐ |
| **检索后重排序** | 融合后直接取 Top-K，未做精排 | 引入 **Cross-Encoder 重排序**：对 Top-20 候选结果做精排，提升 Top-5 的准确率。可用小型 reranker（如 BGE-reranker） | 精排后 Top-5 准确率明显提升 | ⭐⭐⭐⭐ |
| **语义分块** | 纯按标题切分，无法处理无标题文本 | 引入**语义分块**：用 embedding 计算段落间的语义相似度，将语义相近的段落自动聚合成块，而不是硬按标题切 | 适用场景更广（无标题文档、爬虫采集的文本） | ⭐⭐⭐⭐ |
| **增量更新** | 每次导入新数据需重建整个向量库 | 实现**增量索引**：新文档嵌入后直接追加到 ChromaDB，无需重建，同时更新 BM25 的词频统计 | 导入速度提升，避免重建期间检索中断 | ⭐⭐⭐ |
| **评估体系升级** | 固定 50 题 Golden Set，覆盖场景有限 | 扩展 Golden Set 至 100+ 题，覆盖更多查询类型（模糊查询、复合查询、边界查询）。引入**自动化评估 pipeline**：每次知识库变更后自动跑评估，输出质量报告 | 检索质量可量化、可追踪 | ⭐⭐⭐ |
| **多模态扩展** | 仅支持文本检索 | 支持图片知识库：图片 → 图片描述 → 文本向量化。支持图文混合检索（如"发一张图片看看"） | 知识库覆盖范围拓宽 | ⭐⭐⭐⭐⭐ |

#### 建议优先升级顺序

```
第一优先级（低成本、高收益）：
  1. 分片策略优化（自适应分片 + 滑动窗口）
  2. 增加标题关键词匹配第三路召回
  3. 扩展 Golden Set 评估集

第二优先级（中等成本、收益明显）：
  4. 查询重写（LLM 改写用户查询）
  5. 动态权重调节（α 值自适应）
  6. 检索后重排序（Cross-Encoder）

第三优先级（高成本、长期优化）：
  7. 语义分块
  8. 增量更新
  9. 多模态扩展
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

## 待升级开发功能

### 出行模块增强
| 功能 | 说明 | 优先级 |
|------|------|--------|
| **用户开销习惯画像** | 基于 Bill 账单数据，自动分析用户月度预算区间、消费波动规律，用于出行方案预算适配 | ⭐⭐⭐ |
| **出行目的地偏好学习** | 记录用户历史出行目的地选择，自动推荐偏好类型（海滨/城市/自然/古镇） | ⭐⭐⭐ |
| **饮食习惯偏好** | 记录用户口味偏好（辣度、菜系偏好、忌口），出行推荐时自动过滤匹配 | ⭐⭐⭐ |
| **日历引入 & 用户计划** | 对接日历 API，感知用户已有计划（攒钱目标、省钱计划、出行安排），在多 Agent 决策时自动纳入上下文 | ⭐⭐⭐⭐ |
| **自动搜索 & 文档分片整理** | 用户给定目的地后，自动搜索互联网信息（攻略/点评/景点），分片整理后写入知识库，摆脱纯人工维护 | ⭐⭐⭐⭐⭐ |

### 未来其他模块展望

#### 工具类
| 功能 | 说明 |
|------|------|
| **RAG 长文档解析 & 提炼总结** | 用户上传 PDF/Word/论文，自动分片、向量化、支持多轮问答与摘要生成 |

#### 功能类
| 功能 | 说明 |
|------|------|
| **语音识别模块** | 接入语音输入，用户说话即可控制 Agent（语音→文字→意图识别→执行） |
| **图片 OCR 识别** | 上传图片自动识别文字，用于发票、截图、菜单等场景的信息提取与入库 |

#### 业务类
| 功能 | 说明 |
|------|------|
| **AI 面试助手** | 简历识别导入 → 解析技能/经历 → 自动生成模拟面试 → 回答评估 → 面试总结报告。可作为独立子 Agent 运行 |

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


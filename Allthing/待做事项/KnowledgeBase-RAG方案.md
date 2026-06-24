# TravelAgent 知识库（RAG）集成方案

## 一、问题现状

当前 TravelAgent 是**纯 API 调用模式**，存在 4 大知识盲区：

| 盲区 | 表现 | 例子 |
|------|------|------|
| 无本地经验 | 不知道餐厅真实口碑 | 百度显示"蜀大侠 4.8"，但实际排队2小时 |
| 无用户偏好 | 每次都从零开始 | 每次都问"你喜欢什么口味？" |
| 无场景感知 | 不会根据场景推荐 | 午餐推荐火锅店（时间不够） |
| 无预算感知 | 不考虑经济状况 | 推荐85元/人的店，但你月底只剩50元 |

**根本原因**：百度地图 API 只返回结构化数据（评分/价格/地址），缺少"软信息"（排队/口味/避坑）。

---

## 二、解决方案：Agentic RAG

### 核心思路

给 TravelAgent 装上"本地经验记忆"：

```
用户："推荐个好吃的餐厅"

Step 1: 百度地图API搜索（骨架）
  → [蜀大侠 4.8, 湘菜馆 4.5, ...]

Step 2: RAG知识库检索（血肉）← 新增！
  → "蜀大侠：毛肚必点，11:30前免排队"
  → "湘菜馆：偏咸，说少盐"

Step 3: 融合后回复
  → "推荐蜀大侠（4.8），毛肚是招牌，建议11:30前去免排队~"
```

### ReAct 工作流

```
1. 用户输入 → 2. LLM 理解意图 → 3. 同时调用：
                                          ├─ search_knowledge(query)  ← RAG检索
                                          └─ search_nearby_places()   ← 百度API
                                  → 4. 智能融合 → 5. 格式化回复
```

---

## 三、知识库内容规划

### 3.1 本地美食经验库（`knowledge_base/food/`）

**文档：`food_experience.md`**
```markdown
# 中山美食经验手册

## 必吃推荐
### 利品湘木桶饭
- 推荐菜：木桶饭、酸豆角肉末
- 最佳时间：11:30前（免排队）
- 人均：25-35元
- 注意：味道偏咸，说"少盐"

### 蜀大侠火锅
- 必点：毛肚、鹅肠、虾滑
- 人均：70-85元
- 提醒：周末排队1小时+，建议工作日去
- 评分：4.8（真实体验：环境好但偏贵）

## 避坑警告
### XX火锅城
- 问题：差评率>15%，疑似刷评
- 识别方法：实际评分约3.5，但显示4.5
- 建议：避开
```

**文档：`scene_guide.md`**
```markdown
# 场景化攻略

## 快速午餐（30分钟内）
- 优先级：速度 > 口味 > 价格
- 推荐类型：快餐、面馆、木桶饭
- 搜索关键词：快餐、面馆

## 聚餐/约会（2小时+）
- 优先级：环境 > 口味 > 价格
- 推荐类型：火锅、日料、西餐
- 搜索关键词：火锅、日料

## 月底省钱（人均<30元）
- 优先级：价格 > 分量 > 口味
- 推荐类型：快餐、小吃、食堂
- 搜索关键词：小吃、快餐
```

### 3.2 用户偏好画像（`knowledge_base/profile/`）

**文档：`user_preferences.md`**
```json
{
  "口味偏好": ["辣", "粤菜", "日料"],
  "忌讳": ["海鲜过敏", "不吃内脏", "不吃香菜"],
  "价格区间": {
    "日常": "40-60元/人",
    "聚餐": "80-120元/人",
    "月底": "20-30元/人"
  },
  "区域偏好": ["石岐区", "东区"],
  "交通方式": "公交优先，步行<500m",
  "常见场景": ["工作日午餐", "周末聚餐"]
}
```

### 3.3 决策失误案例（`knowledge_base/decisions/`）

**文档：`mistake_cases.md`**
```markdown
# 决策失误案例库

## 案例001：推荐超出预算的餐厅
- 时间：2026-04-15
- 场景：用户月底想聚餐
- 错误：推荐了人均85元的蜀大侠
- 教训：推荐前应确认预算/场景，月底默认按低价推荐
- 规则：IF 月底 AND 用户未指定预算 THEN 默认按 <40元推荐

## 案例002：推荐需排队的店但时间不够
- 时间：2026-04-22
- 场景：用户午休1小时想吃饭
- 错误：推荐了需排队30分钟的网红店
- 教训：快速午餐场景不推荐热门排队店
- 规则：IF 场景=快速午餐 THEN 过滤掉 average_wait > 15分钟的店
```

---

## 四、技术实现

### 4.1 依赖

```txt
# requirements.txt 新增
chromadb>=0.5.0           # 向量数据库
langchain-text-splitters  # 文档分块
tiktoken                  # token 计数
```

### 4.2 目录结构

```
knowledge_base/               # Markdown 知识源文件
├── food/
│   ├── food_experience.md    # 美食经验
│   └── scene_guide.md        # 场景攻略
├── profile/
│   └── user_preferences.md   # 用户偏好
└── decisions/
    └── mistake_cases.md      # 决策失误案例

src/knowledge/                # RAG 管理模块
├── __init__.py
└── rag_manager.py            # ChromaDB 初始化 + 检索接口
```

### 4.3 核心代码（`rag_manager.py`）

```python
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import DirectoryLoader, TextLoader
import os

class RAGManager:
    """知识库管理器：负责 Markdown 文档加载、向量化、检索"""
    
    def __init__(self, kb_dir="knowledge_base", db_dir="data/vectordb"):
        self.kb_dir = kb_dir
        self.embeddings = DashScopeEmbeddings(model="text-embedding-v2")
        self.db_dir = db_dir
        self.vectorstore = None
        self._init_or_load()
    
    def _init_or_load(self):
        if os.path.exists(self.db_dir) and os.listdir(self.db_dir):
            self.vectorstore = Chroma(
                persist_directory=self.db_dir,
                embedding_function=self.embeddings
            )
        else:
            self.rebuild()
    
    def rebuild(self):
        """重新加载所有 Markdown 文档并重建向量库"""
        loader = DirectoryLoader(
            self.kb_dir,
            glob="**/*.md",
            loader_cls=TextLoader,
            loader_kwargs={"encoding": "utf-8"}
        )
        docs = loader.load()
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500, chunk_overlap=50
        )
        chunks = text_splitter.split_documents(docs)
        self.vectorstore = Chroma.from_documents(
            chunks, self.embeddings,
            persist_directory=self.db_dir
        )
    
    def search(self, query: str, k: int = 3) -> str:
        """语义检索"""
        if not self.vectorstore:
            return ""
        results = self.vectorstore.similarity_search(query, k=k)
        if not results:
            return ""
        return "\n".join(f"- {r.page_content}" for r in results)
```

### 4.4 工具封装（新增 `search_knowledge` 工具）

```python
# src/tools/common/knowledge_tools.py

from langchain_core.tools import tool
from src.knowledge.rag_manager import RAGManager

rag = RAGManager()

@tool
def search_knowledge(query: str) -> str:
    """
    从本地知识库检索相关经验信息（美食攻略/避坑指南/场景攻略等）。
    
    当用户需求涉及以下方面时必须调用：
    - 餐厅推荐、美食评价、口味偏好
    - 避坑建议、真实口碑验证
    - 场景化建议（快速午餐/聚餐/省钱）
    
    Args:
        query: 搜索查询，如"好吃的火锅推荐"、"月底省钱吃饭"
    
    Returns:
        检索到的知识片段，无结果则返回空字符串
    """
    result = rag.search(query, k=3)
    if not result:
        return "（本地知识库中暂无相关经验）"
    return f"【本地经验参考】\n{result}"
```

### 4.5 集成到 TravelAgent

在 `travel_agent.py` 中：

```python
# 工具列表新增
MAPS_TOOLS = [
    search_nearby_places,
    get_place_details,
    search_and_get_details,
    get_route_plan,
    get_weather_by_location,
    geocode_address,
    search_knowledge,  # 🆕 新增
]

# SYSTEM_PROMPT 新增规则
"""
【知识库使用规则】
✅ 用户问"推荐餐厅/吃什么/哪家好吃" → 同时调用 search_knowledge + search_nearby_places
✅ 用户指定预算/场景（如"月底省钱""快速午餐"） → 先查 search_knowledge 获取对应攻略
✅ 用户问"XX店怎么样" → 先查 search_knowledge 看有无避坑经验
✅ 知识库结果要融入最终回复，不能单独回复（与API数据融合）
"""
```

---

## 五、跨 Agent 联动（BillAgent → TravelAgent）

```
BillAgent 数据 → TravelAgent 推荐策略

场景：用户问"推荐个好吃的，别太贵"

1. TravelAgent 请求 BillAgent 的财务数据
2. 获取：本月已支出 3500 元，预算 5000 元，剩余 1500 元
3. 判断：还剩 1500 元，日均约 50 元
4. 触发策略：按人均 <50 元过滤推荐结果
5. 融合 RAG 知识库："月底省钱 → 推荐木桶饭/快餐类"

实现方式：在 TravelAgent 的 system_prompt 中注明
"如果用户提到预算/价格相关内容，优先调用 get_budget_status 了解财务状况"
```

---

## 六、实施路线

| 阶段 | 内容 | 预估工作 |
|------|------|----------|
| Phase 1 | 搭建 `knowledge_base/` 目录，写 2-3 篇 Markdown 经验文档 | 30分钟 |
| Phase 2 | 实现 `rag_manager.py` + `search_knowledge` 工具 | 1小时 |
| Phase 3 | 集成到 `travel_agent.py`，修改 SYSTEM_PROMPT | 30分钟 |
| Phase 4 | 测试 RAG 融合效果，对比有无知识库的回答差异 | 30分钟 |
| Phase 5 | 跨 Agent 联动（账单数据影响推荐策略） | 1小时 |

---

## 七、预期效果

### Before（无知识库）
```
用户："推荐个好吃的火锅"

Agent："为您找到以下火锅店：
1. 蜀大侠火锅 ⭐4.8 人均¥80
2. 小龙坎火锅 ⭐4.5 人均¥75
..."
```

### After（有知识库）
```
用户："推荐个好吃的火锅"

Agent：
【本地经验 + 百度数据融合】

1. 蜀大侠火锅 ⭐4.8 人均¥80
   💡 毛肚是招牌必点！建议工作日去（周末排队1h+）
   
2. 小龙坎火锅 ⭐4.5 人均¥75  
   💡 口味正宗，服务好。上次去人均实际花了¥85

⚠️ 避坑提示：XX火锅城差评率较高（>15%），建议避开
📊 结合您本月预算，蜀大侠超预算了点，小龙坎更合适~
```
"""
知识库检索工具 — 基于本地 Markdown 文件的 RAG
使用 DashScope text-embedding-v2 向量模型进行语义检索
支持向量余弦相似度 + 关键词加权 + 标签过滤混合排序
向量已通过 ChromaDB 持久化到磁盘，避免重复调用 API

知识库文件格式：Markdown 自然段落，以 ## 标题分隔数据块。
原始 .md 文件不做结构化清洗——保留自然语言风格。
标签在导入时自动提取（按预定义词库从全文匹配），不作为原始文件的一部分。
"""
import sys
import os
import re
import json
import logging
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from langchain_core.tools import tool
from dashscope import TextEmbedding

import chromadb
from chromadb.config import Settings as ChromaSettings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config.config_loader import config

logger = logging.getLogger("lifeops.knowledge")

KNOWLEDGE_DIR = Path(config.get("paths.knowledge_base_dir", "knowledge_base"))
VECTORDB_DIR = Path(config.get("paths.vectordb_dir", "data/vectordb"))

# ===== Embedding 配置 =====
EMBEDDING_MODEL = "text-embedding-v2"
EMBEDDING_DIM = 1536
EMBEDDING_BATCH_SIZE = 25

# ===== 语义匹配阈值 =====
CONFIDENCE_THRESHOLD = 0.3

# ===== 向量索引缓存 =====
_entries_cache: Optional[List[Dict]] = None
_embeddings_cache: Optional[np.ndarray] = None
_index_mtime: float = 0

# ===== ChromaDB 客户端（惰性初始化） =====
_chroma_client: Optional[chromadb.PersistentClient] = None
_COLLECTION_NAME = "knowledge"

# ===== 标签词库 =====
# 导入时从段落全文自动匹配这些词作为标签，不改原始文件。
# 格式：标签名 → 匹配模式列表（取交集不去重；任一命中即打标）
_TAG_DICT: Dict[str, List[str]] = {
    # 地区和方位
    "石岐区": ["石岐", "孙文西路", "白水井", "兴中广场", "凤鸣路", "烟墩山"],
    "东区": ["东区街道", "长江水世界", "新安村", "库充村", "景观路", "中山三路"],
    "南区": ["南区街道", "詹园", "北台村", "树木园", "银潭二路"],
    "西区": ["西区街道", "岐江西岸", "岐江公园"],
    "沙溪镇": ["沙溪", "隆都", "星宝", "岐江公路乐群"],
    "三乡镇": ["三乡", "雍陌村", "古鹤村", "泉林", "白石村", "罗三妹"],
    "坦洲镇": ["坦洲", "大冲口", "坦神北路"],
    "小榄镇": ["小榄", "孖宝庄园", "樱花里"],
    "古镇镇": ["古镇", "灯都", "灯饰"],
    "南朗街道": ["南朗", "崖口村", "翠亨", "孙中山故居", "孙中山故里", "影视城"],
    "五桂山街道": ["五桂山", "逍遥谷", "旗溪村", "桂南村", "南桥"],
    "翠亨新区": ["马鞍岛", "翠亨新区", "深中通道", "深中大桥", "湿地公园"],
    "港口镇": ["港口", "港福路"],
    "黄圃镇": ["黄圃", "腊味", "新丰北"],
    "东升镇": ["东升", "脆肉鲩"],
    "火炬开发区": ["火炬"],
    "神湾镇": ["神湾", "菠萝"],
    # 美食类型
    "乳鸽": ["乳鸽", "鸽子", "妙龄鸽", "盐焗鸽", "药膳鸽", "鸽血"],
    "早茶": ["早茶", "茶楼", "点心", "虾饺", "金钱肚", "牛仔骨", "凤爪", "烧卖", "茶位"],
    "海鲜": ["海鲜", "蟹", "虾", "鱼", "生蚝", "贝壳", "海螺", "扇贝", "鱿鱼", "龙虾", "海盐"],
    "火锅": ["火锅", "涮", "椰子鸡", "砂锅粥"],
    "烧烤": ["烧烤", "烤肉", "烧鸡", "炭烤", "烤五花", "烤鱼"],
    "宵夜": ["宵夜", "夜宵", "凌晨", "烧鸡铺", "烤吧", "营地"],
    "小吃": ["小吃", "濑粉", "肠粉", "云吞", "煲仔饭", "煎堆", "米酒", "粽", "炸鱼球", "炸云吞"],
    "咖啡": ["咖啡", "手冲", "美式", "冷萃", "拿铁", "咖啡店", "咖啡馆", "咖啡厅"],
    "异国风味": ["印度", "土耳其", "意大利", "东南亚", "南洋", "咖喱", "披萨", "烤肉拼盘"],
    # 旅行类型
    "历史文化": ["博物馆", "故居", "历史", "非遗", "明代", "清代", "古建筑", "华侨", "文塔", "文化馆"],
    "自然风光": ["山", "公园", "湿地", "森林", "水库", "稻田", "绿道", "树木园", "溪流", "竹海"],
    "网红打卡": ["打卡", "网红", "小红书", "拍照", "出片", "摩天轮", "稻田咖啡", "电厂工坊", "碉楼"],
    "温泉": ["温泉", "泡池", "泡汤"],
    "住宿": ["酒店", "民宿", "宾馆", "度假", "住宿", "一晚", "入住"],
    "交通出行": ["城轨", "自驾", "公交", "深中通道", "跨市公交", "高速", "网约车", "打车", "骑行"],
    "购物": ["购物", "商圈", "商场", "手信", "特产", "买", "腊味", "杏仁饼", "广场", "百货"],
    "夜市": ["夜市", "夜经济", "酒吧街", "美食街", "不夜城", "宵夜街"],
    # 主题
    "攻略": ["攻略", "建议", "避坑", "提醒", "贴士", "最佳时间", "预算", "预约", "行程", "路线"],
    "亲子": ["亲子", "儿童", "水上乐园", "游乐园", "滑草"],
    "情侣": ["情侣", "约会", "求婚", "浪漫", "蜜月"],
}

# ===== 城市 → 区镇标签映射（用于判断检索结果是否匹配用户所在城市）=====
CITY_DISTRICTS = {
    "中山": [
        "石岐区", "东区", "南区", "西区", "沙溪镇", "三乡镇", "坦洲镇",
        "小榄镇", "古镇镇", "南朗街道", "五桂山街道", "翠亨新区",
        "港口镇", "黄圃镇", "东升镇", "火炬开发区", "神湾镇",
    ],
    # 后续添加其他城市时在这里补充
}


def _get_chroma() -> chromadb.PersistentClient:
    global _chroma_client
    if _chroma_client is None:
        VECTORDB_DIR.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=str(VECTORDB_DIR),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _chroma_client


def _load_from_chromadb() -> Tuple[Optional[List[Dict]], Optional[np.ndarray], float]:
    """从 ChromaDB 加载持久化的向量和条目，返回 (entries, embeddings, mtime)"""
    try:
        client = _get_chroma()
        collection = client.get_collection(_COLLECTION_NAME)
        count = collection.count()
        if count == 0:
            return None, None, 0.0

        all_data = collection.get(include=["documents", "embeddings", "metadatas"])
        if not all_data["documents"]:
            return None, None, 0.0

        entries = [json.loads(d) for d in all_data["documents"]]
        embeddings = np.array(all_data["embeddings"], dtype=np.float32)

        col_meta = collection.metadata or {}
        stored_mtime = col_meta.get("build_mtime", 0.0)

        return entries, embeddings, stored_mtime
    except Exception:
        return None, None, 0.0


def _save_to_chromadb(entries: List[Dict], embeddings: np.ndarray, mtime: float):
    """将向量和条目持久化到 ChromaDB"""
    client = _get_chroma()

    try:
        client.delete_collection(_COLLECTION_NAME)
    except Exception:
        pass

    collection = client.create_collection(
        _COLLECTION_NAME,
        metadata={"build_mtime": mtime, "dimension": EMBEDDING_DIM},
    )

    batch_size = 100
    for i in range(0, len(entries), batch_size):
        batch_end = min(i + batch_size, len(entries))
        collection.add(
            ids=[f"entry_{j}" for j in range(i, batch_end)],
            embeddings=embeddings[i:batch_end].tolist(),
            documents=[json.dumps(e, ensure_ascii=False) for e in entries[i:batch_end]],
        )


def _extract_tags(title: str, content: str) -> List[str]:
    """
    从段落全文（标题 + 正文）中按预定义词库匹配标签。
    不改原始文件，仅在导入时自动提取。
    返回去重的标签列表。
    """
    full_lower = (title + " " + content).lower()
    matched_tags: Set[str] = set()

    for tag_name, patterns in _TAG_DICT.items():
        for pattern in patterns:
            if pattern.lower() in full_lower:
                matched_tags.add(tag_name)
                break  # 一个标签只加一次

    return sorted(matched_tags)


def _parse_blocks(filepath: str, category: str, rel_path: str) -> List[Dict]:
    """
    解析一个 .md 文件为自然段落块。
    按 ## 标题切分；每个 ## 下的整段文字作为一个检索单元。
    原文不做任何清洗——保留冗余和自由格式。
    标签在解析时自动提取，存储在 entry.tags 中。
    """
    blocks = []
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()
    except Exception:
        return blocks

    raw_chunks = re.split(r"\n(?=##\s)", content)

    for chunk in raw_chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        # 跳过纯注释和元信息行（# 开头但不是 ## 开头的）
        if chunk.startswith("# ") and not chunk.startswith("## "):
            continue

        lines = chunk.split("\n")
        title_line = lines[0].strip()
        title = re.sub(r"^#+\s*", "", title_line).strip()
        # 去掉标题中括号注释
        title = re.sub(r"\s*\([^)]*\)", "", title).strip()

        body_lines = [l for l in lines[1:] if l.strip()]
        body = "\n".join(body_lines) if body_lines else title

        full_text = f"{title}\n{body}"

        # 清洗掉来源标记行
        clean_body = []
        for bl in body_lines:
            low = bl.strip().lower()
            if re.match(r"^(source|references?|data\s*source|抓取|来源|参考)[:：]", low):
                continue
            clean_body.append(bl)
        content_text = "\n".join(clean_body) if clean_body else body

        # 自动提取标签
        tags = _extract_tags(title, content_text)

        blocks.append({
            "title": title,
            "content": content_text,
            "tags": tags,
            "category": category,
            "source_file": rel_path,
            "full_text": full_text,
        })

    return blocks


def _build_index() -> Tuple[List[Dict], np.ndarray]:
    """
    扫描 knowledge_base/ 下所有 .md 文件，按 ## 分块解析段落并生成向量。
    优先从 ChromaDB 加载持久化数据，仅在文件更新或首次运行时调用 API。
    返回 (条目列表, 向量矩阵)
    """
    global _entries_cache, _embeddings_cache, _index_mtime

    # 1. 检查知识库文件是否有更新
    latest_mtime = 0.0
    for root, _, files in os.walk(KNOWLEDGE_DIR):
        for f in files:
            if f.endswith(".md") and not f.startswith("."):
                mtime = os.path.getmtime(os.path.join(root, f))
                if mtime > latest_mtime:
                    latest_mtime = mtime

    # 2. 内存缓存命中
    if _entries_cache is not None and _embeddings_cache is not None and latest_mtime <= _index_mtime:
        return _entries_cache, _embeddings_cache

    # 3. 尝试从 ChromaDB 加载（文件未更新时生效）
    if latest_mtime > 0:
        db_entries, db_embeddings, db_mtime = _load_from_chromadb()
        if db_entries is not None and db_mtime >= latest_mtime:
            _entries_cache = db_entries
            _embeddings_cache = db_embeddings
            _index_mtime = db_mtime
            return db_entries, db_embeddings

    # 4. 文件有更新或 ChromaDB 为空 → 重新构建
    entries = []
    texts_to_embed = []

    for root, _, files in os.walk(KNOWLEDGE_DIR):
        for f in sorted(files):
            if not f.endswith(".md") or f.startswith("."):
                continue
            filepath = os.path.join(root, f)
            rel_path = os.path.relpath(filepath, KNOWLEDGE_DIR)
            category = os.path.basename(root)

            blocks = _parse_blocks(filepath, category, rel_path)
            for block in blocks:
                entries.append(block)
                texts_to_embed.append(block["full_text"])

    # 5. 调 API 生成向量
    if texts_to_embed:
        embeddings = _batch_embed(texts_to_embed)
    else:
        embeddings = np.empty((0, EMBEDDING_DIM))

    # 6. 持久化到 ChromaDB
    if entries:
        _save_to_chromadb(entries, embeddings, latest_mtime)

    _entries_cache = entries
    _embeddings_cache = embeddings
    _index_mtime = latest_mtime
    return entries, embeddings


# ============================================================
# Embedding API
# ============================================================

def _batch_embed(texts: List[str]) -> np.ndarray:
    """批量调用 DashScope 文本转向量"""
    all_vectors = []
    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i:i + EMBEDDING_BATCH_SIZE]
        resp = TextEmbedding.call(model=EMBEDDING_MODEL, input=batch)

        if resp.status_code != 200:
            raise RuntimeError(
                f"Embedding API 调用失败 (batch {i // EMBEDDING_BATCH_SIZE}): "
                f"code={resp.status_code}, message={resp.message}"
            )

        for emb in resp.output["embeddings"]:
            all_vectors.append(emb["embedding"])

    return np.array(all_vectors, dtype=np.float32)


# ============================================================
# 检索策略
# ============================================================

def _vector_search(query: str, entries: List[Dict], emb_matrix: np.ndarray, top_k: int) -> List[Tuple[Dict, float]]:
    """向量语义检索：query 向量化 → 余弦相似度 → 取 top_k"""
    resp = TextEmbedding.call(model=EMBEDDING_MODEL, input=[query])
    if resp.status_code != 200:
        raise RuntimeError(f"查询向量化失败: {resp.message}")
    query_vec = np.array(resp.output["embeddings"][0]["embedding"], dtype=np.float32)

    query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-8)
    doc_norms = emb_matrix / (np.linalg.norm(emb_matrix, axis=1, keepdims=True) + 1e-8)
    scores = np.dot(doc_norms, query_norm)

    if len(scores) == 0:
        return []
    top_indices = np.argsort(scores)[::-1][:top_k]
    return [(entries[i], float(scores[i])) for i in top_indices if scores[i] > 0]


def _keyword_boost(entry: Dict, keywords: List[str]) -> float:
    """
    关键词命中加权：全文匹配 + 标签匹配双路加权。
    标签命中比普通正文命中权重更高（因为标签是语义浓缩）。
    """
    boost = 0.0
    full_text = entry.get("full_text", "").lower()
    title = entry.get("title", "").lower()
    tags = [t.lower() for t in entry.get("tags", [])]

    for kw in keywords:
        kw_lower = kw.lower()

        # 标签命中：高权重（语义级别匹配）
        for tag in tags:
            if kw_lower in tag:
                boost += 0.20
                break

        # 标题命中：中权重
        if kw_lower in title:
            boost += 0.12

        # 正文命中：低权重累积
        count = full_text.count(kw_lower)
        boost += min(count * 0.03, 0.15)

    return min(boost, 0.6)


def _tag_boost(entry_tags: List[str], query_tags: List[str]) -> float:
    """
    标签级别匹配：如果查询中提取到的标签和 entry 的标签有交集，
    给额外加权（标签匹配是精准的语义对齐）。
    """
    if not query_tags or not entry_tags:
        return 0.0
    entry_set = set(t.lower() for t in entry_tags)
    query_set = set(t.lower() for t in query_tags)
    overlap = len(entry_set & query_set)
    if overlap > 0:
        return min(overlap * 0.15, 0.45)
    return 0.0


def _extract_query_tags(query: str) -> List[str]:
    """从查询文本中提取可能匹配的标签（用于标签级别的精准匹配）"""
    query_lower = query.lower()
    matched = []
    for tag_name, patterns in _TAG_DICT.items():
        for pattern in patterns:
            if pattern.lower() in query_lower:
                matched.append(tag_name)
                break
    return matched


def _hybrid_search(
    query: str, entries: List[Dict], emb_matrix: np.ndarray, max_results: int
) -> List[Dict]:
    """
    混合检索：
    1. 向量语义相似度（主排序）
    2. 关键词全文 + 标签命中加权（辅）
    3. 查询标签与条目标签交集加分（精准对齐）
    4. 置信度阈值过滤

    返回的每个条目带 _score / _vector_score / _kw_boost / _tag_boost 字段。
    """
    keywords = re.split(r"[\s,，、]+", query.strip())
    keywords = [k for k in keywords if k]
    query_tags = _extract_query_tags(query)

    candidate_k = max(max_results * 2, 10)
    try:
        candidates = _vector_search(query, entries, emb_matrix, candidate_k)
    except Exception:
        return _keyword_only_search(entries, keywords, max_results)

    results = []
    for entry, vec_score in candidates:
        kw_boost = _keyword_boost(entry, keywords) if keywords else 0.0
        tg_boost = _tag_boost(entry.get("tags", []), query_tags) if query_tags else 0.0
        final_score = vec_score + kw_boost + tg_boost

        result = dict(entry)
        result["_vector_score"] = round(vec_score, 4)
        result["_kw_boost"] = round(kw_boost, 4)
        result["_tag_boost"] = round(tg_boost, 4)
        result["_score"] = round(final_score, 4)
        results.append(result)

    results.sort(key=lambda x: x["_score"], reverse=True)

    if not results or results[0]["_score"] < CONFIDENCE_THRESHOLD:
        return []

    return results[:max_results]


def _keyword_only_search(entries: List[Dict], keywords: List[str], max_results: int) -> List[Dict]:
    """纯关键词检索（向量 API 失败时的回退方案）"""
    if not keywords:
        return [dict(e) for e in entries[:max_results]]

    scored = []
    for e in entries:
        s = 0.0
        full_text = e.get("full_text", "")
        title = e.get("title", "")
        tags = [t.lower() for t in e.get("tags", [])]

        for kw in keywords:
            kw_l = kw.lower()
            if kw_l in title.lower():
                s += 3.0
            for tag in tags:
                if kw_l in tag:
                    s += 2.5
            s += full_text.lower().count(kw_l)

        if s > 0:
            result = dict(e)
            result["_score"] = round(s, 4)
            result["_vector_score"] = 0.0
            result["_kw_boost"] = round(s, 4)
            result["_tag_boost"] = 0.0
            scored.append(result)

    scored.sort(key=lambda x: x["_score"], reverse=True)
    return scored[:max_results]


# ============================================================
# 对外暴露的 LangChain Tool
# ============================================================

def _monotonic_ms() -> float:
    """返回单调时钟毫秒数，用于高精度计时。"""
    import time
    return time.perf_counter() * 1000


# ===== RAG 详细日志（TXT 实时追加） =====
_RAG_LOG_PATH = Path("data/monitoring/rag_detail.log")


def _log_rag_query(query: str, ranked: list, latency_ms: float):
    """详细记录每次 RAG 检索到 TXT + RAGMonitor。"""
    import time as _time
    from datetime import datetime as _datetime

    now_str = _datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- 1. 写入详细 TXT 日志 ----
    try:
        _RAG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(str(_RAG_LOG_PATH), "a", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(f"[{now_str}] 查询: {query}\n")
            f.write(f"耗时: {latency_ms:.1f} ms | 命中数: {len(ranked)} | "
                    f"阈值: {CONFIDENCE_THRESHOLD}\n")
            f.write("-" * 80 + "\n")

            if not ranked:
                f.write("(无匹配结果)\n")
            else:
                for i, r in enumerate(ranked, 1):
                    score = r.get("_score", 0)
                    vs = r.get("_vector_score", 0)
                    kw = r.get("_kw_boost", 0)
                    tg = r.get("_tag_boost", 0)
                    f.write(f"\n  [{i}] {r.get('title', '(无标题)')}\n")
                    f.write(f"      综合得分: {score:.4f}  "
                            f"(向量:{vs:.4f} + 关键词:{kw:.4f} + 标签:{tg:.4f})\n")
                    f.write(f"      标签: {r.get('tags', [])}\n")
                    f.write(f"      来源: {r.get('category', '')}/{r.get('source_file', '')}\n")
                    f.write(f"      内容: {r.get('content', '')[:300]}\n")
            f.write("\n")
    except Exception as e:
        logger.warning("RAG TXT 写入异常: %s", e)

    # ---- 2. 写入 RAGMonitor（仪表盘用） ----
    try:
        from monitoring.rag_logger import RAGMonitor, RAGLogEntry
        monitor = RAGMonitor.get_instance()
        top_scores = [r.get("_score", 0.0) for r in ranked[:3]]
        entry = RAGLogEntry(
            query=query,
            retrieved_count=len(ranked),
            top1_score=top_scores[0] if top_scores else 0.0,
            top3_scores=top_scores,
            avg_confidence=sum(top_scores) / len(top_scores) if top_scores else 0.0,
            latency_ms=round(latency_ms, 2),
            threshold=CONFIDENCE_THRESHOLD,
            passed_threshold=len(ranked) > 0,
        )
        monitor.log(entry)
        logger.debug("RAG 已记录: query=%s, count=%d, buffer=%d",
                     query[:40], len(ranked), len(monitor._buffer))
    except ImportError:
        logger.debug("RAGMonitor 未安装")
    except Exception as e:
        logger.warning("RAG 记录异常: %s: %s", type(e).__name__, e)


@tool
def search_knowledge(query: str, max_results: int = 6, city: str = "") -> str:
    """
    在本地知识库中搜索中山美食/旅行/景点/住宿/交通/购物经验（向量语义检索）。
    这是本地经验库的首要检索工具。当用户询问以下任一类问题时，必须优先使用：
    - 美食推荐："推荐好吃的XX"、"XX哪家好吃"、"早茶/乳鸽/海鲜推荐"、"宵夜去哪"
    - 景点游玩："有什么景点"、"老城/古镇/山水/海滩有什么"、"XX好不好玩"、"游乐场"
    - 行程路线："一日游/两日游路线"、"怎么玩"、"行程规划"、"出行方案"、"怎么安排"
    - 住宿推荐："住哪里"、"推荐酒店/民宿"、"XX附近住宿"、"温泉酒店"
    - 交通出行："怎么去XX"、"深中通道"、"公交/自驾"、"城轨怎么坐"
    - 购物特产："去哪逛街"、"买手信/特产"、"商场推荐"、"杏仁饼/腊味去哪买"
    - 避坑攻略："有什么坑"、"注意什么"、"什么时候去最好"、"排队/预约"

    **重要**：务必传入 city 参数（用户的默认城市），系统会标注每条结果是否匹配该城市。
    如果大量结果 city_match 为 false，说明知识库中缺少该城市的数据，应如实告知用户。

    Args:
        query: 搜索关键词或自然语言描述，如"中山一日游路线"、"推荐好吃的乳鸽"
        max_results: 最大返回条数，默认6
        city: 用户当前所在城市，如"中山"、"梅州"。用于标注结果是否属于该城市

    Returns:
        JSON 格式搜索结果，含 city_match_summary（城市匹配概况）和每条结果的 city_match 标注
    """
    _t0 = _monotonic_ms()

    entries, emb_matrix = _build_index()

    if not entries:
        return json.dumps({"error": "知识库为空，请先导入数据", "total": 0}, ensure_ascii=False)

    ranked = _hybrid_search(query, entries, emb_matrix, max_results)

    _latency_ms = _monotonic_ms() - _t0
    _log_rag_query(query, ranked, _latency_ms)

    # ===== 城市匹配检测 =====
    target_districts = set()
    if city and city in CITY_DISTRICTS:
        target_districts = set(CITY_DISTRICTS[city])

    results = []
    city_match_count = 0
    for e in ranked:
        score = e.get("_score", 0.0)
        tags = e.get("tags", [])

        # 检测该条目属于哪个城市（通过标签与各城市区镇的交集判断）
        entry_district_tags = set()
        city_detected = ""
        city_match = True  # 无城市限制时默认为匹配

        if target_districts:
            for tag in tags:
                for cn, districts in CITY_DISTRICTS.items():
                    if tag in districts:
                        entry_district_tags.add(tag)
                        if cn != city:
                            city_detected = cn
                        break

            # 如果条目标签和当前城市区镇有交集 → 匹配
            matched = bool(entry_district_tags & target_districts)
            # 如果条目标签和任何其他城市区镇匹配，但不匹配当前城市 → 记录了城市标签但不对
            has_other_city_tag = bool(entry_district_tags - target_districts)
            
            if matched:
                city_match = True
                city_match_count += 1
            elif has_other_city_tag:
                city_match = False
                # city_detected 已在上方设置
            elif not entry_district_tags:
                # 条目无城市相关的区域标签（比如纯美食类型标签如"乳鸽""早茶"）
                # 标记为不确定，让 agent 根据内容自行判断
                city_match = True
                city_match_count += 1
            else:
                city_match = False

        # 文本级信心指示器
        if score >= 0.70:
            level = "highly_reliable"
            label = "确信"
        elif score >= 0.45:
            level = "reliable"
            label = "比较确信"
        elif score >= CONFIDENCE_THRESHOLD:
            level = "uncertain"
            label = "低确信"
        else:
            level = "low"
            label = "低于阈值"

        result_entry = {
            "title": e.get("title", ""),
            "tags": tags,
            "content": e.get("content", ""),
            "source": e.get("source_file", ""),
            "confidence": {
                "score": score,
                "level": level,
                "label": label,
                "breakdown": {
                    "vector_similarity": e.get("_vector_score", 0.0),
                    "keyword_boost": e.get("_kw_boost", 0.0),
                    "tag_match_boost": e.get("_tag_boost", 0.0),
                },
            },
        }

        if city:
            result_entry["city_match"] = city_match
            if city_detected:
                result_entry["city_detected"] = city_detected

        results.append(result_entry)

    # 城市匹配概况
    output = {
        "query": query,
        "threshold": CONFIDENCE_THRESHOLD,
        "total": len(results),
        "results": results,
    }
    if city:
        total = len(results)
        if total > 0:
            match_ratio = city_match_count / total
            if match_ratio == 0:
                summary = f"❌ 所有 {total} 条结果均不匹配当前城市「{city}」。知识库中暂无该城市的数据，请不要向用户展示这些结果，如实告知用户知识库仅覆盖中山等已收录城市。"
            elif match_ratio < 0.5:
                summary = f"⚠️ 仅 {city_match_count}/{total} 条匹配当前城市「{city}」，大部分内容可能属于其他城市，请谨慎引用。"
            else:
                summary = f"✅ {city_match_count}/{total} 条匹配当前城市「{city}」。"
        else:
            summary = f"未找到匹配「{city}」的结果。"
        output["city_match_summary"] = summary

    return json.dumps(output, ensure_ascii=False, indent=2)
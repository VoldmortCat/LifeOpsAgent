"""
Milvus 存储层 — 替代 ChromaDB（v3 迁移）

为什么换：
  - Chroma 只当"持久化缓存"用，检索全靠应用层手写 numpy + jieba + rank_bm25
  - Milvus 2.5+ 内置 BM25 全文检索（中文分词器），稠密+稀疏混合搜索在服务端完成，
    替掉整个手写检索流程（hybrid_retriever.py 不再是主路径）

设计要点：
  - city 设为 partition key：城市过滤 expr 下推 → 分区裁剪，几乎零开销
  - text 字段挂 BM25 Function 自动生成 sparse 向量，写入侧零维护
  - tags 用 ARRAY 字段入库（旧版埋在 document JSON 里没法过滤）
  - 价格用 INT16 + (-1) 哨兵表示未知（不因信息缺失误杀）
  - 断连降级：knowledge_tools 持有 JSON 快照，Milvus 挂了走旧 numpy 管线

连接地址: config.yml -> vectordb.uri (默认 http://127.0.0.1:19530)
"""
import json
import logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger("lifeops.knowledge.milvus")

try:
    from pymilvus import (
        MilvusClient, DataType, Function, FunctionType,
        AnnSearchRequest, WeightedRanker,
    )
    _MILVUS_AVAILABLE = True
except ImportError:
    _MILVUS_AVAILABLE = False
    MilvusClient = None

COLLECTION = "knowledge"
DIM = 1536
PRICE_UNKNOWN = -1

_client: Optional["MilvusClient"] = None


def is_available() -> bool:
    return _MILVUS_AVAILABLE


def get_client(uri: str):
    """惰性单例连接。失败抛异常由调用方决定降级。"""
    global _client
    if _client is not None:
        return _client
    if not _MILVUS_AVAILABLE:
        raise RuntimeError("pymilvus 未安装")
    _client = MilvusClient(uri=uri)
    return _client


def _build_schema():
    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)

    schema.add_field("id", DataType.INT64, is_primary=True)
    # BM25 输入字段：启用中文分析器（分词在服务端完成）
    schema.add_field("text", DataType.VARCHAR, max_length=65535,
                     enable_analyzer=True, analyzer_params={"type": "chinese"})
    schema.add_field("dense", DataType.FLOAT_VECTOR, dim=DIM)
    schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
    schema.add_field("title", DataType.VARCHAR, max_length=512)
    schema.add_field("meta_json", DataType.VARCHAR, max_length=65535)  # 完整 entry JSON
    schema.add_field("city", DataType.VARCHAR, max_length=64, is_partition_key=True)
    schema.add_field("category", DataType.VARCHAR, max_length=64)
    schema.add_field("source_file", DataType.VARCHAR, max_length=512)
    schema.add_field("price_min", DataType.INT16)   # -1 = 未知
    schema.add_field("price_max", DataType.INT16)
    schema.add_field("price_level", DataType.INT8)  # 0 = 未知
    schema.add_field("tags", DataType.ARRAY, element_type=DataType.VARCHAR,
                     max_length=64, max_capacity=48)

    # BM25 函数：text -> sparse，服务端自动维护
    schema.add_function(Function(
        name="text_bm25",
        input_field_names=["text"],
        output_field_names=["sparse"],
        function_type=FunctionType.BM25,
    ))
    return schema


def ensure_collection(client) -> bool:
    """集合不存在则创建（含索引与 BM25 函数）。返回 True 表示新建。"""
    if client.has_collection(COLLECTION):
        return False
    index_params = MilvusClient.prepare_index_params()
    index_params.add_index(field_name="dense", index_type="HNSW",
                           metric_type="IP", params={"M": 24, "efConstruction": 256})
    index_params.add_index(field_name="sparse", index_type="AUTOINDEX",
                           metric_type="BM25")
    client.create_collection(COLLECTION, schema=_build_schema(), index_params=index_params)
    logger.info("已创建 Milvus 集合 %s（含中文 BM25 函数）", COLLECTION)
    return True


def drop_collection(client):
    if client.has_collection(COLLECTION):
        client.drop_collection(COLLECTION)


def count(client) -> int:
    return int(client.get_collection_stats(COLLECTION)["row_count"])


def insert_entries(client, entries: List[Dict], embeddings) -> int:
    """批量写入。embeddings: np.ndarray (N, DIM)，归一化由调用方保证。"""
    rows = []
    for i, e in enumerate(entries):
        pmin = e.get("price_min")
        pmax = e.get("price_max")
        rows.append({
            "id": i,
            "text": e.get("full_text", ""),
            "dense": [float(x) for x in embeddings[i]],
            "title": e.get("title", "")[:512],
            "meta_json": json.dumps(e, ensure_ascii=False),
            "city": e.get("city", "未知"),
            "category": e.get("category", "未知"),
            "source_file": e.get("source_file", "")[:512],
            "price_min": PRICE_UNKNOWN if pmin is None else int(pmin),
            "price_max": PRICE_UNKNOWN if pmax is None else int(pmax),
            "price_level": int(e.get("price_level") or 0),
            "tags": list(e.get("tags", [])),
        })
    client.insert(COLLECTION, rows)
    client.flush(COLLECTION)   # 立即可见（否则 count/检索有延迟）
    return len(rows)


def load_all(client) -> Tuple[List[Dict], list]:
    """全量拉取 entries 与 dense 向量（内存缓存/降级快照用）。条目量小无压力。"""
    res = client.query(COLLECTION, filter="", output_fields=["id", "meta_json", "dense"])
    pairs = sorted(((r["id"], r) for r in res), key=lambda x: x[0])
    entries = [json.loads(r["meta_json"]) for _, r in pairs]
    vectors = [[float(x) for x in r["dense"]] for _, r in pairs]
    return entries, vectors


def _esc(s: str) -> str:
    """expr 字符串值转义（LLM 传参不可信）。"""
    return s.replace(chr(92), chr(92)*2).replace('"', chr(92) + '"')


def build_filter(city: str = "", max_price: int = 0,
                 require_tags: Optional[List[str]] = None) -> str:
    """
    构造服务端过滤表达式。
      city          -> partition key 下推
      max_price     -> 预算上限；价格未知(-1)条目保留不误杀
      require_tags  -> 场景标签硬筛（两段式第二段专用）
    """
    parts = []
    if city:
        parts.append(f'city == "{_esc(city)}"')
    if max_price and max_price > 0:
        parts.append(f"(price_min == {PRICE_UNKNOWN} or price_min <= {int(max_price)})")
    if require_tags:
        tag_expr = " or ".join(
            f'ARRAY_CONTAINS(tags, "{_esc(t)}")' for t in require_tags)
        parts.append(f"({tag_expr})")
    return " and ".join(parts)


def hybrid_search(client, query_text: str, query_vec: List[float],
                  expr: str, limit: int,
                  vector_weight: float = 0.6) -> List[Dict]:
    """
    服务端混合检索：BM25 稀疏 + 稠密向量，WeightedRanker 融合。
    vector_weight 对应旧版 alpha=0.6 的语义权重连续性。
    返回 entry(dict) + _fused_score + _dense_vec（本地算余弦置信度用）。
    """
    # 过滤必须下推到每个 AnnSearchRequest（顶层 filter 在部分版本不作用于混合检索）
    reqs = [
        AnnSearchRequest(
            data=[query_vec], anns_field="dense",
            param={"metric_type": "IP", "params": {"ef": 128}},
            limit=limit, expr=expr or "",
        ),
        AnnSearchRequest(
            data=[query_text], anns_field="sparse",   # 直接传原文，服务端分词+BM25
            param={"metric_type": "BM25"},
            limit=limit, expr=expr or "",
        ),
    ]
    hits = client.hybrid_search(
        COLLECTION, reqs, ranker=WeightedRanker(vector_weight, 1.0 - vector_weight),
        limit=limit,
        output_fields=["meta_json", "dense"],
    )
    results = []
    for hit in hits[0] if hits else []:
        ent = json.loads(hit["entity"].get("meta_json", "{}"))
        ent["_fused_score"] = float(hit.get("distance", 0.0))
        ent["_dense_vec"] = hit["entity"].get("dense")
        results.append(ent)
    return results

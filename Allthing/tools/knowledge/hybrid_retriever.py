"""
BM25 混合检索器 — 向量语义检索 + BM25 关键词检索，线性融合

原理：
  - 向量检索：语义匹配（"好吃的"→美食条目）
  - BM25 检索：关键词匹配（"石岐区"→精确命中含"石岐区"的条目）
  - 线性融合：alpha × 向量得分 + (1-alpha) × BM25得分。各取所长。

融合策略（从优到劣依次尝试）：
  1. 线性融合（推荐）：保留原始得分信息，区分度好
  2. RRF 融合：排名融合，无区分度时可用
  3. 纯向量回退：BM25 不可用时

用法：
  retriever = BM25HybridRetriever(entries, emb_matrix)
  results = retriever.search(query="石岐区乳鸽推荐", top_k=5)
"""

import logging
import numpy as np
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger("lifeops.knowledge.hybrid")

# 惰性导入，避免未安装时报错
try:
    import jieba
    _JIEBA_AVAILABLE = True
except ImportError:
    _JIEBA_AVAILABLE = False
    jieba = None

try:
    from rank_bm25 import BM25Okapi
    _BM25_AVAILABLE = True
except ImportError:
    _BM25_AVAILABLE = False
    BM25Okapi = None


class BM25HybridRetriever:
    """
    BM25 + 向量混合检索器。

    检索流程：
      1. 向量语义检索（全量，拿所有条目的余弦相似度）
      2. BM25 关键词检索（全量，拿所有条目的 BM25 得分）
      3. 两种得分各自归一化到 [0, 1]
      4. 线性融合：score = alpha × vec_norm + (1-alpha) × bm25_norm
      5. 取最终 Top-K

    线性融合 vs RRF 融合：
      - 线性融合保留原始得分信息，区分度好（适合少量条目）
      - RRF 只保留排名信息，区分度弱（适合大量条目/多路召回）
    """

    def __init__(
        self,
        entries: List[Dict],
        emb_matrix: np.ndarray,
        alpha: float = 0.6,
    ):
        """
        Args:
            entries: 知识库条目列表
            emb_matrix: 预计算的 embedding 矩阵 (N, 1536)
            alpha: 向量得分权重，0=纯BM25, 1=纯向量, 0.6=60%向量+40%BM25
        """
        self.entries = entries
        self.emb_matrix = emb_matrix
        self.alpha = alpha

        # 构建 BM25 索引
        if _BM25_AVAILABLE and _JIEBA_AVAILABLE:
            tokenized_corpus = []
            for e in entries:
                text = e.get("full_text", e.get("title", "") + " " + e.get("content", ""))
                tokens = jieba.lcut(text)
                tokenized_corpus.append(tokens)
            self.bm25 = BM25Okapi(tokenized_corpus)
            self.bm25_ready = True
            logger.info("BM25 索引构建完成，共 %d 条", len(entries))
        else:
            self.bm25 = None
            self.bm25_ready = False
            if not _BM25_AVAILABLE:
                logger.warning("rank-bm25 未安装，BM25 检索不可用，回退到纯向量检索")
            if not _JIEBA_AVAILABLE:
                logger.warning("jieba 未安装，BM25 检索不可用，回退到纯向量检索")

    def search(
        self,
        query: str,
        top_k: int = 5,
        candidate_k: int = 20,
    ) -> List[Tuple[int, float]]:
        """
        混合检索。

        Returns:
            [(entry_index, fused_score), ...] — 按融合得分降序排列，得分范围 [0, 1]
        """
        if not self.bm25_ready:
            return self._vector_only_search(query, top_k)

        # 1. 向量检索（全量，拿所有条目得分）
        vec_scores = self._vector_scores_all(query)
        if vec_scores is None:
            return self._bm25_only_search(query, top_k)

        # 2. BM25 检索（全量）
        bm25_scores = self._bm25_scores_all(query)

        # 3. 各自归一化
        vec_norm = self._minmax_norm(vec_scores)
        bm25_norm = self._minmax_norm(bm25_scores)

        # 4. 线性融合
        fused = self.alpha * vec_norm + (1 - self.alpha) * bm25_norm

        # 5. 取 Top-K
        top_indices = np.argsort(fused)[::-1][:top_k]
        return [(int(i), float(fused[i])) for i in top_indices]

    def _vector_scores_all(self, query: str) -> Optional[np.ndarray]:
        """向量检索全量得分。"""
        from dashscope import TextEmbedding

        try:
            resp = TextEmbedding.call(model="text-embedding-v2", input=query)
            if resp.status_code != 200:
                logger.warning("Embedding API 失败: %s", resp.message)
                return None
            query_vec = np.array(resp.output["embeddings"][0]["embedding"], dtype=np.float32)
        except Exception as e:
            logger.warning("Embedding API 异常: %s", e)
            return None

        query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-8)
        doc_norms = self.emb_matrix / (np.linalg.norm(self.emb_matrix, axis=1, keepdims=True) + 1e-8)
        return np.dot(doc_norms, query_norm)

    def _bm25_scores_all(self, query: str) -> np.ndarray:
        """BM25 全量得分。"""
        if not self.bm25_ready:
            return np.zeros(len(self.entries))
        tokens = jieba.lcut(query)
        return np.array(self.bm25.get_scores(tokens), dtype=np.float32)

    @staticmethod
    def _minmax_norm(scores: np.ndarray) -> np.ndarray:
        """Min-Max 归一化到 [0, 1]。"""
        s_min = scores.min()
        s_max = scores.max()
        if s_max - s_min < 1e-8:
            return np.ones_like(scores) * 0.5  # 全相等时给中等分
        return (scores - s_min) / (s_max - s_min)

    def _vector_only_search(self, query: str, top_k: int) -> List[Tuple[int, float]]:
        """纯向量检索（BM25 不可用时的回退）"""
        vec = self._vector_scores_all(query)
        if vec is None:
            return []
        top_indices = np.argsort(vec)[::-1][:top_k]
        return [(int(i), float(vec[i])) for i in top_indices]

    def _bm25_only_search(self, query: str, top_k: int) -> List[Tuple[int, float]]:
        """纯 BM25 检索（向量 API 失败时的回退）"""
        scores = self._bm25_scores_all(query)
        top_indices = np.argsort(scores)[::-1][:top_k]
        return [(int(i), float(scores[i])) for i in top_indices]


def is_bm25_available() -> bool:
    """检查 BM25 依赖是否可用"""
    return _BM25_AVAILABLE and _JIEBA_AVAILABLE
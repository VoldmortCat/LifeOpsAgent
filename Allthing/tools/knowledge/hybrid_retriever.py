"""
BM25 混合检索器 — 向量语义检索 + BM25 关键词检索，RRF / 线性两种融合

原理：
  - 向量检索：语义匹配（"好吃的"→美食条目），得分 = 余弦相似度，值域 [-1, 1] 有界
  - BM25 检索：关键词匹配（"石岐区"→精确命中含"石岐区"的条目），得分无上界
  - 融合：把两路结果合成一个排序

两种融合策略（fusion 参数切换，默认 rrf）：
  rrf     倒序排名融合：score(d) = Σ_i 1/(k + rank_i(d))
          只吃排名不吃分数，因此两路得分尺度不同也不需要归一化。
          k 是平滑常数（非权重、非占比）：k 越小越看重头部名次，k 越大越接近
          "是否在候选里"的投票。原论文(Cormack et al. SIGIR 2009)在 TREC 大语料
          上取 k=60；本库仅数十条语料，k 过大会把名次差异压平，50 题评测扫描后默认取 5。
  linear  线性加权：alpha × 归一化向量分 + (1-alpha) × 归一化 BM25 分
          保留绝对得分的区分度，但依赖 min-max 归一化 —— 归一化基准随每次 query
          的得分分布浮动，跨 query 不可比，且单一离群值会压缩其余条目。

为什么默认改成 RRF：
  min-max 归一化在"该路得分全相等"（如 BM25 无词命中、全 0 分）时会返回全 0.5，
  等于把纯噪声伪装成有效信号参与加权。RRF 按排名融合，天然没有这个问题。

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
      3. 融合（默认 RRF，可选线性加权）
      4. 取最终 Top-K

    RRF vs 线性融合：
      - RRF 只依赖名次，两路得分无需同量纲，天然适配"有界余弦 + 无界 BM25"
      - 线性融合保留绝对得分的区分度，但需要归一化，归一化基准随 query 浮动
      - 下游只用 Top-K 排序（Recall/Hit/MRR 都是排名指标）时，RRF 更稳
    """

    def __init__(
        self,
        entries: List[Dict],
        emb_matrix: np.ndarray,
        alpha: float = 0.6,
        fusion: str = "rrf",
        rrf_k: int = 5,
        rrf_candidate_k: int = 20,
    ):
        """
        Args:
            entries: 知识库条目列表
            emb_matrix: 预计算的 embedding 矩阵 (N, 1536)
            alpha: 线性融合模式下的向量得分权重，0=纯BM25, 1=纯向量
            fusion: 融合策略，"rrf"（默认）或 "linear"
            rrf_k: RRF 平滑常数。越小越看重头部名次。原论文在 TREC 大语料取 60，
                   但语料越小该值越要调小，否则名次差异被压平。本库 50 题评测
                   扫描 {1,5,10,20,60} 后取 5（Recall@5 最优平台）。
            rrf_candidate_k: RRF 每路参与融合的候选条数
        """
        self.entries = entries
        self.emb_matrix = emb_matrix
        self.alpha = alpha
        self.fusion = fusion if fusion in ("rrf", "linear") else "rrf"
        self.rrf_k = rrf_k
        self.rrf_candidate_k = rrf_candidate_k

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

        # 3. 融合
        if self.fusion == "rrf":
            fused = self._rrf_fuse([vec_scores, bm25_scores])
        else:
            # 各自归一化后线性加权
            vec_norm = self._minmax_norm(vec_scores)
            bm25_norm = self._minmax_norm(bm25_scores)
            fused = self.alpha * vec_norm + (1 - self.alpha) * bm25_norm

        # 4. 取 Top-K
        top_indices = np.argsort(fused)[::-1][:top_k]
        return [(int(i), float(fused[i])) for i in top_indices]

    def _rrf_fuse(self, score_lists: List[Optional[np.ndarray]]) -> np.ndarray:
        """
        倒序排名融合 Reciprocal Rank Fusion。

            score(d) = Σ_i  1 / (k + rank_i(d))

        只消费名次、不消费原始分数，因此两路得分量纲不同（余弦有界 / BM25 无上界）
        也不需要归一化。单路独有条目只累加该路贡献，不会因缺席另一路而被清零。

        整路跳过条件：该路得分全为 0（如 BM25 无词命中），此时名次无意义，
        参与融合只会引入随机噪声。
        """
        fused = np.zeros(len(self.entries), dtype=np.float32)
        n_valid = 0
        for scores in score_lists:
            if scores is None or not np.any(scores):
                continue
            n_valid += 1
            ranked = np.argsort(scores)[::-1][:self.rrf_candidate_k]
            for rank, idx in enumerate(ranked, start=1):
                fused[idx] += 1.0 / (self.rrf_k + rank)

        # 除以理论最大值（每路都排第 1），归一化到 [0,1]。
        # 目的：让 _score 与其他检索模式同量级，下游的置信度分档阈值才能复用 ——
        # 否则 RRF 原始分只有 1/(k+1)≈0.05 量级，会被统统判成低置信。
        # 注意这是除以常数，不依赖当次 query 的得分分布，与线性融合的 min-max
        # 动态归一化有本质区别，不会引入跨 query 不可比的问题。
        if n_valid:
            fused /= (n_valid / (self.rrf_k + 1.0))
        return fused

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
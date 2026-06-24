"""RAG 监控数据模型 + 线程安全单例记录器。"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List
from pathlib import Path
import json
import threading


@dataclass
class RAGLogEntry:
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    query: str = ""
    retrieved_count: int = 0
    top1_score: float = 0.0
    top3_scores: List[float] = field(default_factory=list)
    avg_confidence: float = 0.0
    latency_ms: float = 0.0
    threshold: float = 0.3
    passed_threshold: bool = False


class RAGMonitor:
    """线程安全单例：记录每次 RAG 检索的元数据，支持实时指标计算。"""

    _instance = None
    _lock = threading.Lock()

    def __init__(self, log_dir: str = "data/monitoring", buffer_size: int = 500):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.buffer_size = buffer_size
        self._buffer: List[RAGLogEntry] = []
        self._jsonl_path = self.log_dir / "rag_logs.jsonl"

    @classmethod
    def get_instance(cls, log_dir: str = "data/monitoring", buffer_size: int = 500) -> "RAGMonitor":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(log_dir=log_dir, buffer_size=buffer_size)
        return cls._instance

    def log(self, entry: RAGLogEntry):
        with self._lock:
            self._buffer.append(entry)
            if len(self._buffer) > self.buffer_size:
                self._buffer = self._buffer[-self.buffer_size:]
            with open(self._jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")

    def get_metrics(self, window_size: int = 100) -> dict:
        with self._lock:
            recent = self._buffer[-window_size:] if len(self._buffer) > window_size else self._buffer

        if not recent:
            return {"total_queries": 0, "message": "暂无 RAG 检索记录"}

        total = len(recent)
        passed = sum(1 for e in recent if e.passed_threshold)
        avg_top1 = sum(e.top1_score for e in recent) / total
        avg_confidence = sum(e.avg_confidence for e in recent) / total
        avg_latency = sum(e.latency_ms for e in recent) / total

        top3_passed = sum(
            1 for e in recent if any(s >= e.threshold for s in e.top3_scores)
        )

        return {
            "total_queries": total,
            "top1_precision": round(passed / total, 4) if total > 0 else 0,
            "top3_precision": round(top3_passed / total, 4) if total > 0 else 0,
            "avg_confidence": round(avg_confidence, 4),
            "avg_latency_ms": round(avg_latency, 1),
            "max_latency_ms": round(max(e.latency_ms for e in recent), 1),
            "queries_below_threshold": total - passed,
        }

    def get_recent_entries(self, n: int = 20) -> List[RAGLogEntry]:
        with self._lock:
            return list(self._buffer[-n:])

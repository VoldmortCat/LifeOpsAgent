"""控制台 RAG 监控仪表盘。"""

from .rag_logger import RAGMonitor


def show_rag_dashboard(monitor: RAGMonitor, window_size: int = 100):
    """打印格式化的实时 RAG 指标面板。"""
    metrics = monitor.get_metrics(window_size=window_size)
    recent = monitor.get_recent_entries(n=10)

    header = "=" * 72
    print(f"\n{header}")
    print("  [RAG] 监控仪表盘")
    print(f"{header}")
    if "message" in metrics:
        print(f"  {metrics['message']}")
        print(f"{header}\n")
        return

    print(f"  查询总量（窗口 {window_size}）:  {metrics['total_queries']}")
    print(f"  Top-1 准确率:                {metrics['top1_precision']:.2%}")
    print(f"  Top-3 准确率:                {metrics['top3_precision']:.2%}")
    print(f"  平均置信度:                  {metrics['avg_confidence']:.4f}")
    print(f"  平均响应时间:                {metrics['avg_latency_ms']:.1f} ms")
    print(f"  最大响应时间:                {metrics['max_latency_ms']:.1f} ms")
    print(f"  低于阈值查询数:              {metrics['queries_below_threshold']}")
    print(f"{header}")

    if recent:
        print(f"  {'查询词':<28s} {'Top1':>6s} {'置信':>6s} {'耗时ms':>8s} {'通过':>4s}")
        print(f"  {'-'*28} {'-'*6} {'-'*6} {'-'*8} {'-'*4}")
        for e in reversed(recent):
            q = e.query[:26] + ".." if len(e.query) > 28 else e.query
            print(f"  {q:<28s} {e.top1_score:>6.4f} {e.avg_confidence:>6.4f} "
                  f"{e.latency_ms:>8.1f} {'Y' if e.passed_threshold else 'N':>4s}")
    print(f"{header}\n")

"""
RAG 评估脚本 — 基于 Golden Set 计算检索指标
支持 baseline（向量）和 hybrid（BM25+向量）两种模式对比

用法：
    cd Allthing
    python scripts/eval_rag.py              # 基线评估
    python scripts/eval_rag.py --hybrid     # BM25 混合检索评估
    python scripts/eval_rag.py --compare    # 对比两种模式

输出：
    - 控制台：每题结果 + 汇总指标 + 对比表
    - data/rag_eval/baseline_results.json：基线原始数据
    - data/rag_eval/hybrid_results.json：混合检索原始数据
"""
import sys
import os
import json
import time
from pathlib import Path

# 确保从 Allthing 目录运行 + 设置 sys.path
ALLTHING_DIR = Path(__file__).resolve().parent.parent
os.chdir(ALLTHING_DIR)
sys.path.insert(0, str(ALLTHING_DIR))

# 临时禁用 ChromaDB 的日志输出
import logging
logging.getLogger("chromadb").setLevel(logging.WARNING)
logging.getLogger("lifeops").setLevel(logging.WARNING)

from tools.knowledge.knowledge_tools import search_knowledge

# ===== 配置 =====
GOLDEN_SET_PATH = "data/rag_golden_set.json"
OUTPUT_DIR = Path("data/rag_eval")
TOP_K = 5
CITY = "中山"


def load_golden_set(path: str) -> list:
    """加载 Golden Set"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_title(result: dict) -> str:
    """从检索结果中提取标题"""
    return result.get("title", "")


def evaluate_single(question: str, expected_titles: list, k: int = TOP_K, city: str = CITY, mode: str = "vector") -> dict:
    """
    对单个问题执行检索并评估。
    mode: "vector"=纯向量检索, "hybrid"=BM25+向量混合检索
    """
    t0 = time.perf_counter()
    try:
        raw_result = search_knowledge.func(query=question, max_results=k, city=city, mode=mode)
    except Exception as e:
        return {
            "question": question,
            "expected": expected_titles,
            "retrieved": [],
            "recall_at_5": 0.0,
            "hit_at_5": False,
            "mrr": 0.0,
            "top1_score": 0.0,
            "latency_ms": 0.0,
            "error": str(e),
        }
    latency_ms = (time.perf_counter() - t0) * 1000

    try:
        data = json.loads(raw_result)
    except json.JSONDecodeError:
        return {
            "question": question,
            "expected": expected_titles,
            "retrieved": [],
            "recall_at_5": 0.0,
            "hit_at_5": False,
            "mrr": 0.0,
            "top1_score": 0.0,
            "latency_ms": latency_ms,
            "error": f"JSON解析失败: {raw_result[:200]}",
        }

    if "error" in data:
        return {
            "question": question,
            "expected": expected_titles,
            "retrieved": [],
            "recall_at_5": 0.0,
            "hit_at_5": False,
            "mrr": 0.0,
            "top1_score": 0.0,
            "latency_ms": latency_ms,
            "error": data["error"],
        }

    results = data.get("results", [])
    retrieved_titles = [extract_title(r) for r in results]
    top1_score = results[0].get("_score", 0.0) if results else 0.0

    expected_set = set(expected_titles)
    hits = set(retrieved_titles) & expected_set
    recall = len(hits) / len(expected_set) if expected_set else 0.0
    hit = len(hits) > 0

    mrr = 0.0
    for i, title in enumerate(retrieved_titles):
        if title in expected_set:
            mrr = 1.0 / (i + 1)
            break

    return {
        "question": question,
        "expected": expected_titles,
        "retrieved": retrieved_titles,
        "recall_at_5": round(recall, 4),
        "hit_at_5": hit,
        "mrr": round(mrr, 4),
        "top1_score": round(top1_score, 4),
        "latency_ms": round(latency_ms, 2),
    }


def run_evaluation(golden_set: list, mode: str = "vector") -> dict:
    """运行完整评估"""
    mode_label = "BM25+向量混合检索 (RRF融合)" if mode == "hybrid" else "纯向量检索 + 关键词加权"
    mode_name = "BM25 Hybrid" if mode == "hybrid" else "Baseline"

    print("=" * 70)
    print(f"RAG 评估 — {mode_name}（{mode_label}）")
    print(f"Golden Set: {len(golden_set)} 题  |  Top-K: {TOP_K}  |  City: {CITY}")
    print("=" * 70)

    print(f"\n[1/1] 逐题评估 ({len(golden_set)} 题)...\n")
    sys.stdout.flush()

    details = []
    category_stats = {}

    for i, item in enumerate(golden_set):
        result = evaluate_single(
            question=item["question"],
            expected_titles=item["expected_titles"],
            k=TOP_K,
            city=CITY,
            mode=mode,
        )
        result["id"] = item["id"]
        result["category"] = item["category"]
        details.append(result)

        status = "✅" if result["hit_at_5"] else "❌"
        recall_str = f"Recall={result['recall_at_5']:.2f}"
        print(f"  [{status}] {item['id']} {recall_str} | {item['question'][:50]}...")

        cat = item["category"]
        if cat not in category_stats:
            category_stats[cat] = {"recalls": [], "hits": [], "mrrs": []}
        category_stats[cat]["recalls"].append(result["recall_at_5"])
        category_stats[cat]["hits"].append(1 if result["hit_at_5"] else 0)
        category_stats[cat]["mrrs"].append(result["mrr"])

    all_recalls = [d["recall_at_5"] for d in details]
    all_hits = [1 if d["hit_at_5"] else 0 for d in details]
    all_mrrs = [d["mrr"] for d in details]
    all_latencies = [d["latency_ms"] for d in details if d["latency_ms"] > 0]
    all_scores = [d["top1_score"] for d in details if d["top1_score"] > 0]

    bad_cases = [d for d in details if not d["hit_at_5"]]
    perfect_cases = [d for d in details if d["recall_at_5"] >= 1.0]

    summary = {
        "experiment": mode,
        "config": {"top_k": TOP_K, "city": CITY, "retrieval": mode_label},
        "golden_set_size": len(golden_set),
        "metrics": {
            "recall_at_5": round(sum(all_recalls) / len(all_recalls), 4),
            "hit_at_5": round(sum(all_hits) / len(all_hits), 4),
            "mrr_at_5": round(sum(all_mrrs) / len(all_mrrs), 4),
            "avg_latency_ms": round(sum(all_latencies) / len(all_latencies), 2) if all_latencies else 0,
            "avg_top1_score": round(sum(all_scores) / len(all_scores), 4) if all_scores else 0,
        },
        "category_breakdown": {},
        "bad_cases_count": len(bad_cases),
        "perfect_cases_count": len(perfect_cases),
        "bad_case_ids": [d["id"] for d in bad_cases],
        "perfect_case_ids": [d["id"] for d in perfect_cases],
    }

    for cat, stats in category_stats.items():
        summary["category_breakdown"][cat] = {
            "recall_at_5": round(sum(stats["recalls"]) / len(stats["recalls"]), 4),
            "hit_at_5": round(sum(stats["hits"]) / len(stats["hits"]), 4),
            "mrr_at_5": round(sum(stats["mrrs"]) / len(stats["mrrs"]), 4),
            "count": len(stats["recalls"]),
        }

    print("\n" + "=" * 70)
    print("评估结果汇总")
    print("=" * 70)
    m = summary["metrics"]
    print(f"  Recall@5:  {m['recall_at_5']:.4f}  ({len(perfect_cases)}/{len(golden_set)} 题全命中)")
    print(f"  Hit@5:     {m['hit_at_5']:.4f}  ({len(golden_set) - len(bad_cases)}/{len(golden_set)} 题至少命中一个)")
    print(f"  MRR@5:     {m['mrr_at_5']:.4f}")
    print(f"  平均延迟:   {m['avg_latency_ms']:.2f}ms")

    print(f"\n分维度 Recall@5:")
    for cat, stats in summary["category_breakdown"].items():
        print(f"  {cat}: {stats['recall_at_5']:.4f} ({stats['count']}题)")

    if bad_cases:
        print(f"\nBad Cases ({len(bad_cases)} 题):")
        for bc in bad_cases:
            print(f"  [{bc['id']}] {bc['question'][:60]}")
            print(f"        期望: {bc['expected'][:3]}")
            print(f"        实际: {bc['retrieved'][:3]}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = "hybrid_results.json" if mode == "hybrid" else "baseline_results.json"
    output_path = OUTPUT_DIR / filename
    output_data = {"summary": summary, "details": details}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\n详细结果已保存至: {output_path}")

    return summary


def compare(baseline: dict, hybrid: dict):
    """对比两种模式"""
    print("\n" + "=" * 70)
    print("对比报告 — Baseline vs BM25 Hybrid")
    print("=" * 70)

    bm = baseline["metrics"]
    hm = hybrid["metrics"]

    # 计算变化
    def delta(new, old):
        if old == 0:
            return "+∞" if new > 0 else "0%"
        pct = (new - old) / old * 100
        sign = "+" if pct >= 0 else ""
        return f"{sign}{pct:.1f}%"

    print(f"\n{'指标':<20} {'Baseline':>10} {'Hybrid':>10} {'变化':>10}")
    print("-" * 50)
    for key, label in [("recall_at_5", "Recall@5"), ("hit_at_5", "Hit@5"), ("mrr_at_5", "MRR@5")]:
        bv = bm[key]
        hv = hm[key]
        print(f"  {label:<18} {bv:>10.4f} {hv:>10.4f} {delta(hv, bv):>10}")

    print(f"\n{'维度':<20} {'Baseline':>10} {'Hybrid':>10} {'变化':>10}")
    print("-" * 50)
    for cat in baseline["category_breakdown"]:
        br = baseline["category_breakdown"][cat]["recall_at_5"]
        hr = hybrid["category_breakdown"].get(cat, {}).get("recall_at_5", 0)
        print(f"  {cat:<18} {br:>10.4f} {hr:>10.4f} {delta(hr, br):>10}")

    # Bad Case 变化
    bb = set(baseline["bad_case_ids"])
    hb = set(hybrid["bad_case_ids"])
    fixed = bb - hb
    new_bad = hb - bb
    print(f"\nBad Case 变化:")
    print(f"  Baseline: {len(bb)} 题 → Hybrid: {len(hb)} 题")
    if fixed:
        print(f"  修复: {sorted(fixed)}")
    if new_bad:
        print(f"  新增: {sorted(new_bad)}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="RAG 评估脚本")
    parser.add_argument("--hybrid", action="store_true", help="只跑 BM25 混合检索")
    parser.add_argument("--compare", action="store_true", help="对比 Baseline 和 Hybrid")
    args = parser.parse_args()

    golden_set = load_golden_set(GOLDEN_SET_PATH)

    if args.compare:
        # 跑两种模式并对比
        print(">>> 阶段 1/2: Baseline 评估\n")
        baseline_summary = run_evaluation(golden_set, mode="vector")
        print("\n\n>>> 阶段 2/2: BM25 Hybrid 评估\n")
        hybrid_summary = run_evaluation(golden_set, mode="hybrid")
        compare(baseline_summary, hybrid_summary)
    elif args.hybrid:
        run_evaluation(golden_set, mode="hybrid")
    else:
        run_evaluation(golden_set, mode="vector")

    print("\n" + "=" * 70)
    print("评估完成 ✅")
    print("=" * 70)
"""
RAG 评估脚本 — 基于 Golden Set 计算检索指标
支持三种检索模式对比：

    vector  纯稠密向量单路（baseline）
    hybrid  BM25+向量双路，RRF 融合：score(d) = Σ 1/(k + rank_i(d))
    linear  BM25+向量双路，min-max 归一化后线性加权（对照实验）

用法：
    cd Allthing
    python scripts/eval_rag.py                  # 默认跑 hybrid（RRF）
    python scripts/eval_rag.py --vector         # 只跑纯向量 baseline
    python scripts/eval_rag.py --linear         # 只跑线性加权对照
    python scripts/eval_rag.py --compare        # 三种模式全跑并对比
    python scripts/eval_rag.py --compare --rrf-k 10   # 指定 RRF 平滑常数

输出：
    - 控制台：每题结果 + 汇总指标 + 对比表
    - data/rag_eval/baseline_results.json：纯向量原始数据
    - data/rag_eval/hybrid_results.json：RRF 融合原始数据
    - data/rag_eval/linear_results.json：线性加权原始数据
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
# 本库实测最优（k∈{1,5,10,20,60} 扫描后取 5，见 README/评测记录）
DEFAULT_RRF_K = 5

# mode -> (展示名, 检索链路描述, 结果文件名)
MODES = {
    "vector": ("Baseline", "纯稠密向量单路检索", "baseline_results.json"),
    "hybrid": ("RRF Hybrid", f"BM25+向量双路 · RRF 融合", "hybrid_results.json"),
    "linear": ("Linear Hybrid", "BM25+向量双路 · min-max 归一化线性加权", "linear_results.json"),
}


def load_golden_set(path: str) -> list:
    """加载 Golden Set"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_title(result: dict) -> str:
    """从检索结果中提取标题"""
    return result.get("title", "")


def evaluate_single(question: str, expected_titles: list, k: int = TOP_K,
                    city: str = CITY, mode: str = "hybrid",
                    rrf_k: int = DEFAULT_RRF_K) -> dict:
    """
    对单个问题执行检索并评估。
    mode: "vector"=纯向量, "hybrid"=RRF 融合, "linear"=线性加权融合
    """
    t0 = time.perf_counter()
    try:
        raw_result = search_knowledge.func(
            query=question, max_results=k, city=city, mode=mode, rrf_k=rrf_k)
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

    # 注意：真实分数字段是 confidence.score。
    # 旧实现取 results[0]["_score"]，而对外输出的条目里没有该字段，
    # 导致 top1_score 恒为 0、avg_top1_score 恒为 0，该指标形同虚设。
    top1_score = 0.0
    if results:
        conf = results[0].get("confidence") or {}
        top1_score = conf.get("score", 0.0)

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


def run_evaluation(golden_set: list, mode: str = "hybrid",
                   rrf_k: int = DEFAULT_RRF_K) -> dict:
    """运行完整评估"""
    mode_name, mode_label, filename = MODES[mode]
    if mode == "hybrid":
        mode_label = f"BM25+向量双路 · RRF 融合 (k={rrf_k})"

    print("=" * 70)
    print(f"RAG 评估 — {mode_name}")
    print(f"链路: {mode_label}")
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
            rrf_k=rrf_k,
        )
        result["id"] = item["id"]
        result["category"] = item["category"]
        details.append(result)

        status = "OK " if result["hit_at_5"] else "MISS"
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
    # 只统计真正有返回结果的题，避免把空检索当 0 分拉低均值
    all_scores = [d["top1_score"] for d in details
                  if not d.get("error") and d["retrieved"]]

    bad_cases = [d for d in details if not d["hit_at_5"]]
    perfect_cases = [d for d in details if d["recall_at_5"] >= 1.0]

    summary = {
        "experiment": mode,
        "config": {"top_k": TOP_K, "city": CITY, "retrieval": mode_label,
                   "rrf_k": rrf_k if mode == "hybrid" else None},
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
    print(f"  Top1 均分:  {m['avg_top1_score']:.4f}")
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
    output_path = OUTPUT_DIR / filename
    output_data = {"summary": summary, "details": details}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\n详细结果已保存至: {output_path}")

    return summary


def compare(summaries: dict):
    """对比多种模式。summaries: {mode: summary}"""
    names = list(summaries.keys())

    def delta(new, old):
        if old == 0:
            return "+inf" if new > 0 else "0%"
        pct = (new - old) / old * 100
        sign = "+" if pct >= 0 else ""
        return f"{sign}{pct:.1f}%"

    base_name = names[0]  # 第一列作为 baseline 基准
    print("\n" + "=" * 78)
    print("对比报告 — " + "  vs  ".join(MODES[n][0] for n in names))
    print("=" * 78)
    print("说明：『变化』列均为相对 Baseline(" + MODES[base_name][0] + ") 的百分变化")

    # 三列全展示：Baseline / RRF / Linear + 各自相对 Baseline 的 delta
    col = 14
    head = f"{'指标':<16}" + "".join(f"{MODES[n][0]:>{col}}" for n in names)
    head += f"{'RRF vs Base':>{col}}{'Linear vs Base':>{col}}"
    print(f"\n{head}")
    print("-" * (16 + col * (len(names) + 2)))

    metrics_rows = [("recall_at_5", "Recall@5"), ("hit_at_5", "Hit@5"),
                    ("mrr_at_5", "MRR@5"), ("avg_top1_score", "Top1 均分")]
    for key, label in metrics_rows:
        vals = [summaries[n]["metrics"][key] for n in names]
        row = f"  {label:<14}" + "".join(f"{v:>{col}.4f}" for v in vals)
        if "hybrid" in names:
            row += f"{delta(summaries['hybrid']['metrics'][key], summaries[base_name]['metrics'][key]):>{col}}"
        else:
            row += f"{'—':>{col}}"
        if "linear" in names:
            row += f"{delta(summaries['linear']['metrics'][key], summaries[base_name]['metrics'][key]):>{col}}"
        else:
            row += f"{'—':>{col}}"
        print(row)

    lat = [summaries[n]["metrics"]["avg_latency_ms"] for n in names]
    row = f"  {'平均延迟(ms)':<14}" + "".join(f"{v:>{col}.1f}" for v in lat)
    if "hybrid" in names:
        row += f"{delta(summaries['hybrid']['metrics']['avg_latency_ms'], summaries[base_name]['metrics']['avg_latency_ms']):>{col}}"
    else:
        row += f"{'—':>{col}}"
    if "linear" in names:
        row += f"{delta(summaries['linear']['metrics']['avg_latency_ms'], summaries[base_name]['metrics']['avg_latency_ms']):>{col}}"
    else:
        row += f"{'—':>{col}}"
    print(row)

    print(f"\n{'维度':<16}" + "".join(f"{MODES[n][0]:>{col}}" for n in names)
          + f"{'RRF vs Base':>{col}}{'Linear vs Base':>{col}}")
    print("-" * (16 + col * (len(names) + 2)))
    for cat in summaries[base_name]["category_breakdown"]:
        vals = [summaries[n]["category_breakdown"][cat]["recall_at_5"]
                if cat in summaries[n]["category_breakdown"] else 0.0
                for n in names]
        row = f"  {cat:<14}" + "".join(f"{v:>{col}.4f}" for v in vals)
        if "hybrid" in names:
            row += f"{delta(summaries['hybrid']['category_breakdown'][cat]['recall_at_5'], summaries[base_name]['category_breakdown'][cat]['recall_at_5']):>{col}}"
        else:
            row += f"{'—':>{col}}"
        if "linear" in names:
            row += f"{delta(summaries['linear']['category_breakdown'][cat]['recall_at_5'], summaries[base_name]['category_breakdown'][cat]['recall_at_5']):>{col}}"
        else:
            row += f"{'—':>{col}}"
        print(row)

    # Bad Case 变化：以首个模式为基准
    base = set(summaries[base_name]["bad_case_ids"])
    last = set(summaries[names[-1]]["bad_case_ids"])
    fixed, new_bad = base - last, last - base
    print(f"\nBad Case 变化（{MODES[base_name][0]} → {MODES[names[-1]][0]}）:")
    print(f"  {len(base)} 题 → {len(last)} 题")
    if fixed:
        print(f"  修复: {sorted(fixed)}")
    if new_bad:
        print(f"  新增: {sorted(new_bad)}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="RAG 评估脚本")
    parser.add_argument("--vector", action="store_true", help="只跑纯向量 baseline")
    parser.add_argument("--hybrid", action="store_true", help="只跑 RRF 混合检索（默认）")
    parser.add_argument("--linear", action="store_true", help="只跑线性加权融合")
    parser.add_argument("--compare", action="store_true", help="三种模式全跑并对比")
    parser.add_argument("--rrf-k", type=int, default=DEFAULT_RRF_K,
                        help=f"RRF 平滑常数（默认 {DEFAULT_RRF_K}）")
    args = parser.parse_args()

    golden_set = load_golden_set(GOLDEN_SET_PATH)

    if args.compare:
        order = ["vector", "hybrid", "linear"]
        summaries = {}
        for i, mode in enumerate(order, 1):
            print(f"\n>>> 阶段 {i}/{len(order)}: {MODES[mode][0]}\n")
            summaries[mode] = run_evaluation(golden_set, mode=mode, rrf_k=args.rrf_k)
        compare(summaries)
    elif args.vector:
        run_evaluation(golden_set, mode="vector", rrf_k=args.rrf_k)
    elif args.linear:
        run_evaluation(golden_set, mode="linear", rrf_k=args.rrf_k)
    else:
        run_evaluation(golden_set, mode="hybrid", rrf_k=args.rrf_k)

    print("\n" + "=" * 70)
    print("评估完成")
    print("=" * 70)

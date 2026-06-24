"""批量测试用例加载 + 自动化评估报告生成。"""

import json
import time
import yaml
from pathlib import Path


def load_test_cases(yaml_path: str) -> list:
    """从 YAML 文件加载测试用例。

    期望格式：
    ```yaml
    test_cases:
      - query: "乳鸽哪家好吃"
        expected_tags: ["乳鸽", "石岐区"]
        min_results: 1
        min_confidence: 0.3
      - query: "深中通道怎么走"
        expected_tags: ["翠亨新区", "交通出行"]
        min_results: 2
        min_confidence: 0.4
    ```
    """
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("test_cases", [])


def run_evaluation(test_cases: list) -> dict:
    """逐条运行测试用例，返回评估结果。"""
    try:
        from tools.knowledge.knowledge_tools import _build_index, _hybrid_search
    except ImportError:
        return {"error": "无法导入 RAG 检索函数", "total": 0, "passed": 0, "failed": 0, "details": []}

    entries, emb_matrix = _build_index()
    if not entries:
        return {"error": "知识库为空", "total": 0, "passed": 0, "failed": 0, "details": []}

    results = []
    passed = 0

    for tc in test_cases:
        start = time.perf_counter()
        ranked = _hybrid_search(tc["query"], entries, emb_matrix, tc.get("max_results", 6))
        latency = (time.perf_counter() - start) * 1000

        top_score = ranked[0]["_score"] if ranked else 0

        checks = {
            "result_count_ok": len(ranked) >= tc.get("min_results", 1),
            "confidence_ok": top_score >= tc.get("min_confidence", 0.3),
            "tags_match": False,
        }

        if tc.get("expected_tags"):
            all_result_tags = set()
            for r in ranked[:3]:
                all_result_tags.update(r.get("tags", []))
            expected = set(tc["expected_tags"])
            checks["tags_match"] = len(expected & all_result_tags) > 0

        overall_pass = all(checks.values())
        if overall_pass:
            passed += 1

        results.append({
            "query": tc["query"],
            "checks": checks,
            "passed": overall_pass,
            "top_score": round(top_score, 4),
            "result_count": len(ranked),
            "latency_ms": round(latency, 1),
        })

    return {
        "total": len(test_cases),
        "passed": passed,
        "failed": len(test_cases) - passed,
        "pass_rate": round(passed / len(test_cases), 4) if test_cases else 0,
        "details": results,
    }


def generate_report(eval_result: dict, output_path: str = None):
    """控制台打印评估报告，可选保存到 JSON。"""
    print("\n" + "=" * 70)
    print("  [RAG] 评估报告")
    print("=" * 70)

    if "error" in eval_result:
        print(f"  [FAIL] {eval_result['error']}")
        return

    print(f"  总用例数:    {eval_result['total']}")
    print(f"  通过:        {eval_result['passed']} ({eval_result['pass_rate']:.1%})")
    print(f"  失败:        {eval_result['failed']}")
    print("=" * 70)

    for r in eval_result["details"]:
        status = "[PASS]" if r["passed"] else "[FAIL]"
        print(f"\n  [{status}] {r['query']}")
        print(f"    结果数: {r['result_count']} | Top分数: {r['top_score']:.4f} | 耗时: {r['latency_ms']:.1f}ms")
        for check_name, check_val in r["checks"].items():
            icon = "[OK]" if check_val else "[FAIL]"
            print(f"    {icon} {check_name}")

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(eval_result, f, ensure_ascii=False, indent=2)
        print(f"\n  [SAVED] 报告已保存到: {output_path}")
    print("=" * 70 + "\n")

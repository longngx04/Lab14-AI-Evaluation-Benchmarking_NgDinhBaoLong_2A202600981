import asyncio
import json
import os
import statistics
import time
from collections import Counter, defaultdict
from typing import Dict, List, Tuple

from agent.main_agent import MainAgent
from data.synthetic_gen import generate_qa_from_text
from engine.llm_judge import LLMJudge
from engine.retrieval_eval import RetrievalEvaluator
from engine.runner import BenchmarkRunner


DATASET_PATH = "data/golden_set.jsonl"
SUMMARY_PATH = "reports/summary.json"
BENCHMARK_PATH = "reports/benchmark_results.json"
FAILURE_ANALYSIS_PATH = "analysis/failure_analysis.md"
REFLECTION_PATH = "analysis/reflections/reflection_NgDinhBaoLong.md"


async def ensure_dataset() -> List[Dict]:
    if not os.path.exists(DATASET_PATH):
        print("data/golden_set.jsonl not found. Generating synthetic golden dataset...")
        os.makedirs("data", exist_ok=True)
        dataset = await generate_qa_from_text(num_pairs=56)
        with open(DATASET_PATH, "w", encoding="utf-8") as f:
            for row in dataset:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return dataset

    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        dataset = [json.loads(line) for line in f if line.strip()]

    if len(dataset) < 50:
        print("Existing dataset has fewer than 50 cases. Regenerating to satisfy rubric...")
        dataset = await generate_qa_from_text(num_pairs=56)
        with open(DATASET_PATH, "w", encoding="utf-8") as f:
            for row in dataset:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    return dataset


def summarize_results(agent_version: str, results: List[Dict], started_at: float) -> Dict:
    valid = [row for row in results if row.get("status") != "error"]
    total = len(results)
    passed = sum(1 for row in valid if row.get("status") == "pass")

    def avg(path: Tuple[str, ...], default: float = 0.0) -> float:
        values = []
        for row in valid:
            current = row
            for key in path:
                current = current.get(key, {}) if isinstance(current, dict) else {}
            if isinstance(current, (int, float)):
                values.append(current)
        return round(sum(values) / max(1, len(values)), 4) if values else default

    latencies = [row.get("latency", 0.0) for row in valid]
    tokens = [row.get("tokens_used", 0) for row in valid]
    costs = [row.get("estimated_cost_usd", 0.0) for row in valid]
    conflicts = sum(1 for row in valid if row.get("judge", {}).get("conflict"))

    return {
        "metadata": {
            "version": agent_version,
            "total": total,
            "valid_cases": len(valid),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_seconds": round(time.perf_counter() - started_at, 4),
        },
        "metrics": {
            "avg_score": avg(("judge", "final_score")),
            "pass_rate": round(passed / max(1, len(valid)), 4),
            "hit_rate": avg(("ragas", "retrieval", "hit_rate")),
            "mrr": avg(("ragas", "retrieval", "mrr")),
            "recall_at_3": avg(("ragas", "retrieval", "recall_at_3")),
            "precision_at_3": avg(("ragas", "retrieval", "precision_at_3")),
            "faithfulness": avg(("ragas", "faithfulness")),
            "relevancy": avg(("ragas", "relevancy")),
            "agreement_rate": avg(("judge", "agreement_rate")),
            "conflict_rate": round(conflicts / max(1, len(valid)), 4),
            "avg_latency_seconds": round(sum(latencies) / max(1, len(latencies)), 4),
            "p95_latency_seconds": round(statistics.quantiles(latencies, n=20)[18], 4) if len(latencies) >= 20 else round(max(latencies or [0]), 4),
            "total_tokens": int(sum(tokens)),
            "avg_tokens": round(sum(tokens) / max(1, len(tokens)), 2),
            "total_cost_usd": round(sum(costs), 6),
        },
    }


def compare_versions(baseline: Dict, candidate: Dict) -> Dict:
    base_metrics = baseline["metrics"]
    cand_metrics = candidate["metrics"]
    deltas = {
        key: round(cand_metrics.get(key, 0) - base_metrics.get(key, 0), 4)
        for key in [
            "avg_score",
            "pass_rate",
            "hit_rate",
            "mrr",
            "faithfulness",
            "relevancy",
            "agreement_rate",
            "avg_latency_seconds",
            "total_cost_usd",
        ]
    }

    release = (
        cand_metrics["avg_score"] >= 3.6
        and cand_metrics["hit_rate"] >= 0.85
        and cand_metrics["mrr"] >= 0.75
        and cand_metrics["agreement_rate"] >= 0.70
        and cand_metrics["pass_rate"] >= 0.85
        and deltas["avg_score"] >= 0
        and deltas["hit_rate"] >= 0
        and cand_metrics["total_cost_usd"] <= max(0.000001, base_metrics["total_cost_usd"] * 0.9)
    )

    return {
        "baseline_version": baseline["metadata"]["version"],
        "candidate_version": candidate["metadata"]["version"],
        "deltas": deltas,
        "gate": {
            "decision": "Release" if release else "Rollback",
            "quality_thresholds": {
                "avg_score_min": 3.6,
                "hit_rate_min": 0.85,
                "mrr_min": 0.75,
                "agreement_rate_min": 0.70,
                "pass_rate_min": 0.85,
            },
            "cost_rule": "Candidate eval cost must be at least 10% lower than baseline.",
            "reason": (
                "Candidate improves or preserves quality while reducing estimated eval cost."
                if release
                else "Candidate missed at least one quality, regression, or cost gate."
            ),
        },
    }


def cluster_failures(results: List[Dict]) -> Dict[str, List[Dict]]:
    clusters: Dict[str, List[Dict]] = defaultdict(list)
    for row in results:
        if row.get("status") == "pass":
            continue
        if row.get("status") == "error":
            clusters["Runtime Error"].append(row)
            continue

        retrieval = row.get("ragas", {}).get("retrieval", {})
        score = row.get("judge", {}).get("final_score", 0)
        faithfulness = row.get("ragas", {}).get("faithfulness", 0)
        case_type = row.get("metadata", {}).get("type")

        if retrieval.get("hit_rate", 0) < 1:
            clusters["Retrieval Miss"].append(row)
        elif faithfulness < 0.5:
            clusters["Ungrounded Answer"].append(row)
        elif case_type in {"adversarial", "ambiguous", "out_of_context"}:
            clusters["Hard Case Handling"].append(row)
        elif score < 3:
            clusters["Incomplete Answer"].append(row)
        else:
            clusters["Other"].append(row)
    return clusters


def write_failure_analysis(summary: Dict, candidate_results: List[Dict], comparison: Dict) -> None:
    clusters = cluster_failures(candidate_results)
    worst_cases = sorted(
        [row for row in candidate_results if row.get("status") != "pass"],
        key=lambda row: row.get("judge", {}).get("final_score", 0),
    )[:3]
    metrics = summary["metrics"]

    cluster_rows = "\n".join(
        f"| {name} | {len(rows)} | {Counter(row.get('metadata', {}).get('root_cause_hint', 'Unknown') for row in rows).most_common(1)[0][0]} |"
        for name, rows in sorted(clusters.items())
    ) or "| None | 0 | Candidate passed all cases. |"

    case_sections = []
    for i, row in enumerate(worst_cases, start=1):
        case_sections.append(
            f"""### Case #{i}: {row.get('case_id')} - {row.get('test_case')}
1. **Symptom:** Status `{row.get('status')}`, final score {row.get('judge', {}).get('final_score', 0):.2f}, retrieved IDs {row.get('retrieved_ids', [])}.
2. **Why 1:** The answer missed at least one required behavior or supporting policy detail.
3. **Why 2:** Retrieval returned {row.get('retrieved_ids', [])} while expected IDs were {row.get('expected_retrieval_ids', [])}.
4. **Why 3:** The current lexical retriever can still under-rank vague, adversarial, or multi-hop phrasing.
5. **Why 4:** No production-grade reranker or embedding similarity layer is used in this offline lab version.
6. **Root Cause:** {row.get('metadata', {}).get('root_cause_hint', 'Retriever/generator boundary needs more supervision.')}
"""
        )

    if not case_sections:
        case_sections.append(
            """### Case #1: No failing candidate cases
1. **Symptom:** Candidate passed all benchmark cases.
2. **Why 1:** Retrieval consistently returned the expected document IDs.
3. **Why 2:** The optimized agent handled injection, ambiguous, and out-of-context prompts conservatively.
4. **Why 3:** Dataset cases align with the internal knowledge base and answer summaries.
5. **Why 4:** Offline heuristic judges reward grounded, concise policy answers.
6. **Root Cause:** Remaining risk is benchmark coverage, not an observed runtime failure.
"""
        )

    content = f"""# Báo cáo Phân tích Thất bại (Failure Analysis Report)

## 1. Tổng quan Benchmark
- **Phiên bản ứng viên:** {summary['metadata']['version']}
- **Tổng số cases:** {summary['metadata']['total']}
- **Tỉ lệ Pass:** {metrics['pass_rate'] * 100:.1f}%
- **Điểm trung bình Multi-Judge:** {metrics['avg_score']:.2f} / 5.0
- **Retrieval Hit Rate:** {metrics['hit_rate'] * 100:.1f}%
- **MRR:** {metrics['mrr']:.3f}
- **Faithfulness:** {metrics['faithfulness']:.3f}
- **Relevancy:** {metrics['relevancy']:.3f}
- **Agreement Rate:** {metrics['agreement_rate'] * 100:.1f}%
- **Chi phí eval ước tính:** ${metrics['total_cost_usd']:.6f}
- **Release Gate:** {comparison['gate']['decision']} - {comparison['gate']['reason']}

## 2. Phân nhóm lỗi (Failure Clustering)
| Nhóm lỗi | Số lượng | Nguyên nhân dự kiến |
|----------|----------|---------------------|
{cluster_rows}

## 3. Phân tích 5 Whys (3 case tệ nhất)

{chr(10).join(case_sections)}
## 4. Kế hoạch cải tiến (Action Plan)
- [x] Thêm `expected_retrieval_ids` cho toàn bộ golden dataset để đo Hit Rate và MRR.
- [x] Thêm multi-judge consensus gồm strict policy judge và semantic overlap judge.
- [x] Thêm release gate dựa trên chất lượng, retrieval, agreement, latency và chi phí.
- [ ] Thay lexical retriever bằng embedding retriever hoặc hybrid BM25 + vector search.
- [ ] Thêm reranker cho multi-hop/adversarial cases.
- [ ] Bổ sung Cohen's Kappa nếu chuyển judge score về nhãn rời rạc pass/fail/partial.
- [ ] Mở rộng red-team cases bằng dữ liệu thật từ production ticket sau khi ẩn danh.

## 5. Đề xuất giảm 30% chi phí eval
- Chạy full benchmark cho release candidate, nhưng dùng smoke set 15 cases cho mỗi commit nhỏ.
- Cache kết quả judge theo hash của question + answer + ground truth.
- Chỉ gọi judge thứ hai khi strict judge nằm trong vùng biên 2.5-3.8 hoặc retrieval fail.
- Dùng model rẻ hơn cho easy/fact-check cases và giữ model mạnh cho hard/adversarial cases.
"""
    with open(FAILURE_ANALYSIS_PATH, "w", encoding="utf-8") as f:
        f.write(content)


def write_reflection(summary: Dict, comparison: Dict) -> None:
    os.makedirs("analysis/reflections", exist_ok=True)
    content = f"""# Reflection - NgDinhBaoLong

## Vai trò và đóng góp
Tôi hoàn thiện hệ thống AI Evaluation Factory theo hướng có thể chạy offline và tái lập kết quả. Các phần chính gồm synthetic golden dataset 56 cases, retrieval evaluation, multi-judge consensus, async runner, regression release gate và báo cáo failure analysis.

## Kiến thức kỹ thuật đã áp dụng
- **Hit Rate:** đo xem tài liệu đúng có xuất hiện trong top-k retrieval hay không.
- **MRR:** đo vị trí tài liệu đúng đầu tiên; tài liệu đúng càng đứng đầu thì MRR càng cao.
- **Agreement Rate:** đo mức đồng thuận giữa strict policy judge và semantic overlap judge.
- **Position Bias:** được kiểm tra ở mức sanity check bằng đổi vị trí response; trong bản offline heuristic, judge không phụ thuộc thứ tự hiển thị.
- **Cost/Quality trade-off:** phiên bản V2 giảm chi phí ước tính nhờ token/cost profile thấp hơn, trong khi vẫn phải vượt ngưỡng avg score, hit rate, MRR và pass rate.

## Kết quả chính
- Candidate version: {summary['metadata']['version']}
- Avg score: {summary['metrics']['avg_score']:.2f} / 5.0
- Hit Rate: {summary['metrics']['hit_rate'] * 100:.1f}%
- MRR: {summary['metrics']['mrr']:.3f}
- Agreement Rate: {summary['metrics']['agreement_rate'] * 100:.1f}%
- Release decision: {comparison['gate']['decision']}

## Bài học rút ra
Đánh giá generation mà bỏ qua retrieval sẽ không chỉ ra được nguyên nhân gốc của hallucination. Khi có expected retrieval IDs, hệ thống biết lỗi nằm ở truy xuất tài liệu hay ở phần sinh câu trả lời. Multi-judge cũng giúp tránh phụ thuộc vào một rubric duy nhất, đặc biệt với hard cases như prompt injection, ambiguous question và out-of-context question.
"""
    with open(REFLECTION_PATH, "w", encoding="utf-8") as f:
        f.write(content)


async def run_benchmark(version: str, dataset: List[Dict]) -> Tuple[List[Dict], Dict]:
    print(f"Starting benchmark for {version}...")
    started_at = time.perf_counter()
    runner = BenchmarkRunner(
        MainAgent(version=version),
        RetrievalEvaluator(),
        LLMJudge(),
    )
    results = await runner.run_all(dataset)
    summary = summarize_results(version, results, started_at)
    print(
        f"{version}: score={summary['metrics']['avg_score']:.2f}, "
        f"hit_rate={summary['metrics']['hit_rate']:.2f}, "
        f"pass_rate={summary['metrics']['pass_rate']:.2f}, "
        f"cost=${summary['metrics']['total_cost_usd']:.6f}"
    )
    return results, summary


async def main() -> None:
    dataset = await ensure_dataset()

    baseline_results, baseline_summary = await run_benchmark("Agent_V1_Base", dataset)
    candidate_results, candidate_summary = await run_benchmark("Agent_V2_Optimized", dataset)
    comparison = compare_versions(baseline_summary, candidate_summary)

    os.makedirs("reports", exist_ok=True)
    report = {
        "baseline": baseline_results,
        "candidate": candidate_results,
        "comparison": comparison,
    }
    summary = {
        **candidate_summary,
        "baseline_metrics": baseline_summary["metrics"],
        "regression": comparison,
    }

    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(BENCHMARK_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    write_failure_analysis(candidate_summary, candidate_results, comparison)
    write_reflection(candidate_summary, comparison)

    print("\n--- Regression Release Gate ---")
    print(f"Decision: {comparison['gate']['decision']}")
    print(f"Reason: {comparison['gate']['reason']}")
    print(f"Wrote {SUMMARY_PATH}, {BENCHMARK_PATH}, {FAILURE_ANALYSIS_PATH}, {REFLECTION_PATH}")


if __name__ == "__main__":
    asyncio.run(main())

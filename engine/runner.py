import asyncio
import time
from typing import Dict, List


class BenchmarkRunner:
    def __init__(self, agent, evaluator, judge):
        self.agent = agent
        self.evaluator = evaluator
        self.judge = judge

    async def run_single_test(self, test_case: Dict) -> Dict:
        start_time = time.perf_counter()

        try:
            response = await self.agent.query(test_case["question"])
            latency = time.perf_counter() - start_time

            ragas_scores = await self.evaluator.score(test_case, response)
            judge_result = await self.judge.evaluate_multi_judge(
                test_case["question"],
                response["answer"],
                test_case["expected_answer"],
                test_case.get("answer_keywords", []),
            )

            passed = (
                judge_result["final_score"] >= 3.0
                and ragas_scores["retrieval"]["hit_rate"] >= 0.8
                and ragas_scores["faithfulness"] >= 0.5
            )

            return {
                "case_id": test_case.get("case_id"),
                "test_case": test_case["question"],
                "expected_answer": test_case.get("expected_answer"),
                "expected_retrieval_ids": test_case.get("expected_retrieval_ids", []),
                "agent_response": response["answer"],
                "retrieved_ids": response.get("retrieved_ids", []),
                "latency": round(latency, 4),
                "tokens_used": response.get("metadata", {}).get("tokens_used", 0),
                "estimated_cost_usd": response.get("metadata", {}).get("estimated_cost_usd", 0.0),
                "ragas": ragas_scores,
                "judge": judge_result,
                "metadata": {
                    **test_case.get("metadata", {}),
                    "agent": response.get("metadata", {}).get("agent"),
                    "model": response.get("metadata", {}).get("model"),
                    "retrieval_scores": response.get("metadata", {}).get("retrieval_scores", {}),
                },
                "status": "pass" if passed else "fail",
            }
        except Exception as exc:
            latency = time.perf_counter() - start_time
            return {
                "case_id": test_case.get("case_id"),
                "test_case": test_case.get("question"),
                "latency": round(latency, 4),
                "status": "error",
                "error": str(exc),
            }

    async def run_all(self, dataset: List[Dict], batch_size: int = 8) -> List[Dict]:
        results = []
        for i in range(0, len(dataset), batch_size):
            batch = dataset[i : i + batch_size]
            tasks = [self.run_single_test(case) for case in batch]
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)
        return results

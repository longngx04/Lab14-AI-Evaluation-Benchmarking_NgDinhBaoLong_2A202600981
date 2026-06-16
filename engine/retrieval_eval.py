import re
from typing import Dict, List, Set


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "does",
    "for",
    "from",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "must",
    "of",
    "or",
    "should",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
}


def _tokens(text: str) -> Set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS}


class RetrievalEvaluator:
    def calculate_hit_rate(self, expected_ids: List[str], retrieved_ids: List[str], top_k: int = 3) -> float:
        if not expected_ids:
            return 1.0 if not retrieved_ids else 0.0

        top_retrieved = retrieved_ids[:top_k]
        hit = any(doc_id in top_retrieved for doc_id in expected_ids)
        return 1.0 if hit else 0.0

    def calculate_mrr(self, expected_ids: List[str], retrieved_ids: List[str]) -> float:
        if not expected_ids:
            return 1.0 if not retrieved_ids else 0.0

        for i, doc_id in enumerate(retrieved_ids):
            if doc_id in expected_ids:
                return 1.0 / (i + 1)
        return 0.0

    def calculate_recall_at_k(self, expected_ids: List[str], retrieved_ids: List[str], top_k: int = 3) -> float:
        if not expected_ids:
            return 1.0 if not retrieved_ids else 0.0

        top_retrieved = set(retrieved_ids[:top_k])
        return len(set(expected_ids) & top_retrieved) / len(set(expected_ids))

    def calculate_precision_at_k(self, expected_ids: List[str], retrieved_ids: List[str], top_k: int = 3) -> float:
        if not retrieved_ids:
            return 1.0 if not expected_ids else 0.0

        top_retrieved = retrieved_ids[:top_k]
        return len(set(expected_ids) & set(top_retrieved)) / len(top_retrieved)

    def calculate_relevancy(self, expected_answer: str, answer: str, keywords: List[str]) -> float:
        answer_lower = answer.lower()
        keyword_score = 0.0
        if keywords:
            hits = sum(1 for keyword in keywords if keyword.lower() in answer_lower)
            keyword_score = hits / len(keywords)

        expected_tokens = _tokens(expected_answer)
        answer_tokens = _tokens(answer)
        overlap_score = len(expected_tokens & answer_tokens) / max(1, len(expected_tokens))
        return round((keyword_score * 0.65) + (overlap_score * 0.35), 4)

    def calculate_faithfulness(self, answer: str, contexts: List[str]) -> float:
        if not contexts:
            answer_lower = answer.lower()
            if "do not know" in answer_lower or "clarification" in answer_lower or "not contain" in answer_lower:
                return 1.0
            return 0.0

        answer_tokens = _tokens(answer)
        context_tokens = _tokens(" ".join(contexts))
        if not answer_tokens:
            return 0.0

        grounded = len(answer_tokens & context_tokens) / len(answer_tokens)
        return round(min(1.0, grounded + 0.15), 4)

    async def score(self, test_case: Dict, response: Dict) -> Dict:
        expected_ids = test_case.get("expected_retrieval_ids", [])
        retrieved_ids = response.get("retrieved_ids", [])
        contexts = response.get("contexts", [])
        answer = response.get("answer", "")

        return {
            "faithfulness": self.calculate_faithfulness(answer, contexts),
            "relevancy": self.calculate_relevancy(
                test_case.get("expected_answer", ""),
                answer,
                test_case.get("answer_keywords", []),
            ),
            "retrieval": {
                "hit_rate": self.calculate_hit_rate(expected_ids, retrieved_ids),
                "mrr": self.calculate_mrr(expected_ids, retrieved_ids),
                "recall_at_3": self.calculate_recall_at_k(expected_ids, retrieved_ids),
                "precision_at_3": self.calculate_precision_at_k(expected_ids, retrieved_ids),
                "expected_ids": expected_ids,
                "retrieved_ids": retrieved_ids,
            },
        }

    async def evaluate_batch(self, dataset: List[Dict]) -> Dict:
        hit_rates = []
        mrrs = []
        for row in dataset:
            expected_ids = row.get("expected_retrieval_ids", [])
            retrieved_ids = row.get("retrieved_ids", [])
            hit_rates.append(self.calculate_hit_rate(expected_ids, retrieved_ids))
            mrrs.append(self.calculate_mrr(expected_ids, retrieved_ids))
        return {
            "avg_hit_rate": sum(hit_rates) / max(1, len(hit_rates)),
            "avg_mrr": sum(mrrs) / max(1, len(mrrs)),
        }

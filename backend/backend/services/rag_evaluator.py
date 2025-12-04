"""
RAG Quality Evaluation with ragas.

Evaluates RAG answer quality using multiple metrics:
- Faithfulness: Answer is faithful to the retrieved context
- Answer Relevancy: Answer is relevant to the question
- Context Precision: Retrieved context is precise
- Context Recall: Retrieved context has good recall

Also tracks additional custom metrics:
- Retrieval score distribution
- Answer length statistics
- Token efficiency
"""

import logging
from typing import Optional, Dict, List, Any
from datetime import datetime
from dataclasses import dataclass, field
import asyncio

logger = logging.getLogger(__name__)

# ragas imports with graceful fallback
try:
    from ragas import evaluate
    from ragas.metrics import (
        faithfulness,
        answer_relevancy,
        context_precision,
        context_recall,
    )
    from datasets import Dataset
    RAGAS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"ragas not available: {e}")
    RAGAS_AVAILABLE = False

# Prometheus metrics for RAG quality
try:
    from prometheus_client import Gauge, Histogram
    rag_faithfulness_gauge = Gauge(
        'rag_faithfulness_score',
        'RAG answer faithfulness score (0-1)',
        ['model']
    )
    rag_relevancy_gauge = Gauge(
        'rag_answer_relevancy_score',
        'RAG answer relevancy score (0-1)',
        ['model']
    )
    rag_context_precision_gauge = Gauge(
        'rag_context_precision_score',
        'RAG context precision score (0-1)',
        ['model']
    )
    rag_context_recall_gauge = Gauge(
        'rag_context_recall_score',
        'RAG context recall score (0-1)',
        ['model']
    )
    rag_evaluation_duration_histogram = Histogram(
        'rag_evaluation_duration_seconds',
        'RAG evaluation duration',
        ['model'],
        buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
    )
except ImportError:
    logger.warning("Prometheus client not available for RAG metrics")


@dataclass
class RAGEvaluationResult:
    """Results from a RAG quality evaluation."""
    question: str
    answer: str
    contexts: List[str]
    ground_truth: Optional[str] = None
    faithfulness: Optional[float] = None
    answer_relevancy: Optional[float] = None
    context_precision: Optional[float] = None
    context_recall: Optional[float] = None
    evaluation_duration: float = 0.0
    model: str = "unknown"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "num_contexts": len(self.contexts),
            "ground_truth_provided": self.ground_truth is not None,
            "faithfulness": self.faithfulness,
            "answer_relevancy": self.answer_relevancy,
            "context_precision": self.context_precision,
            "context_recall": self.context_recall,
            "evaluation_duration": self.evaluation_duration,
            "model": self.model,
            "timestamp": self.timestamp.isoformat(),
            "error": self.error,
        }


class RAGEvaluator:
    """
    Evaluate RAG answer quality using ragas metrics.

    Supports both synchronous and asynchronous evaluation.
    """

    def __init__(self, llm_model: str = "gpt-4o-mini"):
        """
        Initialize RAG evaluator.

        Args:
            llm_model: Model to use for evaluation (uses same model as generation by default)
        """
        self.llm_model = llm_model
        self.evaluation_history: List[RAGEvaluationResult] = []
        self.max_history = 1000

    async def evaluate_answer(
        self,
        question: str,
        answer: str,
        contexts: List[str],
        ground_truth: Optional[str] = None,
        model: Optional[str] = None,
    ) -> RAGEvaluationResult:
        """
        Evaluate a RAG answer using ragas metrics.

        Args:
            question: User's question
            answer: Generated answer
            contexts: Retrieved context chunks
            ground_truth: Optional ground truth answer for recall/precision
            model: Model used for generation

        Returns:
            RAGEvaluationResult with scores
        """
        if not RAGAS_AVAILABLE:
            logger.warning("ragas not available - returning empty result")
            return RAGEvaluationResult(
                question=question,
                answer=answer,
                contexts=contexts,
                ground_truth=ground_truth,
                model=model or self.llm_model,
                error="ragas not installed"
            )

        model = model or self.llm_model
        start_time = asyncio.get_event_loop().time()

        result = RAGEvaluationResult(
            question=question,
            answer=answer,
            contexts=contexts,
            ground_truth=ground_truth,
            model=model,
        )

        try:
            # Prepare dataset for ragas
            data = {
                "question": [question],
                "answer": [answer],
                "contexts": [contexts],
            }

            # Select metrics based on available data
            metrics_to_use = [faithfulness, answer_relevancy]

            # Add context metrics if ground truth is provided
            if ground_truth:
                data["ground_truth"] = [ground_truth]
                metrics_to_use.extend([context_precision, context_recall])

            # Create dataset
            dataset = Dataset.from_dict(data)

            # Run evaluation (this is blocking, so run in executor)
            loop = asyncio.get_event_loop()
            evaluation_result = await loop.run_in_executor(
                None,
                lambda: evaluate(dataset, metrics=metrics_to_use)
            )

            # Extract scores
            result.faithfulness = evaluation_result.get("faithfulness")
            result.answer_relevancy = evaluation_result.get("answer_relevancy")
            result.context_precision = evaluation_result.get("context_precision")
            result.context_recall = evaluation_result.get("context_recall")

            # Record duration
            result.evaluation_duration = asyncio.get_event_loop().time() - start_time

            # Update Prometheus metrics
            if result.faithfulness is not None:
                rag_faithfulness_gauge.labels(model=model).set(result.faithfulness)
            if result.answer_relevancy is not None:
                rag_relevancy_gauge.labels(model=model).set(result.answer_relevancy)
            if result.context_precision is not None:
                rag_context_precision_gauge.labels(model=model).set(result.context_precision)
            if result.context_recall is not None:
                rag_context_recall_gauge.labels(model=model).set(result.context_recall)

            rag_evaluation_duration_histogram.labels(model=model).observe(
                result.evaluation_duration
            )

            logger.info(
                f"RAG evaluation complete - "
                f"Faithfulness: {result.faithfulness:.3f}, "
                f"Relevancy: {result.answer_relevancy:.3f}, "
                f"Duration: {result.evaluation_duration:.2f}s"
            )

        except Exception as e:
            logger.error(f"Error evaluating RAG answer: {e}", exc_info=True)
            result.error = str(e)
            result.evaluation_duration = asyncio.get_event_loop().time() - start_time

        # Store in history
        self.evaluation_history.append(result)
        if len(self.evaluation_history) > self.max_history:
            self.evaluation_history.pop(0)

        return result

    def evaluate_batch(
        self,
        questions: List[str],
        answers: List[str],
        contexts_list: List[List[str]],
        ground_truths: Optional[List[str]] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate a batch of RAG answers.

        Args:
            questions: List of questions
            answers: List of generated answers
            contexts_list: List of context lists (one per question)
            ground_truths: Optional list of ground truth answers
            model: Model used for generation

        Returns:
            Aggregated evaluation results
        """
        if not RAGAS_AVAILABLE:
            logger.warning("ragas not available")
            return {"error": "ragas not installed"}

        model = model or self.llm_model

        try:
            # Prepare dataset
            data = {
                "question": questions,
                "answer": answers,
                "contexts": contexts_list,
            }

            metrics_to_use = [faithfulness, answer_relevancy]

            if ground_truths:
                data["ground_truth"] = ground_truths
                metrics_to_use.extend([context_precision, context_recall])

            dataset = Dataset.from_dict(data)

            # Run batch evaluation
            start_time = datetime.utcnow()
            evaluation_result = evaluate(dataset, metrics=metrics_to_use)
            duration = (datetime.utcnow() - start_time).total_seconds()

            # Aggregate results
            result = {
                "num_samples": len(questions),
                "faithfulness": evaluation_result.get("faithfulness"),
                "answer_relevancy": evaluation_result.get("answer_relevancy"),
                "context_precision": evaluation_result.get("context_precision"),
                "context_recall": evaluation_result.get("context_recall"),
                "evaluation_duration": duration,
                "model": model,
                "timestamp": datetime.utcnow().isoformat(),
            }

            logger.info(
                f"Batch evaluation complete - "
                f"{len(questions)} samples, "
                f"Duration: {duration:.2f}s"
            )

            return result

        except Exception as e:
            logger.error(f"Error in batch evaluation: {e}", exc_info=True)
            return {"error": str(e)}

    def get_summary_metrics(
        self,
        time_window_hours: Optional[int] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get summary statistics from evaluation history.

        Args:
            time_window_hours: Only include last N hours
            model: Filter by model

        Returns:
            Summary statistics
        """
        filtered_results = self.evaluation_history

        # Filter by time window
        if time_window_hours:
            from datetime import timedelta
            cutoff = datetime.utcnow() - timedelta(hours=time_window_hours)
            filtered_results = [
                r for r in filtered_results
                if r.timestamp > cutoff
            ]

        # Filter by model
        if model:
            filtered_results = [r for r in filtered_results if r.model == model]

        if not filtered_results:
            return {"num_evaluations": 0}

        # Calculate aggregates
        successful = [r for r in filtered_results if r.error is None]

        if not successful:
            return {
                "num_evaluations": len(filtered_results),
                "num_successful": 0,
                "num_errors": len(filtered_results),
            }

        def safe_avg(values):
            valid = [v for v in values if v is not None]
            return sum(valid) / len(valid) if valid else None

        faithfulness_scores = [r.faithfulness for r in successful]
        relevancy_scores = [r.answer_relevancy for r in successful]
        precision_scores = [r.context_precision for r in successful]
        recall_scores = [r.context_recall for r in successful]

        return {
            "num_evaluations": len(filtered_results),
            "num_successful": len(successful),
            "num_errors": len(filtered_results) - len(successful),
            "avg_faithfulness": safe_avg(faithfulness_scores),
            "avg_answer_relevancy": safe_avg(relevancy_scores),
            "avg_context_precision": safe_avg(precision_scores),
            "avg_context_recall": safe_avg(recall_scores),
            "avg_evaluation_duration": safe_avg([r.evaluation_duration for r in successful]),
            "models": list(set(r.model for r in filtered_results)),
            "time_window_hours": time_window_hours or "all",
        }

    def get_recent_evaluations(
        self,
        limit: int = 10,
        model: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get recent evaluation results.

        Args:
            limit: Number of results to return
            model: Filter by model

        Returns:
            List of evaluation result dictionaries
        """
        filtered = self.evaluation_history

        if model:
            filtered = [r for r in filtered if r.model == model]

        recent = filtered[-limit:] if len(filtered) > limit else filtered
        return [r.to_dict() for r in reversed(recent)]


# Global singleton
_rag_evaluator: Optional[RAGEvaluator] = None


def get_rag_evaluator(llm_model: str = "gpt-4o-mini") -> RAGEvaluator:
    """Return the global RAGEvaluator instance."""
    global _rag_evaluator
    if _rag_evaluator is None:
        _rag_evaluator = RAGEvaluator(llm_model=llm_model)
    return _rag_evaluator

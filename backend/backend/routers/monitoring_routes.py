"""
Monitoring and Observability API Routes.

Provides endpoints for:
- Unified LLM metrics
- Data quality monitoring (Evidently)
- RAG quality evaluation (ragas)
- OpenTelemetry trace info
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.services.unified_llm_metrics import get_unified_metrics
from backend.services.data_monitor import get_data_monitor
from backend.services.rag_evaluator import get_rag_evaluator

logger = logging.getLogger(__name__)

router = APIRouter()


# Request/Response Models
class RAGEvaluationRequest(BaseModel):
    """Request to evaluate a RAG answer."""
    question: str = Field(..., description="User's question")
    answer: str = Field(..., description="Generated answer")
    contexts: list[str] = Field(..., description="Retrieved context chunks")
    ground_truth: Optional[str] = Field(None, description="Optional ground truth answer")
    model: Optional[str] = Field(None, description="Model used for generation")


class DataDriftRequest(BaseModel):
    """Request to generate data drift report."""
    interaction_type: str = Field("chat", description="Type: chat, rag, agent, code")
    reference_window: Optional[int] = Field(None, description="Reference window size")
    current_window: Optional[int] = Field(None, description="Current window size")


# ==================== LLM Metrics Endpoints ====================

@router.get("/llm/summary", tags=["monitoring"])
async def get_llm_summary(
    model: Optional[str] = Query(None, description="Filter by model"),
    endpoint: Optional[str] = Query(None, description="Filter by endpoint"),
    time_window_minutes: Optional[int] = Query(None, description="Time window in minutes"),
):
    """
    Get summary statistics for LLM calls.

    Returns aggregated metrics including:
    - Total calls, success rate
    - Token usage and costs
    - Average duration
    - Retry statistics
    """
    try:
        unified_metrics = get_unified_metrics()
        stats = unified_metrics.get_summary_stats(
            model=model,
            endpoint=endpoint,
            time_window_minutes=time_window_minutes,
        )
        return stats
    except Exception as e:
        logger.error(f"Error getting LLM summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/recent-calls", tags=["monitoring"])
async def get_recent_llm_calls(
    limit: int = Query(10, description="Number of calls to return"),
    model: Optional[str] = Query(None, description="Filter by model"),
    endpoint: Optional[str] = Query(None, description="Filter by endpoint"),
):
    """
    Get recent LLM call details.

    Useful for debugging and tracking individual calls.
    """
    try:
        unified_metrics = get_unified_metrics()
        calls = unified_metrics.get_recent_calls(
            limit=limit,
            model=model,
            endpoint=endpoint,
        )
        return {"calls": calls, "total": len(calls)}
    except Exception as e:
        logger.error(f"Error getting recent LLM calls: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Data Quality Endpoints ====================

@router.get("/data-quality/summary", tags=["monitoring"])
async def get_data_quality_summary(
    interaction_type: str = Query("chat", description="Type: chat, rag, agent, code"),
    time_window_hours: Optional[int] = Query(None, description="Time window in hours"),
):
    """
    Get summary statistics for data quality.

    Returns metrics like:
    - Total interactions
    - Average query/response lengths
    - Token usage patterns
    - Success rates
    """
    try:
        data_monitor = get_data_monitor()
        stats = data_monitor.get_summary_stats(
            interaction_type=interaction_type,
            time_window_hours=time_window_hours,
        )
        return stats
    except Exception as e:
        logger.error(f"Error getting data quality summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/data-quality/drift-report", tags=["monitoring"])
async def generate_drift_report(request: DataDriftRequest):
    """
    Generate Evidently data drift report.

    Compares reference window (historical baseline) with current window
    to detect distribution shifts and data quality issues.
    """
    try:
        data_monitor = get_data_monitor()
        report = data_monitor.generate_drift_report(
            interaction_type=request.interaction_type,
            reference_window=request.reference_window,
            current_window=request.current_window,
        )

        if report is None:
            raise HTTPException(
                status_code=400,
                detail="Insufficient data for drift report. Need more interactions."
            )

        return report
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating drift report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== RAG Evaluation Endpoints ====================

@router.post("/rag/evaluate", tags=["monitoring"])
async def evaluate_rag_answer(request: RAGEvaluationRequest):
    """
    Evaluate RAG answer quality using ragas metrics.

    Metrics include:
    - Faithfulness: Answer is faithful to retrieved context
    - Answer Relevancy: Answer is relevant to the question
    - Context Precision: Retrieved context is precise (requires ground truth)
    - Context Recall: Retrieved context has good recall (requires ground truth)
    """
    try:
        rag_evaluator = get_rag_evaluator()
        result = await rag_evaluator.evaluate_answer(
            question=request.question,
            answer=request.answer,
            contexts=request.contexts,
            ground_truth=request.ground_truth,
            model=request.model,
        )
        return result.to_dict()
    except Exception as e:
        logger.error(f"Error evaluating RAG answer: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rag/evaluation-summary", tags=["monitoring"])
async def get_rag_evaluation_summary(
    time_window_hours: Optional[int] = Query(None, description="Time window in hours"),
    model: Optional[str] = Query(None, description="Filter by model"),
):
    """
    Get summary statistics from RAG evaluations.

    Returns aggregated metrics across all evaluations.
    """
    try:
        rag_evaluator = get_rag_evaluator()
        summary = rag_evaluator.get_summary_metrics(
            time_window_hours=time_window_hours,
            model=model,
        )
        return summary
    except Exception as e:
        logger.error(f"Error getting RAG evaluation summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rag/recent-evaluations", tags=["monitoring"])
async def get_recent_rag_evaluations(
    limit: int = Query(10, description="Number of evaluations to return"),
    model: Optional[str] = Query(None, description="Filter by model"),
):
    """
    Get recent RAG evaluation results.

    Useful for tracking RAG quality over time.
    """
    try:
        rag_evaluator = get_rag_evaluator()
        evaluations = rag_evaluator.get_recent_evaluations(
            limit=limit,
            model=model,
        )
        return {"evaluations": evaluations, "total": len(evaluations)}
    except Exception as e:
        logger.error(f"Error getting recent RAG evaluations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== System Health Endpoint ====================

@router.get("/health", tags=["monitoring"])
async def monitoring_health():
    """
    Health check for monitoring services.

    Returns status of all monitoring components.
    """
    try:
        from backend.services.unified_llm_metrics import OTEL_AVAILABLE
        from backend.services.data_monitor import EVIDENTLY_AVAILABLE
        from backend.services.rag_evaluator import RAGAS_AVAILABLE

        return {
            "status": "healthy",
            "components": {
                "unified_llm_metrics": "available",
                "opentelemetry": "available" if OTEL_AVAILABLE else "unavailable",
                "evidently": "available" if EVIDENTLY_AVAILABLE else "unavailable",
                "ragas": "available" if RAGAS_AVAILABLE else "unavailable",
            },
            "prometheus_metrics": "/metrics",
        }
    except Exception as e:
        logger.error(f"Error checking monitoring health: {e}", exc_info=True)
        return {
            "status": "degraded",
            "error": str(e),
        }


# ==================== Configuration Endpoint ====================

@router.get("/config", tags=["monitoring"])
async def get_monitoring_config():
    """
    Get monitoring configuration and capabilities.

    Returns information about enabled features and endpoints.
    """
    from backend.services.unified_llm_metrics import OTEL_AVAILABLE
    from backend.services.data_monitor import EVIDENTLY_AVAILABLE
    from backend.services.rag_evaluator import RAGAS_AVAILABLE

    return {
        "features": {
            "llm_metrics": {
                "enabled": True,
                "endpoints": [
                    "/api/monitoring/llm/summary",
                    "/api/monitoring/llm/recent-calls",
                ],
            },
            "data_quality": {
                "enabled": EVIDENTLY_AVAILABLE,
                "endpoints": [
                    "/api/monitoring/data-quality/summary",
                    "/api/monitoring/data-quality/drift-report",
                ],
            },
            "rag_evaluation": {
                "enabled": RAGAS_AVAILABLE,
                "endpoints": [
                    "/api/monitoring/rag/evaluate",
                    "/api/monitoring/rag/evaluation-summary",
                    "/api/monitoring/rag/recent-evaluations",
                ],
            },
            "distributed_tracing": {
                "enabled": OTEL_AVAILABLE,
                "jaeger_ui": "http://localhost:16686",
            },
            "prometheus_metrics": {
                "enabled": True,
                "endpoint": "/metrics",
                "grafana_ui": "http://localhost:3000",
            },
        },
        "documentation": "/docs",
    }

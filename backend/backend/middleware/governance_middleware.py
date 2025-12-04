"""
Governance Middleware for AI-Louie
Automatically tracks governance checkpoints for all RAG operations
"""
import time
import uuid
from functools import wraps
from typing import Callable, Any
import structlog

from backend.services.governance_tracker import (
    GovernanceContext,
    GovernanceCriteria,
    RiskTier,
    get_governance_tracker,
)

logger = structlog.get_logger(__name__)


def with_governance_tracking(
    operation_type: str = "rag",
    risk_tier: RiskTier = RiskTier.R1,
):
    """
    Decorator to add governance tracking to RAG endpoints.

    Automatically records:
    - G3: Evidence contract (input/output logging)
    - G5: Privacy control (PII detection)
    - G7: Observability (trace ID)
    - G8: Evaluation system (latency SLO monitoring)

    Usage:
        @with_governance_tracking(operation_type="rag", risk_tier=RiskTier.R1)
        async def ask_question(request: RAGRequest) -> RAGResponse:
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Extract request from args/kwargs
            request = None
            for arg in args:
                if hasattr(arg, 'question'):  # RAGRequest has question field
                    request = arg
                    break
            if not request and 'request' in kwargs:
                request = kwargs['request']

            # Generate trace ID
            trace_id = str(uuid.uuid4())
            start_time = time.time()

            # Create governance context
            tracker = get_governance_tracker()
            gov_context = GovernanceContext(
                trace_id=trace_id,
                operation_type=operation_type,
                risk_tier=risk_tier,
                active_criteria={
                    GovernanceCriteria.G3_EVIDENCE_CONTRACT,
                    GovernanceCriteria.G5_PRIVACY_CONTROL,
                    GovernanceCriteria.G7_OBSERVABILITY,
                    GovernanceCriteria.G8_EVALUATION_SYSTEM,
                },
                metadata={
                    "endpoint": func.__name__,
                    "question": getattr(request, 'question', None) if request else None,
                }
            )

            try:
                # G7: Observability - Record trace start
                gov_context.add_checkpoint(
                    GovernanceCriteria.G7_OBSERVABILITY,
                    "passed",
                    f"Trace initiated: {trace_id}",
                    {"trace_id": trace_id, "endpoint": func.__name__}
                )

                # G3: Evidence Contract - Log input
                if request and hasattr(request, 'question'):
                    gov_context.add_checkpoint(
                        GovernanceCriteria.G3_EVIDENCE_CONTRACT,
                        "passed",
                        "Input logged",
                        {
                            "question_length": len(request.question),
                            "top_k": getattr(request, 'top_k', None),
                        }
                    )

                # G5: Privacy Control - Basic PII check (simple heuristic)
                if request and hasattr(request, 'question'):
                    question_lower = request.question.lower()
                    # Simple patterns for common PII
                    has_email = '@' in question_lower and '.' in question_lower
                    has_phone = any(digit in question_lower for digit in ['phone', 'mobile', 'cell'])
                    has_address = any(word in question_lower for word in ['address', 'street', 'zip'])

                    if has_email or has_phone or has_address:
                        gov_context.add_checkpoint(
                            GovernanceCriteria.G5_PRIVACY_CONTROL,
                            "warning",
                            "Potential PII detected in query",
                            {"patterns": {"email": has_email, "phone": has_phone, "address": has_address}}
                        )
                    else:
                        gov_context.add_checkpoint(
                            GovernanceCriteria.G5_PRIVACY_CONTROL,
                            "passed",
                            "No obvious PII detected",
                            {}
                        )

                # Execute the actual endpoint
                result = await func(*args, **kwargs)

                # Calculate latency
                latency_ms = (time.time() - start_time) * 1000

                # G8: Evaluation System - Check SLO (< 2s for R1)
                slo_threshold_ms = 2000  # 2 seconds
                slo_status = "passed" if latency_ms < slo_threshold_ms else "warning"
                slo_message = (
                    f"Latency {latency_ms:.0f}ms < {slo_threshold_ms}ms SLO"
                    if slo_status == "passed"
                    else f"Latency {latency_ms:.0f}ms exceeded {slo_threshold_ms}ms SLO"
                )

                gov_context.add_checkpoint(
                    GovernanceCriteria.G8_EVALUATION_SYSTEM,
                    slo_status,
                    slo_message,
                    {"latency_ms": latency_ms, "slo_threshold_ms": slo_threshold_ms}
                )

                # G3: Evidence Contract - Log output
                if result:
                    output_metadata = {}
                    if hasattr(result, 'answer'):
                        output_metadata['answer_length'] = len(result.answer) if result.answer else 0
                    if hasattr(result, 'num_chunks_retrieved'):
                        output_metadata['num_chunks'] = result.num_chunks_retrieved

                    gov_context.add_checkpoint(
                        GovernanceCriteria.G3_EVIDENCE_CONTRACT,
                        "passed",
                        "Output logged",
                        output_metadata
                    )

                # Finalize governance context
                gov_context.complete()
                logger.debug("Governance tracking completed", trace_id=trace_id, checkpoints=len(gov_context.checkpoints))

                return result

            except Exception as e:
                # Log failure
                latency_ms = (time.time() - start_time) * 1000
                gov_context.add_checkpoint(
                    GovernanceCriteria.G8_EVALUATION_SYSTEM,
                    "failed",
                    f"Request failed: {str(e)}",
                    {"latency_ms": latency_ms, "error": str(e)}
                )
                gov_context.complete()
                logger.error("Governance tracking completed with error", trace_id=trace_id, error=str(e))
                raise

        return wrapper
    return decorator

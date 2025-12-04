"""
API routes for Code Assistant (Task 3.4).
"""
import logging
import time
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from backend.models.code_schemas import CodeRequest, CodeResponse, CodeMetrics
from backend.services.code_assistant import get_code_assistant
from backend.services.governance_tracker import get_governance_tracker

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/generate", response_model=CodeResponse)
async def generate_code(request: CodeRequest):
    """
    Generate code with automated testing and self-healing.

    The assistant will:
    1. Generate initial code from natural language description
    2. Run automated tests
    3. If tests fail, analyze errors and fix the code
    4. Retry up to max_retries times
    5. Return final code with test results

    Args:
        request: Code generation request

    Returns:
        Generated code with test results and retry history
    """
    # Start governance tracking
    governance_tracker = get_governance_tracker()
    gov_context = governance_tracker.start_operation(
        operation_type="code",
        metadata={"task": request.task[:200], "language": request.language.value}
    )
    start_time = time.time()

    try:
        logger.info(f"💻 Code generation request: {request.task[:100]}... ({request.language})", extra={"trace_id": gov_context.trace_id})

        # Governance checkpoint: Policy gate
        governance_tracker.checkpoint_policy_gate(
            gov_context.trace_id,
            allowed=True,
            reason="R0 policy allows code generation (internal productivity)"
        )

        assistant = get_code_assistant()
        response = await assistant.generate_code(request)

        # Calculate total time
        total_time_ms = (time.time() - start_time) * 1000

        # Add governance checkpoints
        governance_tracker.checkpoint_generation(
            gov_context.trace_id,
            model=assistant.model_name,
            prompt_version="v1.0"
        )

        # Check test quality
        test_quality = "good" if response.test_passed else "failed"
        governance_tracker.checkpoint_reliability(
            gov_context.trace_id,
            status="passed" if response.test_passed else "warning",
            message=f"Tests {test_quality}: passed={response.test_passed}, retries={response.total_retries}"
        )

        governance_tracker.checkpoint_quality(
            gov_context.trace_id,
            latency_ms=total_time_ms,
            quality_score=1.0 if response.test_passed else 0.5
        )

        governance_tracker.checkpoint_audit(gov_context.trace_id, audit_logged=True)

        # Complete governance tracking and attach to response
        governance_tracker.complete_operation(gov_context.trace_id)
        response.governance_context = gov_context.get_summary()

        logger.info(
            f"✅ Code generated - tests passed: {response.test_passed}, "
            f"retries: {response.total_retries}",
            extra={"trace_id": gov_context.trace_id}
        )

        return response

    except ValueError as e:
        logger.error(f"❌ Validation error: {e}", extra={"trace_id": gov_context.trace_id})

        # Log failure in governance
        try:
            governance_tracker.checkpoint_reliability(
                gov_context.trace_id,
                status="failed",
                message=f"Validation error: {str(e)}"
            )
            governance_tracker.complete_operation(gov_context.trace_id)
        except:
            pass

        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error(f"❌ Code generation failed: {e}", exc_info=True, extra={"trace_id": gov_context.trace_id})

        # Log failure in governance
        try:
            governance_tracker.checkpoint_reliability(
                gov_context.trace_id,
                status="failed",
                message=f"Code generation failed: {str(e)}"
            )
            governance_tracker.complete_operation(gov_context.trace_id)
        except:
            pass

        raise HTTPException(status_code=500, detail=f"Code generation failed: {str(e)}")


@router.get("/health")
async def health_check():
    """
    Health check endpoint for Code Assistant service.

    Returns:
        Service health status
    """
    try:
        assistant = get_code_assistant()

        return JSONResponse(content={
            "status": "healthy",
            "service": "code_assistant",
            "model": assistant.model_name
        })

    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e)
            }
        )


@router.get("/metrics", response_model=CodeMetrics)
async def get_metrics():
    """
    Get Code Assistant performance metrics.

    Returns:
        Code assistant performance metrics
    """
    # Placeholder - in production, track these in a database
    return CodeMetrics(
        total_requests=0,
        success_rate=0.0,
        avg_retries=0.0,
        avg_generation_time_ms=0.0,
        languages_used={}
    )

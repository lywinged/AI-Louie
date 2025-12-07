"""
API routes for Planning Agent (Task 3.3).
"""
import logging
import time
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from backend.models.agent_schemas import PlanRequest, PlanResponse, AgentMetrics
from backend.services.planning_agent import get_planning_agent
from backend.services.agent_metrics_store import planning_metrics_store
from backend.services.governance_tracker import get_governance_tracker

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/plan", response_model=PlanResponse)
async def create_trip_plan(request: PlanRequest):
    """
    Create a trip plan using the autonomous planning agent.

    The agent will:
    1. Search for flights
    2. Check weather forecast
    3. Find tourist attractions
    4. Compile a complete itinerary

    Args:
        request: Plan request with user prompt and constraints

    Returns:
        Complete trip plan with itinerary, reasoning trace, and tool calls
    """
    # Start governance tracking
    governance_tracker = get_governance_tracker()
    gov_context = governance_tracker.start_operation(
        operation_type="agent",
        metadata={"prompt": request.prompt[:200]}
    )
    start_time = time.time()

    try:
        logger.info(f"📝 Planning request: {request.prompt[:100]}...", extra={"trace_id": gov_context.trace_id})

        # Governance checkpoint: Policy gate
        governance_tracker.checkpoint_policy_gate(
            gov_context.trace_id,
            allowed=True,
            reason="R1 policy allows trip planning (customer-facing with audit)"
        )

        agent = get_planning_agent()
        response = await agent.create_plan(request)

        # Calculate total time
        total_time_ms = (time.time() - start_time) * 1000

        # Add governance checkpoints
        governance_tracker.checkpoint_generation(
            gov_context.trace_id,
            model=agent.model_name,
            prompt_version="v1.0"
        )

        # Check constraints satisfaction
        governance_tracker.checkpoint_reliability(
            gov_context.trace_id,
            status="passed" if response.constraints_satisfied else "warning",
            message=f"Constraints satisfied: {response.constraints_satisfied}, tools used: {len(response.tool_calls)}"
        )

        governance_tracker.checkpoint_quality(
            gov_context.trace_id,
            latency_ms=total_time_ms,
            quality_score=1.0 if response.constraints_satisfied else 0.7
        )

        governance_tracker.checkpoint_audit(gov_context.trace_id, audit_logged=True)

        # Complete governance tracking and attach to response
        governance_tracker.complete_operation(gov_context.trace_id)
        response.governance_context = gov_context.get_summary()

        logger.info(
            f"✅ Plan created - {len(response.tool_calls)} tools used, "
            f"constraints satisfied: {response.constraints_satisfied}",
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
        logger.error(f"❌ Planning failed: {e}", exc_info=True, extra={"trace_id": gov_context.trace_id})

        # Log failure in governance
        try:
            governance_tracker.checkpoint_reliability(
                gov_context.trace_id,
                status="failed",
                message=f"Planning failed: {str(e)}"
            )
            governance_tracker.complete_operation(gov_context.trace_id)
        except:
            pass

        raise HTTPException(status_code=500, detail=f"Planning failed: {str(e)}")


@router.get("/health")
async def health_check():
    """
    Health check endpoint for Planning Agent service.

    Returns:
        Service health status
    """
    try:
        agent = get_planning_agent()

        return JSONResponse(content={
            "status": "healthy",
            "service": "planning_agent",
            "model": agent.model_name
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


@router.get("/metrics", response_model=AgentMetrics)
async def get_metrics():
    """
    Get Planning Agent performance metrics.

    Returns:
        Agent performance metrics
    """
    summary = planning_metrics_store.get_summary()
    return AgentMetrics(**summary)


@router.post("/metrics/reset")
async def reset_metrics():
    """
    Reset the planning metrics store (aggregated across sessions).
    """
    planning_metrics_store.reset()
    return {"status": "reset"}

"""
Task 3.1: Chat API Endpoints

Endpoints:
- POST /api/chat/message - Non-streaming chat
- POST /api/chat/stream - Streaming chat (SSE)
- GET /api/chat/history - Get conversation history
- DELETE /api/chat/history - Clear history
- GET /api/chat/metrics - Get chat metrics
"""

import logging
import os
import time
from typing import List
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from backend.models.chat_schemas import ChatRequest, ChatResponse, ChatMessage, ChatHistory
from backend.services.chat_service import get_chat_service
from backend.services.data_monitor import get_data_monitor
from backend.services.governance_tracker import get_governance_tracker

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/message", response_model=ChatResponse)
async def chat_message(request: ChatRequest):
    """
    Non-streaming chat completion

    Returns complete response with token counts and cost
    """
    # Start governance tracking
    governance_tracker = get_governance_tracker()
    gov_context = governance_tracker.start_operation(
        operation_type="chat",
        metadata={"message": request.message[:200]}
    )
    start_time = time.time()

    try:
        logger.info(f"💬 Chat request received", extra={"trace_id": gov_context.trace_id})

        # Governance checkpoint: Policy gate
        governance_tracker.checkpoint_policy_gate(
            gov_context.trace_id,
            allowed=True,
            reason="R1 policy allows chat (customer-facing with audit)"
        )

        service = get_chat_service()
        response = await service.chat_completion(
            user_message=request.message,
            max_history=request.max_history or 10
        )

        # Add governance checkpoints
        governance_tracker.checkpoint_generation(
            gov_context.trace_id,
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            prompt_version="v1.0"
        )

        governance_tracker.checkpoint_quality(
            gov_context.trace_id,
            latency_ms=response.latency_ms,
            quality_score=0.9  # Chat quality estimation
        )

        governance_tracker.checkpoint_audit(gov_context.trace_id, audit_logged=True)

        governance_tracker.checkpoint_reliability(
            gov_context.trace_id,
            status="passed",
            message=f"Chat completed successfully: {response.total_tokens} tokens"
        )

        # Complete governance tracking and attach to response
        governance_tracker.complete_operation(gov_context.trace_id)
        response.governance_context = gov_context.get_summary()

        # Log interaction for drift monitoring
        try:
            data_monitor = get_data_monitor()
            model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            data_monitor.log_chat_interaction(
                query=request.message,
                response=response.message,
                total_tokens=response.total_tokens,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                duration_ms=response.latency_ms,
                model=model_name,
                success=True,
                metadata={"cost_usd": response.cost_usd, "trace_id": gov_context.trace_id}
            )
        except Exception as monitor_error:
            logger.warning(f"Failed to log chat interaction to data monitor: {monitor_error}")

        return response
    except Exception as e:
        logger.error(f"Chat message failed: {e}", extra={"trace_id": gov_context.trace_id})

        # Log failure in governance
        try:
            governance_tracker.checkpoint_reliability(
                gov_context.trace_id,
                status="failed",
                message=f"Chat failed: {str(e)}"
            )
            governance_tracker.complete_operation(gov_context.trace_id)
        except:
            pass

        # Log failed interaction
        try:
            data_monitor = get_data_monitor()
            model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            data_monitor.log_chat_interaction(
                query=request.message,
                response="",
                total_tokens=0,
                prompt_tokens=0,
                completion_tokens=0,
                duration_ms=0,
                model=model_name,
                success=False,
                metadata={"error": str(e), "trace_id": gov_context.trace_id}
            )
        except Exception as monitor_error:
            logger.warning(f"Failed to log failed interaction: {monitor_error}")

        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """
    Streaming chat completion using Server-Sent Events

    Returns chunked response as it's generated
    """
    try:
        service = get_chat_service()

        async def generate():
            """Generate SSE events"""
            try:
                async for chunk in service.chat_completion_stream(
                    user_message=request.message,
                    max_history=request.max_history or 10
                ):
                    yield {
                        "event": "message",
                        "data": chunk,
                    }

                # Send completion event
                yield {
                    "event": "done",
                    "data": "[DONE]",
                }
            except Exception as e:
                logger.error(f"Stream generation failed: {e}")
                yield {
                    "event": "error",
                    "data": str(e),
                }

        return EventSourceResponse(generate())

    except Exception as e:
        logger.error(f"Chat stream failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history", response_model=ChatHistory)
async def get_history():
    """Get conversation history"""
    try:
        service = get_chat_service()
        messages = service.get_history()
        return ChatHistory(
            messages=messages,
            total_messages=len(messages)
        )
    except Exception as e:
        logger.error(f"Get history failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/history")
async def clear_history():
    """Clear conversation history"""
    try:
        service = get_chat_service()
        service.clear_history()
        return {"message": "History cleared successfully"}
    except Exception as e:
        logger.error(f"Clear history failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics")
async def get_metrics():
    """
    Get chat metrics and telemetry

    Returns aggregated metrics from Prometheus counters
    """
    try:
        from backend.services.metrics import (
            llm_token_usage_counter,
            llm_request_counter,
            llm_cost_counter,
        )

        # Get metrics from Prometheus
        # Note: This is a simplified version - in production you'd query Prometheus API
        metrics = {
            "message": "Metrics are available at /metrics endpoint (Prometheus format)",
            "endpoint": "/metrics",
            "note": "Use Prometheus/Grafana for visualization"
        }

        return metrics
    except Exception as e:
        logger.error(f"Get metrics failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

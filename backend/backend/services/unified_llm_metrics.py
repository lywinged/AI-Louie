"""
Unified LLM Metrics Service.

Provides a centralized interface for tracking all LLM-related metrics:
- Token usage and costs (via existing TokenCounter)
- Request latency and throughput
- Error rates and retry statistics
- Model-specific performance metrics
- OpenTelemetry integration for distributed tracing

This service wraps and extends the existing LLMTracker with additional metrics.
"""

import time
import logging
from typing import Optional, Dict, Any, List, AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime

from backend.services.token_counter import get_token_counter, TokenUsage
from backend.services.llm_tracker import get_llm_tracker
from backend.services.metrics import (
    llm_token_usage_counter,
    llm_request_counter,
    llm_cost_counter,
    llm_request_duration_histogram,
)

try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class LLMCallMetrics:
    """Complete metrics for a single LLM API call."""
    model: str
    endpoint: str
    duration: float
    usage: TokenUsage
    cost: float
    success: bool
    error: Optional[str] = None
    retry_count: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    trace_id: Optional[str] = None
    span_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "endpoint": self.endpoint,
            "duration": self.duration,
            "usage": self.usage.to_dict(),
            "cost": self.cost,
            "success": self.success,
            "error": self.error,
            "retry_count": self.retry_count,
            "timestamp": self.timestamp.isoformat(),
            "trace_id": self.trace_id,
            "span_id": self.span_id,
        }


class UnifiedLLMMetrics:
    """
    Unified service for tracking all LLM metrics.

    Features:
    - Automatic token counting and cost calculation
    - Prometheus metrics export
    - OpenTelemetry tracing integration
    - Request/response logging
    - Retry tracking
    - Error rate monitoring
    """

    def __init__(self):
        self.token_counter = get_token_counter()
        self.llm_tracker = get_llm_tracker()
        self.tracer = trace.get_tracer(__name__) if OTEL_AVAILABLE else None
        self.call_history: List[LLMCallMetrics] = []
        self.max_history = 1000  # Keep last 1000 calls in memory

    async def track_chat_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        completion: str,
        duration: float,
        endpoint: str = "chat",
        success: bool = True,
        error: Optional[str] = None,
        retry_count: int = 0,
        trace_context: Optional[Dict[str, str]] = None,
    ) -> LLMCallMetrics:
        """
        Track a chat completion call with full metrics.

        Args:
            model: Model identifier (e.g., "gpt-4o-mini", "gpt-4")
            messages: Input message payload
            completion: Generated completion text
            duration: Request duration in seconds
            endpoint: API endpoint label
            success: Whether the call succeeded
            error: Error message if failed
            retry_count: Number of retries performed
            trace_context: OpenTelemetry trace context

        Returns:
            LLMCallMetrics with complete tracking data
        """
        # Use existing tracker for backward compatibility
        usage = await self.llm_tracker.track_chat_completion(
            model=model,
            messages=messages,
            completion=completion,
            duration=duration,
            endpoint=endpoint,
        )

        # Calculate cost
        cost = self.token_counter.estimate_cost(usage)

        # Extract trace info if available
        trace_id = None
        span_id = None
        if OTEL_AVAILABLE and self.tracer:
            current_span = trace.get_current_span()
            if current_span and current_span.is_recording():
                span_context = current_span.get_span_context()
                trace_id = format(span_context.trace_id, '032x')
                span_id = format(span_context.span_id, '016x')

        # Create metrics object
        metrics = LLMCallMetrics(
            model=model,
            endpoint=endpoint,
            duration=duration,
            usage=usage,
            cost=cost,
            success=success,
            error=error,
            retry_count=retry_count,
            trace_id=trace_id,
            span_id=span_id,
        )

        # Store in history (rolling window)
        self.call_history.append(metrics)
        if len(self.call_history) > self.max_history:
            self.call_history.pop(0)

        return metrics

    async def track_streaming_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        collected_chunks: List[str],
        duration: float,
        endpoint: str = "chat",
        success: bool = True,
        error: Optional[str] = None,
    ) -> LLMCallMetrics:
        """
        Track a streaming chat completion call.

        Args:
            model: Model identifier
            messages: Input message payload
            collected_chunks: All streaming chunks
            duration: Total duration in seconds
            endpoint: API endpoint label
            success: Whether the call succeeded
            error: Error message if failed

        Returns:
            LLMCallMetrics
        """
        completion = "".join(collected_chunks)
        return await self.track_chat_completion(
            model=model,
            messages=messages,
            completion=completion,
            duration=duration,
            endpoint=endpoint,
            success=success,
            error=error,
        )

    @asynccontextmanager
    async def track_llm_call(
        self,
        model: str,
        endpoint: str = "chat",
        operation_name: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Context manager for automatic LLM call tracking with OpenTelemetry.

        Usage:
            async with unified_metrics.track_llm_call("gpt-4o-mini", "chat") as ctx:
                response = await client.chat.completions.create(...)
                ctx["messages"] = messages
                ctx["completion"] = response.choices[0].message.content

        Yields:
            Context dictionary to store call metadata
        """
        start_time = time.time()
        context = {
            "model": model,
            "endpoint": endpoint,
            "success": True,
            "error": None,
            "retry_count": 0,
        }

        # Start OpenTelemetry span
        span = None
        if OTEL_AVAILABLE and self.tracer:
            span_name = operation_name or f"llm.{endpoint}"
            span = self.tracer.start_span(span_name)
            span.set_attribute("llm.model", model)
            span.set_attribute("llm.endpoint", endpoint)
            span.set_attribute("llm.provider", "azure_openai")

        try:
            yield context

            duration = time.time() - start_time

            # Track metrics if messages and completion are provided
            if "messages" in context and "completion" in context:
                metrics = await self.track_chat_completion(
                    model=model,
                    messages=context["messages"],
                    completion=context["completion"],
                    duration=duration,
                    endpoint=endpoint,
                    success=context.get("success", True),
                    error=context.get("error"),
                    retry_count=context.get("retry_count", 0),
                )
                context["metrics"] = metrics

                # Add token info to span
                if span:
                    span.set_attribute("llm.tokens.prompt", metrics.usage.prompt_tokens)
                    span.set_attribute("llm.tokens.completion", metrics.usage.completion_tokens)
                    span.set_attribute("llm.tokens.total", metrics.usage.total_tokens)
                    span.set_attribute("llm.cost_usd", metrics.cost)
                    span.set_attribute("llm.duration_s", duration)

            if span:
                span.set_status(Status(StatusCode.OK))

        except Exception as e:
            duration = time.time() - start_time
            context["success"] = False
            context["error"] = str(e)

            # Record error in metrics
            llm_request_counter.labels(
                model=model,
                endpoint=endpoint,
                status="error"
            ).inc()

            llm_request_duration_histogram.labels(
                model=model,
                endpoint=endpoint
            ).observe(duration)

            if span:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)

            logger.error(
                f"LLM call failed - Model: {model}, "
                f"Endpoint: {endpoint}, "
                f"Duration: {duration:.2f}s, "
                f"Error: {e}"
            )
            raise

        finally:
            if span:
                span.end()

    def get_summary_stats(
        self,
        model: Optional[str] = None,
        endpoint: Optional[str] = None,
        time_window_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get summary statistics for LLM calls.

        Args:
            model: Filter by model (optional)
            endpoint: Filter by endpoint (optional)
            time_window_minutes: Only include calls within last N minutes

        Returns:
            Summary statistics dictionary
        """
        filtered_calls = self.call_history

        # Apply filters
        if model:
            filtered_calls = [c for c in filtered_calls if c.model == model]
        if endpoint:
            filtered_calls = [c for c in filtered_calls if c.endpoint == endpoint]
        if time_window_minutes:
            cutoff = datetime.utcnow().timestamp() - (time_window_minutes * 60)
            filtered_calls = [
                c for c in filtered_calls
                if c.timestamp.timestamp() > cutoff
            ]

        if not filtered_calls:
            return {
                "total_calls": 0,
                "success_rate": 0.0,
                "total_tokens": 0,
                "total_cost": 0.0,
                "avg_duration": 0.0,
                "avg_tokens_per_call": 0.0,
            }

        total_calls = len(filtered_calls)
        successful_calls = sum(1 for c in filtered_calls if c.success)
        total_tokens = sum(c.usage.total_tokens for c in filtered_calls)
        total_cost = sum(c.cost for c in filtered_calls)
        total_duration = sum(c.duration for c in filtered_calls)
        total_retries = sum(c.retry_count for c in filtered_calls)

        return {
            "total_calls": total_calls,
            "successful_calls": successful_calls,
            "failed_calls": total_calls - successful_calls,
            "success_rate": successful_calls / total_calls,
            "total_tokens": total_tokens,
            "total_prompt_tokens": sum(c.usage.prompt_tokens for c in filtered_calls),
            "total_completion_tokens": sum(c.usage.completion_tokens for c in filtered_calls),
            "total_cost": total_cost,
            "avg_duration": total_duration / total_calls,
            "avg_tokens_per_call": total_tokens / total_calls,
            "avg_cost_per_call": total_cost / total_calls,
            "total_retries": total_retries,
            "avg_retries_per_call": total_retries / total_calls,
            "models": list(set(c.model for c in filtered_calls)),
            "endpoints": list(set(c.endpoint for c in filtered_calls)),
        }

    def get_recent_calls(
        self,
        limit: int = 10,
        model: Optional[str] = None,
        endpoint: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get recent LLM calls.

        Args:
            limit: Number of calls to return
            model: Filter by model
            endpoint: Filter by endpoint

        Returns:
            List of call metadata dictionaries
        """
        filtered_calls = self.call_history

        if model:
            filtered_calls = [c for c in filtered_calls if c.model == model]
        if endpoint:
            filtered_calls = [c for c in filtered_calls if c.endpoint == endpoint]

        # Return most recent calls
        recent = filtered_calls[-limit:] if len(filtered_calls) > limit else filtered_calls
        return [call.to_dict() for call in reversed(recent)]


# Global singleton
_unified_metrics: Optional[UnifiedLLMMetrics] = None


def get_unified_metrics() -> UnifiedLLMMetrics:
    """Return the global UnifiedLLMMetrics instance."""
    global _unified_metrics
    if _unified_metrics is None:
        _unified_metrics = UnifiedLLMMetrics()
    return _unified_metrics

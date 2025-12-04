"""
Answer Cache Wrapper for all RAG endpoints

This provides a unified caching layer that works across all RAG modes.
"""
import structlog
import uuid
import time
from typing import Callable, Awaitable
from backend.models.rag_schemas import RAGResponse
from backend.services.enhanced_rag_pipeline import _get_answer_cache
from backend.services.metrics import rag_query_cache_hits_counter, rag_query_cache_misses_counter

logger = structlog.get_logger(__name__)

# Query history for feedback tracking (imported from rag_routes if available)
_query_history = {}


async def with_answer_cache(
    question: str,
    rag_function: Callable[..., Awaitable[RAGResponse]],
    *args,
    **kwargs
) -> RAGResponse:
    """
    Wrapper that adds answer caching to any RAG function.

    Args:
        question: User's question
        rag_function: The RAG function to call (e.g., answer_question, ask_with_reflection)
        *args: Positional arguments to pass to rag_function
        **kwargs: Keyword arguments to pass to rag_function

    Returns:
        RAGResponse (from cache or fresh generation)
    """
    # Step 1: Check answer cache FIRST
    answer_cache = _get_answer_cache()
    if answer_cache:
        try:
            cached = await answer_cache.find_cached_answer(question)
            if cached:
                # Track cache hit metric
                rag_query_cache_hits_counter.inc()
                logger.info(
                    "Answer cache HIT - returning cached answer",
                    query=question[:50],
                    layer=cached['cache_layer'],
                    method=cached['cache_method'],
                    similarity=f"{cached['similarity']:.3f}",
                    time_ms=f"{cached['time_ms']:.2f}"
                )
                # Return cached answer directly, skip all RAG processing!
                # Clear token usage since no LLM was called
                cached_response = cached['answer']
                cached_response.token_usage = None
                cached_response.token_cost_usd = 0.0

                # 🆕 Assign query_id for cached answers to enable feedback
                query_id = str(uuid.uuid4())
                cached_response.query_id = query_id

                # 🆕 Track cached query for potential user feedback
                try:
                    from backend.routers.rag_routes import _query_history as route_query_history
                    route_query_history[query_id] = {
                        "strategy": "cached",
                        "automated_reward": 1.0,  # Cached answers default to high reward
                        "timestamp": time.time(),
                        "question": question[:200],
                        "is_cached": True,
                        "cache_layer": cached['cache_layer'],
                    }
                except ImportError:
                    # Fallback if rag_routes not available
                    _query_history[query_id] = {
                        "strategy": "cached",
                        "automated_reward": 1.0,
                        "timestamp": time.time(),
                        "question": question[:200],
                        "is_cached": True,
                        "cache_layer": cached['cache_layer'],
                    }
                # Clear previous token breakdown so UI shows zero-cost hit
                cached_response.token_breakdown = {
                    "query_classification": {
                        "tokens": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "cost": 0.0,
                        "method": "answer_cache",
                        "llm_used": False,
                        "cached": True,
                    },
                    "answer_cache_lookup": {
                        "tokens": 0,
                        "cost": 0.0,
                        "cache_hit": True,
                        "llm_used": False,
                    },
                    "answer_generation": {
                        "tokens": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "cost": 0.0,
                        "llm_used": False,
                        "iterations": None,
                    },
                    "total": {
                        "tokens": 0,
                        "cost": 0.0,
                        "llm_calls": 0,
                    },
                }
                # Set cache_hit field to indicate this was from cache
                cached_response.cache_hit = True
                # Clear classification tokens too (from first generation)
                if hasattr(cached_response, '_classification_tokens'):
                    cached_response._classification_tokens = None
                if hasattr(cached_response, '_classification_source'):
                    cached_response._classification_source = 'cached'
                return cached_response
        except Exception:
            pass  # Silently continue if cache lookup fails

    # Step 2: Cache MISS - call original RAG function
    # Track cache miss metric
    rag_query_cache_misses_counter.inc()

    # Auto-inject question if not already in kwargs (to support functions that need it)
    if 'question' not in kwargs:
        kwargs['question'] = question
    response = await rag_function(*args, **kwargs)

    # Set cache_hit to False for fresh generation
    if response:
        response.cache_hit = False

    # Step 3: Save answer to cache for future queries (with quality checks)
    if answer_cache and response and response.answer:
        # Quality checks to prevent caching low-quality answers
        num_citations = len(response.citations) if response.citations else 0
        num_chunks = response.num_chunks_retrieved
        confidence = response.confidence

        # Define quality thresholds
        MIN_CITATIONS = 1
        MIN_CHUNKS = 1

        # Check if answer meets quality criteria
        quality_ok = (
            num_citations >= MIN_CITATIONS and
            num_chunks >= MIN_CHUNKS
        )

        if quality_ok:
            try:
                await answer_cache.cache_answer(question, response)
                logger.info("Answer cached successfully", query=question[:50],
                           citations=num_citations, chunks=num_chunks, confidence=confidence)
            except Exception:
                pass  # Silently continue if cache save fails
        else:
            logger.warning(
                "Answer NOT cached due to low quality",
                query=question[:50], citations=num_citations, chunks=num_chunks,
                min_required=f"citations>={MIN_CITATIONS}, chunks>={MIN_CHUNKS}"
            )

    return response

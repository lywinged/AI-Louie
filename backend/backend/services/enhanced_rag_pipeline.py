"""
Enhanced RAG Pipeline with hybrid search, caching, and classification

This module extends the base rag_pipeline with advanced features while maintaining backward compatibility.
"""
import os
import time
from typing import Dict, Any, Optional, List, Tuple
import structlog

from backend.config.settings import settings
from backend.models.rag_schemas import RAGResponse
from backend.services.rag_pipeline import (
    answer_question as base_answer_question,
    retrieve_chunks,
    _generate_answer_with_llm,
    RetrievedChunk,
)
from backend.services.hybrid_retriever import HybridRetriever
from backend.services.query_cache import QueryStrategyCache, get_query_cache, initialize_query_cache
from backend.services.query_classifier import QueryClassifier, get_query_classifier
from backend.services.qdrant_client import get_qdrant_client
from backend.services.answer_cache import MultiLayerAnswerCache, initialize_answer_cache
from backend.services.file_level_fallback import (
    FileLevelFallbackRetriever,
    get_file_level_retriever,
)

logger = structlog.get_logger(__name__)

# Global instances
_hybrid_retriever: Optional[HybridRetriever] = None
_query_cache: Optional[QueryStrategyCache] = None
_query_classifier: Optional[QueryClassifier] = None
_answer_cache: Optional[MultiLayerAnswerCache] = None
_file_level_retriever: Optional[FileLevelFallbackRetriever] = None


def _get_hybrid_retriever() -> Optional[HybridRetriever]:
    """Get or create hybrid retriever instance"""
    global _hybrid_retriever

    # Check if hybrid search is enabled
    if not os.getenv("ENABLE_HYBRID_SEARCH", "true").lower() == "true":
        return None

    if _hybrid_retriever is None:
        try:
            qdrant_client = get_qdrant_client()
            collection_name = settings.QDRANT_COLLECTION
            alpha = float(os.getenv("HYBRID_ALPHA", "0.7"))

            _hybrid_retriever = HybridRetriever(
                qdrant_client=qdrant_client,
                collection_name=collection_name,
                alpha=alpha
            )

            logger.info("Hybrid retriever initialized", alpha=alpha)
        except Exception as e:
            logger.error("Failed to initialize hybrid retriever", error=str(e))
            return None

    return _hybrid_retriever


async def _ensure_hybrid_retriever_ready():
    """Ensure hybrid retriever is initialized"""
    retriever = _get_hybrid_retriever()
    if retriever and not retriever._initialized:
        await retriever.initialize()


def _get_query_cache() -> Optional[QueryStrategyCache]:
    """Get or create query cache instance"""
    global _query_cache

    if not os.getenv("ENABLE_QUERY_CACHE", "true").lower() == "true":
        return None

    if _query_cache is None:
        try:
            threshold = float(os.getenv("QUERY_CACHE_SIMILARITY_THRESHOLD", "0.85"))
            max_size = int(os.getenv("QUERY_CACHE_MAX_SIZE", "1000"))
            ttl_hours = int(os.getenv("QUERY_CACHE_TTL_HOURS", "24"))

            _query_cache = initialize_query_cache(
                similarity_threshold=threshold,
                max_cache_size=max_size,
                ttl_hours=ttl_hours
            )

            # Set embedder (use the same embedding function as RAG)
            from backend.services.rag_pipeline import _embed_texts
            async def embed_single(text: str) -> List[float]:
                return (await _embed_texts([text]))[0]

            _query_cache.set_embedder(embed_single)

            logger.info("Query cache initialized", max_size=max_size, threshold=threshold)
        except Exception as e:
            logger.error("Failed to initialize query cache", error=str(e))
            return None

    return _query_cache


def _get_query_classifier() -> Optional[QueryClassifier]:
    """Get or create query classifier instance"""
    global _query_classifier

    if not os.getenv("ENABLE_QUERY_CLASSIFICATION", "true").lower() == "true":
        return None

    if _query_classifier is None:
        _query_classifier = get_query_classifier()
        logger.info("Query classifier initialized")

    return _query_classifier


def _get_answer_cache() -> Optional[MultiLayerAnswerCache]:
    """Get or create answer cache instance"""
    global _answer_cache

    if not os.getenv("ENABLE_ANSWER_CACHE", "false").lower() == "true":
        return None

    if _answer_cache is None:
        try:
            threshold = float(os.getenv("ANSWER_CACHE_SIMILARITY_THRESHOLD", "0.88"))
            tfidf_threshold = float(os.getenv("ANSWER_CACHE_TFIDF_THRESHOLD", "0.30"))
            max_size = int(os.getenv("ANSWER_CACHE_MAX_SIZE", "1000"))
            ttl_hours = int(os.getenv("ANSWER_CACHE_TTL_HOURS", "72"))

            _answer_cache = initialize_answer_cache(
                similarity_threshold=threshold,
                tfidf_threshold=tfidf_threshold,
                max_cache_size=max_size,
                ttl_hours=ttl_hours
            )

            # Inject existing MiniLM embedding function (reuse current model)
            from backend.services.rag_pipeline import _embed_texts

            async def embed_single(text: str) -> List[float]:
                """Wrapper to convert batch embedding to single"""
                return (await _embed_texts([text]))[0]

            _answer_cache.set_embedder(embed_single)

            logger.info(
                "Answer cache initialized with MiniLM-L6",
                semantic_threshold=threshold,
                tfidf_threshold=tfidf_threshold,
                max_size=max_size,
                ttl_hours=ttl_hours
            )
        except Exception as e:
            logger.error("Failed to initialize answer cache", error=str(e))
            return None

    return _answer_cache


def _get_file_level_retriever() -> Optional[FileLevelFallbackRetriever]:
    """Get or create file-level fallback retriever instance"""
    global _file_level_retriever

    # Check if file-level fallback is enabled
    if not os.getenv("ENABLE_FILE_LEVEL_FALLBACK", "false").lower() == "true":
        return None

    if _file_level_retriever is None:
        try:
            threshold = float(os.getenv("CONFIDENCE_FALLBACK_THRESHOLD", "0.65"))
            _file_level_retriever = get_file_level_retriever(confidence_threshold=threshold)
            logger.info("File-level fallback retriever initialized", threshold=threshold)
        except Exception as e:
            logger.error("Failed to initialize file-level fallback retriever", error=str(e))
            return None

    return _file_level_retriever


async def answer_question_hybrid(
    question: str,
    *,
    top_k: int = 5,
    use_llm: bool = True,
    include_timings: bool = True,
    reranker_override: Optional[str] = None,
    vector_limit: Optional[int] = None,
    content_char_limit: Optional[int] = None,
    use_cache: bool = True,
    use_classifier: bool = True,
) -> RAGResponse:
    """
    Enhanced RAG pipeline with hybrid search, caching, and classification.

    This is the main entry point for the enhanced RAG system.

    Args:
        question: User's question
        top_k: Number of chunks to retrieve
        use_llm: Whether to use LLM for answer generation
        include_timings: Include detailed timing breakdown
        reranker_override: Override reranker selection
        vector_limit: Override vector candidate limit
        content_char_limit: Override content character limit
        use_cache: Use query strategy cache if available
        use_classifier: Use query classifier for optimization

    Returns:
        RAGResponse with answer, citations, and metadata
    """
    tic_total = time.perf_counter()

    # Step 0: Check answer cache FIRST (真正省 token!)
    answer_cache = _get_answer_cache()
    if answer_cache and use_cache:
        try:
            cached = await answer_cache.find_cached_answer(question)
            if cached:
                logger.info(
                    "Answer cache HIT - returning cached answer",
                    query=question[:50],
                    layer=cached['cache_layer'],
                    method=cached['cache_method'],
                    similarity=f"{cached['similarity']:.3f}",
                    time_ms=f"{cached['time_ms']:.2f}"
                )
                # 直接返回缓存答案，跳过所有 RAG 流程！
                cached_response = cached['answer']
                # Ensure cache hits show zero token usage/cost
                cached_response.token_usage = None
                cached_response.token_cost_usd = 0.0
                cached_response.cache_hit = True
                cached_response.llm_used = False
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
                return cached_response
        except Exception as e:
            logger.warning("Answer cache lookup failed", error=str(e))

    # Initialize components
    cache = _get_query_cache() if use_cache else None
    classifier = _get_query_classifier() if use_classifier else None
    hybrid_retriever = _get_hybrid_retriever()
    file_level_retriever = _get_file_level_retriever()

    # Ensure hybrid retriever is ready
    if hybrid_retriever:
        await _ensure_hybrid_retriever_ready()

    # Step 1: Check strategy cache for similar query
    cached_strategy = None
    if cache:
        try:
            cached_strategy = await cache.find_similar_query(question)
            if cached_strategy:
                logger.info(
                    "Using cached strategy",
                    query=question[:50],
                    confidence=cached_strategy['confidence']
                )
                # Apply cached strategy
                if vector_limit is None:
                    vector_limit = cached_strategy['strategy'].get('vector_limit')
                if reranker_override is None:
                    reranker_override = cached_strategy['strategy'].get('reranker_mode')
                if top_k == 5:  # Only override if using default
                    top_k = cached_strategy['strategy'].get('top_k', top_k)
        except Exception as e:
            logger.warning("Cache lookup failed", error=str(e))

    # Step 2: Apply query classification if no cached strategy
    if cached_strategy is None and classifier:
        try:
            strategy = await classifier.get_strategy(question, use_llm=False, use_cache=False)
            logger.info(
                "Applying classified strategy",
                query=question[:50],
                type=strategy.get('query_type')
            )

            # Apply strategy parameters
            if vector_limit is None:
                vector_limit = strategy.get('vector_limit')
            if reranker_override is None:
                reranker_override = strategy.get('reranker_mode')
            if top_k == 5:  # Only override if using default
                top_k = strategy.get('top_k', top_k)

            # Check if hybrid search should use different alpha for this query type
            if hybrid_retriever and 'hybrid_alpha' in strategy:
                hybrid_retriever.update_alpha(strategy['hybrid_alpha'])
        except Exception as e:
            logger.warning("Query classification failed", error=str(e))

    # Step 3: Perform retrieval (with file-level fallback or hybrid search)
    fallback_triggered = False
    fallback_latency_ms = None

    if file_level_retriever:
        # Use file-level fallback retrieval (MiniLM -> BGE on low confidence)
        try:
            logger.info("Using file-level fallback retrieval", query=question[:50])

            fallback_start = time.perf_counter()
            file_level_results = await file_level_retriever.retrieve(
                query=question,
                top_k=top_k,
                minilm_top_k=vector_limit or 20
            )
            retrieval_ms = (time.perf_counter() - fallback_start) * 1000

            # Check if fallback was triggered
            if file_level_results and file_level_results[0].fallback_triggered:
                fallback_triggered = True
                fallback_latency_ms = file_level_results[0].fallback_latency_ms
                logger.info(
                    "File-level BGE fallback triggered",
                    query=question[:50],
                    fallback_latency_ms=fallback_latency_ms
                )

            # Convert to RetrievedChunk format
            chunks = []
            for result in file_level_results:
                chunks.append(
                    RetrievedChunk(
                        content=result.chunk_text,
                        source=result.file_path,
                        score=result.score,
                        metadata=result.metadata
                    )
                )

            timings = {
                "retrieval_ms": retrieval_ms,
                "file_level_fallback": "enabled",
                "fallback_triggered": fallback_triggered,
                "fallback_latency_ms": fallback_latency_ms,
                "confidence_threshold": file_level_retriever.confidence_threshold,
            }

            logger.info(
                "File-level fallback retrieval completed",
                query=question[:50],
                num_results=len(chunks),
                retrieval_ms=retrieval_ms,
                fallback_triggered=fallback_triggered
            )

        except Exception as e:
            logger.error("File-level fallback failed, trying hybrid/standard retrieval", error=str(e))
            file_level_retriever = None  # Disable and try next option

    if not file_level_retriever and hybrid_retriever:
        # Use hybrid retrieval
        try:
            # Get query embedding first
            from backend.services.rag_pipeline import _embed_texts
            query_embedding = (await _embed_texts([question]))[0]

            # Hybrid search
            hybrid_start = time.perf_counter()
            hybrid_results = await hybrid_retriever.hybrid_search(
                query=question,
                query_embedding=query_embedding,
                top_k=vector_limit or 20
            )
            hybrid_ms = (time.perf_counter() - hybrid_start) * 1000

            # Convert hybrid results to RetrievedChunk format
            from backend.services.rag_pipeline import _rerank
            chunks_for_rerank = []
            for result in hybrid_results:
                payload = result.get('payload', {})
                chunks_for_rerank.append(
                    RetrievedChunk(
                        content=payload.get('content', payload.get('text', '')),
                        source=payload.get('source', payload.get('title', 'Unknown')),
                        score=result['score'],
                        metadata=payload.get('metadata', {})
                    )
                )

            # Rerank the hybrid results
            rerank_start = time.perf_counter()
            reranked_chunks, rerank_ms, reranker_model, reranker_mode = await _rerank(
                question=question,
                chunks=chunks_for_rerank,
                override_choice=reranker_override
            )
            rerank_total_ms = (time.perf_counter() - rerank_start) * 1000

            # Take top_k after reranking
            chunks = reranked_chunks[:top_k]

            retrieval_ms = hybrid_ms + rerank_total_ms

            timings = {
                "hybrid_search_ms": hybrid_ms,
                "rerank_ms": rerank_ms,
                "total_retrieval_ms": retrieval_ms,
                "reranker_model": reranker_model,
                "reranker_mode": reranker_mode,
                "vector_limit_used": vector_limit,
                "hybrid_fusion": "enabled",
                "bm25_weight": 1 - hybrid_retriever.alpha,
                "vector_weight": hybrid_retriever.alpha
            }

            logger.info(
                "Hybrid retrieval completed",
                query=question[:50],
                num_results=len(chunks),
                retrieval_ms=retrieval_ms
            )

        except Exception as e:
            logger.error("Hybrid search failed, falling back to standard retrieval", error=str(e))
            # Fallback to standard retrieval
            return await base_answer_question(
                question=question,
                top_k=top_k,
                use_llm=use_llm,
                include_timings=include_timings,
                reranker_override=reranker_override,
                vector_limit=vector_limit,
                content_char_limit=content_char_limit
            )
    else:
        # Use standard retrieval
        return await base_answer_question(
            question=question,
            top_k=top_k,
            use_llm=use_llm,
            include_timings=include_timings,
            reranker_override=reranker_override,
            vector_limit=vector_limit,
            content_char_limit=content_char_limit
        )

    # Step 4: Generate answer with LLM
    if not chunks:
        from backend.config.knowledge_config.inference_config import inference_config
        return RAGResponse(
            answer="I could not find relevant information in the knowledge base.",
            citations=[],
            retrieval_time_ms=retrieval_ms,
            confidence=0.0,
            num_chunks_retrieved=0,
            llm_time_ms=0.0,
            total_time_ms=(time.perf_counter() - tic_total) * 1000,
            timings=timings if include_timings else None,
            models={
                "embedding": settings.ONNX_EMBED_MODEL_PATH or "remote-embed",
                "reranker": settings.ONNX_RERANK_MODEL_PATH or "remote-rerank",
                "llm": settings.OPENAI_MODEL if use_llm else "disabled",
            },
            token_usage=None,
            token_cost_usd=0.0,
            llm_used=False
        )

    llm_model = os.getenv("OPENAI_MODEL") or settings.OPENAI_MODEL or "gpt-4o-mini"
    token_usage = None
    token_cost_usd = 0.0
    llm_used = use_llm

    if use_llm:
        # Limit to top 30 chunks for LLM
        llm_chunks = chunks[:30]
        tic_llm = time.perf_counter()
        answer, token_usage, token_cost_usd = await _generate_answer_with_llm(
            question,
            llm_chunks,
            model=llm_model,
        )
        llm_time_ms = (time.perf_counter() - tic_llm) * 1000
        llm_used = token_usage is not None
    else:
        answer_parts = [chunk.content for chunk in chunks[: min(5, len(chunks))]]
        answer = " ".join(answer_parts)
        llm_time_ms = 0.0
        llm_used = False

    # Step 5: Cache successful strategy
    if cache and llm_used and token_usage:
        try:
            # Calculate success score (confidence based on top chunk score)
            success_score = max(chunk.score for chunk in chunks) if chunks else 0.0

            await cache.cache_strategy(
                query=question,
                strategy={
                    'vector_limit': vector_limit or 20,
                    'top_k': top_k,
                    'reranker_mode': reranker_override or 'auto',
                },
                success_score=success_score,
                metadata={
                    'token_usage': token_usage,
                    'cost_usd': token_cost_usd
                }
            )
        except Exception as e:
            logger.warning("Failed to cache strategy", error=str(e))

    # Build response
    from backend.models.rag_schemas import Citation

    citations = [
        Citation(
            source=chunk.source,
            content=chunk.content,
            score=chunk.score,
            metadata=chunk.metadata,
        )
        for chunk in chunks
    ]

    top_confidence = max(chunk.score for chunk in chunks)
    total_time_ms = (time.perf_counter() - tic_total) * 1000

    if include_timings:
        timings.update({
            "llm_ms": llm_time_ms,
            "end_to_end_ms": total_time_ms,
        })
    else:
        timings = None

    response = RAGResponse(
        answer=answer,
        citations=citations,
        retrieval_time_ms=retrieval_ms,
        confidence=top_confidence,
        num_chunks_retrieved=len(chunks),
        llm_time_ms=llm_time_ms,
        total_time_ms=total_time_ms,
        timings=timings,
        models={
            "embedding": settings.ONNX_EMBED_MODEL_PATH or "remote-embed",
            "reranker": settings.ONNX_RERANK_MODEL_PATH or "remote-rerank",
            "llm": llm_model if llm_used else "disabled",
        },
        token_usage=token_usage,
        token_cost_usd=token_cost_usd,
        llm_used=llm_used
    )

    # Step 6: Cache the answer for future queries (with quality checks)
    if answer_cache and use_cache and llm_used:
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
                await answer_cache.cache_answer(
                    query=question,
                    rag_response=response,
                    metadata={
                        'retrieval_ms': retrieval_ms,
                        'llm_ms': llm_time_ms,
                        'num_chunks': len(chunks),
                        'top_confidence': top_confidence
                    }
                )
                logger.info(
                    "Answer cached successfully",
                    query=question[:50],
                    cache_size=len(answer_cache.exact_cache),
                    citations=num_citations, chunks=num_chunks, confidence=confidence
                )
            except Exception as e:
                logger.warning("Failed to cache answer", error=str(e))
        else:
            logger.warning(
                "Answer NOT cached due to low quality",
                query=question[:50], citations=num_citations, chunks=num_chunks,
                confidence=confidence
            )

    return response

"""
Real-time Smart RAG with SSE streaming support using asyncio Queue.

This module provides truly real-time progress updates for Smart RAG execution
by using asyncio.Queue to push progress events as they happen, rather than
collecting them and emitting after completion.
"""

import asyncio
import json
import logging
import os
from typing import Callable, Dict, Any, Optional

logger = logging.getLogger(__name__)


async def execute_smart_rag_with_realtime_progress(
    request,
    emit_progress: Callable,
    _bandit_enabled: Callable,
    _choose_bandit_arm: Callable,
    get_qdrant_client: Callable,
    answer_question_hybrid: Callable,
    COLLECTION_NAME: str,
):
    """
    Execute Smart RAG with real-time progress emission via callback.

    Args:
        request: RAGRequest object
        emit_progress: Async function to emit progress events
        _bandit_enabled: Function to check if bandit is enabled
        _choose_bandit_arm: Function to choose bandit arm
        get_qdrant_client: Function to get Qdrant client
        answer_question_hybrid: Function for hybrid RAG
        COLLECTION_NAME: Qdrant collection name

    Returns:
        Dict with answer and metadata
    """
    from backend.services.query_classifier import get_query_classifier
    from backend.services.graph_rag_incremental import IncrementalGraphRAG
    from backend.services.table_rag import TableRAG
    from backend.services.rag_pipeline import _get_openai_client
    from backend.models.rag_schemas import RAGResponse

    # Step 1: Classify query
    await emit_progress("🔍 Classifying query...", {})

    classifier = get_query_classifier()
    strategy = await classifier.get_strategy(request.question, use_llm=True, use_cache=True)
    query_type = strategy.get('query_type', 'general')

    # Step 2: Determine strategy
    use_graph_rag = strategy.get('use_graph_rag', False)
    q_lower = request.question.lower()
    graph_cues = [
        "relationship", "relationships", "relation", "relations",
        "role", "roles", "character", "characters", "family tree",
        "connection", "connections",
        "关系", "人物关系", "角色关系", "角色", "关系网", "图谱"
    ]
    if not use_graph_rag and any(cue in q_lower for cue in graph_cues):
        use_graph_rag = True
    use_table_rag = strategy.get('use_table_rag', False)

    cue_hits = [c for c in graph_cues if c in q_lower]
    table_cues = ["table", "数据", "统计", "列", "行", "表格"]
    table_cue_hits = [c for c in table_cues if c in q_lower]

    force_graph = (len(cue_hits) >= 2) or (use_graph_rag and len(cue_hits) >= 1 and not use_table_rag)
    force_table = (len(table_cue_hits) >= 1) and use_table_rag

    if force_table:
        chosen_arm = "table"
    elif force_graph:
        chosen_arm = "graph"
    elif _bandit_enabled():
        if query_type == 'factual_detail':
            available_arms = ["hybrid"]
        elif query_type == 'complex_analysis':
            available_arms = ["hybrid", "iterative"]
        else:
            available_arms = ["hybrid", "iterative", "graph", "table"]
        chosen_arm = _choose_bandit_arm(available_arms)
    else:
        if use_table_rag:
            chosen_arm = "table"
        elif use_graph_rag:
            chosen_arm = "graph"
        else:
            simple_types = ['author_query', 'factual_detail', 'quote_search']
            chosen_arm = "hybrid" if query_type in simple_types else "iterative"

    # Safety net escalation
    if cue_hits and chosen_arm in ["hybrid", "iterative"] and not table_cue_hits and query_type != 'factual_detail':
        chosen_arm = "graph"
    elif table_cue_hits and chosen_arm in ["hybrid", "iterative"] and query_type != 'factual_detail':
        chosen_arm = "table"

    await emit_progress(f"🎯 Strategy selected: {chosen_arm.upper()}",
                      {"strategy": chosen_arm, "query_type": query_type})

    # Step 3: Execute with real-time progress
    if chosen_arm == "graph":
        await emit_progress("🔎 Executing Graph RAG...", {"strategy": "graph"})

        openai_client = _get_openai_client()
        qdrant_client = get_qdrant_client()

        graph_rag = IncrementalGraphRAG(
            openai_client=openai_client,
            qdrant_client=qdrant_client,
            collection_name=COLLECTION_NAME,
            extraction_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            generation_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            max_jit_chunks=int(os.getenv("GRAPH_MAX_JIT_CHUNKS", "50"))
        )

        # Real-time progress callback using queue
        def sync_progress_callback(step, msg, meta):
            """Synchronous callback that pushes to async queue"""
            # Create a task to emit progress
            asyncio.create_task(emit_progress(f"  {msg}", {"step": step, **meta}))

        graph_result = await graph_rag.answer_question(
            question=request.question,
            top_k=request.top_k or 20,
            max_hops=2,
            enable_vector_retrieval=True,
            progress_callback=sync_progress_callback
        )

        return {
            "answer": graph_result['answer'],
            "token_usage": graph_result.get('token_usage'),
            "token_cost_usd": graph_result.get('token_cost_usd'),
            "timings": graph_result.get('timings'),
            "strategy": "graph"
        }

    elif chosen_arm == "table":
        await emit_progress("📊 Executing Table RAG...", {"strategy": "table"})

        openai_client = _get_openai_client()
        qdrant_client = get_qdrant_client()

        table_rag = TableRAG(
            openai_client=openai_client,
            qdrant_client=qdrant_client,
            collection_name=COLLECTION_NAME,
            extraction_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            generation_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        )

        table_result = await table_rag.answer_question(
            question=request.question,
            top_k=request.top_k or 20,
            hybrid_alpha=strategy.get('hybrid_alpha', 0.6)
        )

        return {
            "answer": table_result['answer'],
            "token_usage": table_result.get('token_usage'),
            "token_cost_usd": table_result.get('token_cost_usd'),
            "timings": table_result.get('timings'),
            "strategy": "table"
        }

    else:
        await emit_progress(f"⚡ Executing {chosen_arm.upper()} RAG...", {"strategy": chosen_arm})

        if chosen_arm == "hybrid":
            response = await answer_question_hybrid(
                question=request.question,
                top_k=request.top_k or 5,
                use_llm=True,
                include_timings=request.include_timings
            )
        else:  # iterative
            from backend.services.self_rag import get_self_rag
            self_rag = get_self_rag()

            # Real-time progress callback for iterative RAG
            def sync_progress_callback(step, msg, meta):
                """Synchronous callback that pushes to async queue"""
                # Create a task to emit progress
                asyncio.create_task(emit_progress(f"  {msg}", {"step": step, **meta}))

            # ask_with_reflection returns a RAGResponse object directly
            response = await self_rag.ask_with_reflection(
                question=request.question,
                top_k=request.top_k or strategy.get('top_k', 10),
                use_hybrid=True,
                include_timings=True,
                progress_callback=sync_progress_callback
            )

        return {
            "answer": response.answer,
            "token_usage": response.token_usage,
            "token_cost_usd": response.token_cost_usd,
            "timings": response.timings,
            "strategy": chosen_arm
        }

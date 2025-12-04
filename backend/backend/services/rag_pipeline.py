"""
RAG ingestion and retrieval pipeline backed by Qdrant.
"""
import asyncio
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Tuple, Union, Optional
from pathlib import Path

from fastapi.concurrency import run_in_threadpool
from openai import AsyncOpenAI
from qdrant_client.http import models as qdrant_models

from backend.config.settings import settings, OPENAI_CONFIG
from backend.models.rag_schemas import Citation, DocumentResponse, RAGResponse
from backend.services.metadata_index import search_by_title
from backend.config.knowledge_config.inference_config import inference_config
from backend.services.inference_client import get_embedding_client, get_rerank_client
from backend.services.onnx_inference import (
    get_embedding_model,
    get_reranker_model,
    reranker_is_cpu_only,
    switch_to_fallback_reranker,
    set_reranker_model_path,
    set_embedding_model_path,
    get_current_reranker_path,
    get_current_embed_path,
    _has_cuda_available,
)
from backend.services.query_classifier import get_query_classifier, QueryDifficulty
from backend.services.qdrant_client import ensure_collection, get_qdrant_client
from backend.services.token_counter import get_token_counter, TokenUsage
from backend.utils.text_splitter import split_text
from backend.utils.openai import sanitize_messages
from backend.services.metrics import (
    llm_request_counter,
    llm_token_usage_counter,
    llm_cost_counter,
    llm_request_duration_histogram,
    rag_request_counter,
    rag_request_duration_histogram,
    embedding_duration_histogram,
    rerank_duration_histogram,
    rerank_score_distribution_histogram,
)


COLLECTION_NAME = settings.QDRANT_COLLECTION

# Initialize OpenAI client for answer generation
_openai_client = None
logger = logging.getLogger(__name__)
_reranker_switch_locked = False
_AUTHOR_QUESTION_PATTERN = re.compile(
    r"\bwho\s+(?:wrote|is\s+the\s+author\s+of|authored)\b",
    flags=re.IGNORECASE,
)
_EXCEL_TOOL_KEYWORDS = [
    "反向用电",
    "抄表",
    "发电",
    "kwh",
    "电量",
    "电表",
    "excel",
    "xlsx",
]

VECTOR_LIMIT_MIN = 5
VECTOR_LIMIT_MAX = 20
CONTENT_CHAR_MIN = 150
CONTENT_CHAR_MAX = 1000
DEFAULT_CONTENT_CHAR_LIMIT = 300

_token_counter = get_token_counter()


def _select_adaptive_models(question: str) -> Dict[str, Any]:
    """
    Adaptively select embedding and reranker models based on query difficulty.

    Strategy:
    - SIMPLE: Use fast MiniLM (simple factual queries)
    - MODERATE: Use BGE if available, otherwise MiniLM
    - COMPLEX: Always use BGE (relationships, comparisons, deep reasoning)

    Args:
        question: User's question

    Returns:
        Dict with model selection info (difficulty, embedding_path, reranker_path, reason)
    """
    # Skip if remote inference enabled
    if inference_config.ENABLE_REMOTE_INFERENCE:
        return {
            'difficulty': 'remote',
            'embedding_path': 'remote_service',
            'reranker_path': 'remote_service',
            'reason': 'Remote inference enabled - using remote service'
        }

    # Classify query difficulty
    classifier = get_query_classifier()
    difficulty, difficulty_reason = classifier.classify_query(question)

    # Check if BGE models are available
    bge_embed_path = settings.ONNX_EMBED_MODEL_PATH  # BGE is primary model
    bge_rerank_path = settings.ONNX_RERANK_MODEL_PATH  # BGE is primary model
    minilm_embed_path = settings.EMBED_FALLBACK_MODEL_PATH  # MiniLM is fallback
    minilm_rerank_path = settings.RERANK_FALLBACK_MODEL_PATH  # MiniLM is fallback

    bge_available = bool(bge_embed_path and bge_rerank_path)

    # Get recommended models
    recommended = classifier.get_recommended_models(difficulty, bge_available)

    # Extract paths
    embedding_path = recommended['embedding']
    reranker_path = recommended['reranker']
    selection_reason = recommended['reason']

    # Switch models if needed
    current_embed = get_current_embed_path()
    current_rerank = get_current_reranker_path()

    if current_embed != embedding_path:
        logger.info(
            f"Switching embedding model",
            from_model=current_embed,
            to_model=embedding_path,
            difficulty=difficulty,
            reason=selection_reason
        )
        set_embedding_model_path(embedding_path)

    if current_rerank != reranker_path:
        logger.info(
            f"Switching reranker model",
            from_model=current_rerank,
            to_model=reranker_path,
            difficulty=difficulty,
            reason=selection_reason
        )
        set_reranker_model_path(reranker_path)

    return {
        'difficulty': difficulty,
        'difficulty_reason': difficulty_reason,
        'embedding_path': embedding_path,
        'reranker_path': reranker_path,
        'selection_reason': selection_reason
    }


def _get_openai_client() -> AsyncOpenAI:
    """Get or create OpenAI client singleton."""
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY") or settings.OPENAI_API_KEY or OPENAI_CONFIG.get("api_key")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for LLM answer generation")

        # Support both OPENAI_BASE_URL and OPENAI_BASE_URL
        base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_BASE_URL") or OPENAI_CONFIG.get("base_url")
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        _openai_client = AsyncOpenAI(**client_kwargs)

    return _openai_client


@dataclass
class RetrievedChunk:
    content: str
    source: str
    score: float
    metadata: Dict[str, Any]


async def _embed_texts(texts: List[str]) -> List[List[float]]:
    """Generate embeddings using ONNX runtime in a worker thread."""
    if inference_config.ENABLE_REMOTE_INFERENCE:
        client = get_embedding_client()
        return await client.embed(texts, normalize=True)

    def _encode() -> List[List[float]]:
        model = get_embedding_model()
        vectors = model.encode(texts)
        return vectors.astype("float32").tolist()

    return await run_in_threadpool(_encode)


def _get_vector_size() -> int:
    """Return the expected embedding vector size for the active pipeline."""
    if inference_config.ENABLE_REMOTE_INFERENCE:
        return settings.RAG_VECTOR_SIZE

    from backend.services.onnx_inference import get_embedding_model

    return get_embedding_model().vector_size


def _should_use_excel_tool(question: str, chunks: List["RetrievedChunk"]) -> bool:
    """Heuristic: decide if we should analyze Excel uploads with a tool."""
    lowered = question.lower()
    if not any(k in lowered for k in _EXCEL_TOOL_KEYWORDS):
        return False
    for chunk in chunks:
        meta = chunk.metadata or {}
        doc_type = meta.get("doc_type") or ""
        file_path = meta.get("file_path") or ""
        if str(doc_type).lower() == "excel":
            return True
        if isinstance(file_path, str) and file_path.lower().endswith((".xlsx", ".xls")):
            return True
    return False


def _analyze_excel_file(file_path: str, uploaded_file: str) -> Optional[Dict[str, Any]]:
    """Parse Excel and compute reverse energy totals (heuristic)."""
    try:
        import pandas as pd
    except Exception as exc:  # pragma: no cover - runtime import
        logger.warning("pandas not available for excel analysis: %s", exc)
        return None

    path = Path(file_path)
    if not path.exists():
        logger.warning("Excel file not found for analysis: %s", file_path)
        return None
    try:
        df = pd.read_excel(path)
    except Exception as exc:
        logger.warning("Failed to read excel %s: %s", file_path, exc)
        return None

    reverse_idx = None
    for idx, row in df.iterrows():
        if row.astype(str).str.contains("反向用电", na=False).any():
            reverse_idx = idx
            break
    if reverse_idx is None:
        return None

    slice_df = df.iloc[reverse_idx: reverse_idx + 5]
    col_start = None
    col_end = None
    for c in df.columns:
        if "Unnamed: 4" in str(c):
            col_start = c
        if "Unnamed: 5" in str(c):
            col_end = c
    if col_start is None and len(df.columns) > 4:
        col_start = df.columns[4]
    if col_end is None and len(df.columns) > 5:
        col_end = df.columns[5]
    if col_start is None or col_end is None:
        return None

    labels_col = None
    for c in df.columns:
        if "Unnamed: 3" in str(c):
            labels_col = c
            break
    if labels_col is None and len(df.columns) > 3:
        labels_col = df.columns[3]

    def _to_num(val):
        try:
            return float(val)
        except Exception:
            return None

    rows = []
    total = 0.0
    for _, row in slice_df.iterrows():
        label = str(row.get(labels_col, "")).strip() if labels_col else ""
        start = _to_num(row.get(col_start))
        end = _to_num(row.get(col_end))
        if start is None or end is None:
            continue
        delta = end - start
        total += delta
        rows.append({"label": label or "unknown", "start": start, "end": end, "delta": delta})

    return {
        "uploaded_file": uploaded_file,
        "file_path": str(path),
        "reverse_energy_kwh": total,
        "rows": rows,
        "method": "row with 反向用电 + 4 rows, delta=end-start",
    }


def _should_switch_reranker(latency_ms: float) -> bool:
    """Determine whether to switch to the fallback reranker."""
    if inference_config.ENABLE_REMOTE_INFERENCE:
        return False
    global _reranker_switch_locked
    if _reranker_switch_locked:
        return False
    if not settings.RERANK_FALLBACK_MODEL_PATH:
        _reranker_switch_locked = True
        return False
    if not reranker_is_cpu_only():
        _reranker_switch_locked = True
        return False
    return latency_ms >= settings.RERANK_CPU_SWITCH_THRESHOLD_MS


def _apply_reranker_override(choice: Optional[str]) -> str:
    """Apply manual reranker override if requested."""
    global _reranker_switch_locked

    if inference_config.ENABLE_REMOTE_INFERENCE:
        return "remote"

    if not choice:
        choice = "auto"
    choice_normalized = choice.strip().lower()

    def _maybe_switch(target_path: Optional[str]) -> bool:
        if not target_path:
            return False
        current = get_current_reranker_path()
        if current == target_path:
            return True
        try:
            set_reranker_model_path(target_path)
            return True
        except Exception as exc:
            logger.warning("Failed to switch reranker to %s: %s", target_path, exc)
            return False

    if choice_normalized in ("auto", ""):
        _reranker_switch_locked = False
        _maybe_switch(settings.ONNX_RERANK_MODEL_PATH)
        return "auto"

    if choice_normalized == "primary":
        if _maybe_switch(settings.ONNX_RERANK_MODEL_PATH):
            _reranker_switch_locked = True
            return "primary"
        return "auto"

    if choice_normalized == "fallback":
        if _maybe_switch(settings.RERANK_FALLBACK_MODEL_PATH):
            _reranker_switch_locked = True
            return "fallback"
        logger.warning("Fallback reranker requested but not configured.")
        return "auto"

    resolved = choice.strip()
    if resolved:
        if _maybe_switch(resolved):
            _reranker_switch_locked = True
            return "custom"
    return "auto"


async def _rerank(
    question: str,
    chunks: List[RetrievedChunk],
    override_choice: Optional[str] = None,
) -> Tuple[List[RetrievedChunk], float, str, str]:
    """Apply ONNX reranker to refine relevance ordering."""
    if not chunks:
        mode = "remote" if inference_config.ENABLE_REMOTE_INFERENCE else "auto"
        return [], 0.0, "", mode

    global _reranker_switch_locked

    # Use document content for reranking
    # Keep it simple - let the reranker work with natural content
    # The LLM will receive metadata separately in the answer generation phase
    docs = [chunk.content for chunk in chunks]

    if inference_config.ENABLE_REMOTE_INFERENCE:
        client = get_rerank_client()
        start = time.perf_counter()
        scores = await client.rerank(question, docs, top_k=len(docs))
        duration_ms = (time.perf_counter() - start) * 1000
        model_name = "remote"
        reranker_mode = "remote"
    else:
        reranker_mode = _apply_reranker_override(override_choice)

        def _score(model) -> List[float]:
            scores_local = model.score(question, docs)
            return scores_local.tolist()

        model = get_reranker_model()
        start = time.perf_counter()
        scores = await run_in_threadpool(lambda: _score(model))
        duration_ms = (time.perf_counter() - start) * 1000
        model_name = getattr(model, "resolved_model_path", getattr(model, "model_path", ""))

        if _should_switch_reranker(duration_ms):
            if switch_to_fallback_reranker():
                _reranker_switch_locked = True
                model = get_reranker_model()
                start = time.perf_counter()
                scores = await run_in_threadpool(lambda: _score(model))
                duration_ms = (time.perf_counter() - start) * 1000
                model_name = getattr(model, "resolved_model_path", getattr(model, "model_path", ""))
                logger.info(
                    "Switched to fallback reranker model '%s' after CPU latency %.1f ms.",
                    model_name or "<unknown>",
                    duration_ms,
                )
            else:
                _reranker_switch_locked = True

    reranked: List[RetrievedChunk] = []
    for chunk, score in zip(chunks, scores):
        reranked.append(
            RetrievedChunk(
                content=chunk.content,
                source=chunk.source,
                score=float(score),
                metadata={**chunk.metadata, "base_score": chunk.score},
            )
        )
        # Record rerank score distribution
        model_label = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        rerank_score_distribution_histogram.labels(model=model_label).observe(float(score))

    reranked.sort(key=lambda item: item.score, reverse=True)
    return reranked, duration_ms, model_name, reranker_mode


async def ingest_document(
    title: str,
    content: str,
    *,
    source: str,
    metadata: Dict[str, Any] | None = None,
    collection_name: str | None = None,
) -> DocumentResponse:
    """Chunk a document, embed and upsert into Qdrant."""
    # Use specified collection or default collection
    target_collection = collection_name or COLLECTION_NAME

    vector_size = _get_vector_size()
    ensure_collection(vector_size, collection=target_collection)
    client = get_qdrant_client()

    document_id = int(time.time() * 1000)
    metadata = metadata or {}

    chunks = split_text(
        content,
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
    )

    tic = time.perf_counter()
    embeddings = await _embed_texts(chunks)
    embed_duration_ms = (time.perf_counter() - tic) * 1000

    points = []
    for idx, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
        point_id = uuid.uuid4().hex
        points.append(
            qdrant_models.PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    "document_id": document_id,
                    "chunk_index": idx,
                    "content": chunk_text,
                    "title": title,
                    "source": source,
                    "metadata": metadata,
                },
            )
        )

    client.upsert(collection_name=target_collection, points=points)

    return DocumentResponse(
        document_id=document_id,
        title=title,
        num_chunks=len(points),
        embedding_time_ms=embed_duration_ms,
        collection=target_collection,
    )


def _is_author_question(question: str) -> bool:
    return bool(_AUTHOR_QUESTION_PATTERN.search(question))


def _extract_title_from_question(question: str) -> str:
    cleaned = _AUTHOR_QUESTION_PATTERN.sub("", question.lower())
    cleaned = cleaned.replace("?", " ").strip()
    return cleaned


async def retrieve_chunks(
    question: str,
    *,
    top_k: int = 5,
    search_limit: int = 10,
    include_timings: bool = False,
    semantic_mode: bool = False,
    reranker_override: Optional[str] = None,
    vector_limit_override: Optional[int] = None,
    content_char_limit: Optional[int] = None,
    collection_name: str | None = None,
) -> Union[
    Tuple[List[RetrievedChunk], float],
    Tuple[List[RetrievedChunk], float, Dict[str, Any]],
]:
    """Retrieve relevant chunks from Qdrant and rerank."""
    # Adaptively select models based on query difficulty
    model_selection = _select_adaptive_models(question)
    logger.info("Adaptive model selection %s", model_selection)

    target_collection = collection_name or COLLECTION_NAME

    vector_size = _get_vector_size()
    ensure_collection(vector_size, collection=target_collection)
    client = get_qdrant_client()

    tic_total = time.perf_counter()
    candidate_limit = max(top_k, search_limit)
    # Use 5 as minimum, allow up to 50 for complex queries
    vector_limit = max(5, min(50, candidate_limit))

    if inference_config.ENABLE_REMOTE_INFERENCE:
        embed_model_path = inference_config.EMBEDDING_SERVICE_URL or "remote"
    else:
        embedding_model = get_embedding_model()
        embed_model_path = getattr(
            embedding_model,
            "resolved_model_path",
            getattr(embedding_model, "configured_path", settings.ONNX_EMBED_MODEL_PATH),
        )

    if inference_config.ENABLE_REMOTE_INFERENCE:
        has_gpu = False
    else:
        has_gpu = _has_cuda_available()

    # CPU optimization: limit candidates to save memory and processing time
    # GPU: can handle more candidates with better performance
    if vector_limit_override is not None:
        vector_limit = max(
            top_k,
            min(
                VECTOR_LIMIT_MAX,
                max(VECTOR_LIMIT_MIN, int(vector_limit_override)),
            ),
        )
    elif not has_gpu and semantic_mode:
        vector_limit = max(top_k, min(9, vector_limit))

    char_limit_applied: Optional[int] = None
    if content_char_limit is not None:
        char_limit_applied = min(
            CONTENT_CHAR_MAX,
            max(CONTENT_CHAR_MIN, int(content_char_limit)),
        )
    elif not has_gpu and semantic_mode:
        char_limit_applied = DEFAULT_CONTENT_CHAR_LIMIT

    embed_start = time.perf_counter()
    query_embedding = (await _embed_texts([question]))[0]
    embed_ms = (time.perf_counter() - embed_start) * 1000
    logger.info(f"⏱️ Embedding Time: {embed_ms:.2f}ms")

    vector_start = time.perf_counter()
    base_results = client.search(
        collection_name=target_collection,
        query_vector=query_embedding,
        limit=vector_limit,
        with_payload=["text", "content", "source", "title", "document_id", "chunk_index", "authors", "subjects"],
        # Fetch authors and subjects for proper metadata display
    )
    vector_ms = (time.perf_counter() - vector_start) * 1000
    logger.info(f"⏱️ Vector Search Time: {vector_ms:.2f}ms (found {len(base_results)} candidates)")
    candidates: dict[str, RetrievedChunk] = {}

    candidate_start = time.perf_counter()
    for point in base_results:
        payload = point.payload or {}
        text_content = (
            payload.get("text")
            or payload.get("content")
            or ""
        )
        content = (
            text_content[:char_limit_applied]
            if char_limit_applied is not None
            else text_content
        )

        retrieved = RetrievedChunk(
            content=content,
            source=payload.get("source") or payload.get("title", "Unknown"),
            score=float(point.score or 0.0),
            metadata={
                "document_id": payload.get("document_id"),
                "chunk_index": payload.get("chunk_index"),
                "title": payload.get("title"),
                "point_id": str(point.id),
                "retrieval_source": "vector",
                "authors": payload.get("authors"),
                "subjects": payload.get("subjects"),
            },
        )
        candidates[retrieved.metadata.get("point_id") or uuid.uuid4().hex] = retrieved

    # Disabled author question optimization - it adds 300ms latency
    # if _is_author_question(question):
    #     title_query = _extract_title_from_question(question)
    #     metadata_entries = search_by_title(
    #         title_query,
    #         limit=settings.METADATA_TITLE_MATCH_LIMIT,
    #     )
    #     for entry in metadata_entries:
    #         key = entry.point_id
    #         if key in candidates:
    #             continue
    #         candidates[key] = RetrievedChunk(
    #             content=entry.content,
    #             source=entry.source or entry.title or "Unknown",
    #             score=1.0,
    #             metadata={
    #                 "title": entry.title,
    #                 "authors": entry.authors,
    #                 "retrieval_source": "metadata",
    #                 "point_id": entry.point_id,
    #             },
    #         )

    candidate_list = list(candidates.values())[:candidate_limit]
    candidate_prep_ms = (time.perf_counter() - candidate_start) * 1000
    logger.info(f"⏱️ Candidate Preparation Time: {candidate_prep_ms:.2f}ms (prepared {len(candidate_list)} candidates)")

    pre_rerank_ms = (time.perf_counter() - tic_total) * 1000

    rerank_start = time.perf_counter()
    reranked, rerank_ms, reranker_model_path, reranker_mode = await _rerank(
        question,
        candidate_list,
        override_choice=reranker_override,
    )
    logger.info(f"⏱️ Reranking Time: {rerank_ms:.2f}ms (mode: {reranker_mode})")

    # Filter out low-score results
    filter_start = time.perf_counter()
    score_threshold = settings.RERANK_SCORE_THRESHOLD
    filtered_results = [
        chunk for chunk in reranked
        if chunk.score >= score_threshold
    ]
    filter_ms = (time.perf_counter() - filter_start) * 1000

    # Log if we filtered out results
    if len(filtered_results) < len(reranked):
        logger.info(
            f"⏱️ Filtering Time: {filter_ms:.2f}ms - Filtered {len(reranked) - len(filtered_results)} results below threshold {score_threshold}. "
            f"Remaining: {len(filtered_results)}"
        )
    else:
        logger.info(f"⏱️ Filtering Time: {filter_ms:.2f}ms - No results filtered")

    total_ms = (time.perf_counter() - tic_total) * 1000
    logger.info(f"⏱️ Total Retrieval Time: {total_ms:.2f}ms")

    if include_timings:
        timings = {
            "embed_ms": embed_ms,
            "vector_ms": vector_ms,
            "candidate_prep_ms": candidate_prep_ms,
            "pre_rerank_ms": pre_rerank_ms,
            "rerank_ms": rerank_ms,
            "filter_ms": filter_ms,
            "total_ms": total_ms,
            "reranker_model_path": reranker_model_path,
            "embedding_model_path": embed_model_path,
            "vector_limit_used": vector_limit,
            "content_char_limit_used": char_limit_applied,
            "reranker_mode": reranker_mode,
            "filtered_count": len(reranked) - len(filtered_results),
            "score_threshold": score_threshold,
        }
        # Return total_ms (includes rerank) instead of pre_rerank_ms
        return filtered_results[:top_k], total_ms, timings

    # Return total_ms (includes rerank) instead of pre_rerank_ms
    return filtered_results[:top_k], total_ms


async def _generate_answer_with_llm(
    question: str,
    chunks: List[RetrievedChunk],
    *,
    model: str = "gpt-4o-mini"
) -> Tuple[str, Optional[Dict[str, int]], float]:
    """Generate answer using LLM with retrieved context."""
    if not chunks:
        return (
            "I could not find relevant information in the knowledge base to answer your question.",
            None,
            0.0,
        )

    # Optional: analyze Excel uploads if question hints at calculations
    excel_result = None
    if _should_use_excel_tool(question, chunks):
        for chunk in chunks:
            meta = chunk.metadata or {}
            file_path = meta.get("file_path")
            uploaded_file = meta.get("uploaded_file") or meta.get("filename")
            if file_path and uploaded_file:
                excel_result = _analyze_excel_file(file_path, uploaded_file)
                if excel_result:
                    break

    # Build context from retrieved chunks
    context_parts = []
    if excel_result:
        rows_lines = "\n".join(
            [
                f"- {r.get('label')}: start {r.get('start')}, end {r.get('end')}, delta {r.get('delta')}"
                for r in excel_result.get("rows", [])
            ]
        )
        context_parts.append(
            "Tool: Excel reverse energy analysis\n"
            f"File: {excel_result.get('uploaded_file')}\n"
            f"Total reverse energy (kWh): {excel_result.get('reverse_energy_kwh')}\n"
            f"Details:\n{rows_lines}"
        )

    for i, chunk in enumerate(chunks[:5], 1):  # Use top 5 chunks
        source = chunk.source or "Unknown"

        # Include metadata (title, authors) if available
        metadata_lines = []
        if chunk.metadata:
            title = chunk.metadata.get("title")
            authors = chunk.metadata.get("authors")
            if title and title != source:
                metadata_lines.append(f"Title: {title}")
            if authors:
                metadata_lines.append(f"Authors: {authors}")

        # Build context entry with metadata + content
        header = f"[{i}] Source: {source}"
        if metadata_lines:
            header += "\n" + "\n".join(metadata_lines)

        context_parts.append(f"{header}\n{chunk.content}")

    context = "\n\n".join(context_parts)

    # Build prompt
    prompt = f"""You are a helpful assistant answering questions based on retrieved documents.

Context (Retrieved Documents):
{context}

Question: {question}

Instructions:
1. First, show your **reasoning process**:
   - What information did you find in the context?
   - How do the different pieces of information relate to the question?
   - What inferences can you make based on the available evidence?
   - Which sources are most relevant and why?

2. Then, provide your **final answer**:
   - Answer the question based on the context and your reasoning
   - If direct information is not available, synthesize an answer from related information
   - ALWAYS include inline citations using [1], [2], [3], [4], [5] format
   - For "who wrote" questions, check the "Authors:" metadata field in ALL sources

Format your response as:
**Reasoning:**
[Your step-by-step reasoning process here]

**Answer:**
[Your final answer with citations here]"""

    try:
        llm_start = time.perf_counter()

        client_init_start = time.perf_counter()
        client = _get_openai_client()
        client_init_ms = (time.perf_counter() - client_init_start) * 1000
        logger.info(f"⏱️ OpenAI Client Init Time: {client_init_ms:.2f}ms")

        message_prep_start = time.perf_counter()
        messages = sanitize_messages([
            {"role": "system", "content": "You are a helpful assistant that answers questions based on provided context. Always cite your sources using [1], [2], [3] format."},
            {"role": "user", "content": prompt}
        ])
        message_prep_ms = (time.perf_counter() - message_prep_start) * 1000
        logger.info(f"⏱️ Message Preparation Time: {message_prep_ms:.2f}ms")

        api_call_start = time.perf_counter()
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.3,
            max_tokens=500
        )
        api_call_ms = (time.perf_counter() - api_call_start) * 1000
        logger.info(f"⏱️ LLM API Call Time: {api_call_ms:.2f}ms (model: {model})")

        answer = response.choices[0].message.content.strip()
        usage = getattr(response, "usage", None)
        if usage:
            usage_dict = {
                "prompt": usage.prompt_tokens,
                "completion": usage.completion_tokens,
                "total": usage.total_tokens,
            }
            usage_obj = TokenUsage(
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                model=model,
                timestamp=datetime.utcnow(),
            )
            cost = _token_counter.estimate_cost(usage_obj)
            logger.info(f"⏱️ LLM Token Usage: {usage.total_tokens} tokens (prompt: {usage.prompt_tokens}, completion: {usage.completion_tokens})")
        else:
            usage_dict = None
            cost = 0.0

        total_llm_ms = (time.perf_counter() - llm_start) * 1000
        logger.info(f"⏱️ Total LLM Generation Time: {total_llm_ms:.2f}ms")

        return answer, usage_dict, cost

    except Exception as e:
        # Fallback to simple concatenation if LLM fails
        fallback = f"Error generating answer: {str(e)}. Context: {chunks[0].content[:200]}..."
        return fallback, None, 0.0


async def _generate_answer_with_llm_stream(
    question: str,
    chunks: List[RetrievedChunk],
    *,
    model: str = "gpt-4o-mini"
):
    """
    Generate answer using LLM with streaming (yields chunks as they arrive).

    Yields:
        dict: Streaming chunks with keys:
            - type: "content" | "metadata" | "error"
            - data: chunk content or metadata
    """
    if not chunks:
        yield {
            "type": "content",
            "data": "I could not find relevant information in the knowledge base to answer your question."
        }
        yield {
            "type": "metadata",
            "data": {
                "usage": None,
                "cost": 0.0,
                "model": model
            }
        }
        return

    # Build context from retrieved chunks (same as non-streaming)
    context_parts = []
    for i, chunk in enumerate(chunks[:5], 1):
        source = chunk.source or "Unknown"
        metadata_lines = []
        if chunk.metadata:
            title = chunk.metadata.get("title")
            authors = chunk.metadata.get("authors")
            if title and title != source:
                metadata_lines.append(f"Title: {title}")
            if authors:
                metadata_lines.append(f"Authors: {authors}")

        header = f"[{i}] Source: {source}"
        if metadata_lines:
            header += "\n" + "\n".join(metadata_lines)

        context_parts.append(f"{header}\n{chunk.content}")

    context = "\n\n".join(context_parts)

    prompt = f"""You are a helpful assistant answering questions based on retrieved documents.

Context (Retrieved Documents):
{context}

Question: {question}

Instructions:
1. First, show your **reasoning process**:
   - What information did you find in the context?
   - How do the different pieces of information relate to the question?
   - What inferences can you make based on the available evidence?
   - Which sources are most relevant and why?

2. Then, provide your **final answer**:
   - Answer the question based on the context and your reasoning
   - If direct information is not available, synthesize an answer from related information
   - ALWAYS include inline citations using [1], [2], [3], [4], [5] format
   - For "who wrote" questions, check the "Authors:" metadata field in ALL sources

Format your response as:
**Reasoning:**
[Your step-by-step reasoning process here]

**Answer:**
[Your final answer with citations here]"""

    try:
        client = _get_openai_client()
        messages = sanitize_messages([
            {"role": "system", "content": "You are a helpful assistant that answers questions based on provided context. Always cite your sources using [1], [2], [3] format."},
            {"role": "user", "content": prompt}
        ])

        # Create streaming request
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.3,
            max_tokens=500,
            stream=True  # Enable streaming
        )

        # Stream chunks as they arrive
        full_content = ""
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_content += content
                yield {
                    "type": "content",
                    "data": content
                }

        # After streaming completes, send metadata
        # Note: OpenAI doesn't provide usage in streaming mode, so we estimate
        # TokenUsage is already imported at top of file from token_counter
        estimated_prompt_tokens = len(prompt.split()) * 1.3  # Rough estimate
        estimated_completion_tokens = len(full_content.split()) * 1.3
        estimated_total = int(estimated_prompt_tokens + estimated_completion_tokens)

        usage_obj = TokenUsage(
            prompt_tokens=int(estimated_prompt_tokens),
            completion_tokens=int(estimated_completion_tokens),
            total_tokens=estimated_total,
            model=model,
            timestamp=datetime.utcnow(),
        )
        cost = _token_counter.estimate_cost(usage_obj)

        yield {
            "type": "metadata",
            "data": {
                "usage": {
                    "prompt": int(estimated_prompt_tokens),
                    "completion": int(estimated_completion_tokens),
                    "total": estimated_total
                },
                "cost": cost,
                "model": model,
                "full_answer": full_content
            }
        }

    except Exception as e:
        logger.error(f"Streaming LLM generation failed: {e}")
        yield {
            "type": "error",
            "data": f"Error generating answer: {str(e)}"
        }


async def answer_question(
    question: str,
    *,
    top_k: int = 5,
    use_llm: bool = True,
    include_timings: bool = True,
    reranker_override: Optional[str] = None,
    vector_limit: Optional[int] = None,
    content_char_limit: Optional[int] = None,
) -> RAGResponse:
    """
    High-level RAG pipeline: retrieve chunks and generate answer with LLM.

    Args:
        question: User's question
        top_k: Number of chunks to retrieve
        use_llm: If True, use LLM to generate answer; if False, just concatenate chunks

    Returns:
        RAGResponse with answer, citations, and timing info
    """
    tic_total = time.perf_counter()

    # Step 0: Check answer cache FIRST (maximum token savings!)
    from backend.services.enhanced_rag_pipeline import _get_answer_cache
    answer_cache = _get_answer_cache()
    if answer_cache:
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
                # Return cached answer directly, skip all RAG processing!
                return cached['answer']
        except Exception:
            pass  # Silently continue if cache lookup fails

    search_limit = max(top_k * 2, 10)

    retrieval_kwargs = dict(
        question=question,
        top_k=top_k,
        search_limit=search_limit,
        include_timings=include_timings,
        reranker_override=reranker_override,
        vector_limit_override=vector_limit,
        content_char_limit=content_char_limit,
    )

    if include_timings:
        chunks, retrieval_ms, timings = await retrieve_chunks(**retrieval_kwargs)
    else:
        chunks, retrieval_ms = await retrieve_chunks(**{**retrieval_kwargs, "include_timings": False})
        timings = {}

    if not chunks:
        if inference_config.ENABLE_REMOTE_INFERENCE:
            # When using remote inference with ONNX models, show the actual ONNX model paths
            embedding_model_path = settings.ONNX_EMBED_MODEL_PATH or "remote-embed"
            reranker_model_path = settings.ONNX_RERANK_MODEL_PATH or "remote-rerank"
            reranker_mode = "remote"
        else:
            embedding_model_path = timings.get("embedding_model_path") if timings else getattr(
                get_embedding_model(),
                "resolved_model_path",
                getattr(get_embedding_model(), "configured_path", settings.ONNX_EMBED_MODEL_PATH),
            )
            reranker_model_path = timings.get("reranker_model_path") if timings else get_current_reranker_path()
            reranker_mode = timings.get("reranker_mode") if timings else None

        vector_limit_used = timings.get("vector_limit_used") if timings else vector_limit
        content_char_limit_used = timings.get("content_char_limit_used") if timings else content_char_limit

        return RAGResponse(
            answer="I could not find relevant information in the knowledge base.",
            citations=[],
            retrieval_time_ms=retrieval_ms,
            confidence=0.0,
            num_chunks_retrieved=0,
            llm_time_ms=0.0,
            total_time_ms=(time.perf_counter() - tic_total) * 1000,
            timings=timings or None,
            models={
                "embedding": embedding_model_path,
                "reranker": reranker_model_path,
                "llm": settings.OPENAI_MODEL if use_llm else "disabled",
            },
            token_usage=None,
            token_cost_usd=0.0,
            llm_used=False,
            reranker_mode=reranker_mode,
            vector_limit_used=vector_limit_used,
            content_char_limit_used=content_char_limit_used,
        )

    # Generate answer with LLM or simple concatenation
    llm_model = os.getenv("OPENAI_MODEL") or settings.OPENAI_MODEL or "gpt-4o-mini"
    token_usage = None
    token_cost_usd = 0.0
    llm_used = use_llm
    if use_llm:
        # Limit to top 30 chunks for LLM to improve relevance ratio
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
        # Simple concatenation (for evaluation/debugging)
        answer_parts = [chunk.content for chunk in chunks[: min(5, len(chunks))]]
        answer = " ".join(answer_parts)
        llm_time_ms = 0.0
        llm_used = False

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
    timings = timings or {}
    timings.update({
        "llm_ms": llm_time_ms,
        "end_to_end_ms": total_time_ms,
    })

    if inference_config.ENABLE_REMOTE_INFERENCE:
        # When using remote inference with ONNX models, show the actual ONNX model paths
        embedding_model_path = settings.ONNX_EMBED_MODEL_PATH or "remote-embed"
        reranker_model_path = settings.ONNX_RERANK_MODEL_PATH or "remote-rerank"
        reranker_mode = "remote"
    else:
        embedding_model_path = timings.get("embedding_model_path") or getattr(
            get_embedding_model(),
            "resolved_model_path",
            getattr(get_embedding_model(), "configured_path", settings.ONNX_EMBED_MODEL_PATH),
        )
        reranker_model_path = timings.get("reranker_model_path") or getattr(
            get_reranker_model(),
            "resolved_model_path",
            getattr(get_reranker_model(), "model_path", settings.ONNX_RERANK_MODEL_PATH),
        )
        reranker_mode = timings.get("reranker_mode")

    vector_limit_used = timings.get("vector_limit_used")
    content_char_limit_used = timings.get("content_char_limit_used")

    # Record Prometheus metrics
    try:
        rag_request_counter.labels(
            endpoint="rag_ask",
            status="success" if chunks else "partial"
        ).inc()

        rag_request_duration_histogram.labels(
            endpoint="rag_ask",
            has_role_filter="no"
        ).observe(total_time_ms / 1000)

        if timings and "embed_ms" in timings:
            embedding_duration_histogram.labels(
                model=llm_model,
                source="local" if not inference_config.ENABLE_REMOTE_INFERENCE else "remote",
                batch_size_range="1"
            ).observe(timings["embed_ms"] / 1000)

        if timings and "rerank_ms" in timings:
            rerank_duration_histogram.labels(
                model=llm_model,
                source="local" if not inference_config.ENABLE_REMOTE_INFERENCE else "remote",
                candidate_count_range=f"1-10" if len(chunks) <= 10 else "11-50"
            ).observe(timings["rerank_ms"] / 1000)

        # Record LLM metrics if LLM was used
        if use_llm and token_usage:
            llm_request_counter.labels(
                model=llm_model,
                endpoint="rag",
                status="success"
            ).inc()

            llm_token_usage_counter.labels(
                model=llm_model,
                token_type="prompt"
            ).inc(token_usage.get("prompt", 0))

            llm_token_usage_counter.labels(
                model=llm_model,
                token_type="completion"
            ).inc(token_usage.get("completion", 0))

            llm_cost_counter.labels(model=llm_model).inc(token_cost_usd)

            llm_request_duration_histogram.labels(
                model=llm_model,
                endpoint="rag"
            ).observe(llm_time_ms / 1000)
    except Exception as metrics_error:
        logger.warning(f"Failed to record metrics: {metrics_error}")

    response = RAGResponse(
        answer=answer,
        citations=citations,
        retrieval_time_ms=retrieval_ms,
        confidence=top_confidence,
        num_chunks_retrieved=len(chunks),
        llm_time_ms=llm_time_ms,
        total_time_ms=total_time_ms,
        timings=timings or None,
        models={
            "embedding": embedding_model_path,
            "reranker": reranker_model_path,
            "llm": llm_model if use_llm else "disabled",
        },
        token_usage=token_usage,
        token_cost_usd=token_cost_usd,
        llm_used=llm_used,
        reranker_mode=reranker_mode,
        vector_limit_used=vector_limit_used,
        content_char_limit_used=content_char_limit_used,
    )

    # Save answer to cache for future queries (with quality checks)
    if answer_cache and answer:
        # Quality checks to prevent caching low-quality answers
        num_citations = len(response.citations) if response.citations else 0
        num_chunks = response.num_chunks_retrieved
        confidence = response.confidence

        # Define quality thresholds
        # NOTE: We don't check confidence as it may be negative (log probability from reranker)
        MIN_CITATIONS = 1  # At least 1 source citation
        MIN_CHUNKS = 1     # At least 1 retrieved chunk

        # Check if answer meets quality criteria
        quality_ok = (
            num_citations >= MIN_CITATIONS and
            num_chunks >= MIN_CHUNKS
        )

        if quality_ok:
            try:
                await answer_cache.cache_answer(question, response)
                logger.info(
                    "Answer cached successfully for query %s (citations=%d, chunks=%d, confidence=%.2f)",
                    question[:50], num_citations, num_chunks, confidence
                )
            except Exception:
                pass  # Silently continue if cache save fails
        else:
            logger.warning(
                "Answer NOT cached due to low quality (citations=%d<%d, chunks=%d<%d) for query: %s",
                num_citations, MIN_CITATIONS, num_chunks, MIN_CHUNKS, question[:50]
            )

    return response


async def ingest_documents_batch(documents: List[Tuple[str, str, str]]) -> List[DocumentResponse]:
    """Helper to ingest multiple documents concurrently."""
    tasks = [
        ingest_document(title=title, content=content, source=source)
        for title, content, source in documents
    ]
    return await asyncio.gather(*tasks)

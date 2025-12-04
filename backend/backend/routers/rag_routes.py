"""
Task 3.2: High-Performance RAG endpoints backed by Qdrant.
"""
import logging
import structlog
import os
import json
import time
import random
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from sse_starlette.sse import EventSourceResponse
import tempfile

from backend.config.settings import settings
from backend.models.rag_schemas import (
    Citation,
    DocumentResponse,
    DocumentUpload,
    RAGRequest,
    RAGResponse,
    UserFeedback,
    FeedbackResponse,
)
from backend.services.governance_tracker import get_governance_tracker
from backend.services.onnx_inference import (
    get_current_reranker_path,
    get_current_embed_path,
    switch_to_fallback_mode,
    switch_to_primary_mode,
)
from backend.services.qdrant_client import get_qdrant_client, ensure_collection
from backend.services.qdrant_seed import get_seed_status
from backend.services.rag_pipeline import (
    answer_question,
    ingest_document,
    retrieve_chunks,
    _generate_answer_with_llm_stream,
    VECTOR_LIMIT_MIN,
    VECTOR_LIMIT_MAX,
    CONTENT_CHAR_MIN,
    CONTENT_CHAR_MAX,
    DEFAULT_CONTENT_CHAR_LIMIT,
)
from backend.services.enhanced_rag_pipeline import answer_question_hybrid
from backend.services.self_rag import get_self_rag
from backend.services.query_cache import get_query_cache
from backend.services.answer_cache import get_answer_cache
from backend.services.data_monitor import get_data_monitor
from backend.utils.file_loader import load_document_from_path
from backend.config.knowledge_config.inference_config import inference_config
from backend.services.smart_bandit_state import get_status as get_bandit_status, set_cold_start

logger = structlog.get_logger(__name__)
router = APIRouter()
COLLECTION_NAME = settings.QDRANT_COLLECTION

# ------------------------------------------------------------------
# Smart RAG bandit state (in-memory, process-level)
# ------------------------------------------------------------------
# Bandit state persistence
BANDIT_STATE_FILE = os.getenv("BANDIT_STATE_FILE", "/tmp/smart_bandit_state.json")
DEFAULT_BANDIT_STATE_FILE = "./config/default_bandit_state.json"

def _load_bandit_state() -> Dict[str, Dict[str, float]]:
    """Load bandit state from persistent storage or default config"""
    try:
        # Try to load from runtime state file first
        if os.path.exists(BANDIT_STATE_FILE):
            with open(BANDIT_STATE_FILE, 'r') as f:
                state = json.load(f)
                logger.info(f"Loaded bandit state from {BANDIT_STATE_FILE}", state=state)
                return state

        # If no runtime state, try to load from default config (pre-warmed)
        if os.path.exists(DEFAULT_BANDIT_STATE_FILE):
            with open(DEFAULT_BANDIT_STATE_FILE, 'r') as f:
                state = json.load(f)
                logger.info(f"Loaded default pre-warmed bandit state from {DEFAULT_BANDIT_STATE_FILE}", state=state)
                # Save as runtime state for future updates
                _save_bandit_state(state)
                return state
    except Exception as e:
        logger.warning(f"Failed to load bandit state: {e}")

    # Fallback: cold start with uniform priors
    logger.warning("No bandit state found - starting with cold uniform priors. Consider running warm_smart_bandit.py")
    set_cold_start(True)  # Mark as cold start so frontend knows to run warm-up
    return {
        "hybrid": {"alpha": 1.0, "beta": 1.0},
        "iterative": {"alpha": 1.0, "beta": 1.0},
        "graph": {"alpha": 1.0, "beta": 1.0},
        "table": {"alpha": 1.0, "beta": 1.0},
    }

def _save_bandit_state(state: Dict[str, Dict[str, float]]) -> None:
    """Save bandit state to persistent storage"""
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(BANDIT_STATE_FILE), exist_ok=True)
        with open(BANDIT_STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
        logger.debug(f"Saved bandit state to {BANDIT_STATE_FILE}")
    except Exception as e:
        logger.warning(f"Failed to save bandit state: {e}")

# Load initial state from persistent storage
_smart_bandit: Dict[str, Dict[str, float]] = _load_bandit_state()

# Query tracking for user feedback
# Maps query_id -> {"strategy": str, "reward": float, "timestamp": float}
_query_history: Dict[str, Dict[str, Any]] = {}


def _bandit_enabled() -> bool:
    return os.getenv("SMART_RAG_BANDIT_ENABLED", "true").lower() == "true"


def _choose_bandit_arm(available: list[str]) -> str:
    """
    Thompson Sampling over available arms with exploration bonus.

    Gives preference to under-explored arms to encourage learning about
    all strategies (especially graph and table RAG).
    """
    if not available:
        return "hybrid"

    # Calculate total trials for each arm
    arm_trials = {}
    for arm in available:
        params = _smart_bandit.get(arm, {"alpha": 1.0, "beta": 1.0})
        # Total trials = (alpha + beta - 2) since we start with alpha=1, beta=1
        arm_trials[arm] = params["alpha"] + params["beta"] - 2.0

    # Find minimum trials to identify under-explored arms
    min_trials = min(arm_trials.values()) if arm_trials else 0
    max_trials = max(arm_trials.values()) if arm_trials else 1

    # Sample from Beta distribution with exploration bonus
    samples = {}
    for arm in available:
        params = _smart_bandit.get(arm, {"alpha": 1.0, "beta": 1.0})
        base_sample = random.betavariate(params["alpha"], params["beta"])

        # Add exploration bonus for under-explored arms
        # Bonus decreases as the arm is explored more
        trials = arm_trials[arm]
        if max_trials > 0:
            exploration_bonus = 0.2 * (1.0 - trials / max_trials)
        else:
            exploration_bonus = 0.2

        samples[arm] = base_sample + exploration_bonus

    chosen = max(samples.items(), key=lambda x: x[1])[0]

    # Log exploration info for debugging
    if arm_trials[chosen] < 5:
        logger.debug(f"Bandit chose under-explored arm: {chosen}",
                    trials=arm_trials[chosen],
                    all_trials={k: v for k, v in arm_trials.items()})

    return chosen


def _update_bandit(arm: str, reward: float, user_rating: Optional[float] = None) -> None:
    """
    Update Beta parameters with normalized reward in [0,1] and persist state.

    Args:
        arm: Strategy name (hybrid, iterative, graph, table)
        reward: Automated reward from confidence/coverage/latency
        user_rating: Optional user feedback rating (0.0-1.0)
            - If provided, user rating dominates the update (70% weight)
            - If None, use automated reward only
    """
    if arm not in _smart_bandit:
        return

    # Calculate final reward
    if user_rating is not None:
        # User feedback dominates: 70% user rating, 30% automated metrics
        final_reward = 0.7 * user_rating + 0.3 * reward
        logger.info(f"Bandit update with user feedback",
                   arm=arm,
                   automated_reward=f"{reward:.3f}",
                   user_rating=f"{user_rating:.3f}",
                   final_reward=f"{final_reward:.3f}")
    else:
        # Normal automated reward
        final_reward = reward

    r = max(0.0, min(1.0, final_reward))
    _smart_bandit[arm]["alpha"] += r
    _smart_bandit[arm]["beta"] += (1.0 - r)

    # Persist state after every update
    _save_bandit_state(_smart_bandit)


def _ensure_vector_collection() -> None:
    """Ensure the target Qdrant collection exists with the expected vector size."""
    if inference_config.ENABLE_REMOTE_INFERENCE:
        vector_size = settings.RAG_VECTOR_SIZE
    else:
        from backend.services.onnx_inference import get_embedding_model  # Local import to avoid loading ONNX when remote inference is used

        vector_size = get_embedding_model().vector_size

    ensure_collection(vector_size)


@router.get("/seed-status")
async def seed_status() -> Dict[str, Any]:
    """Expose current Qdrant seed progress."""
    return get_seed_status()


@router.post("/ask", response_model=RAGResponse)
async def ask_question(request: RAGRequest) -> RAGResponse:
    """Answer a question using vector retrieval, reranking and citations."""
    try:
        logger.info("📝 RAG query received")
        from backend.services.answer_cache_wrapper import with_answer_cache
        response = await with_answer_cache(
            request.question,
            answer_question,
            top_k=request.top_k or 5,
            include_timings=request.include_timings,
            reranker_override=request.reranker,
            vector_limit=request.vector_limit,
            content_char_limit=request.content_char_limit,
        )

        # Log interaction for drift monitoring
        try:
            data_monitor = get_data_monitor()
            model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

            # Extract token usage from response
            token_usage = response.token_usage or {}
            prompt_tokens = token_usage.get("prompt", 0)
            completion_tokens = token_usage.get("completion", 0)
            total_tokens = token_usage.get("total", 0)

            # Calculate average retrieval score
            avg_score = sum(c.score for c in response.citations) / len(response.citations) if response.citations else 0.0

            data_monitor.log_rag_query(
                query=request.question,
                answer=response.answer,
                total_tokens=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                duration_ms=response.total_time_ms,
                model=model_name,
                num_retrieved=response.num_chunks_retrieved,
                avg_score=avg_score,
                success=True,
                metadata={
                    "cost_usd": response.token_cost_usd,
                    "confidence": response.confidence,
                    "llm_time_ms": response.llm_time_ms,
                    "retrieval_time_ms": response.retrieval_time_ms,
                }
            )
        except Exception as monitor_error:
            logger.warning(f"Failed to log RAG interaction to data monitor: {monitor_error}")

        return response
    except Exception as exc:
        logger.exception("❌ RAG query failed: %s", exc)

        # Log failed interaction
        try:
            data_monitor = get_data_monitor()
            model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            data_monitor.log_rag_query(
                query=request.question,
                answer="",
                total_tokens=0,
                prompt_tokens=0,
                completion_tokens=0,
                duration_ms=0,
                model=model_name,
                num_retrieved=0,
                avg_score=0.0,
                success=False,
                metadata={"error": str(exc)}
            )
        except Exception as monitor_error:
            logger.warning(f"Failed to log failed RAG interaction: {monitor_error}")

        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/tools/analyze-excel")
async def analyze_excel(payload: Dict[str, str]) -> Dict[str, Any]:
    """
    Analyze an uploaded Excel file and compute total photovoltaic (PV) energy generation.

    Calculates sum of ALL photovoltaic meters' forward AND reverse energy:
    - Finds all "光伏电表" (photovoltaic meter) sections
    - For each meter, processes both "正向用电" (forward) and "反向用电" (reverse) sections
    - Returns total generation = sum of all deltas from all meters

    Request body:
    {
        "uploaded_file": "华达瑞产业园服务用电抄表记录表2025-08-31.xlsx"
    }
    """
    uploaded_file = payload.get("uploaded_file")
    if not uploaded_file:
        raise HTTPException(status_code=400, detail="uploaded_file is required")

    # Resolve file path from uploads directory
    uploads_dir = Path("data/uploads")
    candidate = uploads_dir / uploaded_file
    if not candidate.exists():
        # Try timestamped variants
        matches = list(uploads_dir.glob(f"{Path(uploaded_file).stem}*{Path(uploaded_file).suffix}"))
        if matches:
            candidate = matches[-1]
        else:
            raise HTTPException(status_code=404, detail=f"Uploaded file not found: {uploaded_file}")

    try:
        import pandas as pd
    except ImportError:
        raise HTTPException(status_code=500, detail="pandas not installed on server")

    try:
        df = pd.read_excel(candidate)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read Excel: {exc}")

    # Detect columns containing start/end readings and multiplier
    col_start = None
    col_end = None
    col_multiplier = None
    for c in df.columns:
        if "Unnamed: 4" in str(c):
            col_start = c
        if "Unnamed: 5" in str(c):
            col_end = c
        if "Unnamed: 6" in str(c):
            col_multiplier = c
    # Fallback to positional columns 4/5/6
    if col_start is None and len(df.columns) > 4:
        col_start = df.columns[4]
    if col_end is None and len(df.columns) > 5:
        col_end = df.columns[5]
    if col_multiplier is None and len(df.columns) > 6:
        col_multiplier = df.columns[6]

    if col_start is None or col_end is None:
        raise HTTPException(status_code=400, detail="Could not locate start/end reading columns")

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

    # Find ALL photovoltaic meter sections
    pv_meters = {}  # {meter_name: {forward_idx: int, reverse_idx: int}}
    current_meter = None

    for idx, row in df.iterrows():
        row_str = str(row.tolist())

        # Check if this row starts a new photovoltaic meter
        if '光伏电表' in row_str:
            meter_name = str(row.iloc[0]).strip()
            current_meter = meter_name
            pv_meters[current_meter] = {'forward_idx': None, 'reverse_idx': None}

        # Mark forward/reverse section starts for the current meter
        if current_meter and current_meter in pv_meters:
            if '正向用电' in row_str and pv_meters[current_meter]['forward_idx'] is None:
                pv_meters[current_meter]['forward_idx'] = idx
            elif '反向用电' in row_str and pv_meters[current_meter]['reverse_idx'] is None:
                pv_meters[current_meter]['reverse_idx'] = idx

    if not pv_meters:
        raise HTTPException(status_code=400, detail="Could not find any '光伏电表' (photovoltaic meter) sections in Excel")

    # Helper function to process a section (5 rows with energy readings)
    def process_section(start_idx: int, section_type: str) -> tuple[float, list]:
        """Process 5 rows of energy data and return (total_delta, row_details)"""
        if start_idx is None:
            return 0.0, []

        section_df = df.iloc[start_idx: start_idx + 5]
        section_results = []
        section_total = 0.0

        for _, row in section_df.iterrows():
            label = str(row.get(labels_col, "")).strip() if labels_col else ""
            start = _to_num(row.get(col_start))
            end = _to_num(row.get(col_end))
            multiplier = _to_num(row.get(col_multiplier)) if col_multiplier else 1.0

            if start is None or end is None:
                continue

            # Apply multiplier: delta = (end - start) * multiplier
            delta_raw = end - start
            delta = delta_raw * (multiplier if multiplier else 1.0)
            section_total += delta
            section_results.append({
                "type": section_type,
                "label": label or "unknown",
                "start": start,
                "end": end,
                "multiplier": multiplier if multiplier else 1.0,
                "delta": delta,
            })

        return section_total, section_results

    # Process each photovoltaic meter's forward + reverse sections
    all_results = []
    meter_breakdown = []
    grand_total = 0.0

    for meter_name, indices in pv_meters.items():
        forward_total, forward_rows = process_section(indices['forward_idx'], "正向用电")
        reverse_total, reverse_rows = process_section(indices['reverse_idx'], "反向用电")

        meter_total = forward_total + reverse_total
        grand_total += meter_total

        all_results.extend(forward_rows)
        all_results.extend(reverse_rows)

        meter_breakdown.append({
            "meter": meter_name,
            "forward_kwh": round(forward_total, 2),
            "reverse_kwh": round(reverse_total, 2),
            "total_kwh": round(meter_total, 2),
        })

    return {
        "uploaded_file": uploaded_file,
        "file_path": str(candidate),
        "total_generation_kwh": round(grand_total, 2),
        "num_pv_meters": len(pv_meters),
        "meter_breakdown": meter_breakdown,
        "all_rows": all_results,
        "method": "Sum of all 光伏电表 (正向用电 + 反向用电), delta = (end - start) * multiplier",
    }


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(payload: DocumentUpload) -> DocumentResponse:
    """Ingest a document into the knowledge base."""
    try:
        logger.info("📚 Ingesting document: %s", payload.title)
        return await ingest_document(
            title=payload.title,
            content=payload.content,
            source=payload.source or payload.title,
            metadata=payload.metadata or {},
        )
    except Exception as exc:
        logger.exception("❌ Document ingestion failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/upload-file")
async def upload_file(
    file: UploadFile = File(...),
    use_separate_collection: bool = False
) -> Dict[str, Any]:
    """
    Upload and process a file (PDF, TXT, DOCX, XLSX, CSV).

    Supports:
    - PDF files
    - Text files (.txt)
    - Word documents (.docx)
    - Excel files (.xlsx, .xls)
    - CSV files (.csv)

    Args:
        file: The file to upload
        use_separate_collection: If True (default), upload to user_uploaded_docs collection

    Returns progress information and ingestion results.
    """
    try:
        from fastapi import UploadFile, File
        import tempfile
        import os

        logger.info(f"📤 Received file upload: {file.filename} (separate_collection={use_separate_collection})")

        # Validate file type
        allowed_extensions = {'.pdf', '.txt', '.docx', '.xlsx', '.xls', '.csv'}
        file_ext = os.path.splitext(file.filename)[1].lower()

        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {file_ext}. Allowed types: {', '.join(allowed_extensions)}"
            )

        # Select target collection
        target_collection = "user_uploaded_docs" if use_separate_collection else COLLECTION_NAME

        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_path = tmp_file.name

        # Persist original upload for downstream structured analysis
        uploads_root = os.getenv("UPLOADS_DIR", "data/uploads")
        uploads_dir = Path(uploads_root).resolve()
        uploads_dir.mkdir(parents=True, exist_ok=True)
        dest_path = uploads_dir / file.filename
        if dest_path.exists():
            dest_path = uploads_dir / f"{dest_path.stem}_{int(time.time())}{dest_path.suffix}"
        try:
            dest_path.write_bytes(content)
        except Exception as exc:
            logger.warning(f"Failed to persist uploaded file {file.filename}: {exc}")
            dest_path = None

        try:
            # Load and process document
            docs = load_document_from_path(tmp_path)

            if not docs:
                raise HTTPException(status_code=400, detail="No content extracted from file")

            # Process all documents
            responses = []
            total_chunks = 0

            for doc in docs:
                response = await ingest_document(
                    title=doc.title or file.filename,
                    content=doc.content,
                    source=file.filename,
                    metadata={
                        **doc.metadata,
                        "uploaded_file": file.filename,
                        "file_path": str(dest_path) if dest_path else None,
                        "upload_dir": str(uploads_dir),
                        "collection": target_collection
                    },
                    collection_name=target_collection,
                )
                responses.append(response)
                total_chunks += response.num_chunks

            logger.info(f"✅ Successfully ingested {file.filename} to {target_collection}: {total_chunks} chunks")

            return {
                "success": True,
                "filename": file.filename,
                "file_type": file_ext,
                "documents_processed": len(responses),
                "total_chunks": total_chunks,
                "collection": target_collection,
                "message": f"Successfully processed {file.filename} into {total_chunks} chunks"
            }

        finally:
            # Clean up temporary file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"❌ File upload failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/ingest/sample", response_model=Dict[str, Any])
async def ingest_sample_corpus() -> Dict[str, Any]:
    """
    Convenience endpoint to ingest sample documents from the data/ folder.
    """
    try:
        docs = load_document_from_path("data/The-Prop-Building-Guidebook.txt")
        docs += load_document_from_path("data/Revenge-Of-The-Sith-pdf.pdf")

        responses = []
        for doc in docs:
            responses.append(
                await ingest_document(
                    title=doc.title,
                    content=doc.content,
                    source=doc.source,
                    metadata=doc.metadata,
                )
            )

        return {
            "ingested_documents": [resp.title for resp in responses],
            "total_chunks": sum(resp.num_chunks for resp in responses),
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("❌ Sample ingestion failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/stats")
async def stats() -> Dict[str, Any]:
    """Return basic statistics about the Qdrant collection."""
    _ensure_vector_collection()
    client = get_qdrant_client()
    info = client.get_collection(collection_name=COLLECTION_NAME)
    return {
        "vectors_count": info.vectors_count,  # type: ignore[attr-defined]
        "segments_count": info.segments_count,  # type: ignore[attr-defined]
        "status": info.status,  # type: ignore[attr-defined]
    }


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """Check connectivity with Qdrant."""
    try:
        _ensure_vector_collection()
        return {"status": "healthy"}
    except Exception as exc:
        logger.exception("RAG health check failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/config")
async def rag_config() -> Dict[str, Any]:
    """Expose RAG model metadata and tunable parameter ranges."""
    from backend.services.onnx_inference import get_embedding_model  # Local import keeps lazy loading behavior

    embedding_model = get_embedding_model()
    embedding_path = getattr(
        embedding_model,
        "resolved_model_path",
        getattr(embedding_model, "configured_path", settings.ONNX_EMBED_MODEL_PATH),
    )
    current_embed = get_current_embed_path()
    current_reranker = get_current_reranker_path()

    # Determine current mode
    is_primary_mode = (
        current_embed == settings.ONNX_EMBED_MODEL_PATH
        and current_reranker == settings.ONNX_RERANK_MODEL_PATH
    )
    is_fallback_mode = (
        current_embed == settings.EMBED_FALLBACK_MODEL_PATH
        and current_reranker == settings.RERANK_FALLBACK_MODEL_PATH
    )

    # Mode options - include "auto" for adaptive model selection based on query difficulty
    mode_options = ["auto", "primary", "fallback"]

    return {
        "models": {
            "embedding_current": current_embed,
            "embedding_primary": settings.ONNX_EMBED_MODEL_PATH,
            "embedding_fallback": settings.EMBED_FALLBACK_MODEL_PATH,
            "reranker_current": current_reranker,
            "reranker_primary": settings.ONNX_RERANK_MODEL_PATH,
            "reranker_fallback": settings.RERANK_FALLBACK_MODEL_PATH,
            "llm_default": settings.OPENAI_MODEL,
        },
        "current_mode": "primary" if is_primary_mode else "fallback" if is_fallback_mode else "mixed",
        "reranker_options": mode_options,  # Frontend expects "reranker_options" key
        "limits": {
            "vector_min": VECTOR_LIMIT_MIN,
            "vector_max": VECTOR_LIMIT_MAX,
            "content_char_min": CONTENT_CHAR_MIN,
            "content_char_max": CONTENT_CHAR_MAX,
            "content_char_default": DEFAULT_CONTENT_CHAR_LIMIT,
        },
    }


@router.post("/switch-mode")
async def switch_mode(mode: str) -> Dict[str, Any]:
    """
    Switch between primary (BGE) and fallback (MiniLM) mode.

    Modes:
    - primary: BGE-M3 embed + BGE reranker (high quality, slower)
    - fallback: MiniLM embed + MiniLM reranker (fast, good quality)
    """
    mode = mode.lower()

    if mode not in ["primary", "fallback"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode '{mode}'. Must be 'primary' or 'fallback'."
        )

    try:
        if mode == "primary":
            switched = switch_to_primary_mode()
            new_embed = settings.ONNX_EMBED_MODEL_PATH
            new_reranker = settings.ONNX_RERANK_MODEL_PATH
        else:  # fallback
            switched = switch_to_fallback_mode()
            new_embed = settings.EMBED_FALLBACK_MODEL_PATH
            new_reranker = settings.RERANK_FALLBACK_MODEL_PATH

        return {
            "success": True,
            "mode": mode,
            "switched": switched,
            "models": {
                "embedding": new_embed,
                "reranker": new_reranker,
            },
            "message": f"Switched to {mode} mode (embed + reranker)" if switched else f"Already in {mode} mode"
        }
    except Exception as e:
        logger.error(f"Failed to switch mode to {mode}: {e}")
        raise HTTPException(status_code=500, detail=f"Mode switch failed: {str(e)}")


@router.post("/ask-hybrid", response_model=RAGResponse)
async def ask_question_hybrid_search(request: RAGRequest) -> RAGResponse:
    """
    Answer a question using hybrid search (BM25 + vector) with query caching and classification.

    This endpoint combines:
    - BM25 keyword search + dense vector search (configurable fusion)
    - Query strategy caching for 90% token savings on similar queries
    - Query classification for optimized retrieval parameters

    Returns:
        RAGResponse with answer, citations, and enhanced metadata
    """
    try:
        logger.info("📝 RAG hybrid query received")
        response = await answer_question_hybrid(
            question=request.question,
            top_k=request.top_k or 5,
            use_llm=True,
            include_timings=request.include_timings,
            reranker_override=request.reranker,
            vector_limit=request.vector_limit,
            content_char_limit=request.content_char_limit,
            use_cache=True,
            use_classifier=True
        )

        # Log interaction for drift monitoring
        try:
            data_monitor = get_data_monitor()
            model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

            token_usage = response.token_usage or {}
            prompt_tokens = token_usage.get("prompt", 0)
            completion_tokens = token_usage.get("completion", 0)
            total_tokens = token_usage.get("total", 0)

            avg_score = sum(c.score for c in response.citations) / len(response.citations) if response.citations else 0.0

            data_monitor.log_rag_query(
                query=request.question,
                answer=response.answer,
                total_tokens=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                duration_ms=response.total_time_ms,
                model=model_name,
                num_retrieved=response.num_chunks_retrieved,
                avg_score=avg_score,
                success=True,
                metadata={
                    "cost_usd": response.token_cost_usd,
                    "confidence": response.confidence,
                    "llm_time_ms": response.llm_time_ms,
                    "retrieval_time_ms": response.retrieval_time_ms,
                    "mode": "hybrid"
                }
            )
        except Exception as monitor_error:
            logger.warning(f"Failed to log RAG interaction to data monitor: {monitor_error}")

        return response
    except Exception as exc:
        logger.exception("❌ RAG hybrid query failed: %s", exc)

        # Log failed interaction
        try:
            data_monitor = get_data_monitor()
            model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            data_monitor.log_rag_query(
                query=request.question,
                answer="",
                total_tokens=0,
                prompt_tokens=0,
                completion_tokens=0,
                duration_ms=0,
                model=model_name,
                num_retrieved=0,
                avg_score=0.0,
                success=False,
                metadata={"error": str(exc), "mode": "hybrid"}
            )
        except Exception as monitor_error:
            logger.warning(f"Failed to log failed RAG interaction: {monitor_error}")

        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/ask-iterative", response_model=RAGResponse)
async def ask_question_iterative(request: RAGRequest) -> RAGResponse:
    """
    Answer a question using Self-RAG: iterative retrieval with confidence thresholds.

    This endpoint implements:
    - Iterative document retrieval with self-reflection
    - Confidence assessment after each iteration
    - Automatic follow-up queries for missing information
    - Incremental context (send only new documents to save tokens)

    Best for complex queries requiring multi-hop reasoning.

    Returns:
        RAGResponse with iterative refinement metadata
    """
    try:
        logger.info("📝 RAG iterative query received")

        # Get Self-RAG instance
        self_rag = get_self_rag()

        # Run iterative retrieval with answer cache
        from backend.services.answer_cache_wrapper import with_answer_cache
        response = await with_answer_cache(
            request.question,
            self_rag.ask_with_reflection,
            top_k=request.top_k or 10,  # Higher default for iterative
            use_hybrid=True,  # Use hybrid search by default
            include_timings=request.include_timings
        )

        # Log interaction
        try:
            data_monitor = get_data_monitor()
            model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

            token_usage = response.token_usage or {}
            total_tokens = token_usage.get("total", 0)

            avg_score = sum(c.score for c in response.citations) / len(response.citations) if response.citations else 0.0

            # Extract iteration metadata
            timings = response.timings or {}
            iterations = timings.get('total_iterations', 1)

            data_monitor.log_rag_query(
                query=request.question,
                answer=response.answer,
                total_tokens=total_tokens,
                prompt_tokens=token_usage.get("prompt", 0),
                completion_tokens=token_usage.get("completion", 0),
                duration_ms=response.total_time_ms,
                model=model_name,
                num_retrieved=response.num_chunks_retrieved,
                avg_score=avg_score,
                success=True,
                metadata={
                    "cost_usd": response.token_cost_usd,
                    "confidence": response.confidence,
                    "mode": "iterative",
                    "iterations": iterations,
                    "converged": timings.get('converged', False)
                }
            )
        except Exception as monitor_error:
            logger.warning(f"Failed to log RAG interaction: {monitor_error}")

        return response
    except Exception as exc:
        logger.exception("❌ RAG iterative query failed: %s", exc)

        try:
            data_monitor = get_data_monitor()
            data_monitor.log_rag_query(
                query=request.question,
                answer="",
                total_tokens=0,
                prompt_tokens=0,
                completion_tokens=0,
                duration_ms=0,
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                num_retrieved=0,
                avg_score=0.0,
                success=False,
                metadata={"error": str(exc), "mode": "iterative"}
            )
        except Exception as monitor_error:
            logger.warning(f"Failed to log failed RAG interaction: {monitor_error}")

        raise HTTPException(status_code=500, detail=str(exc))


async def _smart_rag_logic(
    question: str,
    top_k: int,
    include_timings: bool,
    reranker: Optional[str],
    vector_limit: Optional[int],
    content_char_limit: Optional[int]
) -> RAGResponse:
    """Helper function for smart RAG logic (for caching wrapper)"""
    # Classify query to determine complexity (using LLM)
    from backend.services.query_classifier import get_query_classifier

    classifier = get_query_classifier()
    strategy = await classifier.get_strategy(question, use_llm=True, use_cache=True)  # Use LLM with cache
    query_type = strategy.get('query_type', 'general')
    strategy_description = strategy.get('description', 'No description available')
    classification_tokens = strategy.get('classification_tokens')  # Get LLM tokens used
    classification_source = strategy.get('classification_source', 'unknown')  # Get classification source

    # Build candidate arms - ALWAYS include all arms to allow bandit exploration
    use_graph_rag = strategy.get('use_graph_rag', False)
    q_lower = question.lower()
    graph_cues = [
        "relationship", "relationships", "relation", "relations",
        "role", "roles", "character", "characters", "family tree",
        "connection", "connections",
        "关系", "人物关系", "角色关系", "角色", "关系网", "图谱"
    ]
    if not use_graph_rag and any(cue in q_lower for cue in graph_cues):
        use_graph_rag = True
    use_table_rag = strategy.get('use_table_rag', False)

    # OPTIMIZATION: Constrain bandit arms based on query type to prevent slow strategies for simple queries
    # This balances exploration with user experience (latency)
    cue_hits = [c for c in graph_cues if c in q_lower]

    # Detect table-specific cues
    table_cues = ["table", "数据", "统计", "列", "行", "表格"]
    table_cue_hits = [c for c in table_cues if c in q_lower]

    # Force selection only when we have strong signals
    # - Multiple graph cues (2+)
    # - OR classifier explicitly requested graph AND we have cues
    force_graph = (len(cue_hits) >= 2) or (use_graph_rag and len(cue_hits) >= 1 and not use_table_rag)
    force_table = (len(table_cue_hits) >= 1) and use_table_rag

    if force_table:
        chosen_arm = "table"
        logger.info("Smart RAG forced table arm due to table cues/intent", cues=table_cue_hits)
    elif force_graph:
        chosen_arm = "graph"
        logger.info("Smart RAG forced graph arm due to graph cues/intent", cues=cue_hits)
    elif _bandit_enabled():
        # Constrain available arms based on query type
        # factual_detail (simple author queries) → only hybrid (fast)
        # complex_analysis → hybrid or iterative (allow bandit to learn)
        # general → all strategies (full exploration)
        if query_type == 'factual_detail':
            available_arms = ["hybrid"]
            logger.info("Query type factual_detail → constraining to hybrid only (fast)")
        elif query_type == 'complex_analysis':
            available_arms = ["hybrid", "iterative"]
            logger.info("Query type complex_analysis → constraining to hybrid/iterative")
        else:
            available_arms = ["hybrid", "iterative", "graph", "table"]
            logger.info("Query type general → allowing all strategies")

        chosen_arm = _choose_bandit_arm(available_arms)
        logger.info(f"Smart RAG bandit chose: {chosen_arm}", available=available_arms,
                   graph_hint=use_graph_rag, table_hint=use_table_rag)
    else:
        # Fallback when bandit disabled
        if use_table_rag:
            chosen_arm = "table"
        elif use_graph_rag:
            chosen_arm = "graph"
        else:
            simple_types = ['author_query', 'factual_detail', 'quote_search']
            chosen_arm = "hybrid" if query_type in simple_types else "iterative"

    # Safety net: escalate to specialized arms when we have cues
    # but only if bandit chose a basic strategy AND query type allows it
    # DON'T escalate factual_detail queries (simple author queries should stay fast)
    if cue_hits and chosen_arm in ["hybrid", "iterative"] and not table_cue_hits and query_type != 'factual_detail':
        logger.info("Smart RAG escalating to graph due to cues after bandit selection",
                   chosen=chosen_arm, cues=cue_hits)
        chosen_arm = "graph"
    elif table_cue_hits and chosen_arm in ["hybrid", "iterative"] and query_type != 'factual_detail':
        logger.info("Smart RAG escalating to table due to cues after bandit selection",
                   chosen=chosen_arm, cues=table_cue_hits)
        chosen_arm = "table"

    if chosen_arm == "table":
        logger.info(f"Using Table RAG for {query_type} query")
        from backend.services.table_rag import TableRAG
        from backend.services.rag_pipeline import _get_openai_client

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
            question=question,
            top_k=top_k or strategy.get('top_k', 20),
            hybrid_alpha=strategy.get('hybrid_alpha', 0.6)
        )

        timings = table_result.get('timings', {})
        timings['table_data'] = table_result.get('table_data')
        timings['query_intent'] = table_result.get('query_intent')

        response = RAGResponse(
            answer=table_result['answer'],
            citations=[],
            retrieval_time_ms=timings.get('intent_extraction_ms', 0) + timings.get('structuring_ms', 0),
            confidence=1.0,
            num_chunks_retrieved=table_result['num_chunks_retrieved'],
            llm_time_ms=timings.get('answer_generation_ms', 0),
            total_time_ms=timings.get('total_ms', 0),
            timings=timings,
            token_usage=table_result.get('token_usage'),
            llm_used=True,
            models={"llm": os.getenv("OPENAI_MODEL", "gpt-4o")}
        )
        response.selected_strategy = "Table RAG"
        response.strategy_reason = f"Chosen by bandit; query type: {query_type}. {strategy_description}"
    elif chosen_arm == "graph":
        logger.info(f"Using Graph RAG for {query_type} query")
        from backend.services.graph_rag_incremental import IncrementalGraphRAG
        from backend.services.rag_pipeline import _get_openai_client

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

        graph_result = await graph_rag.answer_question(
            question=question,
            top_k=top_k or strategy.get('top_k', 20),
            max_hops=2,
            enable_vector_retrieval=True
        )

        timings = graph_result.get('timings', {})
        timings['graph_context'] = graph_result.get('graph_context')
        timings['jit_stats'] = graph_result.get('jit_stats')
        timings['cache_hit'] = graph_result.get('cache_hit')
        timings['query_entities'] = graph_result.get('query_entities')

        response = RAGResponse(
            answer=graph_result['answer'],
            citations=[],
            retrieval_time_ms=timings.get('graph_query_ms', 0) + timings.get('vector_retrieval_ms', 0),
            confidence=1.0,
            num_chunks_retrieved=graph_result['graph_context']['num_entities'],
            llm_time_ms=timings.get('answer_generation_ms', 0),
            total_time_ms=timings.get('total_ms', 0),
            timings=timings,
            token_usage=graph_result.get('token_usage'),
            llm_used=True,
            models={"llm": os.getenv("OPENAI_MODEL", "gpt-4o")}
        )
        response.selected_strategy = "Graph RAG"
        response.strategy_reason = f"Chosen by bandit; query type: {query_type}. {strategy_description}"
    else:
        # hybrid / iterative
        if chosen_arm == "hybrid":
            response = await answer_question_hybrid(
                question=question,
                top_k=top_k or strategy.get('top_k', 5),
                use_llm=True,
                include_timings=include_timings,
                reranker_override=reranker,
                vector_limit=vector_limit or strategy.get('vector_limit'),
                content_char_limit=content_char_limit,
                use_cache=False,  # Cache handled at outer layer
                use_classifier=True
            )
            response.selected_strategy = "Hybrid RAG"
        else:
            self_rag = get_self_rag()
            response = await self_rag.ask_with_reflection(
                question=question,
                top_k=top_k or strategy.get('top_k', 10),
                use_hybrid=True,
                include_timings=include_timings
            )
            response.selected_strategy = "Iterative Self-RAG"
        response.strategy_reason = f"Chosen by bandit; query type: {query_type}. {strategy_description}"

    # Store chosen arm for reward update
    response._smart_chosen_arm = chosen_arm

    # Store classification tokens and query metadata in response for token breakdown and logging
    response._classification_tokens = classification_tokens
    response._classification_source = classification_source
    response._query_type = query_type
    response._mode = chosen_arm

    return response


@router.post("/ask-smart", response_model=RAGResponse)
async def ask_question_smart(request: RAGRequest) -> RAGResponse:
    """
    Smart RAG endpoint: automatically chooses between hybrid and iterative based on query complexity.

    Decision logic:
    - Simple queries (author, factual): Use hybrid search only (fast)
    - Complex queries (analysis, relationships): Use iterative Self-RAG

    This is the recommended endpoint for production use.

    Returns:
        RAGResponse with optimal strategy applied
    """
    # Start governance tracking
    governance_tracker = get_governance_tracker()
    gov_context = governance_tracker.start_operation(
        operation_type="rag",
        metadata={"question": request.question, "endpoint": "/ask-smart"}
    )
    start_time = time.time()

    try:
        logger.info("📝 RAG smart query received", trace_id=gov_context.trace_id)

        # Governance checkpoint: Policy gate
        governance_tracker.checkpoint_policy_gate(
            gov_context.trace_id,
            allowed=True,
            reason="R1 policy allows RAG queries with citations required"
        )

        # Governance checkpoint: Permission layers (G4)
        # For now, all users have "public" role - future: extract from auth token
        governance_tracker.checkpoint_permission(
            gov_context.trace_id,
            user_role="public",
            authorized=True,
            required_permissions=["rag:query"]
        )

        # Governance checkpoint: Privacy control (G5)
        # Simple PII detection for common patterns
        import re
        pii_patterns = {
            'email': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            'phone': r'\b(?:\+?1[-.]?)?\(?([0-9]{3})\)?[-.]?([0-9]{3})[-.]?([0-9]{4})\b',
            'ssn': r'\b\d{3}-\d{2}-\d{4}\b',
            'credit_card': r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'
        }
        detected_pii_types = []
        for pii_type, pattern in pii_patterns.items():
            if re.search(pattern, request.question):
                detected_pii_types.append(pii_type)

        governance_tracker.checkpoint_privacy(
            gov_context.trace_id,
            pii_detected=len(detected_pii_types) > 0,
            pii_masked=False,  # Not masking for now, just detecting
            pii_types=detected_pii_types
        )

        # Governance checkpoint: Data governance (G9)
        # Track data source and compliance - will be updated after retrieval
        governance_tracker.checkpoint_data_governance(
            gov_context.trace_id,
            data_sources=[COLLECTION_NAME],
            compliance_status="compliant",
            data_quality_score=1.0
        )

        # Governance checkpoint: Dashboard export (G12)
        # Metrics will be exported to Grafana via Prometheus
        governance_tracker.checkpoint_dashboard(
            gov_context.trace_id,
            metrics_exported=True,
            dashboard_type="grafana"
        )

        # Decide early whether to bypass answer cache for graph-heavy intents to avoid stale hybrid hits
        q_lower = request.question.lower()
        graph_cues = [
            "relationship", "relationships", "relation", "relations",
            "role", "roles", "character", "characters", "family tree",
            "connection", "connections",
            "关系", "人物关系", "角色关系", "角色", "关系网", "图谱"
        ]
        force_graph_path = any(cue in q_lower for cue in graph_cues)

        if force_graph_path:
            # Skip answer cache so we don't return an older hybrid answer
            response = await _smart_rag_logic(
                question=request.question,
                top_k=request.top_k,
                include_timings=request.include_timings,
                reranker=request.reranker,
                vector_limit=request.vector_limit,
                content_char_limit=request.content_char_limit
            )
        else:
            # Use answer cache wrapper
            from backend.services.answer_cache_wrapper import with_answer_cache
            response = await with_answer_cache(
                request.question,
                _smart_rag_logic,
                top_k=request.top_k,
                include_timings=request.include_timings,
                reranker=request.reranker,
                vector_limit=request.vector_limit,
                content_char_limit=request.content_char_limit
            )

        # Generate query_id for feedback tracking
        import uuid
        query_id = str(uuid.uuid4())
        response.query_id = query_id

        # Bandit reward update (online, unsupervised)
        try:
            if _bandit_enabled():
                arm = getattr(response, "_smart_chosen_arm", None)
                if arm in {"hybrid", "iterative", "graph", "table"}:
                    latency_budget = float(os.getenv("SMART_RAG_LATENCY_BUDGET_MS", "8000") or 8000)
                    conf = max(0.0, min(1.0, response.confidence or 0.0))
                    coverage = 1.0 if (response.num_chunks_retrieved or 0) > 0 else 0.0
                    latency_penalty = max(0.0, 1.0 - (response.total_time_ms or 0) / latency_budget)
                    # Weighted reward
                    reward = 0.4 * conf + 0.3 * coverage + 0.3 * latency_penalty
                    _update_bandit(arm, reward)
                    logger.info(f"Smart RAG bandit update", arm=arm, reward=f"{reward:.3f}")

                    # Track query for potential user feedback
                    # Preserve is_cached flag if it was set by answer_cache_wrapper
                    existing_entry = _query_history.get(query_id, {})
                    _query_history[query_id] = {
                        "strategy": arm,
                        "automated_reward": reward,
                        "timestamp": time.time(),
                        "question": request.question[:200],  # Truncate for privacy
                        "is_cached": existing_entry.get("is_cached", False),
                        "cache_layer": existing_entry.get("cache_layer", None),
                    }
                    # Keep only last 1000 queries in memory
                    if len(_query_history) > 1000:
                        oldest_id = min(_query_history.keys(), key=lambda k: _query_history[k]["timestamp"])
                        del _query_history[oldest_id]
        except Exception as bandit_error:
            logger.warning(f"Bandit reward update failed: {bandit_error}")

        # Log interaction
        try:
            data_monitor = get_data_monitor()
            token_usage = response.token_usage or {}
            avg_score = sum(c.score for c in response.citations) / len(response.citations) if response.citations else 0.0

            # Get query metadata from response (stored by _smart_rag_logic)
            mode = getattr(response, '_mode', 'unknown')
            query_type = getattr(response, '_query_type', 'general')

            data_monitor.log_rag_query(
                query=request.question,
                answer=response.answer,
                total_tokens=token_usage.get("total", 0),
                prompt_tokens=token_usage.get("prompt", 0),
                completion_tokens=token_usage.get("completion", 0),
                duration_ms=response.total_time_ms,
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                num_retrieved=response.num_chunks_retrieved,
                avg_score=avg_score,
                success=True,
                metadata={
                    "mode": f"smart-{mode}",
                    "query_type": query_type,
                    "confidence": response.confidence
                }
            )
        except Exception as monitor_error:
            logger.warning(f"Failed to log interaction: {monitor_error}")

        # Add detailed token breakdown
        token_usage = response.token_usage or {}

        # Get classification tokens from response (stored by _smart_rag_logic)
        classification_tokens = getattr(response, '_classification_tokens', None)
        classification_source = getattr(response, '_classification_source', 'unknown')

        # If answer came from cache, zero out tokens/cost for display
        if getattr(response, "cache_hit", False):
            response.token_breakdown = {
                "query_classification": {
                    "tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost": 0.0,
                    "method": "answer_cache",
                    "llm_used": False,
                    "cached": True
                },
                "answer_cache_lookup": {
                    "tokens": 0,
                    "cost": 0.0,
                    "cache_hit": True,
                    "llm_used": False
                },
                "answer_generation": {
                    "tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost": 0.0,
                    "llm_used": False,
                    "iterations": None
                },
                "total": {
                    "tokens": 0,
                    "cost": 0.0,
                    "llm_calls": 0
                }
            }

            # Add governance context to response (cache hit)
            governance_tracker.checkpoint_evidence(gov_context.trace_id, len(response.citations or []))
            governance_tracker.checkpoint_audit(gov_context.trace_id, audit_logged=True)
            governance_tracker.complete_operation(gov_context.trace_id)
            response.governance_context = gov_context.get_summary()

            return response

        # Calculate classification cost (approximate)
        classification_cost = 0.0
        classification_total_tokens = 0
        if classification_tokens:
            classification_total_tokens = classification_tokens.get('total', 0)
            # GPT-4o pricing: $2.50 per 1M input, $10 per 1M output
            prompt_cost = classification_tokens.get('prompt', 0) * (2.50 / 1_000_000)
            completion_cost = classification_tokens.get('completion', 0) * (10.0 / 1_000_000)
            classification_cost = prompt_cost + completion_cost

        response.token_breakdown = {
            "query_classification": {
                "tokens": classification_total_tokens,
                "prompt_tokens": classification_tokens.get('prompt', 0) if classification_tokens else 0,
                "completion_tokens": classification_tokens.get('completion', 0) if classification_tokens else 0,
                "cost": classification_cost,
                "method": classification_source,  # Show actual source (llm, exact_cache, semantic_cache, regex)
                "llm_used": classification_tokens is not None,
                "cached": classification_source in ['exact_cache', 'semantic_cache']
            },
            "answer_cache_lookup": {
                "tokens": 0,
                "cost": 0.0,
                "cache_hit": response.token_usage is None,
                "llm_used": False
            },
            "answer_generation": {
                "tokens": token_usage.get("total", 0),
                "prompt_tokens": token_usage.get("prompt", 0),
                "completion_tokens": token_usage.get("completion", 0),
                "cost": response.token_cost_usd or 0.0,
                "llm_used": response.token_usage is not None,
                "iterations": response.iteration_details if hasattr(response, 'iteration_details') else None
            },
            "total": {
                "tokens": classification_total_tokens + token_usage.get("total", 0),
                "cost": classification_cost + (response.token_cost_usd or 0.0),
                "llm_calls": (1 if classification_tokens else 0) + (1 if response.token_usage else 0)
            }
        }

        # Add governance checkpoints
        governance_tracker.checkpoint_retrieval(
            gov_context.trace_id,
            num_chunks=response.num_chunks_retrieved,
            collections=[COLLECTION_NAME]
        )
        governance_tracker.checkpoint_evidence(
            gov_context.trace_id,
            num_citations=len(response.citations or []),
            citation_quality="good" if len(response.citations or []) >= 2 else "low"
        )
        governance_tracker.checkpoint_generation(
            gov_context.trace_id,
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            prompt_version="v1.0"
        )
        governance_tracker.checkpoint_quality(
            gov_context.trace_id,
            latency_ms=response.total_time_ms,
            quality_score=response.confidence
        )
        governance_tracker.checkpoint_audit(gov_context.trace_id, audit_logged=True)
        governance_tracker.checkpoint_reliability(
            gov_context.trace_id,
            status="passed",
            message=f"Smart RAG completed successfully: {response.selected_strategy or 'unknown'}"
        )

        # Complete governance tracking and add to response
        governance_tracker.complete_operation(gov_context.trace_id)
        response.governance_context = gov_context.get_summary()

        return response
    except Exception as exc:
        logger.exception("❌ RAG smart query failed: %s", exc)

        # Log failure in governance
        try:
            governance_tracker.checkpoint_reliability(
                gov_context.trace_id,
                status="failed",
                message=f"RAG query failed: {str(exc)}"
            )
            governance_tracker.complete_operation(gov_context.trace_id)
        except:
            pass

        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/cache/stats")
async def cache_stats() -> Dict[str, Any]:
    """
    Get cache statistics for both query strategy cache and answer cache.

    Returns hit rate, cache size, and other performance metrics.
    """
    try:
        result = {}

        # Query Strategy Cache stats
        query_cache = get_query_cache()
        if query_cache is None:
            result["query_cache"] = {
                "enabled": False,
                "message": "Query cache is disabled. Set ENABLE_QUERY_CACHE=true to enable."
            }
        else:
            query_stats = query_cache.get_stats()
            result["query_cache"] = {
                "enabled": True,
                **query_stats
            }

        # Answer Cache stats
        answer_cache = get_answer_cache()
        if answer_cache is None:
            result["answer_cache"] = {
                "enabled": False,
                "message": "Answer cache is disabled. Set ENABLE_ANSWER_CACHE=true to enable."
            }
        else:
            answer_stats = answer_cache.get_stats()
            result["answer_cache"] = {
                "enabled": True,
                **answer_stats
            }

        return result
    except Exception as exc:
        logger.exception("Failed to get cache stats: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/smart-status")
async def smart_status() -> Dict[str, Any]:
    """Return Smart RAG bandit warm-up status."""
    try:
        return get_bandit_status()
    except Exception as exc:
        logger.warning("Failed to get smart bandit status: %s", exc)
        return {"enabled": False, "started": False, "done": False, "last_error": str(exc)}


@router.post("/cache/clear")
async def clear_cache() -> Dict[str, Any]:
    """Clear both query strategy cache and answer cache."""
    try:
        results = {}

        # Clear query strategy cache
        query_cache = get_query_cache()
        if query_cache is None:
            results["query_cache"] = "disabled"
        else:
            query_cache.clear()
            results["query_cache"] = "cleared"

        # Clear answer cache
        answer_cache = get_answer_cache()
        if answer_cache is None:
            results["answer_cache"] = "disabled"
        else:
            answer_cache.clear()
            results["answer_cache"] = "cleared"

        return {
            "message": "Cache clearing completed",
            **results
        }
    except Exception as exc:
        logger.exception("Failed to clear cache: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/ask-stream")
async def ask_stream(request: RAGRequest):
    """
    🔥 Streaming RAG endpoint - Returns answer chunks as they're generated

    Uses Server-Sent Events (SSE) to stream the LLM response in real-time,
    providing a smooth typing effect instead of waiting for the full response.

    Event types:
    - "retrieval": Sent after document retrieval with citations
    - "content": LLM response chunks (streamed word-by-word)
    - "metadata": Final metadata (tokens, cost, timing)
    - "done": End of stream
    - "error": Error occurred
    """
    try:
        _ensure_vector_collection()

        # Validate parameters
        top_k = min(max(request.top_k, 1), 20)
        vector_limit = request.vector_limit
        if vector_limit is not None:
            vector_limit = min(max(vector_limit, VECTOR_LIMIT_MIN), VECTOR_LIMIT_MAX)

        async def generate():
            """SSE generator function"""
            tic_total = time.perf_counter()

            try:
                # Step 0: Check answer cache FIRST (for streaming endpoint)
                from backend.services.enhanced_rag_pipeline import _get_answer_cache
                answer_cache = _get_answer_cache()
                if answer_cache:
                    try:
                        cached = await answer_cache.find_cached_answer(request.question)
                        if cached:
                            logger.info(
                                "Answer cache HIT (streaming) - returning cached answer",
                                query=request.question[:50],
                                layer=cached['cache_layer'],
                                method=cached['cache_method'],
                                similarity=f"{cached['similarity']:.3f}"
                            )
                            # Stream the cached answer as if it was generated
                            cached_response = cached['answer']

                            # Send retrieval event with cached data
                            yield {
                                "event": "retrieval",
                                "data": json.dumps({
                                    "num_chunks": cached_response.num_chunks_retrieved or 0,
                                    "retrieval_time_ms": 0,
                                    "citations": cached_response.citations or [],
                                    "cached": True
                                })
                            }

                            # Send cached answer directly (no typing simulation - answer already exists)
                            answer_text = cached_response.answer or ""
                            # Send complete answer in one chunk since it's from cache
                            yield {
                                "event": "content",
                                "data": answer_text
                            }

                            # Send metadata with cached flag and zero token usage
                            total_ms = (time.perf_counter() - tic_total) * 1000
                            yield {
                                "event": "metadata",
                                "data": json.dumps({
                                    "total_time_ms": total_ms,
                                    "retrieval_time_ms": 0,
                                    "llm_time_ms": 0,
                                    "cached": True,
                                    "cache_layer": cached['cache_layer'],
                                    "model": cached_response.models.get("llm") if cached_response.models else "cached",
                                    "token_usage": {
                                        "prompt_tokens": 0,
                                        "completion_tokens": 0,
                                        "total_tokens": 0
                                    },
                                    "cost_usd": 0.0
                                })
                            }

                            yield {"event": "done", "data": "[DONE]"}
                            return
                    except Exception:
                        pass  # Silently continue if cache lookup fails

                # Step 1: Retrieve documents (non-streaming)
                tic_retrieval = time.perf_counter()
                result = await retrieve_chunks(
                    question=request.question,
                    top_k=top_k,
                    reranker_override=request.reranker,
                    vector_limit_override=vector_limit,
                    include_timings=request.include_timings
                )

                # Unpack tuple (chunks, retrieval_time_ms) or (chunks, retrieval_time_ms, timings)
                timings = {}
                if isinstance(result, tuple):
                    if len(result) == 3:
                        chunks, retrieval_ms, timings = result
                    else:
                        chunks = result[0]
                        retrieval_ms = result[1] if len(result) > 1 else 0.0
                else:
                    chunks = result
                    retrieval_ms = 0.0

                if not retrieval_ms:
                    retrieval_ms = (time.perf_counter() - tic_retrieval) * 1000

                if not chunks:
                    yield {
                        "event": "error",
                        "data": json.dumps({"error": "No relevant documents found"})
                    }
                    yield {"event": "done", "data": "[DONE]"}
                    return

                # Send retrieval metadata with citations
                from backend.models.rag_schemas import Citation
                citations = [
                    {
                        "source": chunk.source,
                        "content": chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content,
                        "score": chunk.score
                    }
                    for chunk in chunks
                ]

                yield {
                    "event": "retrieval",
                    "data": json.dumps({
                        "num_chunks": len(chunks),
                        "retrieval_time_ms": retrieval_ms,
                        "citations": citations
                    })
                }

                # Step 2: Stream LLM generation
                llm_model = os.getenv("OPENAI_MODEL") or settings.OPENAI_MODEL or "gpt-4o-mini"

                # Collect full answer for caching
                full_answer = ""
                final_metadata = {}

                async for chunk in _generate_answer_with_llm_stream(
                    question=request.question,
                    chunks=chunks,
                    model=llm_model
                ):
                    if chunk["type"] == "content":
                        # Stream content chunks and collect full answer
                        content = chunk["data"]
                        full_answer += content
                        yield {
                            "event": "content",
                            "data": content
                        }
                    elif chunk["type"] == "metadata":
                        # Send final metadata
                        total_ms = (time.perf_counter() - tic_total) * 1000
                        metadata = chunk["data"]
                        metadata["retrieval_time_ms"] = retrieval_ms
                        metadata["total_time_ms"] = total_ms

                        # Include detailed timings if available
                        if timings:
                            metadata["timings"] = timings

                        final_metadata = metadata

                        yield {
                            "event": "metadata",
                            "data": json.dumps(metadata)
                        }
                    elif chunk["type"] == "error":
                        yield {
                            "event": "error",
                            "data": json.dumps({"error": chunk["data"]})
                        }

                # Step 3: Save to answer cache for future queries
                if answer_cache and full_answer:
                    try:
                        from backend.models.rag_schemas import RAGResponse, Citation
                        # Build RAGResponse for caching
                        citations_list = [
                            Citation(
                                source=c.get("source", "Unknown"),
                                content=c.get("content", ""),
                                score=float(c.get("score", 0.0))
                            )
                            for c in citations
                        ]
                        cache_response = RAGResponse(
                            answer=full_answer,
                            num_chunks_retrieved=len(chunks),
                            citations=citations_list,
                            models={"llm": llm_model},
                            confidence=1.0,  # Streaming doesn't calculate confidence
                            total_time_ms=final_metadata.get("total_time_ms", 0),
                            retrieval_time_ms=retrieval_ms,
                            llm_time_ms=final_metadata.get("llm_time_ms", 0)
                        )
                        await answer_cache.cache_answer(request.question, cache_response)
                        logger.info(f"Answer cached successfully (streaming) query={request.question[:50]}")
                    except Exception as e:
                        logger.error(f"Failed to cache streaming answer: {e}")

                # Send completion
                yield {"event": "done", "data": "[DONE]"}

            except Exception as e:
                logger.exception(f"❌ Streaming RAG failed: {e}")
                yield {
                    "event": "error",
                    "data": json.dumps({"error": str(e)})
                }
                yield {"event": "done", "data": "[DONE]"}

        return EventSourceResponse(generate())

    except Exception as exc:
        logger.exception("❌ RAG streaming endpoint failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/ask-graph")
async def ask_question_graph_rag(request: RAGRequest) -> Dict[str, Any]:
    """
    Answer a question using Incremental Graph RAG with JIT building.

    This endpoint:
    - Extracts entities from the query
    - Checks if entities exist in the knowledge graph
    - JIT builds missing entities from Qdrant
    - Queries the graph for relationships
    - Combines graph context with vector retrieval
    - Generates an answer using LLM

    Best for relationship-based queries like:
    - "How are X and Y related?"
    - "What is the connection between X and Y?"
    - "What skills are needed for X?"

    Returns:
        Answer with graph context, JIT statistics, and timings
    """
    try:
        logger.info(
            "📊 Graph RAG query received",
            extra={"question": request.question[:120], "top_k": request.top_k}
        )

        # Get or initialize Graph RAG instance
        from backend.services.graph_rag_incremental import IncrementalGraphRAG
        from backend.services.rag_pipeline import _get_openai_client

        openai_client = _get_openai_client()
        qdrant_client = get_qdrant_client()

        # Initialize Graph RAG (consider caching this instance for performance)
        # Use gpt-4o for extraction since API key doesn't have access to gpt-4o-mini
        max_jit_chunks = int(os.getenv("GRAPH_JIT_MAX_CHUNKS", os.getenv("GRAPH_MAX_JIT_CHUNKS", "20")))
        graph_rag = IncrementalGraphRAG(
            openai_client=openai_client,
            qdrant_client=qdrant_client,
            collection_name=COLLECTION_NAME,
            extraction_model=os.getenv("OPENAI_MODEL", "gpt-4o"),  # Use same model as generation
            generation_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            max_jit_chunks=max_jit_chunks
        )

        # Answer question with Graph RAG
        response = await graph_rag.answer_question(
            question=request.question,
            top_k=request.top_k or 5,
            max_hops=2,  # Graph traversal depth
            enable_vector_retrieval=True  # Combine with vector search
        )

        # Log summary for troubleshooting
        try:
            gc = response.get('graph_context', {}) if isinstance(response, dict) else {}
            logger.info(
                "Graph RAG completed",
                extra={
                    "entities": gc.get('num_entities'),
                    "relationships": gc.get('num_relationships'),
                    "jit_chunks": (response.get('jit_stats') or {}).get('chunks_processed') if isinstance(response, dict) else None,
                    "cache_hit": (response.get('cache_hit') if isinstance(response, dict) else None)
                }
            )
        except Exception:
            pass

        # Log interaction for drift monitoring
        try:
            data_monitor = get_data_monitor()
            model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

            token_usage = response.get('token_usage', {})
            prompt_tokens = token_usage.get("prompt_tokens", 0)
            completion_tokens = token_usage.get("completion_tokens", 0)
            total_tokens = token_usage.get("total_tokens", 0)

            data_monitor.log_rag_query(
                query=request.question,
                answer=response['answer'],
                total_tokens=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                duration_ms=response['timings']['total_ms'],
                model=model_name,
                num_retrieved=response['graph_context']['num_entities'],
                avg_score=0.0,  # Graph doesn't use scores
                success=True,
                metadata={
                    "mode": "graph_rag",
                    "cache_hit": response['cache_hit'],
                    "jit_stats": response.get('jit_stats'),
                    "graph_stats": response.get('graph_stats'),
                    "num_relationships": response['graph_context']['num_relationships']
                }
            )
        except Exception as monitor_error:
            logger.warning(f"Failed to log Graph RAG interaction to data monitor: {monitor_error}")

        return response

    except Exception as exc:
        logger.exception("❌ Graph RAG query failed: %s", exc)

        # Log failed interaction
        try:
            data_monitor = get_data_monitor()
            model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            data_monitor.log_rag_query(
                query=request.question,
                answer="",
                total_tokens=0,
                prompt_tokens=0,
                completion_tokens=0,
                duration_ms=0,
                model=model_name,
                num_retrieved=0,
                avg_score=0.0,
                success=False,
                metadata={"error": str(exc), "mode": "graph_rag"}
            )
        except Exception as monitor_error:
            logger.warning(f"Failed to log failed Graph RAG interaction: {monitor_error}")

        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/graph-stats")
async def get_graph_stats() -> Dict[str, Any]:
    """
    Get current knowledge graph statistics.

    Returns:
        Statistics about entities, relationships, and coverage
    """
    try:
        from backend.services.graph_rag_incremental import IncrementalGraphRAG
        from backend.services.rag_pipeline import _get_openai_client

        openai_client = _get_openai_client()
        qdrant_client = get_qdrant_client()

        # Get existing instance stats (or create new if needed)
        graph_rag = IncrementalGraphRAG(
            openai_client=openai_client,
            qdrant_client=qdrant_client,
            collection_name=COLLECTION_NAME
        )

        stats = graph_rag.get_stats()
        return stats

    except Exception as exc:
        logger.exception("❌ Failed to get graph stats: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/ask-table")
async def ask_question_table_rag(request: RAGRequest) -> Dict[str, Any]:
    """
    Answer a question using Table RAG for structured data presentation.

    This endpoint:
    - Analyzes query intent (comparison, list, aggregation)
    - Retrieves relevant chunks using hybrid search
    - Structures data into table format
    - Generates answer with table context

    Best for queries like:
    - "Compare X and Y"
    - "List all the tools mentioned"
    - "What are the differences between X and Y?"
    - "Show me all characters and their traits"

    Returns:
        Answer with structured table data, query intent, and timings
    """
    try:
        logger.info("📊 Table RAG query received")

        # Get or initialize Table RAG instance
        from backend.services.table_rag import TableRAG
        from backend.services.rag_pipeline import _get_openai_client

        openai_client = _get_openai_client()
        qdrant_client = get_qdrant_client()

        # Initialize Table RAG
        table_rag = TableRAG(
            openai_client=openai_client,
            qdrant_client=qdrant_client,
            collection_name=COLLECTION_NAME,
            extraction_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            generation_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        )

        # Answer question with Table RAG
        response = await table_rag.answer_question(
            question=request.question,
            top_k=request.top_k or 20,
            hybrid_alpha=0.6  # Balance between vector and BM25
        )

        # Log interaction for drift monitoring
        try:
            data_monitor = get_data_monitor()
            model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

            data_monitor.log_rag_query(
                query=request.question,
                answer=response['answer'],
                total_tokens=response.get('total_tokens', 0),
                prompt_tokens=0,  # Table RAG has separate token tracking
                completion_tokens=0,
                duration_ms=response['timings']['total_ms'],
                model=model_name,
                num_retrieved=response['num_chunks_retrieved'],
                avg_score=0.0,
                success=True,
                metadata={
                    "mode": "table_rag",
                    "query_intent": response.get('query_intent'),
                    "num_table_rows": len(response['table_data'].get('rows', [])),
                    "num_table_cols": len(response['table_data'].get('headers', [])),
                }
            )
        except Exception as monitor_error:
            logger.warning(f"Failed to log Table RAG interaction to data monitor: {monitor_error}")

        return response

    except Exception as exc:
        logger.exception("❌ Table RAG query failed: %s", exc)

        # Log failed interaction
        try:
            data_monitor = get_data_monitor()
            model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            data_monitor.log_rag_query(
                query=request.question,
                answer="",
                total_tokens=0,
                prompt_tokens=0,
                completion_tokens=0,
                duration_ms=0,
                model=model_name,
                num_retrieved=0,
                avg_score=0.0,
                success=False,
                metadata={"error": str(exc), "mode": "table_rag"}
            )
        except Exception as monitor_error:
            logger.warning(f"Failed to log failed Table RAG interaction: {monitor_error}")

        raise HTTPException(status_code=500, detail=str(exc))


# === Multi-Collection Management Endpoints ===

@router.get("/user-collections/stats")
async def get_user_collection_stats() -> Dict[str, Any]:
    """Get user upload collection statistics."""
    try:
        client = get_qdrant_client()

        # Check if user collection exists
        try:
            info = client.get_collection(collection_name="user_uploaded_docs")
            return {
                "exists": True,
                "total_points": info.points_count,
                "vector_size": info.config.params.vectors.size,
                "status": info.status
            }
        except Exception:
            return {
                "exists": False,
                "total_points": 0,
                "message": "User collection not created yet"
            }
    except Exception as exc:
        logger.exception(f"Failed to get user collection stats: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/user-collections/clear")
async def clear_user_collection() -> Dict[str, Any]:
    """Clear all user uploaded data."""
    try:
        client = get_qdrant_client()

        try:
            client.delete_collection(collection_name="user_uploaded_docs")
            logger.info("✅ User collection cleared")
            return {
                "success": True,
                "message": "User uploaded data cleared successfully"
            }
        except Exception as exc:
            logger.warning(f"Collection may not exist: {exc}")
            return {
                "success": True,
                "message": "No user data to clear"
            }
    except Exception as exc:
        logger.exception(f"Failed to clear user collection: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/search-multi-collection")
async def search_multi_collection(request: RAGRequest) -> RAGResponse:
    """
    Search across multiple collections with scope control.

    search_scope options (in request.metadata):
    - "all": Search both system and user collections (default)
    - "user_only": Search only user uploaded files
    - "system_only": Search only system data
    """
    try:
        # Get search scope from metadata
        search_scope = "all"
        requested_strategy = None
        if request.metadata and "search_scope" in request.metadata:
            search_scope = request.metadata["search_scope"]
            requested_strategy = request.metadata.get("requested_strategy")
        elif request.metadata:
            requested_strategy = request.metadata.get("requested_strategy")

        # Determine which collections to search
        collections_to_search = []
        if search_scope == "all":
            collections_to_search = [COLLECTION_NAME, "user_uploaded_docs"]
        elif search_scope == "user_only":
            collections_to_search = ["user_uploaded_docs"]
        else:  # system_only
            collections_to_search = [COLLECTION_NAME]

        # If smart strategy requested, delegate to Smart RAG logic (which has bandit, graph cues, etc.)
        # but only for system-only search (Smart RAG doesn't support multi-collection yet)
        if requested_strategy == "smart" and search_scope == "system_only":
            logger.info(f"Delegating to Smart RAG (multi-collection endpoint, system-only scope)")
            # Call smart RAG logic directly
            response = await _smart_rag_logic(
                question=request.question,
                top_k=request.top_k,
                include_timings=request.include_timings,
                reranker=request.reranker,
                vector_limit=request.vector_limit,
                content_char_limit=request.content_char_limit
            )
            # Update strategy labels to indicate multi-collection endpoint
            if response.selected_strategy:
                response.selected_strategy += " (multi-collection)"
            return response

        # Answer cache: check first
        from backend.services.enhanced_rag_pipeline import _get_answer_cache
        answer_cache = _get_answer_cache()
        if answer_cache:
            try:
                cached = await answer_cache.find_cached_answer(request.question)
                if cached:
                    logger.info(
                        "Answer cache HIT (multi-collection)",
                        query=request.question[:50],
                        layer=cached['cache_layer'],
                        method=cached['cache_method'],
                        similarity=f"{cached['similarity']:.3f}",
                    )
                    cached_response = cached['answer']
                    cached_response.cache_hit = True
                    cached_response.selected_strategy = f"{(requested_strategy or 'hybrid').title()} (multi-collection)"
                    cached_response.strategy_reason = (
                        f"Search scope: {search_scope}; "
                        f"collections: {', '.join(collections_to_search)}; "
                        "strategy requested by client (cached)"
                    )
                    return cached_response
            except Exception as e:
                logger.warning(f"Answer cache lookup failed (multi-collection): {e}")

        total_start = time.perf_counter()
        retrieval_ms = 0.0
        timings_agg: Dict[str, Any] = {
            "embed_ms": 0.0,
            "vector_ms": 0.0,
            "candidate_prep_ms": 0.0,
            "rerank_ms": 0.0,
            "total_ms": 0.0,
        }
        last_reranker_mode: Optional[str] = None
        last_reranker_model_path: Optional[str] = None
        last_vector_limit_used: Optional[int] = None
        last_content_char_limit_used: Optional[int] = None

        # Retrieve chunks from multiple collections
        all_chunks = []
        for coll in collections_to_search:
            try:
                coll_start = time.perf_counter()
                chunks, score, coll_timings = await retrieve_chunks(
                    request.question,
                    top_k=request.top_k or 10,
                    collection_name=coll,
                    include_timings=True,
                )
                retrieval_ms += (time.perf_counter() - coll_start) * 1000

                # Aggregate timings across collections
                if coll_timings:
                    timings_agg["embed_ms"] += float(coll_timings.get("embed_ms", 0.0) or 0.0)
                    timings_agg["vector_ms"] += float(coll_timings.get("vector_ms", 0.0) or 0.0)
                    timings_agg["candidate_prep_ms"] += float(coll_timings.get("candidate_prep_ms", 0.0) or 0.0)
                    timings_agg["rerank_ms"] += float(coll_timings.get("rerank_ms", 0.0) or 0.0)
                    timings_agg["total_ms"] += float(coll_timings.get("total_ms", 0.0) or 0.0)
                    last_reranker_mode = coll_timings.get("reranker_mode", last_reranker_mode)
                    last_reranker_model_path = coll_timings.get("reranker_model_path", last_reranker_model_path)
                    last_vector_limit_used = coll_timings.get("vector_limit_used", last_vector_limit_used)
                    last_content_char_limit_used = coll_timings.get("content_char_limit_used", last_content_char_limit_used)

                all_chunks.extend(chunks)
            except Exception as e:
                logger.warning(f"Failed to search collection {coll}: {e}")
                continue

        # Sort by score and return top_k
        all_chunks.sort(key=lambda x: x.score, reverse=True)
        final_chunks = all_chunks[:request.top_k or 10]

        # Generate answer using LLM
        from backend.services.rag_pipeline import _generate_answer_with_llm
        import os
        llm_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        llm_start = time.perf_counter()
        answer, token_usage, token_cost = await _generate_answer_with_llm(
            request.question,
            final_chunks,
            model=llm_model
        )
        llm_ms = (time.perf_counter() - llm_start) * 1000
        total_ms = (time.perf_counter() - total_start) * 1000

        # Build citations
        citations = [
            Citation(
                source=chunk.source,
                content=chunk.content,
                score=chunk.score,
                metadata=chunk.metadata,
            )
            for chunk in final_chunks
        ]

        # Resolve current embed/rerank models
        try:
            current_embed = get_current_embed_path()
        except Exception:
            current_embed = os.getenv("ONNX_EMBED_MODEL_PATH", "unknown")
        try:
            current_rerank = get_current_reranker_path()
        except Exception:
            current_rerank = os.getenv("ONNX_RERANK_MODEL_PATH", "unknown")

        # Build response
        response = RAGResponse(
            answer=answer,
            citations=citations,
            num_chunks_retrieved=len(final_chunks),
            confidence=max([c.score for c in final_chunks]) if final_chunks else 0.0,
            retrieval_time_ms=retrieval_ms,
            llm_time_ms=llm_ms,
            total_time_ms=total_ms,
            token_usage=token_usage,
            token_cost_usd=token_cost,
            llm_used=True,
            search_scope=search_scope,
            collections_searched=collections_to_search,
            selected_strategy=f"{(requested_strategy or 'hybrid').title()} (multi-collection)",
            strategy_reason=(
                f"Search scope: {search_scope}; "
                f"collections: {', '.join(collections_to_search)}; "
                "strategy requested by client"
            ),
            models={
                "embedding": current_embed,
                "reranker": current_rerank,
                "llm": llm_model
            },
            timings={
                **timings_agg,
                "llm_ms": llm_ms,
                "vector_limit_used": last_vector_limit_used,
                "content_char_limit_used": last_content_char_limit_used,
                "reranker_mode": last_reranker_mode,
                "reranker_model_path": last_reranker_model_path,
            },
        )

        # Save to answer cache for future hits
        if answer_cache:
            try:
                await answer_cache.cache_answer(request.question, response)
                logger.info(f"Answer cached (multi-collection) query={request.question[:50]}")
            except Exception as e:
                logger.warning(f"Failed to cache answer (multi-collection): {e}")

        # Explicitly mark as fresh generation
        response.cache_hit = False

        # Return response
        return response

    except Exception as exc:
        logger.exception(f"Multi-collection search failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(feedback: UserFeedback) -> FeedbackResponse:
    """
    Submit user feedback on a RAG response to refine bandit learning.

    User feedback allows manual correction when automated reward metrics
    incorrectly evaluate strategy quality. User ratings override automated
    metrics with 70% weight in the bandit update.

    Args:
        feedback: UserFeedback with query_id and rating (0.0-1.0)
            - 1.0: Satisfied/correct answer
            - 0.5: Neutral/acceptable answer
            - 0.0: Unsatisfied/incorrect answer

    Returns:
        FeedbackResponse with confirmation and updated strategy info
    """
    try:
        query_id = feedback.query_id

        # Check if query exists in history
        if query_id not in _query_history:
            raise HTTPException(
                status_code=404,
                detail=f"Query ID not found. Query may be too old (only last 1000 queries tracked) or invalid."
            )

        query_info = _query_history[query_id]
        strategy = query_info["strategy"]
        automated_reward = query_info["automated_reward"]
        user_rating = feedback.rating
        is_cached = query_info.get("is_cached", False)

        # Debug logging
        logger.debug(
            "Feedback received - query_info details",
            query_id=query_id,
            strategy=strategy,
            is_cached=is_cached,
            cache_layer=query_info.get("cache_layer"),
            has_cache_fields=("cache_layer" in query_info)
        )

        # 🆕 Handle cached answer feedback
        if is_cached:
            cache_layer = query_info.get("cache_layer", "unknown")

            if user_rating < 0.5:
                # Negative feedback on cached answer - invalidate cache
                try:
                    from backend.services.enhanced_rag_pipeline import _get_answer_cache
                    answer_cache = _get_answer_cache()
                    if answer_cache:
                        # Invalidate the cached answer for this question
                        question = query_info["question"]
                        await answer_cache.invalidate(question)

                        logger.warning(
                            "Cache invalidated due to negative user feedback",
                            query_id=query_id,
                            rating=user_rating,
                            cache_layer=cache_layer,
                            question_preview=question[:50],
                            comment=feedback.comment
                        )
                except Exception as cache_error:
                    logger.error(f"Failed to invalidate cache: {cache_error}")

                # Mark query as feedback-processed
                query_info["user_feedback"] = user_rating
                query_info["feedback_comment"] = feedback.comment
                query_info["feedback_timestamp"] = time.time()

                return FeedbackResponse(
                    query_id=query_id,
                    rating=user_rating,
                    strategy_updated="cached",
                    bandit_updated=False,
                    message=f"Cache cleared (layer: {cache_layer}). Next query will re-execute RAG pipeline."
                )
            else:
                # Positive/neutral feedback on cached answer
                logger.info(
                    "Positive feedback on cached answer",
                    query_id=query_id,
                    rating=user_rating,
                    cache_layer=cache_layer,
                    comment=feedback.comment
                )

                # Mark query as feedback-processed
                query_info["user_feedback"] = user_rating
                query_info["feedback_comment"] = feedback.comment
                query_info["feedback_timestamp"] = time.time()

                return FeedbackResponse(
                    query_id=query_id,
                    rating=user_rating,
                    strategy_updated="cached",
                    bandit_updated=False,
                    message="Thank you for feedback! Cached answer quality confirmed."
                )

        # 🆕 Original logic: Non-cached answer bandit update
        # Re-update bandit with user feedback
        if _bandit_enabled():
            _update_bandit(strategy, automated_reward, user_rating=user_rating)

            logger.info(
                f"User feedback applied",
                query_id=query_id,
                strategy=strategy,
                user_rating=user_rating,
                automated_reward=f"{automated_reward:.3f}",
                question_preview=query_info["question"][:50],
                comment=feedback.comment
            )

            # Mark query as feedback-processed
            query_info["user_feedback"] = user_rating
            query_info["feedback_comment"] = feedback.comment
            query_info["feedback_timestamp"] = time.time()

            return FeedbackResponse(
                query_id=query_id,
                rating=user_rating,
                strategy_updated=strategy,
                bandit_updated=True,
                message=f"Feedback applied to {strategy} strategy. Bandit weights updated."
            )
        else:
            return FeedbackResponse(
                query_id=query_id,
                rating=user_rating,
                strategy_updated=None,
                bandit_updated=False,
                message="Feedback received but bandit learning is disabled."
            )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Feedback submission failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

"""
Utility helpers for bootstrapping a local Qdrant collection from a seed file.

This module intentionally avoids importing the heavy qdrant_client package so that
it can run in constrained environments (such as unit tests) without native
dependencies. It relies purely on HTTP requests to the Qdrant REST API.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import requests

from backend.config.settings import settings

logger = logging.getLogger(__name__)


DEFAULT_VECTOR_SIZE = int(os.getenv("QDRANT_SEED_VECTOR_SIZE", "1024"))
DEFAULT_TARGET_COUNT = int(os.getenv("QDRANT_SEED_TARGET_COUNT", "138000"))  # Updated for full corpus
DEFAULT_BATCH_SIZE = int(os.getenv("QDRANT_SEED_BATCH_SIZE", "200"))
DEFAULT_MAX_WORKERS = int(os.getenv("QDRANT_SEED_MAX_WORKERS", "4"))  # Parallel upload workers

_seed_lock = threading.Lock()
_seed_status: Dict[str, Optional[float]] = {
    "state": "idle",
    "seeded": 0,
    "total": DEFAULT_TARGET_COUNT,
    "message": "",
    "started_at": None,
    "finished_at": None,
}
_uploaded_counter = 0  # Thread-safe counter for parallel uploads


def _set_seed_status(**updates: object) -> None:
    with _seed_lock:
        _seed_status.update(updates)


def get_seed_status() -> Dict[str, object]:
    with _seed_lock:
        return dict(_seed_status)


def _base_url() -> str:
    return f"http://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}"


def _collection_endpoint(collection: str) -> str:
    return f"{_base_url()}/collections/{collection}"


def _points_endpoint(collection: str) -> str:
    return f"{_collection_endpoint(collection)}/points?wait=true"


def _read_seed_lines(seed_path: Path) -> Iterable[Dict]:
    with seed_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _fetch_collection_info(collection: str) -> Optional[Dict]:
    response = requests.get(_collection_endpoint(collection), timeout=10)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json().get("result", {})


def _delete_collection(collection: str) -> None:
    response = requests.delete(_collection_endpoint(collection), timeout=30)
    if response.status_code not in (200, 202, 404):
        response.raise_for_status()


def _create_collection(collection: str, vector_size: int) -> None:
    payload = {
        "vectors": {
            "size": vector_size,
            "distance": "Cosine",
        },
    }
    response = requests.put(_collection_endpoint(collection), json=payload, timeout=30)
    response.raise_for_status()


def _upload_points(collection: str, points: Iterable[Dict]) -> None:
    batch = {"points": list(points)}
    if not batch["points"]:
        return
    response = requests.put(_points_endpoint(collection), json=batch, timeout=60)
    response.raise_for_status()


def _upload_batch_with_progress(
    collection: str,
    batch: List[Dict],
    batch_num: int,
    total_points: int,
    started_at: float,
) -> int:
    """Upload a single batch and update progress counter. Returns number of points uploaded."""
    global _uploaded_counter

    try:
        _upload_points(collection, batch)
        batch_size = len(batch)

        # Thread-safe counter update
        with _seed_lock:
            _uploaded_counter += batch_size
            current_count = _uploaded_counter

        # Update status
        _set_seed_status(
            state="in_progress",
            message=f"Uploading batch {batch_num} ({current_count}/{total_points} vectors)",
            seeded=current_count,
            total=total_points,
            started_at=started_at,
            finished_at=None,
        )

        logger.info(f"✓ Batch {batch_num}: uploaded {batch_size} vectors ({current_count}/{total_points})")
        return batch_size
    except Exception as exc:
        logger.error(f"✗ Batch {batch_num} failed: {exc}")
        raise


def ensure_seed_collection(
    *,
    seed_path: Path = Path(os.getenv("QDRANT_SEED_PATH", "data/qdrant_seed/assessment_docs_minilm.jsonl")),
    target_count: int = DEFAULT_TARGET_COUNT,
    vector_size: int = DEFAULT_VECTOR_SIZE,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> Dict[str, int]:
    """
    Ensure that the configured Qdrant collection is populated with seed data.

    Returns a summary describing actions taken.
    """
    collection_name = settings.QDRANT_COLLECTION

    if not seed_path.exists():
        logger.warning("Seed file %s not found; skipping Qdrant bootstrap", seed_path)
        _set_seed_status(
            state="error",
            message=f"Seed file missing ({seed_path})",
            seeded=0,
            total=0,
            started_at=time.time(),
            finished_at=time.time(),
        )
        return {"seed_missing": 1}

    started_at = time.time()
    uploaded = 0
    total_points = target_count

    try:
        _set_seed_status(
            state="checking",
            message="Checking existing Qdrant collection",
            seeded=0,
            total=total_points,
            started_at=started_at,
            finished_at=None,
        )

        logger.info("Checking Qdrant collection '%s' for seed data", collection_name)
        info = _fetch_collection_info(collection_name)

        if info:
            existing_count = int(info.get("vectors_count", 0))
            if existing_count >= target_count:
                logger.info(
                    "Qdrant collection already seeded (vectors: %s >= target %s)",
                    existing_count,
                    target_count,
                )
                _set_seed_status(
                    state="completed",
                    message="Collection already seeded",
                    seeded=existing_count,
                    total=max(existing_count, target_count),
                    started_at=started_at,
                    finished_at=time.time(),
                )
                return {"skipped": existing_count}

            logger.info(
                "Existing collection has %s vectors (< %s target) - recreating",
                existing_count,
                target_count,
            )
            _delete_collection(collection_name)

        # Count total seed vectors for progress reporting
        try:
            counted_points = sum(1 for _ in _read_seed_lines(seed_path))
            if counted_points:
                total_points = counted_points
                target_count = counted_points
        except Exception as exc:
            logger.warning(
                "Failed to count seed file (%s), falling back to target_count. Error: %s",
                seed_path,
                exc,
            )

        _set_seed_status(
            state="initializing",
            message="Creating Qdrant collection",
            seeded=0,
            total=total_points,
            started_at=started_at,
            finished_at=None,
        )

        logger.info("Creating Qdrant collection '%s' (vector size %s)", collection_name, vector_size)
        try:
            _create_collection(collection_name, vector_size)
        except requests.HTTPError as exc:
            status_code = getattr(exc.response, "status_code", None)
            if status_code == 409:
                logger.info("Qdrant collection '%s' already exists; continuing with seed upload", collection_name)
            else:
                raise

        logger.info("Uploading seed vectors from %s (parallel workers: %d)", seed_path, max_workers)
        _set_seed_status(
            state="in_progress",
            message=f"Uploading seed vectors ({max_workers} parallel workers)",
            seeded=0,
            total=total_points,
            started_at=started_at,
            finished_at=None,
        )

        # Reset global counter for this upload session
        global _uploaded_counter
        _uploaded_counter = 0

        # Prepare all batches first
        all_batches: List[List[Dict]] = []
        current_batch: List[Dict] = []

        for point in _read_seed_lines(seed_path):
            current_batch.append(point)
            if len(current_batch) >= batch_size:
                all_batches.append(current_batch)
                current_batch = []

        # Add remaining points
        if current_batch:
            all_batches.append(current_batch)

        total_batches = len(all_batches)
        logger.info(f"📦 Prepared {total_batches} batches ({batch_size} vectors/batch)")

        # Parallel upload with ThreadPoolExecutor - chunked submission to avoid memory issues
        chunk_size = max_workers * 10  # Process 10 batches per worker at a time
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for chunk_start in range(0, total_batches, chunk_size):
                chunk_end = min(chunk_start + chunk_size, total_batches)
                chunk_batches = all_batches[chunk_start:chunk_end]

                # Submit chunk of batches
                futures = {
                    executor.submit(
                        _upload_batch_with_progress,
                        collection_name,
                        batch,
                        chunk_start + batch_idx + 1,
                        total_points,
                        started_at,
                    ): (chunk_start + batch_idx)
                    for batch_idx, batch in enumerate(chunk_batches)
                }

                # Wait for chunk to complete
                for future in as_completed(futures):
                    batch_num = futures[future]
                    try:
                        batch_uploaded = future.result()
                        uploaded += batch_uploaded
                    except Exception as exc:
                        logger.error(f"Batch {batch_num + 1} generated an exception: {exc}")
                        raise

                logger.info(f"🔄 Chunk progress: {chunk_end}/{total_batches} batches processed")

        logger.info(f"✅ All {total_batches} batches uploaded successfully")

    except Exception as exc:
        logger.exception("Seed upload failed: %s", exc)
        _set_seed_status(
            state="error",
            message=str(exc),
            seeded=uploaded,
            total=total_points,
            started_at=started_at,
            finished_at=time.time(),
        )
        raise

    logger.info("Seed upload complete (%s vectors)", uploaded)
    _set_seed_status(
        state="completed",
        message="Seed upload complete",
        seeded=uploaded,
        total=total_points,
        started_at=started_at,
        finished_at=time.time(),
    )
    return {"seeded": uploaded}

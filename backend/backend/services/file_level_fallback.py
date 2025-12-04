"""
File-level BGE fallback retrieval strategy.

Strategy:
1. MiniLM retrieves top_k results (fast keyword search)
2. If top-1 score < threshold:
   a. Find source file of top-1 chunk
   b. Re-chunk and embed entire file with BGE
   c. Search within file chunks with BGE query embedding
   d. Rerank file chunks with BGE reranker
3. Return best results

This approach treats MiniLM as "file finder" (keyword search)
and BGE as "precise chunk locator" (semantic search within file).
"""
import asyncio
import logging
import os
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import numpy as np

from backend.config.settings import settings
from backend.services.onnx_inference import (
    get_embedding_model,
    get_reranker_model,
    set_embedding_model_path,
    get_current_embed_path,
)
from backend.services.qdrant_client import get_qdrant_client
from backend.utils.text_splitter import split_text

logger = logging.getLogger(__name__)


@dataclass
class FileLevelResult:
    """Result from file-level fallback retrieval"""
    chunk_text: str
    chunk_id: str
    score: float
    file_path: str
    metadata: Dict[str, Any]
    fallback_triggered: bool
    fallback_latency_ms: Optional[float] = None


class FileLevelFallbackRetriever:
    """
    File-level BGE fallback retriever.

    Treats MiniLM as file finder (80% accurate, fast)
    and BGE as precise chunk locator (20% fallback, 1-2s acceptable).
    """

    def __init__(
        self,
        confidence_threshold: float = 0.65,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ):
        """
        Initialize file-level fallback retriever.

        Args:
            confidence_threshold: Score below which to trigger BGE fallback
            chunk_size: Chunk size for BGE re-chunking
            chunk_overlap: Overlap for BGE re-chunking
        """
        self.confidence_threshold = confidence_threshold
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.qdrant = get_qdrant_client()
        self.collection = settings.QDRANT_COLLECTION

        # Model paths
        self.minilm_path = settings.ONNX_EMBED_MODEL_PATH
        self.bge_path = settings.EMBED_FALLBACK_MODEL_PATH

        logger.info(
            "FileLevelFallbackRetriever initialized",
            confidence_threshold=confidence_threshold,
            chunk_size=chunk_size,
            minilm_path=self.minilm_path,
            bge_path=self.bge_path,
        )

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        minilm_top_k: int = 20,
    ) -> List[FileLevelResult]:
        """
        Retrieve with file-level BGE fallback.

        Strategy:
        1. MiniLM retrieves top_k candidates (keyword search)
        2. Check top-1 score
        3. If score < threshold:
           - Find top-1 source file
           - Re-embed entire file with BGE
           - Search within file with BGE
        4. Rerank and return best results

        Args:
            query: User query
            top_k: Final number of results to return
            minilm_top_k: Number of MiniLM candidates to retrieve

        Returns:
            List of FileLevelResult objects
        """
        start_time = time.time()

        # Step 1: MiniLM retrieval (keyword search / file finder)
        logger.info("Step 1: MiniLM retrieval", query=query[:50], top_k=minilm_top_k)

        minilm_results = await self._minilm_retrieve(query, top_k=minilm_top_k)

        if not minilm_results:
            logger.warning("No MiniLM results found")
            return []

        top_score = minilm_results[0]['score']
        logger.info("MiniLM top-1 score", score=top_score, threshold=self.confidence_threshold)

        # Step 2: Check confidence
        if top_score >= self.confidence_threshold:
            # High confidence - use MiniLM results directly
            logger.info(
                "High confidence - using MiniLM results",
                top_score=top_score,
                fallback_triggered=False,
            )

            # Rerank MiniLM results
            reranked = await self._rerank_results(query, minilm_results, top_k=top_k)

            return [
                FileLevelResult(
                    chunk_text=r['payload'].get('text', ''),
                    chunk_id=str(r['id']),
                    score=r['score'],
                    file_path=r['payload'].get('file_path', 'unknown'),
                    metadata=r['payload'],
                    fallback_triggered=False,
                )
                for r in reranked
            ]

        # Step 3: Low confidence - trigger BGE file-level fallback
        logger.warning(
            "Low confidence - triggering BGE file-level fallback",
            top_score=top_score,
            threshold=self.confidence_threshold,
        )

        fallback_start = time.time()

        # Get top-1 result and find source file
        top_result = minilm_results[0]
        file_path = top_result['payload'].get('file_path', None)

        if not file_path:
            logger.error("No file_path in top-1 result payload - cannot trigger fallback")
            # Fall back to MiniLM results
            reranked = await self._rerank_results(query, minilm_results, top_k=top_k)
            return [
                FileLevelResult(
                    chunk_text=r['payload'].get('text', ''),
                    chunk_id=str(r['id']),
                    score=r['score'],
                    file_path=r['payload'].get('file_path', 'unknown'),
                    metadata=r['payload'],
                    fallback_triggered=False,
                )
                for r in reranked
            ]

        logger.info("Found source file for BGE re-embedding", file_path=file_path)

        # Step 4: Load and re-chunk file with BGE
        try:
            file_chunks = await self._rechunk_file_with_bge(file_path, query)
        except Exception as e:
            logger.error(
                "Failed to re-chunk file with BGE - falling back to MiniLM results",
                file_path=file_path,
                error=str(e),
            )
            reranked = await self._rerank_results(query, minilm_results, top_k=top_k)
            return [
                FileLevelResult(
                    chunk_text=r['payload'].get('text', ''),
                    chunk_id=str(r['id']),
                    score=r['score'],
                    file_path=r['payload'].get('file_path', 'unknown'),
                    metadata=r['payload'],
                    fallback_triggered=False,
                )
                for r in reranked
            ]

        fallback_latency_ms = (time.time() - fallback_start) * 1000

        logger.info(
            "BGE file-level fallback completed",
            file_path=file_path,
            num_chunks=len(file_chunks),
            fallback_latency_ms=fallback_latency_ms,
        )

        # Step 5: Return top-k BGE results
        return [
            FileLevelResult(
                chunk_text=chunk['text'],
                chunk_id=f"bge_fallback_{idx}",
                score=chunk['score'],
                file_path=file_path,
                metadata={'source': 'bge_fallback', 'original_file': file_path},
                fallback_triggered=True,
                fallback_latency_ms=fallback_latency_ms,
            )
            for idx, chunk in enumerate(file_chunks[:top_k])
        ]

    async def _minilm_retrieve(
        self,
        query: str,
        top_k: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve with MiniLM (keyword search / file finder).

        Args:
            query: User query
            top_k: Number of results to retrieve

        Returns:
            List of dicts with 'id', 'score', 'payload'
        """
        # Ensure MiniLM is active
        current_embed = get_current_embed_path()
        if current_embed != self.minilm_path:
            set_embedding_model_path(self.minilm_path)

        # Get MiniLM embedding
        embed_model = get_embedding_model()
        query_embedding = embed_model.encode(query)

        # Search Qdrant
        try:
            search_results = self.qdrant.search(
                collection_name=self.collection,
                query_vector=query_embedding.tolist(),
                limit=top_k,
                with_payload=True,
            )

            results = [
                {
                    'id': result.id,
                    'score': result.score,
                    'payload': result.payload,
                }
                for result in search_results
            ]

            return results
        except Exception as e:
            logger.error("MiniLM search failed", error=str(e))
            return []

    async def _rechunk_file_with_bge(
        self,
        file_path: str,
        query: str,
    ) -> List[Dict[str, Any]]:
        """
        Re-chunk file and search with BGE.

        Steps:
        1. Load file content
        2. Re-chunk with specified chunk_size/overlap
        3. Embed all chunks with BGE
        4. Calculate similarity with BGE query embedding
        5. Rerank chunks with BGE reranker
        6. Return top chunks sorted by score

        Args:
            file_path: Path to source file
            query: User query

        Returns:
            List of dicts with 'text', 'score'
        """
        # Step 1: Load file content
        logger.info("Loading file content", file_path=file_path)

        try:
            # Try to load from filesystem
            full_path = Path(file_path)
            if not full_path.exists():
                # Try relative to data directory
                data_dir = Path(settings.DATA_DIR) if hasattr(settings, 'DATA_DIR') else Path('./data')
                full_path = data_dir / file_path

            if not full_path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")

            # Load content based on file extension
            if full_path.suffix.lower() == '.txt':
                content = full_path.read_text(encoding='utf-8')
            else:
                # Use file_loader utility for other formats
                from backend.utils.file_loader import load_file_content
                content = load_file_content(str(full_path))

            logger.info("File loaded", file_path=file_path, content_length=len(content))

        except Exception as e:
            logger.error("Failed to load file", file_path=file_path, error=str(e))
            raise

        # Step 2: Re-chunk with BGE parameters
        chunks = split_text(
            content,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

        logger.info("File re-chunked", num_chunks=len(chunks))

        # Step 3: Switch to BGE and embed
        logger.info("Switching to BGE for embedding")
        set_embedding_model_path(self.bge_path)

        bge_embed_model = get_embedding_model()

        # Embed query
        query_embedding = bge_embed_model.encode(query)

        # Embed all chunks
        chunk_embeddings = [bge_embed_model.encode(chunk) for chunk in chunks]

        logger.info("All chunks embedded with BGE", num_chunks=len(chunk_embeddings))

        # Step 4: Calculate cosine similarity
        def cosine_similarity(a, b):
            return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

        chunk_scores = [
            {
                'text': chunks[idx],
                'score': cosine_similarity(query_embedding, chunk_embeddings[idx]),
                'index': idx,
            }
            for idx in range(len(chunks))
        ]

        # Sort by score
        chunk_scores.sort(key=lambda x: x['score'], reverse=True)

        logger.info("Chunks scored and sorted", top_score=chunk_scores[0]['score'] if chunk_scores else 0.0)

        # Step 5: Rerank top chunks with BGE reranker
        top_candidates = chunk_scores[:20]  # Rerank top 20

        reranker = get_reranker_model()

        reranked_chunks = []
        for candidate in top_candidates:
            rerank_score = reranker.compute_score([[query, candidate['text']]])[0]
            reranked_chunks.append({
                'text': candidate['text'],
                'score': rerank_score,
                'embedding_score': candidate['score'],
            })

        # Sort by rerank score
        reranked_chunks.sort(key=lambda x: x['score'], reverse=True)

        logger.info(
            "Chunks reranked with BGE reranker",
            top_rerank_score=reranked_chunks[0]['score'] if reranked_chunks else 0.0,
        )

        # Switch back to MiniLM
        set_embedding_model_path(self.minilm_path)

        return reranked_chunks

    async def _rerank_results(
        self,
        query: str,
        results: List[Dict[str, Any]],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Rerank results with BGE reranker.

        Args:
            query: User query
            results: List of results to rerank
            top_k: Number of top results to return

        Returns:
            Reranked list of results
        """
        if not results:
            return []

        reranker = get_reranker_model()

        # Prepare pairs for reranking
        pairs = [[query, r['payload'].get('text', '')] for r in results]

        # Compute rerank scores
        rerank_scores = reranker.compute_score(pairs)

        # Attach rerank scores
        for idx, result in enumerate(results):
            result['rerank_score'] = rerank_scores[idx]

        # Sort by rerank score
        reranked = sorted(results, key=lambda x: x.get('rerank_score', 0.0), reverse=True)

        return reranked[:top_k]


# Singleton instance
_file_level_retriever: Optional[FileLevelFallbackRetriever] = None


def get_file_level_retriever(
    confidence_threshold: Optional[float] = None,
) -> FileLevelFallbackRetriever:
    """
    Get or create singleton FileLevelFallbackRetriever instance.

    Args:
        confidence_threshold: Override default confidence threshold

    Returns:
        FileLevelFallbackRetriever instance
    """
    global _file_level_retriever

    if _file_level_retriever is None:
        threshold = confidence_threshold or float(
            os.getenv('CONFIDENCE_FALLBACK_THRESHOLD', '0.65')
        )
        _file_level_retriever = FileLevelFallbackRetriever(
            confidence_threshold=threshold
        )

    return _file_level_retriever

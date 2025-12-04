"""
Hybrid Retriever combining BM25 keyword search with dense vector retrieval
"""
import asyncio
import pickle
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from rank_bm25 import BM25Okapi
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import ScoredPoint
import structlog

logger = structlog.get_logger(__name__)


class HybridRetriever:
    """
    Combines BM25 (keyword-based) and dense vector retrieval for improved recall.

    Uses Reciprocal Rank Fusion (RRF) to combine scores from both methods.
    """

    def __init__(
        self,
        qdrant_client: QdrantClient,
        collection_name: str,
        cache_dir: str = "./cache",
        alpha: float = 0.7  # Weight for vector vs BM25 (0.7 = 70% vector, 30% BM25)
    ):
        """
        Initialize hybrid retriever.

        Args:
            qdrant_client: Qdrant client instance
            collection_name: Name of Qdrant collection
            cache_dir: Directory to cache BM25 index
            alpha: Weight for vector search (0-1). 1-alpha will be BM25 weight.
        """
        self.qdrant = qdrant_client
        self.collection = collection_name
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.alpha = alpha

        # BM25 components
        self.bm25_index: Optional[BM25Okapi] = None
        self.doc_corpus: List[str] = []
        self.doc_ids: List[str] = []  # Maps corpus index to Qdrant point ID
        self.id_to_corpus_idx: Dict[str, int] = {}  # Reverse mapping

        self._initialized = False

    async def initialize(self, force_rebuild: bool = False):
        """
        Initialize BM25 index. Loads from cache if available, otherwise builds from Qdrant.

        Args:
            force_rebuild: Force rebuild index even if cache exists
        """
        if self._initialized and not force_rebuild:
            logger.info("HybridRetriever already initialized")
            return

        cache_file = self.cache_dir / f"{self.collection}_bm25.pkl"

        if cache_file.exists() and not force_rebuild:
            logger.info("Loading BM25 index from cache", cache_file=str(cache_file))
            try:
                with open(cache_file, 'rb') as f:
                    cache_data = pickle.load(f)
                    self.bm25_index = cache_data['bm25_index']
                    self.doc_corpus = cache_data['doc_corpus']
                    self.doc_ids = cache_data['doc_ids']
                    self.id_to_corpus_idx = cache_data['id_to_corpus_idx']
                    self._initialized = True
                    logger.info("BM25 index loaded from cache", num_docs=len(self.doc_corpus))
                    return
            except Exception as e:
                logger.warning("Failed to load BM25 cache, rebuilding", error=str(e))

        # Build BM25 index from Qdrant
        logger.info("Building BM25 index from Qdrant collection", collection=self.collection)
        await self._build_bm25_index()

        # Cache the index
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump({
                    'bm25_index': self.bm25_index,
                    'doc_corpus': self.doc_corpus,
                    'doc_ids': self.doc_ids,
                    'id_to_corpus_idx': self.id_to_corpus_idx
                }, f)
            logger.info("BM25 index cached", cache_file=str(cache_file))
        except Exception as e:
            logger.warning("Failed to cache BM25 index", error=str(e))

        self._initialized = True

    async def _build_bm25_index(self):
        """Build BM25 index by fetching all documents from Qdrant"""
        # Fetch all points from Qdrant (scroll API for large collections)
        offset = None
        all_points = []

        while True:
            try:
                result = self.qdrant.scroll(
                    collection_name=self.collection,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False  # Don't need vectors for BM25
                )

                points = result[0]
                if not points:
                    break

                all_points.extend(points)
                offset = result[1]  # Next offset

                if offset is None:
                    break
            except Exception as e:
                logger.error("Failed to fetch points from Qdrant", error=str(e))
                break

        logger.info("Fetched points from Qdrant", num_points=len(all_points))

        # Extract text content and build corpus
        self.doc_corpus = []
        self.doc_ids = []

        for point in all_points:
            doc_id = str(point.id)
            payload = point.payload or {}

            # Get text content from payload (adjust field name if different)
            text = payload.get('text', payload.get('content', ''))
            if not text:
                # Try to find any text field
                for key, value in payload.items():
                    if isinstance(value, str) and len(value) > 10:
                        text = value
                        break

            if text:
                self.doc_corpus.append(text)
                self.doc_ids.append(doc_id)

        # Build reverse mapping
        self.id_to_corpus_idx = {doc_id: idx for idx, doc_id in enumerate(self.doc_ids)}

        # Tokenize corpus and build BM25 index
        tokenized_corpus = [self._tokenize(doc) for doc in self.doc_corpus]
        self.bm25_index = BM25Okapi(tokenized_corpus)

        logger.info("BM25 index built", num_docs=len(self.doc_corpus))

    def _tokenize(self, text: str) -> List[str]:
        """
        Simple tokenization for BM25.
        Can be enhanced with stemming, stopword removal, etc.
        """
        # Basic whitespace tokenization + lowercase
        return text.lower().split()

    async def hybrid_search(
        self,
        query: str,
        query_embedding: List[float],
        top_k: int = 50,
        bm25_top_k: Optional[int] = None,
        vector_top_k: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Perform hybrid retrieval combining BM25 and vector search.

        Args:
            query: Raw text query
            query_embedding: Dense vector embedding of query
            top_k: Final number of results to return
            bm25_top_k: Number of BM25 candidates (default: top_k * 2)
            vector_top_k: Number of vector candidates (default: top_k * 2)

        Returns:
            List of dicts with 'id', 'score', 'payload', 'bm25_score', 'vector_score'
        """
        if not self._initialized:
            await self.initialize()

        bm25_top_k = bm25_top_k or min(top_k * 2, 100)
        vector_top_k = vector_top_k or min(top_k * 2, 100)

        # Run both searches in parallel
        bm25_task = asyncio.create_task(self._bm25_search(query, bm25_top_k))
        vector_task = asyncio.create_task(self._vector_search(query_embedding, vector_top_k))

        bm25_results, vector_results = await asyncio.gather(bm25_task, vector_task)

        # Fuse scores using weighted combination
        fused_results = self._fuse_scores(bm25_results, vector_results, top_k)

        return fused_results

    async def _bm25_search(self, query: str, top_k: int) -> List[Tuple[str, float]]:
        """
        Perform BM25 search.

        Returns:
            List of (doc_id, bm25_score) tuples
        """
        if self.bm25_index is None:
            return []

        tokenized_query = self._tokenize(query)
        scores = self.bm25_index.get_scores(tokenized_query)

        # Get top-k indices
        top_indices = np.argsort(scores)[-top_k:][::-1]

        results = []
        for idx in top_indices:
            if idx < len(self.doc_ids):
                doc_id = self.doc_ids[idx]
                score = float(scores[idx])
                results.append((doc_id, score))

        logger.debug("BM25 search completed", num_results=len(results), top_score=results[0][1] if results else 0)
        return results

    async def _vector_search(self, query_embedding: List[float], top_k: int) -> List[ScoredPoint]:
        """
        Perform dense vector search in Qdrant.

        Returns:
            List of ScoredPoint objects from Qdrant
        """
        try:
            results = self.qdrant.search(
                collection_name=self.collection,
                query_vector=query_embedding,
                limit=top_k
            )
            logger.debug("Vector search completed", num_results=len(results))
            return results
        except Exception as e:
            logger.error("Vector search failed", error=str(e))
            return []

    def _fuse_scores(
        self,
        bm25_results: List[Tuple[str, float]],
        vector_results: List[ScoredPoint],
        top_k: int
    ) -> List[Dict[str, Any]]:
        """
        Fuse BM25 and vector scores using weighted combination.

        Uses Reciprocal Rank Fusion (RRF) combined with normalized scores.
        """
        # Normalize BM25 scores (min-max normalization)
        if bm25_results:
            bm25_scores_raw = [score for _, score in bm25_results]
            max_bm25 = max(bm25_scores_raw) if bm25_scores_raw else 1.0
            min_bm25 = min(bm25_scores_raw) if bm25_scores_raw else 0.0
            score_range = max_bm25 - min_bm25

            bm25_normalized = {}
            for doc_id, score in bm25_results:
                if score_range > 0:
                    normalized = (score - min_bm25) / score_range
                else:
                    normalized = 1.0 if score > 0 else 0.0
                bm25_normalized[doc_id] = normalized
        else:
            bm25_normalized = {}

        # Vector scores are already normalized (cosine similarity 0-1)
        vector_normalized = {str(point.id): point.score for point in vector_results}

        # Collect all unique document IDs
        all_doc_ids = set(bm25_normalized.keys()) | set(vector_normalized.keys())

        # Compute fused scores
        fused_scores = []
        for doc_id in all_doc_ids:
            bm25_score = bm25_normalized.get(doc_id, 0.0)
            vector_score = vector_normalized.get(doc_id, 0.0)

            # Weighted combination
            fused_score = self.alpha * vector_score + (1 - self.alpha) * bm25_score

            fused_scores.append({
                'id': doc_id,
                'fused_score': fused_score,
                'bm25_score': bm25_score,
                'vector_score': vector_score
            })

        # Sort by fused score
        fused_scores.sort(key=lambda x: x['fused_score'], reverse=True)

        # Retrieve full payloads from Qdrant for top-k results
        top_results = []
        for item in fused_scores[:top_k]:
            try:
                # Convert string ID back to int if it's a numeric ID
                point_id = item['id']
                try:
                    point_id = int(point_id)
                except (ValueError, TypeError):
                    pass  # Keep as string if not convertible

                point = self.qdrant.retrieve(
                    collection_name=self.collection,
                    ids=[point_id],
                    with_payload=True
                )

                if point:
                    top_results.append({
                        'id': item['id'],
                        'score': item['fused_score'],
                        'bm25_score': item['bm25_score'],
                        'vector_score': item['vector_score'],
                        'payload': point[0].payload
                    })
            except Exception as e:
                logger.warning("Failed to retrieve point payload", doc_id=item['id'], error=str(e))

        logger.info(
            "Hybrid search completed",
            total_candidates=len(all_doc_ids),
            returned=len(top_results),
            top_fused_score=top_results[0]['score'] if top_results else 0,
            alpha=self.alpha
        )

        return top_results

    def update_alpha(self, alpha: float):
        """Update the vector/BM25 weight ratio"""
        if not 0 <= alpha <= 1:
            raise ValueError("alpha must be between 0 and 1")
        self.alpha = alpha
        logger.info("Updated alpha", alpha=alpha)

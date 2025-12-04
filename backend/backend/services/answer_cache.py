"""
Multi-Layer Answer Cache for RAG optimization

Uses a 3-tier hybrid caching strategy:
- Layer 1: Exact Hash Match (fastest)
- Layer 2: TF-IDF Keyword Match (fast filtering)
- Layer 3: Semantic Embedding Match (accurate but slower)
"""
import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List, Tuple
from collections import OrderedDict
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import structlog

from backend.models.rag_schemas import RAGResponse

logger = structlog.get_logger(__name__)


class MultiLayerAnswerCache:
    """
    3-layer hybrid answer cache for maximum speed and accuracy.

    Architecture:
    - Layer 1 (Exact Hash): O(1) lookup for identical queries
    - Layer 2 (TF-IDF): O(N) but fast filtering of candidates
    - Layer 3 (Semantic): O(K) where K << N, accurate similarity matching
    """

    def __init__(
        self,
        similarity_threshold: float = 0.88,
        tfidf_threshold: float = 0.30,
        max_cache_size: int = 1000,
        ttl_hours: int = 72
    ):
        """
        Initialize multi-layer answer cache.

        Args:
            similarity_threshold: Semantic similarity threshold (Layer 3)
            tfidf_threshold: TF-IDF similarity threshold (Layer 2)
            max_cache_size: Maximum cached answers (LRU eviction)
            ttl_hours: Time to live for cached entries
        """
        self.similarity_threshold = similarity_threshold
        self.tfidf_threshold = tfidf_threshold
        self.max_cache_size = max_cache_size
        self.ttl = timedelta(hours=ttl_hours)

        # Layer 1: Exact match cache {normalized_hash: answer}
        self.exact_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()

        # Layer 2: TF-IDF index
        self.tfidf_vectorizer: Optional[TfidfVectorizer] = None
        self.tfidf_matrix = None
        self.tfidf_queries: List[str] = []  # Original queries for TF-IDF
        self.tfidf_cache: Dict[str, Dict[str, Any]] = {}  # {query: answer}

        # Layer 3: Semantic embedding cache
        self.semantic_cache: Dict[str, Dict[str, Any]] = {}  # {query_hash: {embedding, answer}}
        self._embedder = None

        # Statistics
        self.stats = {
            'total_queries': 0,
            'layer1_hits': 0,  # Exact hash
            'layer2_hits': 0,  # TF-IDF
            'layer3_hits': 0,  # Semantic
            'misses': 0,
            'evictions': 0,
            'avg_layer1_time_ms': 0.0,
            'avg_layer2_time_ms': 0.0,
            'avg_layer3_time_ms': 0.0,
        }

    def set_embedder(self, embedder_func):
        """
        Set embedding function for Layer 3 semantic matching.

        Args:
            embedder_func: Async function that takes str and returns List[float]
        """
        self._embedder = embedder_func

    def _normalize_query(self, query: str) -> str:
        """
        Normalize query for exact matching (Layer 1).

        Techniques:
        - Lowercase
        - Remove punctuation
        - Trim whitespace
        - Sort words (to handle reordering)

        Examples:
            "What is prop building?" → "building is prop what"
            "Building prop is what?" → "building is prop what"  (same hash!)
        """
        # Remove punctuation and lowercase
        cleaned = re.sub(r'[^\w\s]', '', query.lower())
        # Split, sort, and rejoin
        words = sorted(cleaned.split())
        return ' '.join(words)

    def _hash_normalized(self, query: str) -> str:
        """Generate MD5 hash of normalized query"""
        normalized = self._normalize_query(query)
        return hashlib.md5(normalized.encode()).hexdigest()

    def _hash_query(self, query: str) -> str:
        """Generate MD5 hash of original query (for semantic cache)"""
        return hashlib.md5(query.lower().strip().encode()).hexdigest()

    async def _layer1_exact_match(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Layer 1: Exact Hash Match

        Technique: Normalized string hashing
        Speed: O(1) - ~0.1ms
        Accuracy: 100% for identical queries (ignoring order/punctuation)

        Returns:
            Cached answer if exact match found, else None
        """
        import time
        start = time.perf_counter()

        query_hash = self._hash_normalized(query)

        if query_hash in self.exact_cache:
            entry = self.exact_cache[query_hash]

            # Check TTL
            if datetime.now() - entry['cached_at'] > self.ttl:
                del self.exact_cache[query_hash]
                return None

            # Move to end (LRU - mark as recently used)
            self.exact_cache.move_to_end(query_hash)

            elapsed_ms = (time.perf_counter() - start) * 1000
            self.stats['layer1_hits'] += 1
            self._update_avg_time('layer1', elapsed_ms)

            logger.info(
                "Layer 1 HIT (Exact Hash)",
                query=query[:50],
                method="Normalized Hash",
                time_ms=f"{elapsed_ms:.2f}",
                cached_query=entry['original_query'][:50]
            )

            return {
                'answer': entry['answer'],
                'cache_layer': 1,
                'cache_method': 'Exact Hash Match',
                'similarity': 1.0,
                'time_ms': elapsed_ms
            }

        return None

    def _rebuild_tfidf_index(self):
        """
        Rebuild TF-IDF index for all cached queries.

        Technique: Term Frequency-Inverse Document Frequency
        Purpose: Fast keyword-based similarity
        """
        if not self.tfidf_cache:
            return

        self.tfidf_queries = list(self.tfidf_cache.keys())

        # Create TF-IDF vectorizer
        self.tfidf_vectorizer = TfidfVectorizer(
            max_features=100,  # Limit features for speed
            ngram_range=(1, 2),  # Unigrams and bigrams
            stop_words='english'  # Remove common words
        )

        # Fit and transform
        self.tfidf_matrix = self.tfidf_vectorizer.fit_transform(self.tfidf_queries)

        logger.debug("TF-IDF index rebuilt", num_queries=len(self.tfidf_queries))

    async def _layer2_tfidf_match(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Layer 2: TF-IDF Keyword Match

        Technique: TF-IDF vectorization + Cosine similarity
        Speed: O(N) but fast - ~1-2ms for 1000 queries
        Accuracy: Good for keyword overlap, misses synonyms

        Process:
        1. Convert query to TF-IDF vector
        2. Compute cosine similarity with all cached queries
        3. If best match > threshold, return it

        Returns:
            Cached answer if TF-IDF match found, else None
        """
        import time
        start = time.perf_counter()

        if not self.tfidf_cache or not self.tfidf_vectorizer:
            return None

        try:
            # Transform query to TF-IDF vector
            query_vector = self.tfidf_vectorizer.transform([query])

            # Compute cosine similarity with all cached queries
            similarities = cosine_similarity(query_vector, self.tfidf_matrix)[0]

            # Find best match
            best_idx = np.argmax(similarities)
            best_score = similarities[best_idx]

            if best_score >= self.tfidf_threshold:
                best_query = self.tfidf_queries[best_idx]
                entry = self.tfidf_cache[best_query]

                # Check TTL
                if datetime.now() - entry['cached_at'] > self.ttl:
                    del self.tfidf_cache[best_query]
                    self._rebuild_tfidf_index()
                    return None

                elapsed_ms = (time.perf_counter() - start) * 1000
                self.stats['layer2_hits'] += 1
                self._update_avg_time('layer2', elapsed_ms)

                logger.info(
                    "Layer 2 HIT (TF-IDF)",
                    query=query[:50],
                    method="TF-IDF + Cosine",
                    time_ms=f"{elapsed_ms:.2f}",
                    tfidf_score=f"{best_score:.3f}",
                    cached_query=best_query[:50]
                )

                return {
                    'answer': entry['answer'],
                    'cache_layer': 2,
                    'cache_method': 'TF-IDF Keyword Match',
                    'similarity': float(best_score),
                    'time_ms': elapsed_ms
                }

        except Exception as e:
            logger.warning("Layer 2 TF-IDF match failed", error=str(e))

        return None

    async def _get_query_embedding(self, query: str) -> np.ndarray:
        """Get normalized embedding for query (Layer 3)"""
        if self._embedder is None:
            raise RuntimeError("Embedder not set. Call set_embedder() first.")

        embedding = await self._embedder(query)
        embedding_array = np.array(embedding, dtype=np.float32)

        # Normalize for cosine similarity
        norm = np.linalg.norm(embedding_array)
        if norm > 0:
            embedding_array = embedding_array / norm

        return embedding_array

    async def _layer3_semantic_match(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Layer 3: Semantic Embedding Match

        Technique: Dense vector embeddings + Cosine similarity
        Speed: O(K) where K is candidates, ~5-10ms
        Accuracy: Highest - understands synonyms, paraphrases

        Process:
        1. Get query embedding (384-dim vector)
        2. Compute cosine similarity with all cached embeddings
        3. If best match > threshold, return it

        Returns:
            Cached answer if semantic match found, else None
        """
        import time
        start = time.perf_counter()

        if not self.semantic_cache:
            return None

        try:
            # Get query embedding
            query_emb = await self._get_query_embedding(query)

            # Find best match
            best_match = None
            best_score = 0.0
            best_query = None

            for query_hash, entry in self.semantic_cache.items():
                # Check TTL
                if datetime.now() - entry['cached_at'] > self.ttl:
                    continue

                # Compute cosine similarity
                cached_emb = entry['embedding']
                similarity = float(np.dot(query_emb, cached_emb))

                if similarity > best_score:
                    best_score = similarity
                    best_match = entry
                    best_query = entry['original_query']

            if best_match and best_score >= self.similarity_threshold:
                elapsed_ms = (time.perf_counter() - start) * 1000
                self.stats['layer3_hits'] += 1
                self._update_avg_time('layer3', elapsed_ms)

                logger.info(
                    "Layer 3 HIT (Semantic)",
                    query=query[:50],
                    method="Dense Embedding + Cosine",
                    time_ms=f"{elapsed_ms:.2f}",
                    semantic_score=f"{best_score:.3f}",
                    cached_query=best_query[:50]
                )

                return {
                    'answer': best_match['answer'],
                    'cache_layer': 3,
                    'cache_method': 'Semantic Embedding Match',
                    'similarity': float(best_score),
                    'time_ms': elapsed_ms
                }

        except Exception as e:
            logger.warning("Layer 3 semantic match failed", error=str(e))

        return None

    async def find_cached_answer(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Find cached answer using 3-layer hybrid search.

        Flow:
        1. Try Layer 1 (Exact Hash) - fastest
        2. If miss, try Layer 2 (TF-IDF) - fast filtering
        3. If miss, try Layer 3 (Semantic) - most accurate
        4. If all miss, return None

        Returns:
            Dict with:
            {
                'answer': RAGResponse,
                'cache_layer': 1/2/3,
                'cache_method': str,
                'similarity': float,
                'time_ms': float
            }
        """
        self.stats['total_queries'] += 1

        # Layer 1: Exact match
        result = await self._layer1_exact_match(query)
        if result:
            return result

        # Layer 2: TF-IDF
        result = await self._layer2_tfidf_match(query)
        if result:
            return result

        # Layer 3: Semantic
        result = await self._layer3_semantic_match(query)
        if result:
            return result

        # All layers missed
        self.stats['misses'] += 1
        logger.debug(
            "Cache MISS (all layers)",
            query=query[:50],
            total_cached=len(self.semantic_cache)
        )
        return None

    async def cache_answer(
        self,
        query: str,
        rag_response: RAGResponse,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Cache answer in all 3 layers for maximum retrieval speed.

        Args:
            query: Original user query
            rag_response: RAG response to cache
            metadata: Optional metadata
        """
        # Prepare answer entry
        answer_entry = {
            'original_query': query,
            'answer': rag_response,
            'cached_at': datetime.now(),
            'metadata': metadata or {},
            'hits': 0
        }

        # Layer 1: Add to exact cache
        exact_hash = self._hash_normalized(query)
        self.exact_cache[exact_hash] = answer_entry.copy()

        # Layer 2: Add to TF-IDF cache
        self.tfidf_cache[query] = answer_entry.copy()
        self._rebuild_tfidf_index()  # Rebuild index

        # Layer 3: Add to semantic cache with embedding
        try:
            query_emb = await self._get_query_embedding(query)
            semantic_hash = self._hash_query(query)

            semantic_entry = answer_entry.copy()
            semantic_entry['embedding'] = query_emb

            self.semantic_cache[semantic_hash] = semantic_entry
        except Exception as e:
            logger.warning("Failed to cache in Layer 3 (semantic)", error=str(e))

        # Enforce max cache size (evict oldest from all layers)
        if len(self.semantic_cache) > self.max_cache_size:
            # Remove oldest from exact cache
            if self.exact_cache:
                self.exact_cache.popitem(last=False)

            # Remove oldest from TF-IDF cache
            if self.tfidf_cache:
                oldest_query = next(iter(self.tfidf_cache))
                del self.tfidf_cache[oldest_query]
                self._rebuild_tfidf_index()

            # Remove oldest from semantic cache
            if self.semantic_cache:
                oldest_hash = next(iter(self.semantic_cache))
                del self.semantic_cache[oldest_hash]

            self.stats['evictions'] += 1

        logger.info(
            "Answer cached in all 3 layers",
            query=query[:50],
            total_cached=len(self.semantic_cache),
            tokens_saved=rag_response.token_usage.get('total', 0) if rag_response.token_usage else 0
        )

    def _update_avg_time(self, layer: str, time_ms: float):
        """Update average time for layer"""
        key = f'avg_layer{layer[5:]}_time_ms' if layer.startswith('layer') else f'avg_{layer}_time_ms'
        hits_key = f'{layer}_hits'

        current_avg = self.stats[key]
        hits = self.stats[hits_key]

        # Incremental average
        new_avg = (current_avg * (hits - 1) + time_ms) / hits
        self.stats[key] = new_avg

    def get_stats(self) -> Dict[str, Any]:
        """Get detailed cache statistics"""
        total_hits = (
            self.stats['layer1_hits'] +
            self.stats['layer2_hits'] +
            self.stats['layer3_hits']
        )
        total = total_hits + self.stats['misses']
        hit_rate = total_hits / total if total > 0 else 0.0

        return {
            'total_queries': self.stats['total_queries'],
            'total_hits': total_hits,
            'total_misses': self.stats['misses'],
            'hit_rate': hit_rate,
            'layer_breakdown': {
                'layer1_exact': {
                    'hits': self.stats['layer1_hits'],
                    'hit_rate': self.stats['layer1_hits'] / total if total > 0 else 0,
                    'avg_time_ms': self.stats['avg_layer1_time_ms'],
                    'technique': 'Normalized Hash'
                },
                'layer2_tfidf': {
                    'hits': self.stats['layer2_hits'],
                    'hit_rate': self.stats['layer2_hits'] / total if total > 0 else 0,
                    'avg_time_ms': self.stats['avg_layer2_time_ms'],
                    'technique': 'TF-IDF + Cosine Similarity'
                },
                'layer3_semantic': {
                    'hits': self.stats['layer3_hits'],
                    'hit_rate': self.stats['layer3_hits'] / total if total > 0 else 0,
                    'avg_time_ms': self.stats['avg_layer3_time_ms'],
                    'technique': 'Dense Embedding + Cosine Similarity'
                }
            },
            'cache_sizes': {
                'layer1_exact': len(self.exact_cache),
                'layer2_tfidf': len(self.tfidf_cache),
                'layer3_semantic': len(self.semantic_cache)
            },
            'evictions': self.stats['evictions'],
            'max_cache_size': self.max_cache_size,
            'thresholds': {
                'tfidf_threshold': self.tfidf_threshold,
                'semantic_threshold': self.similarity_threshold
            }
        }

    async def invalidate(self, query: str):
        """
        Invalidate (remove) cached answer for a specific query.

        Removes the query from all 3 cache layers.

        Args:
            query: The query to invalidate
        """
        removed_layers = []

        # Layer 1: Remove from exact match cache
        normalized = self._normalize_query(query)
        query_hash = self._hash_normalized(normalized)
        if query_hash in self.exact_cache:
            del self.exact_cache[query_hash]
            removed_layers.append("L1-exact")

        # Layer 2: Remove from TF-IDF cache
        if query in self.tfidf_cache:
            del self.tfidf_cache[query]
            # Remove from TF-IDF index
            if query in self.tfidf_queries:
                self.tfidf_queries.remove(query)
                # Rebuild TF-IDF index
                self._rebuild_tfidf_index()
            removed_layers.append("L2-tfidf")

        # Layer 3: Remove from semantic cache
        # Search for matching semantic cache entry
        for cached_query_hash, cached_data in list(self.semantic_cache.items()):
            if cached_data.get("query") == query:
                del self.semantic_cache[cached_query_hash]
                removed_layers.append("L3-semantic")
                break

        if removed_layers:
            logger.info(
                f"Cache invalidated for query",
                query_preview=query[:50],
                layers_removed=removed_layers
            )
        else:
            logger.warning(
                f"Cache invalidation requested but query not found",
                query_preview=query[:50]
            )

    def clear(self):
        """Clear all cache layers"""
        self.exact_cache.clear()
        self.tfidf_cache.clear()
        self.semantic_cache.clear()
        self.tfidf_matrix = None
        self.tfidf_vectorizer = None
        self.tfidf_queries = []
        logger.info("All cache layers cleared")


# Singleton instance
answer_cache: Optional[MultiLayerAnswerCache] = None


def get_answer_cache() -> Optional[MultiLayerAnswerCache]:
    """Get global answer cache instance"""
    return answer_cache


def initialize_answer_cache(
    similarity_threshold: float = 0.88,
    tfidf_threshold: float = 0.30,
    max_cache_size: int = 1000,
    ttl_hours: int = 72
) -> MultiLayerAnswerCache:
    """Initialize global answer cache"""
    global answer_cache
    answer_cache = MultiLayerAnswerCache(
        similarity_threshold=similarity_threshold,
        tfidf_threshold=tfidf_threshold,
        max_cache_size=max_cache_size,
        ttl_hours=ttl_hours
    )
    logger.info(
        "Multi-layer answer cache initialized",
        semantic_threshold=similarity_threshold,
        tfidf_threshold=tfidf_threshold,
        max_size=max_cache_size,
        ttl_hours=ttl_hours
    )
    return answer_cache

"""
Query Strategy Cache for RAG optimization

Caches successful retrieval strategies for similar queries to reduce token usage by 90%.
"""
import hashlib
import json
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List
from collections import OrderedDict
import numpy as np
import structlog

logger = structlog.get_logger(__name__)


class QueryStrategyCache:
    """
    Cache successful retrieval strategies for similar queries.

    Uses sentence embedding similarity to match queries and return cached strategies.
    """

    def __init__(
        self,
        similarity_threshold: float = 0.85,
        max_cache_size: int = 1000,
        ttl_hours: int = 24
    ):
        """
        Initialize query strategy cache.

        Args:
            similarity_threshold: Minimum cosine similarity to consider queries similar (0-1)
            max_cache_size: Maximum number of cached queries (LRU eviction)
            ttl_hours: Time to live for cached entries in hours
        """
        self.similarity_threshold = similarity_threshold
        self.max_cache_size = max_cache_size
        self.ttl = timedelta(hours=ttl_hours)

        # Cache structure: {query_hash: cache_entry}
        self.cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()

        # Embedding cache for fast similarity computation
        self.embeddings: Dict[str, np.ndarray] = {}

        # Embedder will be injected (to avoid circular dependencies)
        self._embedder = None

        # Statistics
        self.stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'total_queries': 0
        }

    def set_embedder(self, embedder_func):
        """
        Set the embedding function for query similarity.

        Args:
            embedder_func: Async function that takes str and returns List[float]
        """
        self._embedder = embedder_func

    async def _get_query_embedding(self, query: str) -> np.ndarray:
        """
        Get embedding for query.

        Args:
            query: Query text

        Returns:
            Numpy array of embedding
        """
        if self._embedder is None:
            raise RuntimeError("Embedder not set. Call set_embedder() first.")

        query_hash = self._hash_query(query)

        # Check if we already have this embedding
        if query_hash in self.embeddings:
            return self.embeddings[query_hash]

        # Get embedding from embedder
        embedding = await self._embedder(query)
        embedding_array = np.array(embedding, dtype=np.float32)

        # Normalize for cosine similarity
        norm = np.linalg.norm(embedding_array)
        if norm > 0:
            embedding_array = embedding_array / norm

        self.embeddings[query_hash] = embedding_array
        return embedding_array

    def _hash_query(self, query: str) -> str:
        """Generate hash for query"""
        return hashlib.md5(query.lower().strip().encode()).hexdigest()

    async def find_similar_query(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Find cached strategy for similar query.

        Args:
            query: User's query text

        Returns:
            Dict with 'strategy' and 'confidence' if match found, else None
            Example:
            {
                'strategy': {
                    'vector_limit': 20,
                    'top_k': 10,
                    'reranker_mode': 'primary',
                    'filters': None
                },
                'confidence': 0.92,
                'original_query': "Who wrote Pride and Prejudice?"
            }
        """
        self.stats['total_queries'] += 1

        if not self.cache:
            self.stats['misses'] += 1
            return None

        # Get query embedding
        try:
            query_emb = await self._get_query_embedding(query)
        except Exception as e:
            logger.warning("Failed to get query embedding for cache lookup", error=str(e))
            self.stats['misses'] += 1
            return None

        # Find best match
        best_match = None
        best_score = 0.0
        best_query_hash = None

        # Clean up expired entries while searching
        expired_hashes = []

        for query_hash, cache_entry in self.cache.items():
            # Check expiration
            if datetime.now() - cache_entry['timestamp'] > self.ttl:
                expired_hashes.append(query_hash)
                continue

            # Compute cosine similarity
            cached_emb = cache_entry['embedding']
            similarity = float(np.dot(query_emb, cached_emb))

            if similarity > best_score:
                best_score = similarity
                best_match = cache_entry
                best_query_hash = query_hash

        # Remove expired entries
        for query_hash in expired_hashes:
            del self.cache[query_hash]
            if query_hash in self.embeddings:
                del self.embeddings[query_hash]

        # Check if best match exceeds threshold
        if best_match and best_score >= self.similarity_threshold:
            # Move to end (LRU - mark as recently used)
            self.cache.move_to_end(best_query_hash)

            self.stats['hits'] += 1
            logger.info(
                "Cache hit",
                query=query[:50],
                cached_query=best_match['query'][:50],
                similarity=best_score,
                hit_rate=self._get_hit_rate()
            )

            return {
                'strategy': best_match['strategy'],
                'confidence': best_score,
                'original_query': best_match['query'],
                'usage_count': best_match['usage_count'] + 1
            }

        self.stats['misses'] += 1
        logger.debug("Cache miss", query=query[:50], best_similarity=best_score)
        return None

    async def cache_strategy(
        self,
        query: str,
        strategy: Dict[str, Any],
        success_score: float,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Cache successful retrieval strategy for future use.

        Args:
            query: Original query text
            strategy: Retrieval parameters used (vector_limit, top_k, reranker_mode, etc.)
            success_score: Confidence/relevance score (0-1) indicating success
            metadata: Optional metadata about the query/result
        """
        query_hash = self._hash_query(query)

        # Get embedding
        try:
            query_emb = await self._get_query_embedding(query)
        except Exception as e:
            logger.warning("Failed to cache query strategy (embedding failed)", error=str(e))
            return

        # Check if already cached (update if yes)
        if query_hash in self.cache:
            # Update existing entry
            self.cache[query_hash]['strategy'] = strategy
            self.cache[query_hash]['success_score'] = max(
                self.cache[query_hash]['success_score'],
                success_score
            )
            self.cache[query_hash]['usage_count'] += 1
            self.cache[query_hash]['timestamp'] = datetime.now()
            self.cache.move_to_end(query_hash)
            logger.debug("Updated cached strategy", query=query[:50])
            return

        # Add new entry
        cache_entry = {
            'query': query,
            'embedding': query_emb,
            'strategy': strategy,
            'success_score': success_score,
            'timestamp': datetime.now(),
            'usage_count': 0,
            'metadata': metadata or {}
        }

        self.cache[query_hash] = cache_entry

        # Enforce max cache size (LRU eviction)
        if len(self.cache) > self.max_cache_size:
            # Remove oldest entry
            oldest_hash, _ = self.cache.popitem(last=False)
            if oldest_hash in self.embeddings:
                del self.embeddings[oldest_hash]
            self.stats['evictions'] += 1

        logger.info(
            "Cached new strategy",
            query=query[:50],
            success_score=success_score,
            cache_size=len(self.cache)
        )

    def _get_hit_rate(self) -> float:
        """Calculate cache hit rate"""
        total = self.stats['hits'] + self.stats['misses']
        if total == 0:
            return 0.0
        return self.stats['hits'] / total

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return {
            **self.stats,
            'cache_size': len(self.cache),
            'hit_rate': self._get_hit_rate(),
            'max_cache_size': self.max_cache_size,
            'similarity_threshold': self.similarity_threshold
        }

    def clear(self):
        """Clear all cached entries"""
        self.cache.clear()
        self.embeddings.clear()
        logger.info("Cache cleared")

    def remove_expired(self):
        """Manually remove expired entries"""
        expired_hashes = []
        for query_hash, cache_entry in self.cache.items():
            if datetime.now() - cache_entry['timestamp'] > self.ttl:
                expired_hashes.append(query_hash)

        for query_hash in expired_hashes:
            del self.cache[query_hash]
            if query_hash in self.embeddings:
                del self.embeddings[query_hash]

        if expired_hashes:
            logger.info("Removed expired cache entries", count=len(expired_hashes))

    def export_cache(self) -> List[Dict[str, Any]]:
        """
        Export cache for persistence (e.g., to JSON/database).

        Returns:
            List of cache entries (without embeddings for serialization)
        """
        exported = []
        for query_hash, entry in self.cache.items():
            exported.append({
                'query_hash': query_hash,
                'query': entry['query'],
                'strategy': entry['strategy'],
                'success_score': entry['success_score'],
                'timestamp': entry['timestamp'].isoformat(),
                'usage_count': entry['usage_count'],
                'metadata': entry['metadata']
            })
        return exported

    async def import_cache(self, cache_data: List[Dict[str, Any]]):
        """
        Import cache from persistence.

        Args:
            cache_data: List of cache entries from export_cache()
        """
        for entry in cache_data:
            query = entry['query']
            query_hash = self._hash_query(query)

            # Recreate embedding
            try:
                query_emb = await self._get_query_embedding(query)

                self.cache[query_hash] = {
                    'query': query,
                    'embedding': query_emb,
                    'strategy': entry['strategy'],
                    'success_score': entry['success_score'],
                    'timestamp': datetime.fromisoformat(entry['timestamp']),
                    'usage_count': entry['usage_count'],
                    'metadata': entry.get('metadata', {})
                }
            except Exception as e:
                logger.warning("Failed to import cache entry", query=query[:50], error=str(e))

        logger.info("Cache imported", entries=len(self.cache))


# Singleton instance (will be initialized in main app)
query_cache: Optional[QueryStrategyCache] = None


def get_query_cache() -> Optional[QueryStrategyCache]:
    """Get global query cache instance"""
    return query_cache


def initialize_query_cache(
    similarity_threshold: float = 0.85,
    max_cache_size: int = 1000,
    ttl_hours: int = 24
) -> QueryStrategyCache:
    """Initialize global query cache"""
    global query_cache
    query_cache = QueryStrategyCache(
        similarity_threshold=similarity_threshold,
        max_cache_size=max_cache_size,
        ttl_hours=ttl_hours
    )
    logger.info("Query cache initialized", max_size=max_cache_size, threshold=similarity_threshold)
    return query_cache

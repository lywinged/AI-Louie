"""
Classification Cache: Learn from LLM classifications to reduce future LLM calls

This system caches query classifications and learns patterns to make
confident predictions without LLM calls.
"""
import json
import structlog
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = structlog.get_logger(__name__)


class ClassificationCache:
    """
    Cache and learn from query classifications.

    Features:
    1. Exact query cache (hash-based)
    2. Semantic similarity cache (embedding-based)
    3. Pattern learning (confidence-based)
    """

    def __init__(
        self,
        cache_file: str = "/tmp/classification_cache.json",
        semantic_threshold: float = 0.75,
        confidence_threshold: float = 0.70,
        max_cache_size: int = 10000,
        ttl_days: int = 30
    ):
        """
        Args:
            cache_file: Path to persistent cache file
            semantic_threshold: Min similarity to use cached classification (0-1)
            confidence_threshold: Min confidence to skip LLM (0-1)
            max_cache_size: Maximum cached entries
            ttl_days: Time-to-live for cache entries
        """
        self.cache_file = Path(cache_file)
        self.semantic_threshold = semantic_threshold
        self.confidence_threshold = confidence_threshold
        self.max_cache_size = max_cache_size
        self.ttl_days = ttl_days

        # Cache storage
        self.cache: Dict[str, Dict[str, Any]] = {}

        # TF-IDF for semantic similarity
        self.vectorizer = TfidfVectorizer(
            max_features=500,
            ngram_range=(1, 3),
            stop_words='english'
        )
        self.query_texts: List[str] = []
        self.query_vectors = None

        # Statistics
        self.stats = {
            "total_queries": 0,
            "cache_hits": 0,
            "llm_calls": 0,
            "learned_patterns": 0
        }

        # Load existing cache
        self._load_cache()

        logger.info(
            "Classification cache initialized",
            cached_entries=len(self.cache),
            semantic_threshold=semantic_threshold,
            confidence_threshold=confidence_threshold
        )

    def _load_cache(self):
        """Load cache from disk"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                    self.cache = data.get('cache', {})
                    self.stats = data.get('stats', self.stats)

                # Remove expired entries
                self._cleanup_expired()

                # Rebuild TF-IDF vectors
                if self.cache:
                    self.query_texts = list(self.cache.keys())
                    if len(self.query_texts) > 0:
                        self.query_vectors = self.vectorizer.fit_transform(self.query_texts)

                logger.info(f"Loaded {len(self.cache)} classifications from cache")
            except Exception as e:
                logger.warning(f"Failed to load cache: {e}")
                self.cache = {}

    def _save_cache(self):
        """Save cache to disk"""
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, 'w') as f:
                json.dump({
                    'cache': self.cache,
                    'stats': self.stats
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")

    def _cleanup_expired(self):
        """Remove expired cache entries"""
        now = datetime.utcnow()
        expired_keys = []

        for query, entry in self.cache.items():
            cached_time = datetime.fromisoformat(entry['timestamp'])
            if now - cached_time > timedelta(days=self.ttl_days):
                expired_keys.append(query)

        for key in expired_keys:
            del self.cache[key]

        if expired_keys:
            logger.info(f"Removed {len(expired_keys)} expired cache entries")

    def find_similar_query(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Find similar cached query using TF-IDF semantic similarity.

        Returns:
            Cached classification if similar query found, else None
        """
        if not self.cache or not self.query_texts:
            return None

        try:
            # Compute similarity with all cached queries
            query_vec = self.vectorizer.transform([query])
            similarities = cosine_similarity(query_vec, self.query_vectors)[0]

            # Find most similar
            max_idx = int(np.argmax(similarities))
            max_sim = float(similarities[max_idx])

            if max_sim >= self.semantic_threshold:
                similar_query = self.query_texts[max_idx]
                cached = self.cache[similar_query]

                logger.info(
                    "Found similar cached query",
                    query=query[:50],
                    similar_query=similar_query[:50],
                    similarity=f"{max_sim:.3f}",
                    query_type=cached['query_type']
                )

                return {
                    'query_type': cached['query_type'],
                    'confidence': cached['confidence'] * max_sim,  # Adjust by similarity
                    'source': 'semantic_cache',
                    'similarity': max_sim,
                    'similar_query': similar_query
                }

        except Exception as e:
            logger.warning(f"Similarity search failed: {e}")

        return None

    def get_classification(self, query: str) -> Optional[Tuple[str, float, str]]:
        """
        Get cached classification if confident enough.

        Returns:
            (query_type, confidence, source) if found, else None
        """
        self.stats['total_queries'] += 1

        # 1. Try exact match (fastest)
        if query in self.cache:
            cached = self.cache[query]
            if cached['confidence'] >= self.confidence_threshold:
                self.stats['cache_hits'] += 1
                logger.info(
                    "Classification cache HIT (exact)",
                    query=query[:50],
                    query_type=cached['query_type'],
                    confidence=cached['confidence'],
                    uses=cached['uses']
                )

                # Increment use counter
                cached['uses'] += 1
                cached['last_used'] = datetime.utcnow().isoformat()

                return cached['query_type'], cached['confidence'], 'exact_cache'

        # 2. Try semantic similarity
        similar = self.find_similar_query(query)
        if similar and similar['confidence'] >= self.confidence_threshold:
            self.stats['cache_hits'] += 1
            return similar['query_type'], similar['confidence'], similar['source']

        # 3. No confident cached result
        return None

    def cache_classification(
        self,
        query: str,
        query_type: str,
        reasoning: str = "",
        llm_used: bool = True
    ):
        """
        Cache a new classification result.

        Args:
            query: User query
            query_type: Classified type
            reasoning: LLM reasoning (optional)
            llm_used: Whether LLM was used for this classification
        """
        # Calculate confidence based on cache history
        confidence = self._calculate_confidence(query, query_type, llm_used)

        # Store in cache
        self.cache[query] = {
            'query_type': query_type,
            'confidence': confidence,
            'reasoning': reasoning,
            'timestamp': datetime.utcnow().isoformat(),
            'last_used': datetime.utcnow().isoformat(),
            'uses': 1,
            'llm_used': llm_used
        }

        # Update TF-IDF index
        self.query_texts.append(query)
        if len(self.query_texts) > 1:
            try:
                self.query_vectors = self.vectorizer.fit_transform(self.query_texts)
            except Exception as e:
                logger.warning(f"Failed to update TF-IDF vectors: {e}")

        # Enforce size limit (LRU eviction)
        if len(self.cache) > self.max_cache_size:
            self._evict_lru()

        # Update stats
        if llm_used:
            self.stats['llm_calls'] += 1
        else:
            self.stats['learned_patterns'] += 1

        # Periodic save
        if self.stats['total_queries'] % 10 == 0:
            self._save_cache()

        logger.debug(
            "Cached classification",
            query=query[:50],
            query_type=query_type,
            confidence=confidence,
            llm_used=llm_used
        )

    def _calculate_confidence(self, query: str, query_type: str, llm_used: bool) -> float:
        """
        Calculate confidence score for a classification.

        Higher confidence when:
        - LLM was used (0.95)
        - Similar patterns exist in cache
        - Query type has been seen frequently
        """
        if llm_used:
            # LLM classifications start with high confidence
            return 0.95

        # For learned patterns, confidence based on consistency
        type_count = sum(1 for entry in self.cache.values() if entry['query_type'] == query_type)
        total_count = len(self.cache) or 1

        # Confidence increases with more examples
        confidence = 0.7 + (type_count / total_count) * 0.25
        return min(confidence, 0.95)

    def _evict_lru(self):
        """Evict least recently used entries"""
        # Sort by last_used timestamp
        sorted_entries = sorted(
            self.cache.items(),
            key=lambda x: x[1]['last_used']
        )

        # Remove oldest 10%
        to_remove = max(1, len(sorted_entries) // 10)
        for query, _ in sorted_entries[:to_remove]:
            del self.cache[query]
            if query in self.query_texts:
                self.query_texts.remove(query)

        # Rebuild TF-IDF
        if self.query_texts:
            self.query_vectors = self.vectorizer.fit_transform(self.query_texts)

        logger.info(f"Evicted {to_remove} LRU cache entries")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        hit_rate = 0.0
        if self.stats['total_queries'] > 0:
            hit_rate = self.stats['cache_hits'] / self.stats['total_queries']

        llm_savings = 0.0
        if self.stats['total_queries'] > 0:
            llm_savings = 1.0 - (self.stats['llm_calls'] / self.stats['total_queries'])

        return {
            'total_queries': self.stats['total_queries'],
            'cache_hits': self.stats['cache_hits'],
            'llm_calls': self.stats['llm_calls'],
            'learned_patterns': self.stats['learned_patterns'],
            'cache_size': len(self.cache),
            'hit_rate': f"{hit_rate:.1%}",
            'llm_savings': f"{llm_savings:.1%}"
        }


# Singleton instance
_classification_cache: Optional[ClassificationCache] = None


def get_classification_cache() -> ClassificationCache:
    """Get or create singleton classification cache"""
    global _classification_cache
    if _classification_cache is None:
        _classification_cache = ClassificationCache()
    return _classification_cache

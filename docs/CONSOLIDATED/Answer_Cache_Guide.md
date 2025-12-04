# Answer Cache Implementation & Integration

Consolidates: `ANSWER_CACHE_IMPLEMENTATION_COMPLETE.md`, `ANSWER_CACHE_HYBRID_METHOD.md`, `ANSWER_CACHE_INTEGRATION.md`.

## Architecture
- Three-layer hybrid cache: Exact Hash (normalized), TF-IDF, Semantic (MiniLM embedding).
- TTL, thresholds, size configurable via `.env` (`ENABLE_ANSWER_CACHE`, `ANSWER_CACHE_*`).

## Entry Points
- RAG endpoints (ask/ask-smart/ask-stream etc.) check Answer Cache first; hits return directly with zero tokens.
- Multi-collection search also uses the cache.

## Embedding
- Reuses MiniLM embedder (same as retrieval), injected at initialization.

## Monitoring & Logging
- Hits/misses log layer, similarity, and time; UI shows cache HIT/MISS.

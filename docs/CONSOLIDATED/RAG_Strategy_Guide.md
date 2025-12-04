# RAG Strategy & Pipeline Guide

Consolidates: `RAG_STRATEGY_COMPREHENSIVE.md`, `RAG_STRATEGIES_GUIDE.md`, `RAG_STRATEGY_SELECTOR_GUIDE.md`, `RAG_COMPARISON_GUIDE.md`, `RAG_TECH_DISPLAY_GUIDE.md`.

## Strategies
- Standard / Hybrid / Iterative / Smart (multi-collection) / Graph / Table
- Default is Hybrid; Smart switches between Hybrid / Iterative by query complexity; multi-collection can force Smart.

## Retrieval & Ranking
- Hybrid retrieval: vector + BM25, tunable alpha; falls back to basic retriever if enhanced is unavailable.
- Rerank: cross-encoder; reranker mode/model configurable.

## Caching & Acceleration
- Answer Cache (multi-layer) and Query Strategy Cache; semantic cache hits return immediately and are shown in UI.
- Config via `.env`: `ENABLE_ANSWER_CACHE`, thresholds, TTL.

## Graph / Table Notes
- Graph: JIT graph building; extracts entities/relationships; if graph is empty, uses query entities to seed minimal nodes.
- Table: Excel tool auto-detects meter tables, aggregates `(current-prev)*multiplier`; UI shows tool status and breakdowns.

## UI & Metrics
- Frontend shows strategy selection, steps, timing breakdown (embed/vector/rerank/LLM), model info, tool status.
- Graph has Plotly visualization; Table shows Excel tool output and fallback table.

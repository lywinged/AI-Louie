# Streaming Integration Guide

Consolidates: `RAG_STREAMING_GUIDE.md`, `frontend/STREAMING_INTEGRATION_GUIDE.md`.

## Backend
- `/api/rag/ask-stream` SSE events: retrieval/content/metadata/done/error.
- Retrieval event first (may include citations), then streamed content.
- Answer Cache hits are streamed as cached answers in the same event format.

## Frontend
- Streamlit uses `requests` streaming to consume SSE.
- Non-multi-collection strategies default to streaming; multi-collection/Smart/Graph/Table use non-streaming to show full pipeline.

## Typical Config
- Timeout: frontend 180s; backend defaults.
- To disable streaming, switch to non-streaming endpoint in the strategy branch.

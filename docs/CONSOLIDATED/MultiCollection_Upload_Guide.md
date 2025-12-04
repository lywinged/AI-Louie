# Multi-Collection & Upload Integration Guide

Consolidates: `MULTI_COLLECTION_IMPLEMENTATION_COMPLETE.md`, `UPLOAD_COLLECTION_IMPLEMENTATION.md`.

## Search Scope
- `search_scope`: `all` (system + user), `user_only`, `system_only`; switchable in UI.
- Smart/Hybrid/Iterative can call `/api/rag/search-multi-collection` in multi-collection mode.

## Uploads & Metadata
- Upload path: `data/uploads` (or `UPLOADS_DIR`). Metadata stores `file_path`, `upload_dir`, `uploaded_file`.
- Table RAG/Excel tool relies on `file_path`/`uploaded_file` to resolve the real file.

## Qdrant Collections
- System: `assessment_docs_minilm`
- User: `user_uploaded_docs`
- Scope determines which collections to merge; results sorted then truncated to top_k.

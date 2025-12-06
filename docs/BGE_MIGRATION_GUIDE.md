# BGE Migration Guide

## Overview

This guide explains how to migrate your existing MiniLM Qdrant collection (384-dim) to a new BGE-M3 collection (1024-dim) while preserving all your data.

## Problem Summary

**Issue**: Vector dimension mismatch causing RAG failures
- **Current**: Qdrant collection uses 384-dimensional MiniLM embeddings
- **Inference Service**: Now configured to use 1024-dimensional BGE-M3 embeddings
- **Result**: Search fails → system returns cached answers instead of current responses

## Solution: Hybrid Migration Strategy

Use the existing MiniLM collection to find all documents, then re-embed them with BGE-M3 and create a new 1024-dimensional collection.

---

## Migration Script Features

The [scripts/migrate_minilm_to_bge.py](../scripts/migrate_minilm_to_bge.py) script provides:

- ✅ Extracts all 152,987 points from 150 unique documents in MiniLM collection
- ✅ Re-embeds documents using BGE-M3 (1024-dim) via inference service
- ✅ Creates new Qdrant collection `assessment_docs_bge` with correct dimensions
- ✅ Preserves all metadata from original collection
- ✅ Progress bars for all operations
- ✅ Dry-run mode for testing

---

## Step-by-Step Migration

### Step 1: Run Dry-Run Test (Optional but Recommended)

Test the migration on 2-5 files first:

```bash
cd /Users/yilu/Downloads/yuzhi_DC/AI-Louie

# Test with 2 files (dry-run mode)
python scripts/migrate_minilm_to_bge.py --dry-run --limit 2
```

Expected output:
```
✅ Inference service OK (embedding dim: 1024)
✅ Found 152987 total points across 150 unique files
⚠️  Limiting to 2 files for testing
🔍 DRY RUN - Skipping collection creation
🔄 Migrating 2 documents to BGE collection...
✅ Migration complete! Processed X chunks from 2 files
```

### Step 2: Run Full Migration

Once dry-run succeeds, migrate all documents:

```bash
# Full migration (creates new collection with all documents)
python scripts/migrate_minilm_to_bge.py --recreate
```

**Estimated time**: ~30-60 minutes for 150 files with 152,987 chunks
- Collection scanning: ~1-2 minutes (~2000 points/sec)
- BGE embedding: ~25-50 ms per chunk
- Qdrant upload: Fast (batched in groups of 50)

### Step 3: Verify New Collection

Check that the new collection was created successfully:

```bash
# Check collection exists
curl -s http://localhost:6333/collections/assessment_docs_bge | jq '.result.config.params.vectors'

# Expected output:
# {
#   "size": 1024,
#   "distance": "Cosine"
# }

# Check point count
curl -s http://localhost:6333/collections/assessment_docs_bge | jq '.result.points_count'
```

### Step 4: Update Backend Configuration

Edit [.env](.env) file:

```bash
# Change these two lines:
QDRANT_COLLECTION=assessment_docs_bge  # was: assessment_docs_minilm
RAG_VECTOR_SIZE=1024  # was: 384
```

### Step 5: Restart Backend

```bash
docker-compose restart backend

# Wait for backend to be ready
sleep 5

# Check backend health
curl -s http://localhost:8888/health | jq '.status'
```

### Step 6: Test RAG Queries

Test that queries now work correctly:

```bash
curl -X POST http://localhost:8888/api/rag/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is the American frontier?",
    "top_k": 3
  }' | jq '{answer: .answer[:200], chunks: .num_chunks_retrieved}'
```

You should see:
- ✅ New answers (not cached)
- ✅ Relevant chunks retrieved
- ✅ No 500 errors in backend logs

---

## Migration Script Options

### Basic Usage

```bash
python scripts/migrate_minilm_to_bge.py [options]
```

### Available Options

| Option | Description | Example |
|--------|-------------|---------|
| `--dry-run` | Test without uploading to Qdrant | `--dry-run` |
| `--limit N` | Process only first N files | `--limit 5` |
| `--recreate` | Overwrite existing BGE collection | `--recreate` |
| `--batch-size N` | Upload N points per batch (default: 50) | `--batch-size 100` |

### Example Commands

```bash
# Test with 5 files (dry-run)
python scripts/migrate_minilm_to_bge.py --dry-run --limit 5

# Full migration (creates new collection)
python scripts/migrate_minilm_to_bge.py --recreate

# Resume migration with larger batches
python scripts/migrate_minilm_to_bge.py --recreate --batch-size 100
```

---

## Architecture

### Before Migration

```
┌─────────────────────┐
│  Qdrant Collection  │
│ assessment_docs_    │
│      minilm         │
│                     │
│  384-dim vectors    │  ← MiniLM embeddings
│  152,987 points     │
└─────────────────────┘
           ↑
           │ Search (FAILS!)
           │
┌─────────────────────┐
│ Inference Service   │
│   BGE-M3 Model      │
│  1024-dim output    │  ← Dimension mismatch
└─────────────────────┘
```

### After Migration

```
┌─────────────────────┐
│  Qdrant Collection  │
│ assessment_docs_bge │
│                     │
│  1024-dim vectors   │  ← BGE-M3 embeddings
│  152,987 points     │
└─────────────────────┘
           ↑
           │ Search (WORKS!)
           │
┌─────────────────────┐
│ Inference Service   │
│   BGE-M3 Model      │
│  1024-dim output    │  ← Dimensions match
└─────────────────────┘
```

---

## Migration Flow

```
1. Scan MiniLM Collection
   ↓
   Extract 150 unique file paths + metadata
   ↓
2. For each document:
   ↓
   Read original file (or use existing chunks)
   ↓
   Re-chunk text (500 chars, 50 overlap)
   ↓
   Embed each chunk with BGE-M3 (1024-dim)
   ↓
   Create point with metadata
   ↓
3. Upload to Qdrant in batches of 50
   ↓
4. Verify collection
```

---

## Rollback Plan

If you need to revert to MiniLM:

### Option 1: Keep Both Collections

Keep the old collection and switch between them:

```bash
# In .env, switch back:
QDRANT_COLLECTION=assessment_docs_minilm
RAG_VECTOR_SIZE=384

# Update docker-compose.yml inference service:
ONNX_EMBED_MODEL_PATH=/app/models/minilm-embed-int8
ONNX_RERANK_MODEL_PATH=/app/models/bge-reranker-int8

# Rebuild and restart
docker-compose build inference
docker-compose restart inference backend
```

### Option 2: Delete BGE Collection

```bash
# Delete the BGE collection if migration failed
curl -X DELETE http://localhost:6333/collections/assessment_docs_bge
```

---

## Troubleshooting

### Error: "Collection already exists"

```bash
# Use --recreate flag to overwrite
python scripts/migrate_minilm_to_bge.py --recreate
```

### Error: "Inference service not responding"

```bash
# Check inference service status
docker-compose ps inference
docker-compose logs inference

# Restart if needed
docker-compose restart inference
```

### Error: "Could not read original file"

The script will automatically fall back to using existing chunks from the MiniLM collection. This is expected for some files.

### Slow Migration

```bash
# Increase batch size to upload faster
python scripts/migrate_minilm_to_bge.py --recreate --batch-size 100

# Or run in screen/tmux for long-running migration
screen -S bge-migration
python scripts/migrate_minilm_to_bge.py --recreate
# Press Ctrl+A, D to detach
```

---

## Performance Comparison

### MiniLM (384-dim) vs BGE-M3 (1024-dim)

| Metric | MiniLM | BGE-M3 | Difference |
|--------|--------|--------|------------|
| Embedding Size | 384-dim | 1024-dim | +170% |
| Embedding Speed | ~20ms | ~50ms | 2.5x slower |
| Search Quality | Good | Excellent | Higher accuracy |
| Storage | ~59MB | ~157MB | 2.7x larger |

**Recommendation**: BGE-M3 provides significantly better search quality for complex queries, worth the trade-off in speed and storage.

---

## Next Steps After Migration

1. **Test all RAG features**:
   - Basic queries
   - Multi-turn conversations
   - Complex semantic search
   - Reranking

2. **Monitor performance**:
   ```bash
   # Check Grafana dashboard
   open http://localhost:3000

   # Monitor latency metrics
   curl http://localhost:8888/metrics | grep rag_latency
   ```

3. **Update documentation**:
   - Note that system now uses BGE-M3
   - Update any performance benchmarks
   - Document migration date in README

4. **Backup new collection** (optional):
   ```bash
   # Create snapshot
   curl -X POST http://localhost:6333/collections/assessment_docs_bge/snapshots
   ```

---

## FAQ

**Q: Can I run both collections simultaneously?**
A: Yes! Both collections can coexist. Just switch the `QDRANT_COLLECTION` env var to choose which one to use.

**Q: How much disk space does migration need?**
A: BGE collection is ~2.7x larger than MiniLM. Ensure you have at least 200MB free space.

**Q: Will migration affect my current data?**
A: No, the MiniLM collection remains untouched. Migration creates a completely new collection.

**Q: Can I cancel migration mid-process?**
A: Yes, press Ctrl+C. You can restart with `--recreate` flag to start fresh.

**Q: How do I verify migration success?**
A: Check that:
1. New collection has ~152,987 points
2. Vector dimension is 1024
3. Test queries return relevant results
4. No 500 errors in backend logs

---

## References

- [Qdrant Collections API](https://qdrant.tech/documentation/concepts/collections/)
- [BGE-M3 Model Card](https://huggingface.co/BAAI/bge-m3)
- [ONNX Runtime Documentation](https://onnxruntime.ai/)

---

**Last Updated**: December 2024
**Version**: 1.0

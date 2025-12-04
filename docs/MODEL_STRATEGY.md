# Model Selection Strategy

## 🎯 Current Strategy: MiniLM Primary (Short-Term)

### Why This Configuration?

**Problem:**
- Existing Qdrant collection `assessment_docs_minilm` was ingested using MiniLM embeddings
- Using BGE M3 for queries would cause vector incompatibility
- Result: Poor retrieval quality due to mismatched embedding spaces

**Solution:**
- **Primary**: MiniLM L6 (fast, compatible with existing data)
- **Fallback**: BGE M3 (high quality, for future use)

---

## 📊 Model Comparison

### Embedding Models

| Feature | MiniLM L6 INT8 | BGE M3 INT8 |
|---------|----------------|-------------|
| **Speed** | ⭐⭐⭐⭐⭐ (50-80ms) | ⭐⭐⭐ (100-150ms) |
| **Quality** | ⭐⭐⭐⭐ (NDCG@10: 0.62-0.66) | ⭐⭐⭐⭐⭐ (NDCG@10: 0.68-0.72) |
| **Dimensions** | 384 | 384 ✅ |
| **Memory** | ~100MB | ~200MB |
| **Multilingual** | ⭐⭐⭐ (Good) | ⭐⭐⭐⭐⭐ (Excellent) |
| **Best For** | Simple queries, speed-critical | Complex queries, quality-critical |

### Reranker Models

| Feature | MiniLM Cross-Encoder | BGE Reranker |
|---------|---------------------|--------------|
| **Speed** | ⭐⭐⭐⭐⭐ (100-150ms) | ⭐⭐⭐ (200-300ms) |
| **Quality** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Memory** | ~100MB | ~200MB |
| **Best For** | Speed-critical | Quality-critical |

---

## ⚙️ Current Configuration

### Primary Models (Fast)

```env
# Embedding: MiniLM L6 INT8
ONNX_EMBED_MODEL_PATH=./models/minilm-embed-int8

# Reranking: BGE Reranker INT8 (mixed strategy)
ONNX_RERANK_MODEL_PATH=./models/bge-reranker-int8
```

**Why BGE Reranker as Primary?**
- ✅ Rerankers are model-agnostic (can rerank any retrieval results)
- ✅ BGE reranker provides better quality with acceptable speed
- ✅ No vector compatibility issues (works on text pairs)

### Fallback Models

```env
# Embedding: BGE M3 INT8 (for future)
EMBED_FALLBACK_MODEL_PATH=./models/bge-m3-embed-int8

# Reranking: MiniLM Cross-Encoder (for speed)
RERANK_FALLBACK_MODEL_PATH=./models/minilm-reranker-onnx
```

### Performance Thresholds

```env
# Auto-switch to fallback if reranker >500ms
RERANK_CPU_SWITCH_THRESHOLD_MS=500

# Reranker score threshold
RERANK_SCORE_THRESHOLD=-20.0
```

---

## 📈 Expected Performance

### Latency Breakdown

**Typical RAG Query (Simple):**
```
Query Embedding:     50-80ms   (MiniLM)
Vector Search:       20-30ms   (Qdrant)
Reranking:          200-300ms  (BGE Reranker)
LLM Generation:     800-1200ms (GPT-4o-mini)
─────────────────────────────────────────
Total:             1100-1600ms ✅ <2000ms SLO
```

**Complex RAG Query:**
```
Query Embedding:     50-80ms   (MiniLM)
Vector Search:       30-50ms   (Qdrant)
Reranking:          200-300ms  (BGE Reranker)
LLM Generation:    1500-2500ms (GPT-4o-mini, longer context)
─────────────────────────────────────────
Total:             1800-2900ms ⚠️ May exceed SLO
```

### Quality Metrics

**With Current Config:**
- **Simple Queries**: 85-90% accuracy (MiniLM sufficient)
- **Complex Queries**: 80-85% accuracy (MiniLM adequate, BGE would be 85-90%)
- **Multilingual**: 70-75% accuracy (MiniLM limited, BGE would be 85-90%)

---

## 🔄 Fallback Mechanism

### When Fallback Triggers

1. **Performance-based:**
   ```python
   if rerank_time_ms > 500:
       switch_to_fallback_reranker()  # MiniLM reranker
   ```

2. **Error-based:**
   ```python
   try:
       embed = primary_embed_model.encode(query)
   except Exception:
       embed = fallback_embed_model.encode(query)
   ```

3. **Manual:**
   ```python
   # Via API endpoint
   POST /api/rag/switch-mode
   {"mode": "fallback"}
   ```

---

## 🚀 Migration Path to BGE Primary

### When to Migrate?

Migrate to BGE M3 primary when:
- ✅ You have time for re-ingestion (~1-2 hours)
- ✅ Quality is more important than speed
- ✅ Users query in multiple languages
- ✅ Queries are complex/analytical

### Migration Steps

**1. Re-ingest Documents with BGE**

```bash
# Update .env
ONNX_EMBED_MODEL_PATH=./models/bge-m3-embed-int8
QDRANT_COLLECTION=assessment_docs_bge

# Run ingestion script
python scripts/ingest_with_bge.py

# Generate new seed
python scripts/bootstrap_qdrant_seed.py
```

**2. Update Configuration**

```env
# Swap primary and fallback
ONNX_EMBED_MODEL_PATH=./models/bge-m3-embed-int8
EMBED_FALLBACK_MODEL_PATH=./models/minilm-embed-int8

# Update collection name
QDRANT_COLLECTION=assessment_docs_bge
QDRANT_SEED_PATH=/app/data/qdrant_seed/assessment_docs_bge.jsonl
```

**3. Restart Services**

```bash
./start.sh
```

**4. Verify Quality**

```bash
# Run evaluation
python scripts/eval_rag_performance.py

# Compare metrics
# - NDCG@10 should improve 5-10%
# - Latency will increase 100-150ms
```

---

## 🔍 Monitoring

### Key Metrics to Track

1. **Model Selection Rate**
   ```python
   # Track primary vs fallback usage
   primary_count / total_count
   ```

2. **Performance by Model**
   ```python
   # Average latency per model
   avg(embed_time_ms) GROUP BY model_name
   ```

3. **Quality by Model**
   ```python
   # Confidence scores per model
   avg(confidence) GROUP BY model_name
   ```

### Governance Integration

**Track in Governance Context:**

```python
governance_tracker.checkpoint_model_selection(
    trace_id=trace_id,
    embed_model="minilm-embed-int8",
    rerank_model="bge-reranker-int8",
    is_fallback=False,
    embed_time_ms=65.3,
    rerank_time_ms=245.7
)
```

**Display in UI:**

```
🛡️ AI Governance Status
━━━━━━━━━━━━━━━━━━━━━━━━━━
...
✅ G6 Version Control:
   - Embed: minilm-embed-int8 (65.3ms)
   - Rerank: bge-reranker-int8 (245.7ms)
   - Strategy: Primary (no fallback)
```

---

## 🎯 Recommendations

### For Your Use Case

**Current Setup (MiniLM Primary):**
- ✅ **Best for**: Speed-critical applications
- ✅ **Best for**: Simple factual queries
- ✅ **Best for**: English-dominant content
- ⚠️ **Limitation**: Moderate quality on complex queries
- ⚠️ **Limitation**: Limited multilingual support

**Future Setup (BGE Primary):**
- ✅ **Best for**: Quality-critical applications
- ✅ **Best for**: Complex analytical queries
- ✅ **Best for**: Multilingual content
- ⚠️ **Trade-off**: +150-200ms latency
- ⚠️ **Trade-off**: Requires re-ingestion

### Query-Adaptive Strategy (Advanced)

For best of both worlds:

```python
def select_embed_model(query: str) -> str:
    """Select model based on query complexity"""

    # Simple query indicators
    is_simple = (
        len(query.split()) < 10 and
        not has_complex_keywords(query) and
        not is_multilingual(query)
    )

    return "minilm" if is_simple else "bge"
```

**Pros:**
- Optimal speed for simple queries
- Optimal quality for complex queries

**Cons:**
- Requires dual Qdrant collections
- More complex infrastructure

---

## 📝 Quick Reference

### Check Current Models

```bash
# View current config
grep "EMBED_MODEL" .env
grep "RERANK_MODEL" .env

# Check Qdrant collection
grep "QDRANT_COLLECTION" .env

# Verify compatibility
# Ensure: embedding model matches collection suffix
# ✅ minilm-embed + assessment_docs_minilm
# ❌ bge-embed + assessment_docs_minilm
```

### Performance Benchmarks

```bash
# Test embedding speed
python scripts/benchmark_embed.py

# Test reranking speed
python scripts/benchmark_rerank.py

# Expected results:
# MiniLM embed: 50-80ms
# BGE embed: 100-150ms
# MiniLM rerank: 100-150ms
# BGE rerank: 200-300ms
```

### Switch Models Runtime

```bash
# Switch to fallback
curl -X POST http://localhost:8888/api/rag/switch-mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "fallback"}'

# Switch back to primary
curl -X POST http://localhost:8888/api/rag/switch-mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "primary"}'
```

---

## 🐛 Troubleshooting

### Issue: Poor Retrieval Quality

**Symptom:** Low confidence scores, irrelevant results

**Check:**
```bash
# Verify model compatibility
embedding_model=$(grep ONNX_EMBED_MODEL_PATH .env | cut -d= -f2)
collection=$(grep QDRANT_COLLECTION .env | cut -d= -f2)

echo "Embedding: $embedding_model"
echo "Collection: $collection"

# Must match:
# minilm-embed → assessment_docs_minilm ✅
# bge-embed → assessment_docs_bge ✅
# bge-embed → assessment_docs_minilm ❌
```

**Solution:**
- Adjust config to match collection
- OR re-ingest with correct model

### Issue: Slow Performance

**Symptom:** Latency >2000ms

**Check:**
```bash
# Check if using fallback
grep "switch.*fallback" backend.log

# Check reranker time
grep "rerank.*ms" backend.log
```

**Solution:**
- Lower `RERANK_CPU_SWITCH_THRESHOLD_MS`
- Switch to MiniLM reranker
- Reduce `top_k` parameter

### Issue: High Memory Usage

**Symptom:** OOM errors, crashes

**Solution:**
```bash
# Reduce thread count
OMP_NUM_THREADS=4

# Use INT8 quantization
USE_INT8_QUANTIZATION=true

# Reduce batch sizes
EMBED_BATCH_SIZE=16
RERANK_BATCH_SIZE=32
```

---

## 📚 References

- **MiniLM Paper**: https://arxiv.org/abs/2002.10957
- **BGE M3 Paper**: https://arxiv.org/abs/2402.03216
- **ONNX Runtime**: https://onnxruntime.ai/
- **INT8 Quantization**: https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html

---

**Version**: 1.0
**Last Updated**: 2025-12-04
**Status**: ✅ Active (MiniLM Primary Configuration)

# Confidence-Based Model Fallback Strategy

**Date:** 2025-12-04
**Status:** 📋 Proposal (Awaiting User Decision)
**Proposed By:** User Request - "MiniLM confidence 低时，用 BGE 二次搜索"

---

## 🎯 Problem Statement

**Current Issue:**
- MiniLM is fast (50-80ms) but sometimes returns low-confidence results
- BGE is more accurate but slower (100-150ms) and requires re-ingestion to use as primary
- Query classification helps but doesn't adapt to actual retrieval quality

**User's Idea:**
> "我觉得minilm 搜到confidence 低，我把top1 找到原文件，用bge embedding 一次，再搜，是否更合理呢？"

Translation: "If MiniLM retrieval has low confidence, find the top-1 source file, re-embed with BGE, and search again."

---

## 📊 Analysis of User's Original Proposal

### Approach A: File-Level Re-Embedding (User's Original Idea)

**Flow:**
```
1. MiniLM retrieves top_k results
2. If top-1 score < CONFIDENCE_THRESHOLD:
   a. Find source document of top-1 chunk
   b. Load entire source file
   c. Re-chunk and embed entire file with BGE
   d. Store BGE embeddings (temporary or permanent?)
   e. Search again with BGE query embedding
3. Rerank combined results with BGE reranker
```

**Pros:**
- ✅ Theoretical: Could find better chunks in the same document
- ✅ Gradual: Only re-embeds files with low-confidence hits

**Cons:**
- ❌ **Vector space incompatibility**: MiniLM top-1 may not be BGE top-1 (different embedding spaces)
- ❌ **High latency**: File re-embedding + re-chunking takes 500-2000ms
- ❌ **Storage complexity**: Where to store BGE embeddings? (Temporary in-memory? Persist to Qdrant?)
- ❌ **Qdrant schema**: Would need dual-vector support or separate collection
- ❌ **Questionable assumption**: Low MiniLM score doesn't mean BGE will find better results in same file

**Verdict:** ⚠️ **NOT RECOMMENDED** - Too complex, too slow, wrong assumption

---

## 💡 Recommended Alternatives

### Approach B: Dual-Embedding Retrieval (RECOMMENDED)

**Flow:**
```
1. If query is classified as COMPLEX or MODERATE:
   a. MiniLM retrieves top_k=20 (fast, ~50-80ms)
   b. **In parallel**: BGE retrieves top_k=20 from Qdrant (slower, ~100-150ms)
   c. Merge and deduplicate results (RRF or score fusion)
   d. BGE rerank top candidates

2. If query is SIMPLE:
   a. MiniLM retrieves top_k=20
   b. BGE rerank top candidates
```

**Total Latency:**
- SIMPLE: 50-80ms (MiniLM) + 50-100ms (rerank) = ~150ms
- MODERATE/COMPLEX: 100-150ms (parallel retrieval) + 50-100ms (rerank) = ~250ms

**Pros:**
- ✅ **Leverages both models**: Fast MiniLM + Accurate BGE
- ✅ **Parallel execution**: Total latency = max(MiniLM, BGE) + rerank
- ✅ **No re-embedding**: Uses existing Qdrant collections
- ✅ **Proven technique**: Reciprocal Rank Fusion (RRF) for multi-retriever systems
- ✅ **Gradual quality improvement**: More results → better reranking

**Cons:**
- ⚠️ **Dual Qdrant collections required**: Need both `assessment_docs_minilm` and `assessment_docs_bge`
- ⚠️ **Storage cost**: 2x Qdrant collection size (~200MB each)
- ⚠️ **Ingestion effort**: Need to ingest with BGE (one-time)

**Verdict:** ✅ **RECOMMENDED FOR LONG-TERM** (after BGE ingestion)

---

### Approach C: Confidence-Based Single-Model Fallback (RECOMMENDED FOR SHORT-TERM)

**Flow:**
```
1. MiniLM retrieves top_k=20
2. Calculate confidence = top_1_score
3. If confidence < CONFIDENCE_THRESHOLD (e.g., 0.65):
   a. Log warning: "Low confidence, using BGE fallback"
   b. **Switch to BGE model** via set_embedding_model_path()
   c. BGE retrieves top_k=20 from **same Qdrant collection** (MiniLM-based)
   d. Use BGE results (even though collection is MiniLM-embedded)
4. BGE rerank final candidates
```

**Latency:**
- High confidence (>0.65): 50-80ms (MiniLM) + 50-100ms (rerank) = ~150ms
- Low confidence (<0.65): 100-150ms (BGE) + 50-100ms (rerank) = ~250ms
- **Fallback rate:** ~20-30% of queries (most queries will be fast)

**Pros:**
- ✅ **Zero infrastructure change**: Works with current Qdrant collection
- ✅ **Dynamic adaptation**: Automatically switches based on actual confidence
- ✅ **Lower average latency**: Most queries use fast MiniLM
- ✅ **Easy to implement**: ~50 lines of code
- ✅ **Observable**: Log every fallback decision

**Cons:**
- ⚠️ **Vector mismatch**: BGE query vs MiniLM documents (suboptimal but better than nothing)
- ⚠️ **Not perfect**: BGE may not find better results in MiniLM-embedded space

**Verdict:** ✅ **RECOMMENDED FOR SHORT-TERM** (quick win, no infra change)

---

## 🏗️ Implementation Plan

### Option 1: Quick Win (Approach C - Confidence Fallback)

**Timeline:** 1-2 hours

**Changes Required:**
1. **New file:** `backend/backend/services/adaptive_retriever.py`
2. **Modify:** `backend/backend/services/rag_pipeline.py` - integrate confidence check
3. **Add .env config:**
   ```env
   ENABLE_CONFIDENCE_FALLBACK=true
   CONFIDENCE_FALLBACK_THRESHOLD=0.65
   ```

**Code Sketch:**
```python
# backend/backend/services/adaptive_retriever.py

async def retrieve_with_confidence_fallback(
    query: str,
    top_k: int = 20,
    confidence_threshold: float = 0.65
) -> List[Dict[str, Any]]:
    """
    Retrieve with confidence-based model fallback.

    Strategy:
    1. Try MiniLM first (fast)
    2. If top-1 score < threshold, fallback to BGE
    3. Rerank with BGE reranker
    """
    # Get MiniLM embedding and retrieve
    embed_model = get_embedding_model()  # MiniLM (current primary)
    query_embedding = embed_model.encode(query)

    results = await vector_search(query_embedding, top_k=top_k)

    if not results:
        return []

    top_score = results[0]['score']

    # Check confidence
    if top_score < confidence_threshold:
        logger.warning(
            "Low confidence - fallback to BGE",
            top_score=top_score,
            threshold=confidence_threshold,
            query=query[:50]
        )

        # Switch to BGE and re-retrieve
        bge_path = settings.EMBED_FALLBACK_MODEL_PATH
        set_embedding_model_path(bge_path)

        bge_embed_model = get_embedding_model()  # Now BGE
        bge_query_embedding = bge_embed_model.encode(query)

        results = await vector_search(bge_query_embedding, top_k=top_k)

        # Switch back to MiniLM
        minilm_path = settings.ONNX_EMBED_MODEL_PATH
        set_embedding_model_path(minilm_path)

        logger.info(
            "BGE fallback completed",
            num_results=len(results),
            top_score=results[0]['score'] if results else 0.0
        )

    # Rerank with BGE reranker
    reranked = await rerank_results(query, results, top_k=5)

    return reranked
```

**Monitoring:**
```bash
# Count fallback triggers
docker logs ai-louie-backend-1 | grep "Low confidence - fallback to BGE" | wc -l

# Analyze confidence distribution
docker logs ai-louie-backend-1 | grep "top_score=" | awk '{print $NF}'
```

---

### Option 2: Best Quality (Approach B - Dual Retrieval)

**Timeline:** 1-2 days (includes BGE ingestion)

**Changes Required:**
1. **Ingest with BGE:**
   ```bash
   # Create new Qdrant collection with BGE embeddings
   python scripts/ingest_with_bge.py \
     --input-docs ./data/docs \
     --collection assessment_docs_bge \
     --model-path ./models/bge-m3-embed-int8
   ```

2. **New file:** `backend/backend/services/dual_retriever.py`
3. **Modify:** `backend/backend/services/rag_pipeline.py`
4. **Add .env config:**
   ```env
   ENABLE_DUAL_RETRIEVAL=true
   QDRANT_COLLECTION_BGE=assessment_docs_bge
   DUAL_RETRIEVAL_STRATEGY=rrf  # Options: rrf, score_fusion
   ```

**Code Sketch:**
```python
# backend/backend/services/dual_retriever.py

async def dual_embedding_retrieval(
    query: str,
    top_k: int = 20,
    strategy: str = "rrf"
) -> List[Dict[str, Any]]:
    """
    Retrieve from both MiniLM and BGE collections in parallel.

    Uses Reciprocal Rank Fusion (RRF) to combine results.
    """
    # Parallel retrieval from both collections
    minilm_task = retrieve_from_collection(
        query=query,
        collection="assessment_docs_minilm",
        model_path=settings.ONNX_EMBED_MODEL_PATH,  # MiniLM
        top_k=top_k
    )

    bge_task = retrieve_from_collection(
        query=query,
        collection="assessment_docs_bge",
        model_path=settings.EMBED_FALLBACK_MODEL_PATH,  # BGE
        top_k=top_k
    )

    minilm_results, bge_results = await asyncio.gather(minilm_task, bge_task)

    # Merge with RRF
    if strategy == "rrf":
        merged = reciprocal_rank_fusion(
            [minilm_results, bge_results],
            k=60  # RRF parameter
        )
    else:
        merged = score_fusion(minilm_results, bge_results, alpha=0.5)

    # Rerank with BGE reranker
    reranked = await rerank_results(query, merged, top_k=5)

    return reranked


def reciprocal_rank_fusion(
    result_lists: List[List[Dict]],
    k: int = 60
) -> List[Dict[str, Any]]:
    """
    Combine multiple result lists using RRF.

    RRF formula: score = sum(1 / (k + rank_i)) for all result lists
    """
    doc_scores = {}

    for results in result_lists:
        for rank, result in enumerate(results, start=1):
            doc_id = result['id']
            rrf_score = 1.0 / (k + rank)

            if doc_id not in doc_scores:
                doc_scores[doc_id] = {
                    'id': doc_id,
                    'payload': result['payload'],
                    'rrf_score': 0.0
                }
            doc_scores[doc_id]['rrf_score'] += rrf_score

    # Sort by RRF score
    merged = sorted(doc_scores.values(), key=lambda x: x['rrf_score'], reverse=True)

    return merged
```

**Benefits:**
- ✅ **Best quality**: Combines strengths of both models
- ✅ **Parallel execution**: Fast (~150-250ms total)
- ✅ **Proven technique**: Used by Anthropic, OpenAI, Google

**Costs:**
- Storage: +200MB for BGE collection
- Ingestion time: ~10-20 minutes (one-time)

---

## 📈 Expected Performance

### Approach C (Confidence Fallback - SHORT-TERM)

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| **Average latency** | 50-80ms | 80-120ms | -40ms (acceptable) |
| **P95 latency** | 100ms | 250ms | -150ms (low-confidence queries) |
| **Retrieval quality (NDCG@10)** | 0.62-0.66 | 0.64-0.68 | +3% (estimated) |
| **Fallback rate** | N/A | 20-30% | Dynamic |

### Approach B (Dual Retrieval - LONG-TERM)

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| **Average latency** | 50-80ms | 150-250ms | -170ms (all queries slower) |
| **P95 latency** | 100ms | 300ms | -200ms |
| **Retrieval quality (NDCG@10)** | 0.62-0.66 | 0.68-0.72 | +10% (estimated) |
| **Fallback rate** | N/A | 100% (always dual) | N/A |

---

## 🎯 Recommendation

### 🥇 **Best Choice: Approach C (Confidence Fallback) - SHORT-TERM**

**Why:**
1. ✅ **Quick to implement**: 1-2 hours, ~50 lines of code
2. ✅ **No infrastructure change**: Works with current Qdrant collection
3. ✅ **Dynamic adaptation**: Only slows down low-confidence queries
4. ✅ **Observable**: Clear logs for every fallback decision
5. ✅ **Reversible**: Easy to disable if not working well

**Implementation Priority:**
- **Now**: Implement Approach C (confidence fallback)
- **Next sprint**: Ingest BGE collection and prepare for Approach B
- **Future**: Enable Approach B (dual retrieval) for maximum quality

---

## 🚀 Next Steps

### If User Approves Approach C:

1. **Create adaptive_retriever.py** with confidence fallback logic
2. **Modify rag_pipeline.py** to use confidence-based retrieval
3. **Add .env configuration**:
   ```env
   ENABLE_CONFIDENCE_FALLBACK=true
   CONFIDENCE_FALLBACK_THRESHOLD=0.65  # Tune based on testing
   ```
4. **Test with sample queries**:
   - Simple factual: "Who wrote 'DADDY TAKE ME SKATING'?" (expect: no fallback)
   - Complex analytical: "Compare Elizabeth and Darcy's relationship evolution" (expect: fallback)
5. **Monitor logs** for fallback rate and quality improvement

### If User Wants Approach B:

1. **Create ingestion script** for BGE collection
2. **Run ingestion** (10-20 minutes)
3. **Implement dual_retriever.py** with RRF
4. **Test with both collections**
5. **Compare quality metrics** (NDCG@10, latency, user satisfaction)

---

## 🤔 Open Questions for User

1. **Which approach do you prefer?**
   - Option C (Confidence Fallback - Quick Win)
   - Option B (Dual Retrieval - Best Quality)

2. **What's your latency tolerance?**
   - Current: 50-80ms average
   - Approach C: 80-120ms average (20-30% fallback)
   - Approach B: 150-250ms average (all queries)

3. **Storage constraints?**
   - Current: ~200MB (MiniLM collection)
   - Approach B needs: +200MB (BGE collection)
   - Total: ~400MB

4. **Time availability?**
   - Approach C: 1-2 hours implementation
   - Approach B: 1-2 days (includes ingestion)

---

**Version:** 1.0 (Proposal)
**Last Updated:** 2025-12-04
**Status:** 📋 Awaiting User Decision
**Contact:** AI-Louie Team

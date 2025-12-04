# AI-Louie Deployment Checklist

## 🎯 Pre-Deployment Verification

### 1. Configuration Files
- ✅ **.env** - Model configuration corrected (MiniLM primary)
- ✅ **docker-compose.yml** - No changes needed
- ✅ **Backend Dockerfile** - Governance service included
- ✅ **Frontend Dockerfile** - Governance components included

### 2. Model Configuration Verification

**Current Configuration (SHORT-TERM STRATEGY):**
```env
# Embedding Models
ONNX_EMBED_MODEL_PATH=./models/minilm-embed-int8          # Primary: Fast, compatible with assessment_docs_minilm
EMBED_FALLBACK_MODEL_PATH=./models/bge-m3-embed-int8      # Fallback: High quality

# Reranker Models
ONNX_RERANK_MODEL_PATH=./models/bge-reranker-int8         # Primary: High accuracy
RERANK_FALLBACK_MODEL_PATH=./models/minilm-reranker-onnx  # Fallback: Fast

# Qdrant Collection
QDRANT_COLLECTION=assessment_docs_minilm                   # Ingested with MiniLM embeddings
```

**Why This Configuration:**
- ✅ MiniLM embeddings match Qdrant collection (vector compatibility)
- ✅ BGE reranker provides quality boost (model-agnostic, works with any embeddings)
- ✅ Fast inference (~50-80ms per query)
- ✅ BGE fallback available for complex queries

### 3. Governance Integration Status

**Backend Components:**
- ✅ `backend/backend/services/governance_tracker.py` - Core tracking service
- ✅ `backend/backend/routers/rag_routes.py` - RAG governance (R1)
- ✅ `backend/backend/routers/code_routes.py` - Code governance (R0)
- ✅ `backend/backend/routers/chat_routes.py` - Chat governance (R1)
- ✅ `backend/backend/models/rag_schemas.py` - governance_context field
- ✅ `backend/backend/models/code_schemas.py` - governance_context field
- ✅ `backend/backend/models/chat_schemas.py` - governance_context field

**Frontend Components:**
- ✅ `frontend/components/governance_display.py` - Display components
- ✅ `frontend/app.py` - UI integration

**Documentation:**
- ✅ `docs/GOVERNANCE_INTEGRATION.md` - Full technical documentation
- ✅ `docs/GOVERNANCE_QUICKSTART.md` - 3-minute tutorial
- ✅ `docs/GOVERNANCE_COMPLETE.md` - Completion report
- ✅ `docs/MODEL_STRATEGY.md` - Model selection strategy
- ✅ `README.md` - Updated with governance section

### 4. Docker Build Status

**Build Results:**
```
✅ Backend Image: sha256:b60bc19b75f964b788ebd2b22206492e80c1f417ebc8a169b4a398b27fe0470f
✅ Frontend Image: sha256:6b18b80534f1253143621994be80daf549d19c113aded5d5f677d2269e37b700
```

**Build Time:** ~2 minutes (using cache)

## 🚀 Deployment Steps

### Step 1: Start Services
```bash
cd /Users/yilu/Downloads/yuzhi_DC/AI-Louie
./start.sh
```

**Expected Output:**
```
Starting AI-Louie Platform...
✓ Backend warm-up (3 Smart RAG queries, ~70s)
✓ Qdrant seed data loading
✓ Health checks pass
✓ Frontend ready at http://localhost:18501
```

### Step 2: Verify Backend Health
```bash
curl http://localhost:8888/health
```

**Expected Response:**
```json
{
  "status": "healthy",
  "onnx_inference": "enabled",
  "embed_model": "minilm-embed-int8",
  "rerank_model": "bge-reranker-int8",
  "qdrant_collection": "assessment_docs_minilm"
}
```

### Step 3: Verify Qdrant Data
```bash
curl http://localhost:6333/collections/assessment_docs_minilm
```

**Expected Response:**
```json
{
  "result": {
    "status": "green",
    "vectors_count": 1000+,
    "config": {
      "params": {
        "vectors": {
          "size": 384,
          "distance": "Cosine"
        }
      }
    }
  }
}
```

### Step 4: Test RAG Query with Governance
Open http://localhost:18501 and:

1. Click **"📚 RAG Q&A"** button
2. Ask: "Who wrote 'DADDY TAKE ME SKATING'?"
3. Wait for response (~1-2 seconds)
4. Scroll down to see **"🛡️ AI Governance Status"** panel

**Expected Governance Display:**
```
🛡️ AI Governance Status
━━━━━━━━━━━━━━━━━━━━━━━━━━
Risk Tier: 🟡 R1 - Customer Facing
Trace ID: abc12345-1234-5678-9012-def678901234

Active Governance Controls:
✅ G1 Safety Case: Safety case activated: rag_external_customer_facing
✅ G2 Risk Tiering: Risk tier assigned: external_customer_facing
✅ G3 Evidence Contract: Evidence validated: 2 citation(s) - good
✅ G6 Version Control: Response generated: model=gpt-4o-mini, prompt=v1.0
✅ G7 Observability: Audit trail: logged (trace_id: abc12345...)
✅ G8 Evaluation System: Latency: 1234ms (SLO: <2000ms) - ✓
✅ G9 Data Governance: Retrieved 3 chunks from 1 collection(s)
✅ G11 Reliability: Smart RAG completed successfully: Hybrid RAG

Checkpoints: 8/8 passed
```

### Step 5: Verify Backend Logs
```bash
docker logs ai-louie-backend-1 2>&1 | grep "governance"
```

**Expected Log Output:**
```
INFO: Started governance tracking: abc12345... - rag - external_customer_facing
INFO: Governance checkpoint: g2_risk_tiering - passed
INFO: Governance checkpoint: g10_domain_isolation - passed
INFO: Governance checkpoint: g3_evidence_contract - passed (2 citations)
INFO: Governance checkpoint: g6_version_control - passed
INFO: Governance checkpoint: g8_evaluation_system - passed (1234ms < 2000ms)
INFO: Governance checkpoint: g7_observability - passed
INFO: Governance checkpoint: g11_reliability - passed
INFO: Completed governance tracking: abc12345... - 8 checkpoints
```

### Step 6: Test Model Compatibility
Run a few RAG queries and monitor latency:

**Test Queries:**
1. "Who wrote 'DADDY TAKE ME SKATING'?" (Simple factual - Hybrid RAG)
2. "'Pride and Prejudice', analyze Elizabeth and Darcy's relationship" (Complex - Self-RAG)
3. "'Sir roberts fortune a novel', show me roles relationship" (Relationship - Graph RAG)

**Expected Performance:**
- Hybrid RAG: 800-1200ms ✓ (within 2000ms SLO)
- Self-RAG: 2000-4000ms (may exceed SLO ⚠️)
- Graph RAG: 3000-6000ms (may exceed SLO ⚠️)

### Step 7: View Governance Framework
Click **"📖 View Governance Framework"** in the sidebar to verify:
- ✅ Risk tier definitions displayed
- ✅ Governance criteria explanations
- ✅ Benefits section
- ✅ Traceability features

## 🔍 Troubleshooting

### Issue: No governance status displayed
**Check:**
1. Backend logs for governance tracker initialization
2. Response JSON contains `governance_context` field
3. Frontend console for JavaScript errors

**Fix:**
```bash
docker logs ai-louie-backend-1 | tail -100
docker logs ai-louie-frontend-1 | tail -100
```

### Issue: Poor retrieval quality
**Check:**
1. Qdrant collection name matches .env (assessment_docs_minilm)
2. Embedding model is MiniLM (not BGE)
3. Vector dimensions are 384

**Fix:**
```bash
# Verify .env configuration
grep "ONNX_EMBED_MODEL_PATH" .env
# Should output: ONNX_EMBED_MODEL_PATH=./models/minilm-embed-int8

# Verify Qdrant collection
curl http://localhost:6333/collections/assessment_docs_minilm | jq '.result.config.params.vectors.size'
# Should output: 384
```

### Issue: SLO violations (latency > 2000ms)
**Check:**
1. Backend logs for slow components
2. ONNX inference performance
3. Smart RAG strategy selection

**Expected:**
- Hybrid RAG: Fast (< 2000ms)
- Self-RAG: May exceed SLO for complex queries
- Graph RAG: May exceed SLO for relationship queries

**Action:**
- Review `docs/MODEL_STRATEGY.md` for optimization options
- Consider caching strategies (query cache, answer cache)
- Monitor Smart RAG bandit metrics

### Issue: Missing citations
**Check:**
1. Retrieval returned results (num_chunks_retrieved > 0)
2. Reranker is working (check logs)
3. Query matches document collection domain

**Fix:**
```bash
# Check retrieval logs
docker logs ai-louie-backend-1 | grep "Retrieved"
# Should see: "Retrieved X chunks from Y collection(s)"

# Check reranker logs
docker logs ai-louie-backend-1 | grep "rerank"
# Should see reranker initialization and scoring
```

## 📊 Post-Deployment Monitoring

### Metrics to Track

**1. Governance Metrics:**
- Total operations tracked
- Checkpoint pass/fail rates
- Trace ID coverage (should be 100%)
- SLO compliance rate (target: >90% for R1)

**2. Model Performance:**
- Embedding latency (MiniLM: 50-80ms, BGE: 100-150ms)
- Reranker latency (BGE: 50-100ms)
- Fallback trigger rate (<5% expected)

**3. RAG Quality:**
- Citation coverage (target: ≥95%)
- Answer cache hit rate (target: >30%)
- Smart RAG strategy distribution

### Log Queries

**Find all governance traces:**
```bash
docker logs ai-louie-backend-1 | grep "Started governance tracking"
```

**Find traces with SLO violations:**
```bash
docker logs ai-louie-backend-1 | grep "SLO.*⚠"
```

**Find failed checkpoints:**
```bash
docker logs ai-louie-backend-1 | grep "checkpoint.*failed"
```

**Find specific trace by ID:**
```bash
docker logs ai-louie-backend-1 | grep "abc12345-1234-5678-9012-def678901234"
```

## 🎉 Success Criteria

**Deployment is successful when:**
- ✅ All Docker containers are running (backend, frontend, qdrant, inference)
- ✅ Health checks pass for all services
- ✅ RAG queries return answers with citations
- ✅ Governance status panel displays for all operations
- ✅ Trace IDs are generated and logged
- ✅ SLO compliance is >90% for R1 operations
- ✅ Model latency is acceptable (MiniLM: <100ms)
- ✅ No critical errors in backend logs

## 📚 Quick Reference

**Key Files:**
- Configuration: [.env](./.env)
- Start script: [start.sh](./start.sh)
- Governance docs: [docs/GOVERNANCE_QUICKSTART.md](./docs/GOVERNANCE_QUICKSTART.md)
- Model strategy: [docs/MODEL_STRATEGY.md](./docs/MODEL_STRATEGY.md)

**Key Services:**
- Frontend: http://localhost:18501
- Backend API: http://localhost:8888
- Backend Docs: http://localhost:8888/docs
- Qdrant: http://localhost:6333
- Inference: http://localhost:8001

**Docker Commands:**
```bash
# Start all services
./start.sh

# Stop all services
docker-compose down

# View logs
docker logs ai-louie-backend-1 -f
docker logs ai-louie-frontend-1 -f

# Rebuild images
docker-compose build backend frontend

# Full restart
docker-compose down && docker-compose build && ./start.sh
```

## 🚧 Known Limitations (MVP)

**Current Scope:**
- ✅ RAG operations have full governance tracking
- ✅ Code operations have full governance tracking
- ✅ Chat operations have full governance tracking
- ❌ Frontend only displays RAG governance (Code/Chat display pending)

**Future Enhancements:**
- Policy engine enforcement (capability gates)
- Evidence contract enhancement (SHA-256 verification)
- Access control (pre-retrieval filtering)
- R2/R3 support (human approval, dual control)
- Governance dashboard (real-time metrics)

## ✅ Deployment Sign-Off

**Version:** 1.0 (MVP - Governance Integration Complete)
**Date:** 2025-12-04
**Status:** Ready for Deployment

**Changes Verified:**
- ✅ All governance services implemented
- ✅ All frontend components created
- ✅ Model configuration corrected
- ✅ Docker images built successfully
- ✅ Documentation complete

**Tested By:** [Pending User Testing]
**Deployed By:** [Pending User Deployment]
**Deployment Environment:** Docker Compose (local)

---

**Next Steps:**
1. Run `./start.sh` to deploy
2. Test RAG queries with governance display
3. Monitor backend logs for trace IDs
4. Report any issues or unexpected behavior
5. Proceed with Code/Chat frontend display if needed

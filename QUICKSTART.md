# AI-Louie Quick Start Guide

## 🚀 One-Command Launch

```bash
./start.sh
```

The script automatically handles:
- ✅ Data download and extraction (150 classic books corpus)
- ✅ OpenAI API key configuration
- ✅ Docker container orchestration
- ✅ Qdrant vector database seeding (150k+ embeddings)
- ✅ Smart RAG warm-up with Thompson Sampling
- ✅ Browser auto-launch when ready

**First run:** ~5-10 minutes (data download + vector seeding)
**Subsequent runs:** ~10-30 seconds (data persisted, skip seeding)

---

## 📋 Prerequisites

- **Docker Desktop** installed and running
- **8+ GB RAM** available
- **10+ GB disk space** for vector database
- **OpenAI API key** (prompted on first run)

---

## 🎯 Product Features

### 1. **Adaptive Multi-Strategy RAG**
- **Thompson Sampling Bandit**: Automatically learns optimal retrieval strategy per query type
- **4 Retrieval Strategies**:
  - **Hybrid Search**: BM25 + vector search fusion (best for factual queries)
  - **Iterative Refinement**: Self-RAG with confidence scoring (best for complex questions)
  - **Graph RAG**: Entity relationship extraction (best for "who/what/how" queries)
  - **Table RAG**: Structured data extraction (best for comparative queries)
- **Performance**: 40-60% latency reduction vs. fixed-strategy baseline

### 2. **High-Performance Inference**
- **ONNX Runtime**: INT8 quantized models for 3-4x faster embedding/reranking
- **Remote Inference Service**: Dedicated container for parallel processing
- **Dual Model Strategy**:
  - **MiniLM** (primary): Fast 384-dim embeddings, compatible with existing data
  - **BGE** (fallback): High-accuracy 768-dim for low-confidence queries
- **Adaptive Fallback**: Confidence-based switching (MiniLM → BGE at <0.65 score)

### 3. **Production-Grade Caching**
- **3-Layer Cache System**:
  - **Query Cache**: Semantic similarity matching (>0.85 threshold, 24h TTL)
  - **Answer Cache**: Exact query deduplication
  - **Classification Cache**: Query type prediction results
- **Cache Hit Rate**: 30-50% for typical workloads
- **Persistence**: SQLite-backed, survives restarts

### 4. **Full Observability Stack**
- **Prometheus Metrics**: Request latency, cache hits, strategy distribution
- **Grafana Dashboards**: Real-time performance monitoring
- **Jaeger Tracing**: Distributed request tracing with OTLP integration
- **Structured Logging**: JSON logs with correlation IDs

### 5. **Zero-Downtime Persistence**
- **Qdrant Vector DB**: 150k+ embeddings persisted in Docker volumes
- **Thompson Sampling Weights**: Alpha/beta parameters saved to `./cache/smart_bandit_state.json`
- **BM25 Index**: Prebuilt index cached for instant hybrid search
- **Auto-Recovery**: Skips re-seeding on restart if data exists

---

## 🌐 Service Access

| Service | URL | Credentials |
|---------|-----|-------------|
| **Frontend (Streamlit)** | http://localhost:18501 | - |
| **Backend API** | http://localhost:8888 | - |
| **API Docs (Swagger)** | http://localhost:8888/docs | - |
| **Qdrant Dashboard** | http://localhost:6333/dashboard | - |
| **Grafana Monitoring** | http://localhost:3000 | admin/admin |
| **Prometheus Metrics** | http://localhost:9090 | - |
| **Jaeger Tracing** | http://localhost:16686 | - |

---

## 🔧 Usage Examples

### Web UI (Streamlit)
1. Open http://localhost:18501
2. Select RAG strategy or use "Smart RAG" (auto-selection)
3. Enter your question
4. View answer with source citations, strategy used, and performance metrics

### REST API
```bash
# Smart RAG (auto-selects best strategy)
curl -X POST http://localhost:8888/api/rag/ask-smart \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are the main themes in Pride and Prejudice?",
    "top_k": 3
  }'

# Hybrid Search (BM25 + vector)
curl -X POST http://localhost:8888/api/rag/ask-hybrid \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Who wrote The Great Gatsby?",
    "top_k": 5,
    "alpha": 0.7
  }'

# Graph RAG (entity relationships)
curl -X POST http://localhost:8888/api/rag/ask-graph \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How are Elizabeth and Mr. Darcy related?",
    "top_k": 3
  }'

# Streaming responses
curl -N -X POST http://localhost:8888/api/rag/ask-smart-stream \
  -H "Content-Type: application/json" \
  -d '{"question": "Summarize Moby Dick", "top_k": 5}'
```

---

## 🛑 Shutdown

### Graceful Shutdown (Recommended)
Press **Ctrl+C** in the terminal where `start.sh` is running.
- Containers stopped via `docker-compose down`
- **Data persisted** (Qdrant vectors, cache, bandit weights)

### Manual Shutdown
```bash
# Stop containers, keep data
docker-compose down

# Full clean (⚠️ removes all data)
docker-compose down -v
```

---

## 🔍 Health Checks

```bash
# Backend API
curl http://localhost:8888/health

# Qdrant (should return collection info)
curl http://localhost:6333/collections/assessment_docs_minilm

# Check vector count (should be ~150k)
curl -s http://localhost:6333/collections/assessment_docs_minilm | grep points_count

# Smart RAG bandit status
curl http://localhost:8888/api/rag/smart-status
```

---

## 📊 Performance Benchmarks

**Hardware**: M1 MacBook (8-core, 16GB RAM)

| Operation | Latency (p50) | Latency (p95) |
|-----------|---------------|---------------|
| Hybrid Search | 450ms | 850ms |
| Iterative RAG | 1.2s | 2.5s |
| Graph RAG | 2.8s | 5.5s |
| Table RAG | 1.8s | 3.2s |
| Smart RAG (cached) | 120ms | 300ms |

**Cache Hit Rate**: 30-50% for typical workloads
**Thompson Sampling Overhead**: <50ms per query
**Vector Seeding**: ~5-8 minutes (150k embeddings, 6-10 workers)

---

## 🐛 Troubleshooting

### Issue: "Collection has 0 vectors"
**Cause**: Qdrant seeding incomplete or data deleted
**Fix**: Wait for seeding to complete (check progress in terminal), or re-run `./start.sh`

### Issue: "Browser opens but UI not loading"
**Cause**: Backend warm-up not complete
**Fix**: Wait 5 seconds after warm-up completes (automatically handled in latest version), or refresh browser

### Issue: "docker-compose: command not found"
**Cause**: Docker Desktop not installed or not in PATH
**Fix**: Install Docker Desktop from https://www.docker.com/products/docker-desktop

### Issue: "Port already in use"
**Cause**: Previous containers still running
**Fix**: Run `docker-compose down` or `docker ps` to check running containers

### Check Logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f qdrant
```

---

## 📚 Dataset

**Corpus**: 150 classic books from Project Gutenberg
**Source**: https://huggingface.co/datasets/louielunz/150books
**Format**: JSONL with pre-computed embeddings (MiniLM-L6, 384-dim)
**Size**: ~1.2GB compressed, 3.5GB extracted
**Vector Count**: ~150,000 chunks (512 tokens each, 50 token overlap)

---

## 🔐 Environment Variables

Key configuration options in `.env`:

```bash
# LLM Configuration
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1

# RAG Features
ENABLE_HYBRID_SEARCH=true
ENABLE_QUERY_CACHE=true
ENABLE_SELF_RAG=true
ENABLE_QUERY_CLASSIFICATION=true

# Performance Tuning
QDRANT_SEED_MAX_WORKERS=8  # Auto-detected by default
BM25_TOP_K=25
HYBRID_ALPHA=0.7  # Weight: 0.7 vector + 0.3 BM25
QUERY_CACHE_SIMILARITY_THRESHOLD=0.85
```

See `.env.example` for full configuration options.

---

## 🚢 Architecture

```
┌─────────────┐
│  Streamlit  │  ← User Interface (port 18501)
│   Frontend  │
└──────┬──────┘
       │
┌──────▼──────┐
│   FastAPI   │  ← REST API (port 8888)
│   Backend   │
└──────┬──────┘
       │
       ├─────────────┐─────────────┐─────────────┐
       │             │             │             │
┌──────▼──────┐ ┌───▼────┐ ┌──────▼──────┐ ┌───▼────────┐
│   Qdrant    │ │ ONNX   │ │ Prometheus  │ │  Jaeger    │
│  (vectors)  │ │Inference│ │  (metrics)  │ │ (tracing)  │
└─────────────┘ └────────┘ └──────┬──────┘ └────────────┘
                                   │
                            ┌──────▼──────┐
                            │   Grafana   │
                            │ (dashboards)│
                            └─────────────┘
```

---

## 📖 Next Steps

- Explore API documentation: http://localhost:8888/docs
- View Grafana dashboards: http://localhost:3000
- Monitor Thompson Sampling learning: Check bandit alpha/beta values in Grafana
- Experiment with different RAG strategies via UI or API
- Analyze query performance with Jaeger tracing

For detailed documentation, see [README.md](README.md)

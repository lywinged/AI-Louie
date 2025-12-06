# AI-Louie: Enterprise AI Assessment Platform

A comprehensive Streamlit + FastAPI platform featuring advanced RAG strategies, autonomous planning agents, self-healing code generation, and enterprise-grade monitoring.

---

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- 8GB+ RAM recommended
- OpenAI API key (or compatible endpoint)

### Installation
1. **Clone and configure**:
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

2. **(Optional) Download large BGE models**:
   ```bash
   # System works with included MiniLM models (44MB)
   # Download BGE models (834MB) for higher accuracy
   ./scripts/download_models.sh
   ```
   > 📥 See [Model Download Guide](docs/MODEL_DOWNLOAD_GUIDE.md) for detailed instructions

3. **Start all services**:
   ```bash
   ./start.sh
   ```

4. **Access the platform**:
   - 🎨 **Frontend UI**: http://localhost:18501
   - 📡 **Backend API**: http://localhost:8888/docs
   - 📊 **Grafana**: http://localhost:3000 (admin/admin)
   - 🔍 **Jaeger**: http://localhost:16686
   - 📈 **Prometheus**: http://localhost:9090

### First-Time Startup
- **Warm-up**: Backend performs 3 Smart RAG warm-up queries (~70s)
- **Seed data**: Qdrant automatically loads ~153K vectors from seed file
- **Health checks**: Frontend waits for backend health before starting (no connection errors)

---

## ✨ Core Features

### 🛡️ AI Governance Framework (NEW!)
- **Risk Tier Classification**: Automatic R0-R3 tier assignment per operation
  - 🟢 R0 (Low Risk Internal): Code generation, statistics
  - 🟡 R1 (Customer Facing): RAG Q&A, chat agents - **Citations REQUIRED**
  - 🟠 R2 (Decision Support): Future - human approval required
  - 🔴 R3 (Automated Actions): Future - dual control + rollback
- **12 Governance Criteria (G1-G12)**: Safety case, evidence contract, observability, SLO monitoring
- **Real-Time Tracking**: Unique trace IDs, checkpoint logging, audit trails
- **Visual Status Display**: Governance panel showing active controls and compliance
- **SLO Targets**: R1 latency <2s, citation coverage ≥95%, confidence ≥0.7
- **Inspiration**: Based on Air NZ AI Governance and aviation SMS standards
- **Documentation**: See [GOVERNANCE_INTEGRATION.md](docs/GOVERNANCE_INTEGRATION.md)

### 🎯 Task 3.1: Conversational Chat with Streaming
- **Streaming responses**: Token-by-token SSE (Server-Sent Events)
- **Session management**: SQLite-backed conversation history
- **Context awareness**: Multi-turn conversation with history
- **Metrics tracking**: Token usage, cost estimation, response times

### 📚 Task 3.2: High-Performance RAG Q&A

#### Multi-Strategy RAG System
Seven RAG strategies with automatic selection:

1. **🎯 Smart Auto-Select (Recommended)**
   - Thompson Sampling multi-armed bandit algorithm
   - Automatically chooses from 4 strategies:
     - **Hybrid RAG**: Simple factual queries
     - **Iterative Self-RAG**: Complex analytical queries
     - **Graph RAG**: Relationship/character queries
     - **Table RAG**: Structured data queries
   - Learning system that adapts to usage patterns
   - Exploration bonus (20%) for under-explored strategies
   - Warm-up: 3 queries covering all strategies (~70s)

2. **📝 Standard RAG**
   - Dense vector similarity search (cosine)
   - Basic embedding → retrieval → generation pipeline
   - Best for: Simple semantic search

3. **🔍 Hybrid Search**
   - BM25 keyword search (30%) + Vector search (70%)
   - RRF (Reciprocal Rank Fusion) score fusion
   - Cross-encoder reranking
   - Best for: Queries with specific keywords

4. **🔁 Iterative Self-RAG**
   - Confidence-based iterative refinement
   - Self-assessment and query refinement
   - Max 3 iterations with early stopping (0.05 improvement threshold)
   - Confidence threshold: 0.75
   - Best for: Complex analytical questions

5. **⚡ Streaming RAG**
   - Real-time token-by-token streaming
   - Lower perceived latency
   - Same retrieval quality as Standard RAG
   - Best for: Interactive chat experiences

6. **🕸️ Graph RAG**
   - JIT (Just-In-Time) entity relationship extraction
   - Graph traversal for connected entities
   - Combines graph context + vector retrieval
   - Batch extraction with parallel processing
   - Max 50 JIT chunks, batch size 4, 30s timeout
   - Best for: "Who knows whom", character relationships, entity connections

7. **📊 Table RAG**
   - Structured data extraction and table generation
   - Intent analysis (comparison/list/aggregation)
   - Markdown table formatting
   - Best for: Comparison queries, data listing

#### Advanced Caching System

**Multi-Layer Answer Cache with Quality Control**:
- **Quality thresholds**: Only cache answers with ≥1 citation AND ≥1 chunk
- **No blind caching**: Prevents pollution from low-quality answers
- **3-layer architecture**:
  1. Exact match (O(1) lookup)
  2. TF-IDF similarity (threshold: 0.85)
  3. Semantic embedding (threshold: 0.85)
- **TTL**: 24 hours (configurable)
- **Max size**: 1000 entries (configurable)
- **Token savings**: Displays saved tokens on cache hit

**Query Strategy Cache**:
- Caches query classification results
- Reduces LLM calls for similar queries
- Improves response time

#### Multi-Collection Search
- **System documents**: Pre-loaded seed data (~153K vectors)
- **User uploads**: Personal document collection
- **Search scopes**:
  - 🌐 All Documents (system + uploads)
  - 📁 My Uploads Only
  - 📚 System Data Only
- **Smart RAG integration**: Works seamlessly with auto-selection

#### Performance Optimizations
- **ONNX inference**: INT8 quantized models for 3-4x speedup
- **Remote inference service**: Dedicated container for embeddings/reranking
- **Model warm-up**: 3 queries for fast first response
- **Reranker fallback**: Auto-switch from BGE to MiniLM if query >300ms
- **BM25 indexing**: File-based persistence for instant startup

### ✈️ Task 3.3: Autonomous Trip Planning Agent
- **Multi-stage planning**: Collects 4 key constraints (destination, origin, days, budget)
- **Flight search**: Real-time flight API integration
- **Itinerary generation**: Day-by-day plans with activities
- **Cost breakdown**: Flights, accommodation, meals, transport
- **Conversation memory**: Tracks constraint collection progress
- **Currency handling**: Automatic FX conversion and display

### 💻 Task 3.4: Self-Healing Code Assistant

#### Code Generation with Testing
- **Automatic test generation**: Creates pytest/unittest tests
- **Print output injection**: AST manipulation to display execution results
  - Supports plain `assert` statements
  - Supports `unittest.TestCase` assertions (self.assertEqual, etc.)
  - Shows "=== Program Output ===" sections in test results
  - Enabled by default (`include_samples=True`)
- **Multiple languages**: Python, JavaScript, Java, C++, Go, Rust
- **Test frameworks**: pytest, unittest, Jest, JUnit, googletest, cargo test

#### Self-Healing Capabilities
- **Automatic retry**: Up to 3 attempts on test failure
- **Error analysis**: LLM-powered fix generation
- **Strategy learning**: Tracks success rates by strategy
  - `minimal_planner`: Quick iterations
  - `detailed_planner`: Comprehensive analysis
  - `step_by_step`: Incremental approach
- **Metrics tracking**: Success rate, retry count, execution time

#### Enhanced UI Display
- **Initial plan**: Numbered steps with proper formatting (no duplication)
- **Test results**: Colored output with execution details
- **Code download**: Complete code + tests in single file
- **Progress tracking**: Real-time status updates

---

## 🎨 User Interface Features

### Mode Switching
- **4 modes**: General Chat, RAG Q&A, Trip Planning, Code Generation
- **Activation messages**: Displayed on every mode switch (not just first time)
- **Updated examples**: Includes new Graph RAG query examples
- **Context preservation**: Automatic cleanup of mode-specific state

### RAG Strategy Selector
- **Visual descriptions**: Detailed info box for each strategy
- **Smart RAG details**: Explicitly lists covered strategies
- **Pipeline explanations**: Step-by-step technical flow
- **Use case guidance**: "Best for" recommendations

### Configuration Controls
- **Reranker selection**: BGE-M3 (accurate) / MiniLM (fast) / Fallback (auto)
- **Vector limits**: Configurable candidate count
- **Content limits**: Character truncation for context
- **Search scope**: Multi-collection selection

---

## 🏗️ Architecture

### Services (Docker Compose)

1. **Frontend** (Streamlit)
   - Port: 18501
   - Depends on: backend (health check)
   - Volume: Frontend code (not mounted, rebuild required)

2. **Backend** (FastAPI)
   - Port: 8888
   - Endpoints: `/api/chat`, `/api/rag`, `/api/agent`, `/api/code`, `/api/monitoring`
   - Depends on: qdrant, inference
   - Volumes: models, data, cache, session DB

3. **Inference** (ONNX Service)
   - Port: 8001
   - Provides: `/embed` and `/rerank` endpoints
   - Models: INT8 quantized MiniLM

4. **Qdrant** (Vector DB)
   - Ports: 6333 (HTTP), 6334 (gRPC)
   - Persistent storage: `qdrant_storage` volume
   - Seed: Auto-loads from `data/qdrant_seed/`

5. **Prometheus** (Metrics)
   - Port: 9090
   - Scrapes: backend, inference, blackbox-exporter
   - Alert rules: `monitoring/prometheus/alert_rules.yml`

6. **Grafana** (Dashboards)
   - Port: 3000
   - Credentials: admin/admin (change in .env)
   - Dashboards: `monitoring/grafana/dashboards/`

7. **Jaeger** (Tracing)
   - Port: 16686 (UI), 4317 (OTLP gRPC), 4318 (OTLP HTTP)
   - OpenTelemetry integration

8. **Blackbox Exporter**
   - Port: 9115
   - Probes: HTTP endpoint health

### Key Directories

```
AI-Louie/
├── backend/
│   ├── backend/
│   │   ├── routers/         # API endpoints
│   │   ├── services/        # Business logic (RAG, chat, code, etc.)
│   │   ├── models/          # Pydantic schemas
│   │   └── config/          # Settings
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── app.py               # Main Streamlit UI
│   ├── components/          # Reusable UI components
│   ├── Dockerfile
│   └── requirements.txt
├── inference/
│   ├── main.py              # ONNX inference service
│   └── Dockerfile
├── models/
│   ├── minilm-embed-int8/   # Embedding model
│   └── minilm-reranker-onnx/# Reranker model
├── data/
│   ├── qdrant_seed/         # Pre-embedded vectors (153K)
│   └── uploads/             # User uploaded files
├── monitoring/
│   ├── prometheus/          # Config, alert rules, blackbox
│   └── grafana/             # Dashboards, provisioning
├── cache/                   # BM25 index, query cache
├── docs/
│   ├── CONSOLIDATED/        # Main documentation
│   └── ARCHIVE/             # Legacy docs
├── docker-compose.yml
├── .env.example
└── start.sh
```

---

## 🔧 Configuration

### Environment Variables (.env)

#### API Keys
```bash
OPENAI_API_KEY=your_key_here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

#### Qdrant
```bash
QDRANT_HOST=qdrant
QDRANT_PORT=6333
QDRANT_COLLECTION=assessment_docs_minilm
QDRANT_SEED_PATH=data/qdrant_seed
QDRANT_SEED_VECTOR_SIZE=384
QDRANT_SEED_TARGET_COUNT=138000
```

#### ONNX Inference
```bash
USE_ONNX_INFERENCE=true
USE_INT8_QUANTIZATION=true
ENABLE_REMOTE_INFERENCE=true
EMBEDDING_SERVICE_URL=http://inference:8001
RERANK_SERVICE_URL=http://inference:8001
```

#### Advanced RAG Features
```bash
# Hybrid Search
ENABLE_HYBRID_SEARCH=true
HYBRID_ALPHA=0.7              # Vector weight (0.7 = 70% vector, 30% BM25)
BM25_TOP_K=25

# Query Cache
ENABLE_QUERY_CACHE=true
QUERY_CACHE_SIMILARITY_THRESHOLD=0.85
QUERY_CACHE_MAX_SIZE=1000
QUERY_CACHE_TTL_HOURS=24

# Query Classification
ENABLE_QUERY_CLASSIFICATION=true

# Self-RAG
ENABLE_SELF_RAG=true
SELF_RAG_CONFIDENCE_THRESHOLD=0.75
SELF_RAG_MAX_ITERATIONS=3
SELF_RAG_MIN_IMPROVEMENT=0.05

# Smart RAG Warm-up
WARM_SMART_RAG=1              # Set to 0 to disable
SMART_RAG_LATENCY_BUDGET_MS=8000

# Graph RAG
GRAPH_MAX_JIT_CHUNKS=50
```

#### Monitoring
```bash
ENABLE_METRICS=true
ENABLE_TELEMETRY=true
OTLP_ENDPOINT=http://jaeger:4317
GRAFANA_ADMIN_PASSWORD=admin
```

---

## 🚀 Advanced Features

### 🧠 Thompson Sampling Multi-Armed Bandit
- **Adaptive strategy selection**: Automatically learns optimal RAG strategy per query type
- **Exploration-exploitation balance**: 20% exploration bonus for under-explored strategies
- **Persistent learning**: Saves bandit state to disk for cross-session knowledge retention
- **Real-time metrics**: Prometheus metrics for arm selection, rewards, and regret
- **Warm-up optimization**: 3 strategic queries to initialize all arms (~70s)
- **Feedback loop**: User ratings (👍/👎) update bandit weights dynamically

### 🔄 Answer Cache with Quality Control
- **Multi-layer cache architecture**:
  - Layer 1: Exact match (O(1) lookup)
  - Layer 2: TF-IDF similarity (threshold: 0.85)
  - Layer 3: Semantic embedding (threshold: 0.85)
- **Quality thresholds**: Only cache answers with ≥1 citation AND ≥1 chunk
- **TTL management**: Configurable expiration (default: 24h)
- **LRU eviction**: Max 1000 entries with automatic cleanup
- **Token savings tracking**: Displays saved tokens/cost on cache hit
- **Cache hit visualization**: Green checkmark indicator in UI

### 🕸️ Just-In-Time Graph RAG
- **Dynamic entity extraction**: On-the-fly relationship discovery from retrieved chunks
- **Parallel processing**: Batch extraction with configurable workers (default: 4)
- **Graph persistence**: NetworkX graph cached across queries
- **Incremental updates**: Adds new entities/relationships without rebuilding
- **Timeout protection**: Configurable max processing time (default: 30s)
- **Max chunk limit**: Prevents runaway extraction (default: 50 chunks)
- **Relationship scoring**: Weighted edges for semantic connection strength

### 📊 Table RAG with Intent Analysis
- **Intent classification**: Automatically detects comparison/list/aggregation queries
- **Structured extraction**: LLM-powered tabular data identification
- **Markdown formatting**: Clean, readable table output
- **Multi-column support**: Dynamic column detection based on content
- **Header inference**: Automatic column naming from data patterns

### 🔍 Hybrid Retriever with RRF Fusion
- **Dual-mode search**: BM25 keyword (30%) + Dense vector (70%)
- **Reciprocal Rank Fusion**: Score fusion with configurable weights
- **Cross-encoder reranking**: BGE-M3 or MiniLM for final scoring
- **File-based BM25 index**: Instant startup with persistent cache
- **Fallback mechanism**: Auto-switch to fast reranker if >300ms

### 🔁 Iterative Self-RAG with Confidence Scoring
- **Confidence-based iteration**: Continues until threshold (0.75) or max iterations (3)
- **Self-assessment**: LLM evaluates answer quality and generates refinement queries
- **Early stopping**: Halts if improvement <0.05 between iterations
- **Query refinement**: Automatically reformulates questions for better retrieval
- **Iteration tracking**: Detailed per-iteration token/cost/confidence display

### 🎯 Query Classification Cache
- **Strategy prediction cache**: Reduces LLM calls for similar query types
- **Semantic similarity**: Embedding-based classification lookup
- **TTL management**: Configurable expiration per classification
- **Classification override**: Manual strategy selection bypasses cache

### ⚡ ONNX INT8 Quantization
- **3-4x speedup**: Quantized embedding and reranking models
- **Memory efficiency**: 75% smaller model footprint
- **Remote inference service**: Dedicated container for model execution
- **GPU support**: CUDA acceleration when available
- **Model warm-up**: Pre-loads models during startup for fast first query

### 📁 Multi-Collection Search
- **Dual collection support**: System documents + User uploads
- **Collection isolation**: Separate Qdrant collections with independent vectors
- **Search scope control**: Filter by "All", "My Uploads", or "System" documents
- **Smart RAG integration**: Works seamlessly with auto-selection across collections
- **Upload management**: Document ingestion with chunking, embedding, and metadata

### 🧪 Code Generation with Print Injection
- **AST manipulation**: Automatically injects print statements into test code
- **Framework support**: pytest, unittest, Jest, JUnit, googletest, cargo test
- **Assertion handling**:
  - Plain `assert` statements
  - unittest.TestCase methods (assertEqual, assertTrue, etc.)
  - Shows "=== Program Output ===" sections
- **Multi-language**: Python, JavaScript, Java, C++, Go, Rust
- **Download support**: Combined code + tests in single file

### 🎨 Dynamic UI Enhancements
- **Mode activation messages**: Displayed on every switch (not just first time)
- **Strategy descriptions**: Detailed info boxes for each RAG strategy
- **Example question dropdowns**: Context-aware suggestions per mode
- **Progress indicators**: Real-time status for long-running operations (Graph RAG, Self-RAG)
- **Governance panel**: Live checkpoint tracking with color-coded status
- **Token cost breakdown**: Per-query token usage and USD cost estimation

### 🔐 AI Governance Integration
- **12 governance criteria**: Safety case, risk tiering, observability, SLO monitoring
- **Automated checkpoints**:
  - G4 Permission Layers: User authorization
  - G6 Version Control: Model/prompt versioning
  - G7 Observability: Audit trails and trace IDs
  - G8 Evaluation System: Latency/quality SLO checks
  - G9 Data Governance: Data source tracking
  - G12 Dashboard: Metrics export for Grafana
- **Risk tier classification**: R0 (Internal) → R1 (Customer Facing) → R2 (Decision Support) → R3 (Automated Actions)
- **Citation enforcement**: R1 operations require ≥95% citation coverage
- **Trace ID propagation**: Unique IDs across distributed services for audit

### 📈 Distributed Tracing (Jaeger)
- **End-to-end visibility**: Request flow across frontend → backend → inference → Qdrant
- **Instrumentation**: FastAPI, HTTPX, SQLAlchemy auto-instrumentation
- **Custom spans**: RAG pipeline stages, LLM calls, cache lookups
- **Performance profiling**: Identify bottlenecks in complex queries
- **Error correlation**: Link failures across service boundaries

### 🔄 Session Management with SQLite
- **Persistent conversations**: Chat history survives container restarts
- **Multi-mode support**: Separate conversation threads per mode
- **Message metadata**: Timestamps, token usage, confidence scores
- **Session export**: Download conversation history as JSON
- **Auto-cleanup**: Configurable retention policies

### 🚦 Health Check Orchestration
- **Dependency waiting**: Frontend blocks until backend is healthy
- **Graceful startup**: Sequential service initialization (Qdrant → Backend → Frontend)
- **Auto-retry**: Exponential backoff for failed health checks
- **Status display**: UI shows "System Initializing" during seed upload
- **Progress tracking**: Real-time vector count during Qdrant seeding

---

## 📊 Monitoring & Observability

### Metrics (Prometheus)
- **System metrics**: CPU, memory, request rates
- **RAG metrics**: Query latency, cache hit rates, strategy selection
- **LLM metrics**: Token usage, cost, model performance
- **Code metrics**: Test pass rate, retry count, strategy success

### Tracing (Jaeger)
- **Distributed tracing**: End-to-end request flow
- **Instrumentation**: FastAPI, HTTPX, SQLAlchemy
- **Span details**: Timing, tags, logs

### Dashboards (Grafana)
- **RAG Performance**: Query times, cache effectiveness
- **LLM Usage**: Token consumption, cost tracking
- **System Health**: Service status, error rates
- **Smart RAG**: Bandit state, strategy distribution

### Health Checks
- **Backend**: `GET /health` - Service status, config details
- **Frontend**: `GET /_stcore/health` - Streamlit health
- **Blackbox probes**: HTTP endpoint monitoring

---

## 🧪 Testing

### Backend Tests
```bash
cd backend
pytest tests/ -v
pytest tests/test_rag_api.py -v
pytest tests/test_monitoring_routes.py -v
```

### Frontend Tests
```bash
cd frontend
pytest tests/ -v
```

### Integration Tests
```bash
# Test RAG endpoint
python3 test_cache_quality.py
python3 test_smart_rag_selection.py
```

---

## 🚢 Deployment

### Production Checklist
- [ ] Change default passwords (Grafana, etc.)
- [ ] Configure CORS origins in `backend/main.py`
- [ ] Set proper API rate limits
- [ ] Enable HTTPS/TLS
- [ ] Set up log aggregation
- [ ] Configure backup for Qdrant volumes
- [ ] Set resource limits in docker-compose
- [ ] Enable authentication/authorization

### Scaling Recommendations
- **Qdrant**: Use Qdrant Cloud or cluster mode for production
- **Inference**: Scale horizontally with load balancer
- **Backend**: Use Gunicorn with multiple workers
- **Caching**: Consider Redis for distributed cache

---

## 📚 Documentation

Detailed guides available in `docs/CONSOLIDATED/`:
- `QUICKSTART.md` - Getting started guide
- `RAG_Strategy_Guide.md` - RAG strategies explained
- `Answer_Cache_Guide.md` - Caching system details
- `MultiCollection_Upload_Guide.md` - User uploads
- `Streaming_Guide.md` - SSE implementation
- `UI_Visualization.md` - Frontend features
- `Monitoring_Summary.md` - Observability setup
- `Smart_RAG_Policy.md` - Bandit algorithm details

---

## 🐛 Troubleshooting

### Common Issues

**1. "Connection refused" on startup**
- **Fixed**: Frontend now waits for backend health check
- If still occurs: Check logs with `docker-compose logs backend`

**2. Slow first query**
- **Normal**: Models need warm-up (~3-5 seconds)
- Subsequent queries are fast (<1 second)

**3. Cache not working**
- Check quality: Answers need ≥1 citation AND ≥1 chunk
- Verify: `ENABLE_QUERY_CACHE=true` in .env

**4. Graph RAG timeout**
- First run needs ~40-60s for JIT graph building
- Increase timeout or reduce `GRAPH_MAX_JIT_CHUNKS`

**5. Docker build issues**
- Clean rebuild: `docker-compose build --no-cache`
- Check disk space: Graph RAG needs 2GB+ for models

### Logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f frontend

# Last 100 lines
docker-compose logs --tail=100 backend
```

---

## 🤝 Contributing

### Code Style
- **Python**: Follow PEP 8
- **Type hints**: Required for new functions
- **Docstrings**: Google style
- **Tests**: Write tests for new features

### Pull Request Process
1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

### Before Committing
```bash
# Syntax check
python3 -m py_compile backend/**/*.py frontend/**/*.py

# Run tests
pytest

# Format code (optional)
black backend/ frontend/
```

---

## 📝 License

This project is for educational and assessment purposes.

---

## 🙏 Acknowledgments

- **OpenAI**: GPT models
- **Qdrant**: Vector database
- **Streamlit**: Frontend framework
- **FastAPI**: Backend framework
- **ONNX Runtime**: Optimized inference

---

## 📞 Support

For issues and questions:
- Check documentation in `docs/CONSOLIDATED/`
- Review troubleshooting section above
- Check Docker logs for error details
- Ensure all environment variables are set correctly

---

## 🎯 Roadmap

### Completed Features ✅
- [x] Multi-strategy RAG with Smart Auto-Select
- [x] Graph RAG with JIT building
- [x] Table RAG for structured data
- [x] Multi-layer answer cache with quality control
- [x] Self-healing code generation
- [x] Autonomous trip planning
- [x] Enterprise monitoring (Prometheus, Grafana, Jaeger)
- [x] ONNX optimization with INT8 quantization
- [x] Multi-collection search
- [x] Print output injection for code testing
- [x] Mode switching with activation messages
- [x] RAG strategy descriptions in UI
- [x] Optimized warm-up (3 queries)

### Future Enhancements 🚀
- [ ] Authentication and user management
- [ ] Document versioning and history
- [ ] Advanced graph visualization
- [ ] Custom model fine-tuning
- [ ] API rate limiting and quotas
- [ ] Multi-language support
- [ ] Mobile-responsive UI
- [ ] Batch document processing
- [ ] Advanced analytics dashboard

---

**Version**: 1.0.0
**Last Updated**: December 2024
**Status**: Production Ready ✅

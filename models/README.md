# AI-Louie Models Directory

This directory contains ONNX models for embedding and reranking in the AI-Louie RAG system.

## 📦 Model Overview

### Included in Git Repository (46MB total)
These lightweight models are committed to git for instant usage:

- **MiniLM Embedding** (`minilm-embed-int8/`) - 23MB
  - Model: `sentence-transformers/all-MiniLM-L6-v2` (INT8 quantized)
  - Vector dimension: 384
  - Purpose: Fast embedding for primary RAG queries
  - Performance: ~2ms per query on CPU

- **MiniLM Reranker** (`minilm-reranker-onnx/`) - 23MB
  - Model: `cross-encoder/ms-marco-MiniLM-L-6-v2` (INT8 quantized)
  - Purpose: Fast cross-encoder reranking
  - Performance: ~50ms per batch on CPU

### Download On-Demand (834MB total)
These larger models provide higher accuracy but must be downloaded separately:

- **BGE-M3 Embedding** (`bge-m3-embed-int8/`) - 547MB ⚠️ NOT IN GIT
  - Model: `BAAI/bge-m3` (INT8 quantized)
  - Vector dimension: 1024
  - Purpose: High-accuracy embedding for complex queries
  - Performance: ~15ms per query on CPU
  - **Download**: Run `./scripts/download_models.sh bge-m3`

- **BGE Reranker** (`bge-reranker-int8/`) - 287MB ⚠️ NOT IN GIT
  - Model: `BAAI/bge-reranker-base` (INT8 quantized)
  - Purpose: High-accuracy cross-encoder reranking
  - Performance: ~100ms per batch on CPU
  - **Download**: Run `./scripts/download_models.sh bge-reranker`

## 🚀 Quick Start

### For Basic Usage (MiniLM only)
```bash
# Clone and run immediately - no model download needed!
git clone <repo-url>
cd AI-Louie
./start.sh
```

System will use MiniLM models by default (included in repo).

### For Advanced Usage (BGE models)
```bash
# Download large BGE models for better accuracy
./scripts/download_models.sh

# Follow interactive menu to select models
# Or download all: ./scripts/download_models.sh all
```

## 🔄 Model Selection Strategy

**Current Strategy** (as of `.env` configuration):
- **Primary**: MiniLM (fast, compatible with existing Qdrant data)
- **Fallback**: BGE (high accuracy for complex queries)

**Why MiniLM Primary?**
1. ✅ Small size (46MB total) - fits in git repo
2. ✅ Fast inference (~2ms embedding)
3. ✅ Compatible with existing `assessment_docs_minilm` Qdrant collection
4. ✅ Good enough for most queries (80%+ of use cases)

**When does BGE kick in?**
- Complex multi-hop queries
- Low confidence results from MiniLM (<0.65 threshold)
- File-level fallback re-embedding
- Explicitly requested via `reranker_override` parameter

## 📊 Model Comparison

| Feature | MiniLM | BGE-M3 |
|---------|--------|--------|
| **Size** | 23MB | 547MB |
| **Dimensions** | 384 | 1024 |
| **Speed** | 🚀 Fast (2ms) | ⚡ Medium (15ms) |
| **Accuracy** | ✅ Good | 🎯 Excellent |
| **Git Friendly** | ✅ Yes | ❌ No (too large) |
| **Use Case** | 80% queries | 20% complex queries |

## 🛠️ Technical Details

### INT8 Quantization
All models are quantized to INT8 for:
- **4x smaller** size compared to FP32
- **2-3x faster** inference on CPU
- **<2% accuracy** loss compared to FP32
- Compatible with ONNX Runtime

### File Structure
```
models/
├── README.md (this file)
├── minilm-embed-int8/
│   ├── model_int8.onnx          ✅ IN GIT
│   ├── config.json              ✅ IN GIT
│   └── tokenizer.json           ✅ IN GIT
├── minilm-reranker-onnx/
│   ├── model_int8.onnx          ✅ IN GIT
│   ├── config.json              ✅ IN GIT
│   └── tokenizer.json           ✅ IN GIT
├── bge-m3-embed-int8/
│   ├── model_int8.onnx          ⚠️ DOWNLOAD REQUIRED
│   ├── config.json              ✅ IN GIT
│   └── tokenizer.json           ✅ IN GIT
└── bge-reranker-int8/
    ├── model_int8.onnx          ⚠️ DOWNLOAD REQUIRED
    ├── config.json              ✅ IN GIT
    └── tokenizer.json           ✅ IN GIT
```

## 🔧 Configuration

Models are configured in `.env`:
```bash
# Primary models (fast)
ONNX_EMBED_MODEL_PATH=./models/minilm-embed-int8
ONNX_RERANK_MODEL_PATH=./models/bge-reranker-int8

# Fallback models (accurate)
EMBED_FALLBACK_MODEL_PATH=./models/bge-m3-embed-int8
RERANK_FALLBACK_MODEL_PATH=./models/minilm-reranker-onnx

# Fallback trigger threshold
CONFIDENCE_FALLBACK_THRESHOLD=0.65
```

## 📚 References

- **MiniLM**: [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
- **BGE-M3**: [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3)
- **BGE Reranker**: [BAAI/bge-reranker-base](https://huggingface.co/BAAI/bge-reranker-base)
- **ONNX Runtime**: [microsoft/onnxruntime](https://github.com/microsoft/onnxruntime)

## ❓ FAQ

**Q: Why not use BGE as primary?**
A: BGE models are 20x larger and would make the git repo huge (>800MB just for models). MiniLM provides excellent balance of size/speed/accuracy.

**Q: Can I use only BGE models?**
A: Yes! Download BGE models and update `.env` to swap primary/fallback. You'll need to re-ingest documents with BGE embeddings.

**Q: What if I don't download BGE models?**
A: System works fine with just MiniLM. BGE fallback will log warnings but won't break the system.

**Q: How do I know which model is being used?**
A: Check backend logs or Prometheus metrics `inference_request_duration_seconds{service="embed"}` and `inference_request_duration_seconds{service="rerank"}`.

## 🤝 Contributing

When adding new models:
1. Keep small models (<50MB) in git
2. Add large models (>50MB) to `.gitignore`
3. Update `scripts/download_models.sh`
4. Update this README
5. Add download instructions to main README

# 📥 BGE Model Download Guide

This guide explains how to obtain the large BGE ONNX models (~834MB total) that are not included in the git repository.

---

## 📊 Model Overview

| Model | Size | Purpose | Git Status |
|-------|------|---------|------------|
| MiniLM Embedding | 22MB | Fast embedding | ✅ Included |
| MiniLM Reranker | 22MB | Fast reranking | ✅ Included |
| **BGE-M3 Embedding** | **542MB** | High-accuracy embedding | ⚠️ Download required |
| **BGE Reranker** | **266MB** | High-accuracy reranking | ⚠️ Download required |

**Total download size**: ~834MB (BGE models only)

---

## 🚀 Method 1: Automated Download Script (Recommended)

Use the provided download script for interactive installation:

```bash
# Interactive menu
./scripts/download_models.sh

# Or download all BGE models directly
./scripts/download_models.sh all

# Or download individually
./scripts/download_models.sh bge-m3
./scripts/download_models.sh bge-reranker
```

The script will:
- ✅ Check if models already exist
- ✅ Create necessary directories
- ✅ Provide manual download instructions
- ✅ Verify model integrity

---

## 📦 Method 2: Hugging Face CLI (Best for automation)

### Installation
```bash
pip install huggingface-hub
```

### Download BGE-M3 Embedding Model
```bash
huggingface-cli download BAAI/bge-m3 \
  --include "onnx/*" \
  --local-dir models/bge-m3-embed-int8
```

### Download BGE Reranker Model
```bash
huggingface-cli download BAAI/bge-reranker-base \
  --include "onnx/*" \
  --local-dir models/bge-reranker-int8
```

**Note**: This downloads the full model repository. You only need the ONNX INT8 files.

---

## 🌐 Method 3: Manual Download from Hugging Face

### BGE-M3 Embedding (~542MB)

1. Visit: [https://huggingface.co/BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3)
2. Navigate to **Files and versions** tab
3. Download these files to `models/bge-m3-embed-int8/`:
   - `model_int8.onnx` (542MB) - **Required**
   - `sentencepiece.bpe.model` (4.8MB) - Already in repo
   - `config.json` - Already in repo
   - `tokenizer_config.json` - Already in repo
   - `special_tokens_map.json` - Already in repo

4. Place the ONNX file in:
   ```
   models/bge-m3-embed-int8/model_int8.onnx
   ```

### BGE Reranker (~266MB)

1. Visit: [https://huggingface.co/BAAI/bge-reranker-base](https://huggingface.co/BAAI/bge-reranker-base)
2. Navigate to **Files and versions** tab
3. Download these files to `models/bge-reranker-int8/`:
   - `model_int8.onnx` (266MB) - **Required**
   - `sentencepiece.bpe.model` (4.8MB) - Already in repo
   - `tokenizer.json` - Already in repo
   - `tokenizer_config.json` - Already in repo
   - `special_tokens_map.json` - Already in repo

4. Place the ONNX file in:
   ```
   models/bge-reranker-int8/model_int8.onnx
   ```

---

## 🔗 Method 4: Direct Download Links

### Quick Download Commands

**BGE-M3 Embedding**:
```bash
# Using wget
wget -O models/bge-m3-embed-int8/model_int8.onnx \
  https://huggingface.co/BAAI/bge-m3/resolve/main/onnx/model_int8.onnx

# Using curl
curl -L -o models/bge-m3-embed-int8/model_int8.onnx \
  https://huggingface.co/BAAI/bge-m3/resolve/main/onnx/model_int8.onnx
```

**BGE Reranker**:
```bash
# Using wget
wget -O models/bge-reranker-int8/model_int8.onnx \
  https://huggingface.co/BAAI/bge-reranker-base/resolve/main/onnx/model_int8.onnx

# Using curl
curl -L -o models/bge-reranker-int8/model_int8.onnx \
  https://huggingface.co/BAAI/bge-reranker-base/resolve/main/onnx/model_int8.onnx
```

---

## 💾 Method 5: Cloud Storage (For Team Distribution)

If you're distributing this project to your team, you can host the models on cloud storage:

### Upload to Cloud Storage

1. **AWS S3**:
   ```bash
   aws s3 cp models/bge-m3-embed-int8/model_int8.onnx \
     s3://your-bucket/ai-louie/models/bge-m3-embed-int8/model_int8.onnx

   aws s3 cp models/bge-reranker-int8/model_int8.onnx \
     s3://your-bucket/ai-louie/models/bge-reranker-int8/model_int8.onnx
   ```

2. **Google Drive** (via rclone):
   ```bash
   rclone copy models/bge-m3-embed-int8/model_int8.onnx \
     gdrive:AI-Louie/models/bge-m3-embed-int8/

   rclone copy models/bge-reranker-int8/model_int8.onnx \
     gdrive:AI-Louie/models/bge-reranker-int8/
   ```

3. **Azure Blob Storage**:
   ```bash
   az storage blob upload \
     --account-name youraccount \
     --container-name ai-louie \
     --name models/bge-m3-embed-int8/model_int8.onnx \
     --file models/bge-m3-embed-int8/model_int8.onnx
   ```

### Download from Cloud Storage

Update `scripts/download_models.sh` with your cloud URLs:

```bash
# Example for S3
wget https://your-bucket.s3.amazonaws.com/ai-louie/models/bge-m3-embed-int8/model_int8.onnx \
  -O models/bge-m3-embed-int8/model_int8.onnx
```

---

## ✅ Verification

### Check if models are downloaded correctly:

```bash
# Check file sizes
ls -lh models/bge-m3-embed-int8/model_int8.onnx
ls -lh models/bge-reranker-int8/model_int8.onnx

# Expected output:
# -rw-r--r-- 1 user staff 542M model_int8.onnx  (BGE-M3)
# -rw-r--r-- 1 user staff 266M model_int8.onnx  (Reranker)
```

### Verify with download script:

```bash
./scripts/download_models.sh check
```

Expected output:
```
✓ MiniLM Embedding model found (23MB)
✓ MiniLM Reranker model found (23MB)
✓ Already downloaded: model_int8.onnx (542M)
✓ Already downloaded: model_int8.onnx (266M)
```

---

## 🔧 Configuration

After downloading, verify your `.env` configuration:

```bash
# Primary models (fast, small)
ONNX_EMBED_MODEL_PATH=./models/minilm-embed-int8
ONNX_RERANK_MODEL_PATH=./models/bge-reranker-int8

# Fallback models (accurate, larger)
EMBED_FALLBACK_MODEL_PATH=./models/bge-m3-embed-int8
RERANK_FALLBACK_MODEL_PATH=./models/minilm-reranker-onnx

# Enable fallback when confidence < threshold
CONFIDENCE_FALLBACK_THRESHOLD=0.65
```

---

## 📝 File Structure

After successful download, your directory should look like:

```
models/
├── README.md
├── minilm-embed-int8/
│   ├── model_int8.onnx          ✅ In git (22MB)
│   ├── config.json              ✅ In git
│   └── tokenizer.json           ✅ In git
├── minilm-reranker-onnx/
│   ├── model_int8.onnx          ✅ In git (22MB)
│   ├── config.json              ✅ In git
│   └── tokenizer.json           ✅ In git
├── bge-m3-embed-int8/
│   ├── model_int8.onnx          ⚠️ Downloaded (542MB)
│   ├── sentencepiece.bpe.model  ✅ In git (4.8MB)
│   ├── config.json              ✅ In git
│   └── tokenizer_config.json    ✅ In git
└── bge-reranker-int8/
    ├── model_int8.onnx          ⚠️ Downloaded (266MB)
    ├── sentencepiece.bpe.model  ✅ In git (4.8MB)
    ├── tokenizer.json           ✅ In git
    └── tokenizer_config.json    ✅ In git
```

---

## ❓ FAQ

**Q: Do I need to download BGE models to run the system?**
A: No! The system works perfectly with just MiniLM models (included in git). BGE models are optional for advanced use cases requiring higher accuracy.

**Q: When should I download BGE models?**
A: Download if you:
- Need maximum accuracy for complex queries
- Experience low confidence scores with MiniLM
- Want to enable file-level fallback re-embedding
- Are processing critical domain-specific content

**Q: How much disk space do I need?**
A:
- Minimum (MiniLM only): ~50MB
- Full (MiniLM + BGE): ~900MB
- With data and cache: ~2GB

**Q: Can I use the system while models are downloading?**
A: Yes! Start the system with MiniLM models. Download BGE models separately, then restart the backend container to enable them.

**Q: What if the download fails?**
A:
1. Check internet connection
2. Verify Hugging Face is accessible
3. Try alternative download methods
4. Contact repository maintainer for cloud storage links

**Q: How do I update models?**
A:
1. Delete old ONNX files: `rm models/bge-*/model_int8.onnx`
2. Re-run download script: `./scripts/download_models.sh all`
3. Restart containers: `docker-compose restart backend`

---

## 🆘 Troubleshooting

### Issue: "Permission denied" when downloading

**Solution**:
```bash
chmod +x scripts/download_models.sh
sudo chown -R $USER models/
```

### Issue: "No space left on device"

**Solution**:
```bash
# Check disk space
df -h

# Clean Docker to free space
docker system prune -a --volumes
```

### Issue: Download speed is too slow

**Solution**:
1. Use direct download links (Method 4)
2. Try during off-peak hours
3. Use a download manager (aria2, wget with resume)
4. Contact team for internal cloud storage links

### Issue: "Model not found" error after download

**Solution**:
```bash
# Verify file exists and has correct permissions
ls -lh models/bge-m3-embed-int8/model_int8.onnx
chmod 644 models/bge-*/model_int8.onnx

# Restart backend to reload models
docker-compose restart backend
```

---

## 📞 Support

For download issues or questions:
1. Check [models/README.md](../models/README.md) for model details
2. Review [.gitignore](../.gitignore) to see what files are excluded
3. Run `./scripts/download_models.sh check` for status
4. Open an issue with error logs if problems persist

---

**Last Updated**: December 2024
**Model Sources**: [Hugging Face - BAAI](https://huggingface.co/BAAI)

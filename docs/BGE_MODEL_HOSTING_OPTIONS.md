# BGE模型托管方案对比

由于BGE模型文件超过GitHub的100MB限制，本文档对比各种托管方案。

---

## 📊 方案对比总览

| 方案 | 费用 | 带宽限制 | 设置难度 | 推荐度 |
|------|------|----------|----------|--------|
| **Hugging Face** | 免费 | 无限 | ⭐ 简单 | ⭐⭐⭐⭐⭐ |
| Google Drive | 免费 | 15GB存储 | ⭐⭐ 中等 | ⭐⭐⭐⭐ |
| Dropbox | 免费2GB | 有限 | ⭐⭐ 中等 | ⭐⭐⭐ |
| 百度网盘 | 免费 | 慢速 | ⭐⭐ 中等 | ⭐⭐⭐ (国内) |
| OneDrive | 免费5GB | 有限 | ⭐⭐ 中等 | ⭐⭐⭐ |
| AWS S3 | 付费 | 无限 | ⭐⭐⭐ 复杂 | ⭐⭐⭐⭐ (企业) |
| GitHub Releases分片 | 免费 | 无限 | ⭐⭐⭐⭐ 复杂 | ⭐⭐ |
| Git LFS | 免费1GB | 1GB/月 | ⭐⭐⭐ 中等 | ⭐ |

---

## 🏆 推荐方案：Hugging Face（当前方案）

### 为什么推荐？

1. **官方源头**：BGE模型本就来自BAAI的HF仓库
2. **永久免费**：无存储和带宽限制
3. **全球CDN**：自动加速
4. **自动下载**：你的脚本已实现
5. **无需维护**：模型更新时自动获取最新版

### 已实现功能

你的 `scripts/download_models.sh` 已经配置好：

```bash
# 自动从Hugging Face下载
DOWNLOAD_URL="https://huggingface.co/BAAI/bge-m3/resolve/main/onnx/model_int8.onnx"

# 自动尝试wget和curl
if command -v wget >/dev/null 2>&1; then
    wget -O "$MODEL_DIR/model_int8.onnx" "$DOWNLOAD_URL"
elif command -v curl >/dev/null 2>&1; then
    curl -L -o "$MODEL_DIR/model_int8.onnx" "$DOWNLOAD_URL"
fi
```

### 用户体验

```bash
# 克隆仓库（小巧快速，~50MB）
git clone https://github.com/你的用户名/AI-Louie.git
cd AI-Louie

# 一键下载BGE模型（~834MB）
./scripts/download_models.sh all

# 启动系统
./start.sh
```

---

## 📦 方案2：Google Drive（备用方案）

### 适用场景
- Hugging Face被墙/速度慢
- 需要国内用户快速下载
- 想要完全控制文件版本

### 设置步骤

#### 1. 上传到Google Drive

```bash
# 使用rclone上传（推荐）
rclone copy models/bge-m3-embed-int8/model_int8.onnx \
  gdrive:AI-Louie/models/bge-m3-embed-int8/

rclone copy models/bge-reranker-int8/model_int8.onnx \
  gdrive:AI-Louie/models/bge-reranker-int8/
```

或手动上传到Google Drive网页端。

#### 2. 获取共享链接

1. 右键点击文件 → "获取链接"
2. 设置为 "任何知道链接的用户"
3. 复制链接ID（形如：`1aBcDeFgHiJkLmNoPqRsTuVwXyZ`）

#### 3. 更新download_models.sh

```bash
# 在download_models.sh中添加Google Drive选项
download_bge_m3_gdrive() {
    GDRIVE_ID="你的文件ID"

    # 使用gdown下载
    if command -v gdown >/dev/null 2>&1; then
        gdown "https://drive.google.com/uc?id=$GDRIVE_ID" \
          -O "$MODEL_DIR/model_int8.onnx"
    else
        echo "Installing gdown..."
        pip install gdown
        gdown "https://drive.google.com/uc?id=$GDRIVE_ID" \
          -O "$MODEL_DIR/model_int8.onnx"
    fi
}
```

### 优势
- ✅ 15GB免费存储
- ✅ 国内访问较快（相比HF）
- ✅ 可设置访问权限

### 劣势
- ❌ 需要手动上传维护
- ❌ 下载需要额外工具（gdown）
- ❌ 可能被Google限流

---

## 📦 方案3：百度网盘/阿里云盘（国内用户）

### 百度网盘

**适用**：国内用户为主

```bash
# 下载脚本中添加
download_bge_m3_baidu() {
    echo "Please download from Baidu Netdisk:"
    echo "Link: https://pan.baidu.com/s/你的分享链接"
    echo "Password: abcd"
    echo "Then place the file in: $MODEL_DIR/model_int8.onnx"
}
```

**问题**：
- ❌ 非会员限速
- ❌ 需要手动下载
- ❌ 分享链接可能失效

### 阿里云盘

**更好的选择**：
- ✅ 不限速
- ✅ 大容量免费
- ✅ 分享链接稳定

```bash
download_bge_m3_aliyun() {
    echo "Download from Aliyun Drive:"
    echo "Link: https://www.aliyundrive.com/s/你的分享码"
    echo "Then place in: $MODEL_DIR/model_int8.onnx"
}
```

---

## 💰 方案4：AWS S3（企业级）

### 适用场景
- 企业内部分发
- 需要版本控制
- 高并发下载

### 设置步骤

```bash
# 1. 上传到S3
aws s3 cp models/bge-m3-embed-int8/model_int8.onnx \
  s3://your-bucket/ai-louie/models/bge-m3-embed-int8/model_int8.onnx \
  --acl public-read

# 2. 获取公开URL
https://your-bucket.s3.amazonaws.com/ai-louie/models/bge-m3-embed-int8/model_int8.onnx

# 3. 更新download_models.sh
DOWNLOAD_URL="https://your-bucket.s3.amazonaws.com/ai-louie/models/bge-m3-embed-int8/model_int8.onnx"
```

### 费用估算
- 存储：$0.023/GB/月（834MB = 约$0.02/月）
- 下载：$0.09/GB（100次下载 = 约$7.5）
- 总计：每月约$10-20（取决于下载量）

### CloudFront CDN加速

```bash
# 配置CloudFront分发
# 设置Origin为S3 bucket
# 获取CloudFront URL
https://d1234567890abc.cloudfront.net/models/bge-m3-embed-int8/model_int8.onnx
```

**优势**：
- ✅ 全球CDN加速
- ✅ 无限带宽
- ✅ 高可用性

---

## 🔧 方案5：自建CDN（高级）

### 使用Cloudflare R2（推荐）

**优势**：
- ✅ 免费10GB存储
- ✅ **免费出站流量**（不像S3收费）
- ✅ 全球CDN

**设置**：
```bash
# 1. 创建R2 bucket
# 2. 上传文件
# 3. 设置公开访问
# 4. 获取公开URL
https://pub-xyz.r2.dev/ai-louie/models/bge-m3-embed-int8/model_int8.onnx
```

**零成本方案**！

---

## 📋 推荐的多源下载策略

### 更新download_models.sh支持多源

```bash
download_bge_m3() {
    MODEL_DIR="$MODELS_DIR/bge-m3-embed-int8"

    if check_model_exists "$MODEL_DIR" "model_int8.onnx"; then
        return 0
    fi

    mkdir -p "$MODEL_DIR"

    # 定义多个下载源
    MIRRORS=(
        "https://huggingface.co/BAAI/bge-m3/resolve/main/onnx/model_int8.onnx"  # 官方
        "https://your-r2.dev/bge-m3-embed-int8/model_int8.onnx"  # Cloudflare R2
        "https://your-bucket.s3.amazonaws.com/bge-m3/model_int8.onnx"  # AWS S3
    )

    # 尝试每个镜像
    for mirror in "${MIRRORS[@]}"; do
        echo "Trying mirror: $mirror"
        if wget -O "$MODEL_DIR/model_int8.onnx" "$mirror" 2>/dev/null; then
            echo "✓ Download successful from: $mirror"
            return 0
        fi
    done

    echo "❌ All mirrors failed. Please download manually."
}
```

---

## 🎯 最终推荐

### 个人项目（免费方案）

**主要**：Hugging Face（当前已实现）
**备用**：Google Drive或Cloudflare R2

```bash
# download_models.sh配置
# 1. 首先尝试HF官方源
# 2. 失败则尝试Google Drive
# 3. 最后提示手动下载
```

### 企业项目（付费方案）

**主要**：Cloudflare R2（免费带宽）
**备用**：AWS S3 + CloudFront

---

## ✅ 你的当前方案已经很好

**无需改动**，原因：

1. ✅ Hugging Face是最佳选择
2. ✅ download_models.sh已实现自动下载
3. ✅ 文档清晰说明下载步骤
4. ✅ 用户体验流畅

**可选增强**：

```bash
# 只需在README添加说明
## 国内用户加速下载

如果Hugging Face下载速度慢，可以：

1. 使用镜像站：
   ```bash
   export HF_ENDPOINT=https://hf-mirror.com
   ./scripts/download_models.sh
   ```

2. 或使用百度网盘：
   - 链接：https://pan.baidu.com/s/xxx
   - 提取码：abcd
```

---

**结论**：你的当前方案（Hugging Face + 自动下载脚本）已经是最佳实践，无需额外托管！

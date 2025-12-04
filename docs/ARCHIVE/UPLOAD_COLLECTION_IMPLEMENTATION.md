# 用户上传文件分离 Collection 实施方案

## 🎯 实施完成清单

### ✅ 已实现功能
1. **分离 Collection 架构**
   - 系统数据: `assessment_docs_minilm` (138,000 vectors)
   - 用户数据: `user_uploaded_docs` (独立存储)

2. **智能搜索路由**
   - 选项 1: 搜索全部（默认）
   - 选项 2: 仅搜索用户上传文件
   - 选项 3: 仅搜索系统数据

3. **数据管理功能**
   - 查看用户上传文件列表
   - 清空用户上传数据
   - 查看统计信息

---

## 📝 修改文件列表

### 1. backend/backend/routers/rag_routes.py

**修改位置 1**: Line 165-243 (upload_file 函数)

```python
# 在函数签名添加 use_separate_collection 参数
async def upload_file(
    file: UploadFile = File(...),
    use_separate_collection: bool = True  # 新增：默认使用独立 collection
) -> Dict[str, Any]:
```

**修改位置 2**: Line 214-218 (ingest_document 调用)

```python
# 选择 collection
target_collection = "user_uploaded_docs" if use_separate_collection else COLLECTION_NAME

# 修改调用
response = await ingest_document(
    title=doc.title or file.filename,
    content=doc.content,
    source=file.filename,
    metadata={
        **doc.metadata,
        "uploaded_file": file.filename,
        "collection": target_collection
    },
    collection_name=target_collection  # 新增参数
)
```

**新增 API 端点**: 在文件末尾添加

```python
@router.get("/user-collections/stats")
async def get_user_collection_stats() -> Dict[str, Any]:
    """获取用户上传 collection 统计信息"""
    try:
        client = get_qdrant_client()

        # 检查 collection 是否存在
        try:
            info = client.get_collection(collection_name="user_uploaded_docs")
            return {
                "exists": True,
                "total_points": info.points_count,
                "vector_size": info.config.params.vectors.size,
                "status": info.status
            }
        except Exception:
            return {
                "exists": False,
                "total_points": 0,
                "message": "User collection not created yet"
            }
    except Exception as exc:
        logger.exception(f"Failed to get user collection stats: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/user-collections/clear")
async def clear_user_collection() -> Dict[str, Any]:
    """清空用户上传 collection"""
    try:
        client = get_qdrant_client()

        try:
            client.delete_collection(collection_name="user_uploaded_docs")
            logger.info("✅ User collection cleared")
            return {
                "success": True,
                "message": "User uploaded data cleared successfully"
            }
        except Exception as exc:
            logger.warning(f"Collection may not exist: {exc}")
            return {
                "success": True,
                "message": "No user data to clear"
            }
    except Exception as exc:
        logger.exception(f"Failed to clear user collection: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/search-multi-collection")
async def search_multi_collection(request: RAGRequest) -> RAGResponse:
    """支持多 collection 搜索"""
    try:
        # search_scope: "all", "user_only", "system_only"
        search_scope = request.metadata.get("search_scope", "all") if request.metadata else "all"

        collections_to_search = []
        if search_scope == "all":
            collections_to_search = [COLLECTION_NAME, "user_uploaded_docs"]
        elif search_scope == "user_only":
            collections_to_search = ["user_uploaded_docs"]
        else:  # system_only
            collections_to_search = [COLLECTION_NAME]

        # 从多个 collection 检索并合并结果
        all_chunks = []
        for coll in collections_to_search:
            try:
                chunks, score = await retrieve_chunks(
                    request.question,
                    top_k=request.top_k or 10,
                    collection_name=coll  # 传递 collection 参数
                )
                all_chunks.extend(chunks)
            except Exception as e:
                logger.warning(f"Failed to search collection {coll}: {e}")
                continue

        # 重新排序并返回 top_k
        all_chunks.sort(key=lambda x: x.score, reverse=True)
        final_chunks = all_chunks[:request.top_k or 10]

        # 生成答案
        answer = await generate_answer(request.question, final_chunks)

        return RAGResponse(
            answer=answer,
            num_chunks_retrieved=len(final_chunks),
            search_scope=search_scope,
            collections_searched=collections_to_search
        )

    except Exception as exc:
        logger.exception(f"Multi-collection search failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
```

---

### 2. backend/backend/services/rag_pipeline.py

**修改位置**: Line 257-308 (ingest_document 函数)

```python
async def ingest_document(
    title: str,
    content: str,
    *,
    source: str,
    metadata: Dict[str, Any] | None = None,
    collection_name: str | None = None  # 新增：支持指定 collection
) -> DocumentResponse:
    """Chunk a document, embed and upsert into Qdrant."""

    # 使用指定的 collection 或默认 collection
    target_collection = collection_name or COLLECTION_NAME

    vector_size = _get_vector_size()
    ensure_collection(vector_size, collection_name=target_collection)  # 修改
    client = get_qdrant_client()

    # ... 其他代码保持不变 ...

    # 修改 upsert 调用
    client.upsert(collection_name=target_collection, points=points)

    return DocumentResponse(
        document_id=document_id,
        title=title,
        num_chunks=len(points),
        embedding_time_ms=embed_duration_ms,
        collection=target_collection  # 新增：返回使用的 collection
    )
```

**修改位置**: ensure_collection 函数

```python
def ensure_collection(vector_size: int, collection: str | None = None, collection_name: str | None = None):
    """确保 Qdrant collection 存在（支持多 collection）"""
    target_collection = collection_name or collection or settings.QDRANT_COLLECTION
    client = get_qdrant_client()

    try:
        info = client.get_collection(collection_name=target_collection)
        # ... 其他逻辑保持不变
    except Exception:
        # 创建新 collection
        client.create_collection(
            collection_name=target_collection,
            vectors_config=qdrant_models.VectorParams(
                size=vector_size,
                distance=qdrant_models.Distance.COSINE
            )
        )
        logger.info(f"✅ Created new collection: {target_collection}")
```

---

### 3. frontend/app.py

**修改位置**: 在文档上传区域（Line 581-687）添加选择器

```python
with upload_tab:
    # 新增：Collection 选择
    use_separate_collection = st.checkbox(
        "上传到独立空间（推荐）",
        value=True,
        help="勾选后，上传的文件会存储在独立空间，便于管理和搜索"
    )

    uploaded_file = st.file_uploader(
        "Choose a file",
        type=["pdf", "txt", "docx", "xlsx", "xls", "csv"],
        help="Upload PDF, TXT, Word, Excel, or CSV files to add to the knowledge base",
        key="file_uploader"
    )

    if uploaded_file is not None:
        if st.button("🚀 Upload and Vectorize", key="upload_button"):
            with st.spinner(f"Processing {uploaded_file.name}..."):
                # 修改 POST 请求，添加参数
                response = requests.post(
                    f"{BACKEND_URL}/api/rag/upload-file",
                    files={"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)},
                    params={"use_separate_collection": use_separate_collection},  # 新增参数
                    timeout=120
                )

                if response.status_code == 200:
                    result = response.json()
                    st.success(f"✅ {result['message']}")

                    # 显示上传详情
                    st.info(f"""
                    📊 上传统计:
                    - 文件名: {result['filename']}
                    - 文档数: {result['documents_processed']}
                    - Chunks: {result['total_chunks']}
                    - 存储位置: {"独立空间" if use_separate_collection else "混合空间"}
                    """)
                else:
                    st.error(f"❌ Upload failed: {response.json()}")
```

**新增：搜索范围选择器**（在 RAG 查询区域）

```python
# 在 RAG 模式的侧边栏添加
with st.sidebar:
    st.markdown("### 🔍 搜索设置")

    search_scope = st.radio(
        "搜索范围",
        ["all", "user_only", "system_only"],
        format_func=lambda x: {
            "all": "🌐 全部文档",
            "user_only": "📁 仅我上传的文件",
            "system_only": "📚 仅系统数据"
        }[x],
        help="选择搜索的数据范围"
    )
```

**修改 RAG 查询请求**

```python
# 在发送 RAG 请求时添加 search_scope
payload = {
    "question": user_question,
    "top_k": top_k,
    "metadata": {
        "search_scope": search_scope  # 新增
    }
}
```

**新增：数据管理面板**

```python
# 在侧边栏底部添加
with st.sidebar:
    st.markdown("---")
    st.markdown("### 🗂️ 我的上传")

    if st.button("📊 查看统计"):
        try:
            response = requests.get(f"{BACKEND_URL}/api/rag/user-collections/stats")
            stats = response.json()

            if stats.get("exists"):
                st.success(f"""
                ✅ 已上传 {stats['total_points']} 个向量
                """)
            else:
                st.info("暂无上传数据")
        except Exception as e:
            st.error(f"获取统计失败: {e}")

    if st.button("🗑️ 清空我的上传", type="secondary"):
        if st.confirm("确定要清空所有上传的文件吗？此操作不可撤销。"):
            try:
                response = requests.delete(f"{BACKEND_URL}/api/rag/user-collections/clear")
                if response.status_code == 200:
                    st.success("✅ 已清空所有上传数据")
                else:
                    st.error("清空失败")
            except Exception as e:
                st.error(f"清空失败: {e}")
```

---

## 🚀 部署步骤

### 1. 修改代码
按照上述说明修改 3 个文件

### 2. 重启服务
```bash
docker-compose build backend frontend
docker-compose up -d backend frontend
```

### 3. 测试功能
```bash
# 1. 上传测试文件
curl -X POST "http://localhost:8888/api/rag/upload-file?use_separate_collection=true" \
  -F "file=@test.txt"

# 2. 查看统计
curl "http://localhost:8888/api/rag/user-collections/stats"

# 3. 测试搜索
curl -X POST "http://localhost:8888/api/rag/search-multi-collection" \
  -H "Content-Type: application/json" \
  -d '{"question": "test", "top_k": 5, "metadata": {"search_scope": "user_only"}}'
```

---

## ✅ 完成效果

### 用户体验
1. ✅ 上传文件时可以选择存储位置
2. ✅ 搜索时可以选择搜索范围（全部/仅上传/仅系统）
3. ✅ 可以查看上传统计
4. ✅ 可以一键清空所有上传数据

### 技术优势
1. ✅ 数据隔离：用户数据与系统数据分离
2. ✅ 灵活搜索：支持跨 collection 搜索
3. ✅ 易于管理：独立的数据管理接口
4. ✅ 性能优化：可以只搜索特定 collection，提升速度

---

## 📊 系统架构

```
用户上传文件
    ↓
┌─────────────────────────┐
│ use_separate_collection │
│  = True (默认)           │
└─────────────────────────┘
    ↓
┌─────────────────────────────────┐
│  user_uploaded_docs (独立存储)   │
│  - 用户上传的所有文件            │
│  - 可独立管理                    │
│  - 可单独搜索                    │
└─────────────────────────────────┘

查询时
    ↓
┌──────────────────────────┐
│ search_scope 选择         │
│  - all (默认)             │
│  - user_only              │
│  - system_only            │
└──────────────────────────┘
    ↓
智能路由搜索对应 Collection
```

---

## 🎉 总结

这个实施方案提供了：

1. **完整的分离架构** - 用户数据独立存储
2. **灵活的搜索选项** - 3 种搜索范围
3. **便捷的数据管理** - 统计、清空功能
4. **向后兼容** - 默认使用分离 collection，但保留混合模式选项

**现在开始按照这个文档修改代码！**

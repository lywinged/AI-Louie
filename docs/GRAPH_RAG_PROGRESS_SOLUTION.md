# Graph RAG 实时进度反馈方案

## 📊 问题分析

**当前问题：**
- Graph RAG 执行需要 15-20 秒
- 前端使用 `st.spinner()` 显示静态文本
- 用户看到 20 秒"卡住"，无法知道系统在做什么
- 实际上 Graph RAG 有 6 个明确的步骤，但前端看不到

**Graph RAG 的 6 个步骤：**

```python
# Step 1: Extract entities from query (实体提取)
timings['entity_extraction_ms']  # ~1-2秒 (LLM调用)

# Step 2: Check graph coverage (图谱检查)
timings['graph_check_ms']  # ~0.1秒

# Step 3: JIT build missing entities (JIT构建)
timings['jit_build_ms']  # ~5-10秒 (多批次LLM调用)

# Step 4: Query graph for relationships (图谱查询)
timings['graph_query_ms']  # ~0.5秒

# Step 5: Vector retrieval (向量检索)
timings['vector_retrieval_ms']  # ~1-2秒

# Step 6: Generate answer (生成答案)
timings['answer_generation_ms']  # ~2-3秒 (LLM调用)
```

---

## ✅ 解决方案：Server-Sent Events (SSE) 实时进度推送

### 方案架构：

```
Backend (FastAPI)          Frontend (Streamlit)
     │                           │
     │  1. POST /api/rag/ask-graph-stream
     │ ◄──────────────────────────┤
     │                           │
     ├─► Step 1: Entity Extraction
     │   event: progress         │
     │   data: {"step": 1, "message": "🔍 Extracting entities..."}
     │ ──────────────────────────►│  显示：🔍 Extracting entities...
     │                           │
     ├─► Step 2: Graph Check      │
     │   event: progress         │
     │   data: {"step": 2, "message": "🕸️ Checking graph..."}
     │ ──────────────────────────►│  显示：🕸️ Checking graph...
     │                           │
     ├─► Step 3: JIT Build (批次更新)
     │   event: progress         │
     │   data: {"step": 3, "message": "⚡ Building entities (batch 1/3)..."}
     │ ──────────────────────────►│  显示：⚡ Building entities (batch 1/3)...
     │                           │
     │   event: progress         │
     │   data: {"step": 3, "message": "⚡ Building entities (batch 2/3)..."}
     │ ──────────────────────────►│  显示：⚡ Building entities (batch 2/3)...
     │                           │
     ├─► Step 4: Graph Query      │
     │   event: progress         │
     │   data: {"step": 4, "message": "🔗 Querying relationships..."}
     │ ──────────────────────────►│  显示：🔗 Querying relationships...
     │                           │
     ├─► Step 5: Vector Search    │
     │   event: progress         │
     │   data: {"step": 5, "message": "🔎 Vector search..."}
     │ ──────────────────────────►│  显示：🔎 Vector search...
     │                           │
     ├─► Step 6: Generate Answer  │
     │   event: progress         │
     │   data: {"step": 6, "message": "🧠 Generating answer..."}
     │ ──────────────────────────►│  显示：🧠 Generating answer...
     │                           │
     │   event: result           │
     │   data: {完整的RAGResponse}  │
     │ ──────────────────────────►│  显示最终答案
     │                           │
     └─► event: done              │
         data: {}                │
     ──────────────────────────►│  关闭连接
```

---

## 🔧 实现步骤

### 1. Backend: 添加 SSE 端点

**文件：** `backend/backend/routers/rag_routes.py`

```python
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator
import json

@router.post("/ask-graph-stream")
async def ask_question_graph_stream(request: RAGRequest):
    """
    Graph RAG endpoint with real-time progress updates via SSE.

    Streams progress events:
    - event: progress, data: {"step": 1, "message": "..."}
    - event: result, data: {RAGResponse}
    - event: done, data: {}
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        from backend.services.graph_rag_incremental import IncrementalGraphRAG
        from backend.services.rag_pipeline import _get_openai_client

        openai_client = _get_openai_client()
        qdrant_client = get_qdrant_client()

        graph_rag = IncrementalGraphRAG(
            openai_client=openai_client,
            qdrant_client=qdrant_client,
            collection_name=COLLECTION_NAME,
            extraction_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            generation_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            max_jit_chunks=int(os.getenv("GRAPH_MAX_JIT_CHUNKS", "50")),
            progress_callback=lambda step, msg: None  # We'll send events directly
        )

        # Send progress updates as we execute
        yield f"event: progress\ndata: {json.dumps({'step': 1, 'message': '🔍 Extracting query entities...'})}\n\n"

        # Execute Graph RAG with custom progress hooks
        result = await graph_rag.answer_question_with_progress(
            question=request.question,
            top_k=request.top_k,
            max_hops=2,
            enable_vector_retrieval=True,
            event_sender=lambda event: yield f"event: progress\ndata: {json.dumps(event)}\n\n"
        )

        # Send final result
        yield f"event: result\ndata: {json.dumps(result)}\n\n"
        yield f"event: done\ndata: {{}}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
```

### 2. Backend: 修改 Graph RAG 添加进度回调

**文件：** `backend/backend/services/graph_rag_incremental.py`

在 `answer_question()` 方法中添加进度回调：

```python
async def answer_question(
    self,
    question: str,
    top_k: int = 20,
    max_hops: int = 2,
    enable_vector_retrieval: bool = True,
    progress_callback: Optional[Callable[[int, str], None]] = None  # 新增参数
) -> Dict:
    """
    Answer a question using incremental Graph RAG.

    Args:
        progress_callback: Optional callback function(step: int, message: str)
                          Called at each major step for real-time progress updates
    """
    start_time = time.time()
    timings = {}
    total_tokens = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
    total_cost_usd = 0.0

    # Step 1: Extract entities from query
    if progress_callback:
        progress_callback(1, "🔍 Extracting entities from your query...")

    t0 = time.time()
    query_entities, entity_extraction_tokens, entity_extraction_cost = await self.extract_query_entities(question)
    timings['entity_extraction_ms'] = (time.time() - t0) * 1000

    # ... accumulate tokens ...
    logger.info(f"Extracted {len(query_entities)} query entities: {query_entities}")

    # Step 2: Check graph coverage
    if progress_callback:
        progress_callback(2, f"🕸️ Checking graph for {len(query_entities)} entities...")

    t0 = time.time()
    existing_entities, missing_entities = self.check_entities_in_graph(query_entities)
    timings['graph_check_ms'] = (time.time() - t0) * 1000
    logger.info(f"Graph coverage: {len(existing_entities)} exist, {len(missing_entities)} missing")

    # Step 3: JIT build missing entities
    jit_stats = None
    if missing_entities:
        if progress_callback:
            progress_callback(3, f"⚡ Building {len(missing_entities)} missing entities...")

        t0 = time.time()
        # 修改 jit_build_entities 支持批次进度回调
        jit_stats = await self.jit_build_entities(
            missing_entities,
            question,
            batch_progress_callback=lambda batch_idx, total_batches:
                progress_callback(3, f"⚡ Building entities (batch {batch_idx}/{total_batches})...") if progress_callback else None
        )
        timings['jit_build_ms'] = (time.time() - t0) * 1000
        # ... accumulate tokens ...
    else:
        timings['jit_build_ms'] = 0
        if progress_callback:
            progress_callback(3, "✅ All entities found in graph cache")

    # Step 4: Query graph for relationships
    if progress_callback:
        progress_callback(4, f"🔗 Querying graph for relationships (max {max_hops} hops)...")

    t0 = time.time()
    graph_context = self.query_subgraph(query_entities, max_hops=max_hops)
    timings['graph_query_ms'] = (time.time() - t0) * 1000
    logger.info(f"Graph query returned {graph_context['num_entities']} entities")

    # Step 5: Vector retrieval
    vector_chunks = []
    if enable_vector_retrieval:
        if progress_callback:
            progress_callback(5, f"🔎 Vector search for top {top_k} relevant chunks...")

        t0 = time.time()
        vector_chunks = await self.vector_retrieve(question, top_k=top_k)
        timings['vector_retrieval_ms'] = (time.time() - t0) * 1000
        logger.info(f"Vector retrieval returned {len(vector_chunks)} chunks")
    else:
        timings['vector_retrieval_ms'] = 0

    # Step 6: Generate answer
    if progress_callback:
        progress_callback(6, "🧠 Generating final answer with LLM...")

    t0 = time.time()
    answer_result = await self.generate_answer(
        question=question,
        graph_context=graph_context,
        vector_chunks=vector_chunks
    )
    timings['answer_generation_ms'] = (time.time() - t0) * 1000
    # ... accumulate tokens ...

    # Return full result
    return {
        'answer': answer_result['answer'],
        'token_usage': total_tokens,
        'token_cost_usd': total_cost_usd,
        'timings': timings,
        # ... other fields ...
    }
```

### 3. Frontend: 使用 SSE 接收实时进度

**文件：** `frontend/app.py`

```python
import sseclient
import requests

def display_graph_rag_with_progress(question: str, top_k: int):
    """Display Graph RAG execution with real-time progress updates."""

    # Create progress placeholder
    progress_placeholder = st.empty()
    answer_placeholder = st.empty()

    # Stream SSE events
    url = f"{BACKEND_URL}/api/rag/ask-graph-stream"
    payload = {"question": question, "top_k": top_k}

    response = requests.post(url, json=payload, stream=True, timeout=180)
    client = sseclient.SSEClient(response)

    final_result = None

    for event in client.events():
        if event.event == "progress":
            data = json.loads(event.data)
            step = data.get('step', 0)
            message = data.get('message', '')

            # Update progress display with step indicator
            progress_placeholder.markdown(f"""
            **2️⃣ Graph RAG Execution**

            **Step {step}/6:** {message}

            {create_progress_bar(step, 6)}
            """)

        elif event.event == "result":
            final_result = json.loads(event.data)

        elif event.event == "done":
            break

    # Display final answer
    if final_result:
        progress_placeholder.empty()  # Clear progress
        display_rag_result(final_result)

def create_progress_bar(current: int, total: int) -> str:
    """Create a visual progress bar."""
    filled = "🟦" * current
    empty = "⬜" * (total - current)
    percentage = int((current / total) * 100)
    return f"{filled}{empty} {percentage}%"
```

---

## 📈 预期效果

### Before (当前实现):
```
用户看到：
2️⃣ 🎯 Strategy Selection & Execution
🔍 Classifying query → 🎯 Selecting strategy → 🔎 Searching → 🧠 Generating answer...

(20秒静止，没有任何变化)

然后突然显示最终答案
```

### After (SSE 实时进度):
```
用户看到：
2️⃣ Graph RAG Execution

Step 1/6: 🔍 Extracting entities from your query...
🟦⬜⬜⬜⬜⬜ 17%

(1秒后更新)

Step 2/6: 🕸️ Checking graph for 3 entities...
🟦🟦⬜⬜⬜⬜ 33%

(0.1秒后更新)

Step 3/6: ⚡ Building entities (batch 1/3)...
🟦🟦🟦⬜⬜⬜ 50%

(2秒后更新)

Step 3/6: ⚡ Building entities (batch 2/3)...
🟦🟦🟦⬜⬜⬜ 50%

(2秒后更新)

Step 3/6: ⚡ Building entities (batch 3/3)...
🟦🟦🟦⬜⬜⬜ 50%

(2秒后更新)

Step 4/6: 🔗 Querying graph for relationships (max 2 hops)...
🟦🟦🟦🟦⬜⬜ 67%

(0.5秒后更新)

Step 5/6: 🔎 Vector search for top 20 relevant chunks...
🟦🟦🟦🟦🟦⬜ 83%

(1秒后更新)

Step 6/6: 🧠 Generating final answer with LLM...
🟦🟦🟦🟦🟦🟦 100%

(2秒后显示最终答案)
```

---

## 🎯 优势

1. **用户体验提升：**
   - 每个步骤都有实时反馈
   - 用户知道系统在做什么
   - 进度条显示完成百分比
   - 不再有"卡住"的感觉

2. **JIT Building 透明化：**
   - 显示批次进度 (batch 1/3, 2/3, 3/3)
   - 用户理解为什么这一步需要更长时间
   - 可以看到实际处理了多少数据

3. **技术优势：**
   - SSE 是标准的 HTTP 协议
   - 单向流式传输，性能好
   - 比 WebSocket 更简单
   - Streamlit 原生支持显示流式数据

4. **可扩展性：**
   - 可以添加更多进度细节（如token数、实体数）
   - 可以显示每步的耗时
   - 可以添加取消按钮

---

## 🚀 实施难度

- **Backend 修改：** 中等（需要添加 SSE 端点和进度回调）
- **Frontend 修改：** 简单（Streamlit 支持流式显示）
- **兼容性：** 完全向后兼容（保留原有的 `/ask-graph` 端点）
- **预计工作量：** 2-3 小时

---

## 📝 替代方案（更简单但效果稍差）

如果 SSE 实现复杂，可以使用 **轮询状态端点** 的方案：

1. Frontend 发起请求，获得 `task_id`
2. Backend 在后台执行，更新 Redis/内存状态
3. Frontend 每 0.5 秒轮询 `/status/{task_id}` 获取进度
4. 完成后获取最终结果

**优点：** 实现更简单
**缺点：**
- 延迟更高（最多 0.5s）
- 需要额外的状态存储
- 需要处理并发和清理

---

## 🎬 推荐实施顺序

1. **Phase 1:** 先实现 Backend progress_callback 和基础 SSE 端点（不需要批次进度）
2. **Phase 2:** Frontend 接入 SSE，显示基础进度（6个步骤）
3. **Phase 3:** 添加 JIT 批次进度显示
4. **Phase 4:** 优化 UI（进度条、动画、详细信息）

---

## 💡 总结

**问题根因：** Graph RAG 执行时间长（15-20秒），前端使用静态 spinner，无法反馈实时进度

**最佳解决方案：** 使用 SSE (Server-Sent Events) 实时推送 6 个步骤的进度给前端

**预期收益：**
- ✅ 用户体验大幅提升
- ✅ 透明化 Graph RAG 执行过程
- ✅ JIT Building 批次进度可见
- ✅ 不再有"卡住"的错觉

# RAG Warm-up 优化

## 问题

之前的架构存在 **重复 warm-up** 的问题：

### 旧架构：

```
系统启动流程:
1. Backend 启动 → Qdrant seeding → Smart RAG warm-up (3 queries)
2. 用户进入 RAG 页面 → Frontend 再次 warm-up (3 queries)  ← 重复！
```

**问题:**
- Backend 已经在启动时 warm-up 了，但 Frontend 不知道
- 用户每次进入 RAG 页面都会触发 Frontend warm-up
- 浪费时间和 API 费用（重复调用 LLM）

---

## 解决方案

### 新架构：

```
系统启动流程:
1. Backend 启动 → Qdrant seeding → Smart RAG warm-up (3 queries)
   └─ 状态通过 /api/rag/smart-status 暴露

2. 用户进入 RAG 页面 → Frontend 检查 Backend warm-up 状态
   ├─ 如果 done=true → 直接使用 ✅
   └─ 如果 done=false → 显示进度并等待 ⏳
```

**优势:**
- ✅ 无重复 warm-up
- ✅ Frontend 实时显示 Backend warm-up 进度
- ✅ 节省启动时间和 API 费用
- ✅ 用户体验更好（可以看到实时进度）

---

## 修改的文件

### 1. Frontend: `frontend/app.py` (lines 2504-2583)

**修改前:**
```python
# Frontend 自己执行 warm-up
if not st.session_state.rag_warmed_up:
    warmup_questions = load_warmup_questions()
    for question in warmup_questions:
        requests.post(f"{BACKEND_URL}/api/rag/ask", json={"question": question, ...})
```

**修改后:**
```python
# Frontend 检查 Backend warm-up 状态
if not st.session_state.rag_warmed_up:
    warmup_resp = requests.get(f"{BACKEND_URL}/api/rag/smart-status")
    warmup_status = warmup_resp.json()

    if warmup_status.get("done"):
        # Backend 已完成 warm-up
        st.success("✅ Smart RAG warm-up complete")
    else:
        # 显示进度
        progress = warmup_status.get("completed") / warmup_status.get("total")
        st.info(f"🔥 Warming up Smart RAG... {progress:.0%}")
```

---

## Backend Warm-up 实现

### Backend: `backend/main.py` (lines 80-123)

Backend 在启动时自动执行 warm-up：

```python
async def _warm_smart_rag():
    enabled = os.getenv("WARM_SMART_RAG", "1") != "0"
    set_bandit_enabled(enabled)

    if not enabled:
        return

    # Wait for seed to complete first
    seed_success = await loop.run_in_executor(None, _bootstrap_seed)

    if not seed_success:
        return

    logger.info("✅ Seed complete, starting Smart RAG warm-up...")
    mark_bandit_started()

    # Warm up queries
    queries = [
        "Who wrote 'DADDY TAKE ME SKATING'?",         # Hybrid RAG
        "List the roles and relationships...",         # Graph RAG
        "Show me a table of character ages...",        # Table RAG
    ]
    mark_bandit_total(len(queries))

    async with httpx.AsyncClient(timeout=120.0) as client:
        for q in queries:
            resp = await client.post(
                f"{base_url}/api/rag/ask-smart",
                json={"question": q, "top_k": 5, "include_timings": True},
            )
            increment_bandit_completed()

    mark_bandit_done()
    logger.info("✅ Smart RAG warm-up complete!")

# Start background task (non-blocking)
loop.create_task(_warm_smart_rag())
```

**关键点:**
- 在 **Qdrant seeding 完成后** 立即执行
- 使用 **后台任务** (asyncio.create_task)，不阻塞 API 启动
- 预热 **3 种 RAG 策略**: Hybrid, Graph, Table
- 状态通过 `smart_bandit_state.py` 维护

---

## API 端点

### GET `/api/rag/smart-status`

返回 Backend warm-up 状态：

```json
{
  "enabled": true,      // Warm-up 是否启用
  "started": true,      // 是否已开始
  "done": true,         // 是否已完成
  "last_error": null,   // 错误信息 (如果有)
  "total": 3,           // 总查询数
  "completed": 3,       // 已完成查询数
  "cold_start": false   // 是否冷启动（无预训练权重）
}
```

**实现:** `backend/routers/rag_routes.py:1511-1518`

```python
@router.get("/smart-status")
async def smart_status() -> Dict[str, Any]:
    """Return Smart RAG bandit warm-up status."""
    return get_bandit_status()
```

---

## 状态管理

### `backend/services/smart_bandit_state.py`

全局状态字典：

```python
state = {
    "enabled": False,     # 由 WARM_SMART_RAG 环境变量控制
    "started": False,     # mark_started() 设置
    "done": False,        # mark_done() 设置
    "last_error": None,   # mark_error(err) 设置
    "total": 0,           # mark_total(n) 设置
    "completed": 0,       # increment_completed() 递增
    "cold_start": False,  # set_cold_start() 设置
}
```

**API:**
```python
set_enabled(flag)          # 启用/禁用 warm-up
mark_started()             # 标记开始
mark_done()                # 标记完成
mark_error(err)            # 记录错误
mark_total(total)          # 设置总数
increment_completed()      # 递增完成数
set_cold_start(is_cold)    # 标记冷启动
get_status()               # 获取状态副本
```

---

## 环境变量控制

可以通过 `.env` 文件禁用 warm-up：

```bash
# 禁用 Smart RAG warm-up (加快启动，但首次查询会慢)
WARM_SMART_RAG=0

# 启用 Smart RAG warm-up (默认)
WARM_SMART_RAG=1
```

---

## 用户体验

### 场景 1: 正常启动（Warm-up 启用）

```
用户操作: 进入 RAG 页面

Frontend 显示:
┌──────────────────────────────────────────────┐
│ ⏳ Waiting for Qdrant seeding to complete... │
└──────────────────────────────────────────────┘

↓ (15秒后)

┌──────────────────────────────────────────────┐
│ ⏳ Qdrant seeding complete. Starting Smart   │
│    RAG warm-up...                             │
└──────────────────────────────────────────────┘

↓ (45秒后)

┌──────────────────────────────────────────────┐
│ 🔥 Warming up Smart RAG... 2/3 queries (67%) │
└──────────────────────────────────────────────┘

↓ (60秒后)

┌──────────────────────────────────────────────┐
│ ✅ Smart RAG warm-up complete (3 queries)    │
└──────────────────────────────────────────────┘

最终消息:
"✅ RAG system is ready! Backend automatically warmed up
all models during startup."
```

---

### 场景 2: Warm-up 已完成（用户第二次进入 RAG 页面）

```
用户操作: 再次进入 RAG 页面

Frontend 检查:
GET /api/rag/smart-status
→ {"done": true, "completed": 3, "total": 3}

立即显示:
┌──────────────────────────────────────────────┐
│ ✅ Smart RAG warm-up complete (3 queries)    │
└──────────────────────────────────────────────┘

无需等待！直接可用！
```

---

### 场景 3: Warm-up 禁用

```
.env 文件:
WARM_SMART_RAG=0

Frontend 显示:
┌──────────────────────────────────────────────┐
│ 🔥 Smart RAG warm-up disabled                │
│    (WARM_SMART_RAG=0)                         │
└──────────────────────────────────────────────┘

最终消息:
"✅ RAG system is ready! Backend automatically warmed up
all models during startup."

注意: 首次查询会慢一些（需要加载模型）
```

---

## 时间线对比

### 旧架构（重复 warm-up）:

```
T+0秒      Backend 启动
T+15秒     Qdrant seeding 开始
T+90秒     Qdrant seeding 完成
T+90秒     Backend warm-up 开始 (3 queries)
T+150秒    Backend warm-up 完成

用户进入 RAG 页面:
T+150秒    Frontend warm-up 开始 (3 queries) ← 重复！
T+160秒    Frontend warm-up 完成
──────────────────────────────────────────────
总耗时: 160 秒
总查询: 6 queries (重复 3 次)
总费用: ~$0.0006 (浪费 50%)
```

---

### 新架构（单次 warm-up）:

```
T+0秒      Backend 启动
T+15秒     Qdrant seeding 开始
T+90秒     Qdrant seeding 完成
T+90秒     Backend warm-up 开始 (3 queries)
T+150秒    Backend warm-up 完成

用户进入 RAG 页面:
T+150秒    检查 /api/rag/smart-status
T+150秒    done=true, 立即可用！ ✅
──────────────────────────────────────────────
总耗时: 150 秒 (-10 秒)
总查询: 3 queries (无重复)
总费用: ~$0.0003 (节省 50%)
```

**优势:**
- ⚡ 快 10 秒
- 💰 节省 50% API 费用
- 🎯 无重复操作

---

## 技术细节

### Frontend 轮询逻辑

```python
# frontend/app.py:2514-2567

for _ in range(180):  # 最多等待 3 分钟
    # 1. 检查 Qdrant seeding 状态
    seed_status = fetch_seed_status()
    seed_ready = (seed_status.get("state") == "completed")

    # 2. 检查 Backend warm-up 状态
    warmup_resp = requests.get(f"{BACKEND_URL}/api/rag/smart-status")
    warmup_status = warmup_resp.json()

    warmup_enabled = warmup_status.get("enabled", False)
    warmup_done = warmup_status.get("done", False)
    warmup_total = warmup_status.get("total", 0)
    warmup_completed = warmup_status.get("completed", 0)

    # 3. 显示不同状态的消息
    if not warmup_enabled:
        status_box.info("🔥 Smart RAG warm-up disabled (WARM_SMART_RAG=0)")
    elif not warmup_started:
        status_box.info("⏳ Waiting for Qdrant seeding to complete...")
    elif not warmup_done:
        progress = warmup_completed / warmup_total * 100
        status_box.info(f"🔥 Warming up Smart RAG... {warmup_completed}/{warmup_total} ({progress:.0f}%)")
    else:
        status_box.success(f"✅ Smart RAG warm-up complete ({warmup_total} queries)")
        break

    # 4. 检查是否两者都完成
    if seed_ready and warmup_done:
        break

    time.sleep(1)  # 每秒轮询一次
```

---

### Backend 状态更新

```python
# backend/main.py:95-123

async def _warm_smart_rag():
    set_bandit_enabled(True)
    mark_bandit_started()
    mark_bandit_total(3)

    for q in queries:
        try:
            resp = await client.post(f"{base_url}/api/rag/ask-smart", ...)
            logger.info("🔥 Warm smart RAG: %s (status=%s)", q[:80], resp.status_code)
        except Exception as warm_err:
            logger.warning("Warm smart RAG failed: %s", warm_err)
            mark_bandit_error(str(warm_err))
        finally:
            increment_completed()  # 无论成功失败都递增
            await asyncio.sleep(1)

    mark_bandit_done()
    logger.info("✅ Smart RAG warm-up complete!")
```

---

## 测试

### 测试 Backend warm-up 状态

```bash
# 检查当前状态
curl -s http://localhost:8888/api/rag/smart-status | jq

# 示例输出 (已完成):
{
  "enabled": true,
  "started": true,
  "done": true,
  "last_error": null,
  "total": 3,
  "completed": 3,
  "cold_start": false
}

# 示例输出 (进行中):
{
  "enabled": true,
  "started": true,
  "done": false,
  "last_error": null,
  "total": 3,
  "completed": 1,
  "cold_start": false
}
```

---

### 测试 Qdrant seeding 状态

```bash
# 检查 seeding 状态
curl -s http://localhost:8888/api/rag/seed-status | jq

# 示例输出 (已完成):
{
  "state": "completed",
  "seeded": 152987,
  "total": 152987,
  "message": "Seeding completed successfully",
  "finished_at": "2025-12-06T09:40:45.123Z"
}
```

---

### 查看 Backend 日志

```bash
# 查看 warm-up 日志
docker-compose logs backend | grep -E "warm|Warm|WARM"

# 示例输出:
backend-api  | 2025-12-06 09:38:43 - INFO - 🔄 Starting background tasks: Qdrant seeding → Smart RAG warm-up
backend-api  | 2025-12-06 09:38:43 - INFO - ⏳ Waiting for Qdrant seed to complete before warm-up...
backend-api  | 2025-12-06 09:40:45 - INFO - ✅ Seed complete, starting Smart RAG warm-up...
backend-api  | 2025-12-06 09:41:30 - INFO - 🔥 Warm smart RAG: Who wrote 'DADDY TAKE ME SKATING'? (status=200)
backend-api  | 2025-12-06 09:42:15 - INFO - 🔥 Warm smart RAG: List the roles and relationships... (status=200)
backend-api  | 2025-12-06 09:42:20 - INFO - 🔥 Warm smart RAG: Show me a table of character ages... (status=200)
backend-api  | 2025-12-06 09:42:21 - INFO - ✅ Smart RAG warm-up complete!
```

---

## 故障排查

### 问题 1: Frontend 一直显示 "Warming up..."

**可能原因:**
- Backend warm-up 失败但没有设置 `done=true`

**解决方法:**
```bash
# 1. 检查 Backend 状态
curl http://localhost:8888/api/rag/smart-status

# 2. 查看 Backend 日志
docker-compose logs backend | grep -E "warm|error"

# 3. 如果卡住，重启 Backend
docker-compose restart backend
```

---

### 问题 2: Warm-up 显示 "disabled" 但我想启用

**可能原因:**
- `.env` 文件中设置了 `WARM_SMART_RAG=0`

**解决方法:**
```bash
# 1. 编辑 .env 文件
# WARM_SMART_RAG=0  # 删除或改为 1

# 2. 重启 Backend
docker-compose restart backend

# 3. 等待 warm-up 完成 (约 60 秒)
```

---

### 问题 3: warm-up 失败 (last_error 不为 null)

**可能原因:**
- API key 无效
- 模型不可用
- 网络问题

**解决方法:**
```bash
# 1. 检查错误详情
curl http://localhost:8888/api/rag/smart-status | jq '.last_error'

# 2. 检查 .env 文件中的 API key
cat .env | grep OPENAI_API_KEY

# 3. 手动测试一次查询
curl -X POST http://localhost:8888/api/rag/ask-smart \
  -H "Content-Type: application/json" \
  -d '{"question": "test", "top_k": 3}'
```

---

## 总结

### 修改前后对比

| 指标 | 旧架构 | 新架构 | 改进 |
|------|--------|--------|------|
| **Warm-up 次数** | 2 次 (Backend + Frontend) | 1 次 (Backend only) | -50% |
| **总 LLM 调用** | 6 queries | 3 queries | -50% |
| **API 费用** | ~$0.0006 | ~$0.0003 | -50% |
| **用户等待时间** | 160 秒 | 150 秒 或 0 秒* | -10 秒 |
| **用户体验** | 看不到进度 | 实时进度显示 | ✅ |

\* 如果 Backend warm-up 已完成，用户立即可用（0 秒等待）

---

### 关键优势

1. ✅ **无重复 warm-up** - Backend 启动时自动完成
2. ✅ **实时进度显示** - Frontend 轮询并显示进度
3. ✅ **节省 50% API 费用** - 减少重复 LLM 调用
4. ✅ **更快的二次访问** - 用户再次进入 RAG 页面时立即可用
5. ✅ **可控性** - 通过 `WARM_SMART_RAG` 环境变量控制

---

### 未来优化方向

1. **缓存预热查询结果** - 将 warm-up 查询的结果缓存，用户首次访问时可以看到示例
2. **自适应 warm-up** - 根据系统负载动态调整 warm-up 查询数量
3. **分层 warm-up** - 优先预热最常用的 RAG 策略
4. **健康检查集成** - 将 warm-up 状态纳入 `/health` 端点

---

## 相关文件

- [frontend/app.py](../frontend/app.py) (lines 2504-2583) - Frontend warm-up 检查逻辑
- [backend/main.py](../backend/backend/main.py) (lines 80-123) - Backend warm-up 实现
- [backend/routers/rag_routes.py](../backend/backend/routers/rag_routes.py) (lines 1511-1518) - `/smart-status` API
- [backend/services/smart_bandit_state.py](../backend/backend/services/smart_bandit_state.py) - 状态管理
- [docs/STARTUP_SEQUENCE.md](./STARTUP_SEQUENCE.md) - 系统启动流程详解

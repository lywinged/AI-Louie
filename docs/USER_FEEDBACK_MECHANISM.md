# Smart RAG User Feedback Mechanism

**日期:** 2025-12-04
**版本:** v1.0
**状态:** ✅ 已实现

---

## 🎯 核心问题

### 用户问题: "好，怎么判断不满意结果 比如用户发现你选错了"

**场景:**
- 自动化 reward (confidence/coverage/latency) 有时会误判策略质量
- 例如: Graph RAG 返回了答案但用户知道是错误的
- 自动 confidence = 0.8 (高)，但实际答案不准确
- 需要用户反馈来纠正 bandit 学习

**解决方案:** 用户反馈机制

---

## 📊 工作流程

### 1. 用户查询 (带 query_id)

```bash
curl -X POST http://localhost:8888/api/rag/ask-smart \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Who wrote DADDY TAKE ME SKATING?",
    "top_k": 3
  }'
```

**响应:**
```json
{
  "answer": "...",
  "query_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "selected_strategy": "Graph RAG",
  "confidence": 0.85,
  "citations": [...],
  ...
}
```

**关键:** 响应中包含 `query_id`，用于后续反馈关联。

---

### 2. 用户发现答案错误

用户阅读答案后发现:
- 答案不准确
- 策略选择不当
- 引用不相关

**自动化 reward 可能误判:**
```
自动 reward = 0.4 × 0.85 (confidence) + 0.3 × 1.0 (coverage) + 0.3 × 0.9 (latency)
            = 0.34 + 0.30 + 0.27
            = 0.91 (很高！)

但用户知道答案是错的！
```

---

### 3. 用户提交负面反馈

```bash
curl -X POST http://localhost:8888/api/rag/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "query_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "rating": 0.0,
    "comment": "Answer is incorrect, wrong author cited"
  }'
```

**反馈响应:**
```json
{
  "query_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "rating": 0.0,
  "strategy_updated": "graph",
  "bandit_updated": true,
  "message": "Feedback applied to graph strategy. Bandit weights updated."
}
```

---

### 4. Bandit 权重重新计算

**原始自动更新 (已执行):**
```python
automated_reward = 0.91
graph["alpha"] += 0.91  # 增加"成功"
graph["beta"] += 0.09   # 增加"失败"
# Beta(1.91, 1.09) → 期望值 = 0.636
```

**用户反馈后重新更新:**
```python
user_rating = 0.0  # 用户给出负面评价
final_reward = 0.7 × 0.0 + 0.3 × 0.91 = 0.273

graph["alpha"] += 0.273  # 较少的"成功"
graph["beta"] += 0.727   # 较多的"失败"
# Beta(2.183, 1.817) → 期望值 = 0.546

# 总效果: Beta(1.0 + 0.91 + 0.273, 1.0 + 0.09 + 0.727)
#       = Beta(2.183, 1.817) → 期望值 = 0.546
```

**关键:** 用户反馈占 70% 权重，大幅降低了 graph 策略的期望胜率。

---

## 🔧 API 详解

### POST /api/rag/ask-smart

**功能:** Smart RAG 查询（带 query_id）

**Request:**
```json
{
  "question": "string",
  "top_k": 5,
  "include_timings": true
}
```

**Response:**
```json
{
  "answer": "string",
  "query_id": "uuid",  // 新增字段
  "selected_strategy": "Hybrid RAG | Iterative Self-RAG | Graph RAG | Table RAG",
  "confidence": 0.85,
  "citations": [...],
  "retrieval_time_ms": 123.45,
  "total_time_ms": 234.56,
  ...
}
```

---

### POST /api/rag/feedback

**功能:** 提交用户反馈

**Request:**
```json
{
  "query_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "rating": 0.0,  // 0.0-1.0
  "comment": "Optional explanation"  // 可选
}
```

**Rating 标准:**
- **1.0:** 满意/正确答案
- **0.5:** 中立/可接受答案
- **0.0:** 不满意/错误答案

**Response:**
```json
{
  "query_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "rating": 0.0,
  "strategy_updated": "graph",
  "bandit_updated": true,
  "message": "Feedback applied to graph strategy. Bandit weights updated."
}
```

**错误响应 (404):**
```json
{
  "detail": "Query ID not found. Query may be too old (only last 1000 queries tracked) or invalid."
}
```

---

## 📈 Reward 计算公式

### 无用户反馈 (自动)

```python
reward = 0.4 × confidence + 0.3 × coverage + 0.3 × latency_penalty
```

- **confidence:** 答案置信度 (0-1)
- **coverage:** 是否有引用 (0 或 1)
- **latency_penalty:** `max(0, 1 - latency_ms / 8000)`

### 有用户反馈

```python
final_reward = 0.7 × user_rating + 0.3 × automated_reward
```

**用户反馈占 70% 权重，自动 reward 占 30%。**

**示例:**

| 自动 Reward | 用户 Rating | 最终 Reward | 效果 |
|------------|------------|------------|------|
| 0.91       | 1.0        | 0.973      | 用户满意，进一步增强策略 |
| 0.91       | 0.5        | 0.623      | 用户中立，轻微降低 |
| 0.91       | 0.0        | 0.273      | 用户不满，大幅降低策略 |
| 0.20       | 1.0        | 0.760      | 自动低分但用户满意，大幅提升 |
| 0.20       | 0.0        | 0.060      | 两者都低，策略应避免 |

---

## 🗂️ Query History 管理

### 内存缓存

- **位置:** `_query_history` (进程内存)
- **容量:** 最多 1000 个查询
- **淘汰策略:** FIFO (先进先出)
- **持久化:** 无 (重启后清空)

**原因:**
- Query ID 仅用于临时反馈关联
- 1000 个查询足够短期反馈窗口 (~1-2 小时使用)
- 避免内存泄漏

### Query Info 结构

```python
{
  "strategy": "graph",
  "automated_reward": 0.91,
  "timestamp": 1733281234.5,
  "question": "Who wrote DADDY TAKE ME SKATING?",  # Truncated to 200 chars
  "user_feedback": 0.0,  # Added after feedback
  "feedback_comment": "Answer is incorrect",
  "feedback_timestamp": 1733281456.7
}
```

---

## 🚀 使用场景

### 场景 1: 自动 Reward 误判高分

**情况:**
- Graph RAG 返回了答案
- Confidence = 0.85 (高)
- Coverage = 1.0 (有引用)
- Latency = 200ms (快)
- **自动 reward = 0.91** (很高)

**但用户发现:**
- 答案引用的文档不相关
- 实际答案是错误的

**用户操作:**
```bash
# 提交负面反馈
curl -X POST http://localhost:8888/api/rag/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "query_id": "...",
    "rating": 0.0,
    "comment": "Citations are irrelevant"
  }'
```

**结果:**
- Graph RAG 权重降低
- 下次类似查询更可能选择 Hybrid 或 Iterative

---

### 场景 2: 自动 Reward 误判低分

**情况:**
- Iterative Self-RAG 用了 3 次迭代
- Latency = 25s (超出 8s budget)
- **latency_penalty = 0** (timeout 惩罚)
- Confidence = 0.70 (中)
- **自动 reward = 0.58** (中低)

**但用户发现:**
- 答案非常详细准确
- 多次迭代带来了更好的质量

**用户操作:**
```bash
# 提交正面反馈
curl -X POST http://localhost:8888/api/rag/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "query_id": "...",
    "rating": 1.0,
    "comment": "Excellent detailed answer, worth the wait"
  }'
```

**结果:**
- Final reward = 0.7 × 1.0 + 0.3 × 0.58 = 0.874
- Iterative Self-RAG 权重提升
- 系统学习: 对于复杂查询，牺牲延迟换质量是值得的

---

### 场景 3: 策略完全错误

**情况:**
- 用户问作者问题: "Who wrote Pride and Prejudice?"
- Smart RAG 选择了 Graph RAG (错误)
- Graph RAG 构建关系图 (35s)
- 答案可能正确，但策略浪费了时间

**用户操作:**
```bash
# 提交负面反馈
curl -X POST http://localhost:8888/api/rag/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "query_id": "...",
    "rating": 0.0,
    "comment": "Simple factual query, should use Hybrid not Graph"
  }'
```

**结果:**
- Graph RAG 权重降低
- 下次简单 factual 查询更可能用 Hybrid (快速)

---

## 📊 监控和分析

### 查看反馈日志

```bash
# 查看所有反馈
docker logs ai-louie-backend-1 2>&1 | grep "User feedback applied"

# 示例输出:
# User feedback applied query_id=a1b2... strategy=graph user_rating=0.0 automated_reward=0.910 question_preview="Who wrote DADDY TAKE ME SKATING?" comment="Answer is incorrect"
```

### 统计反馈分布

```bash
# 统计各策略的反馈评分
docker logs ai-louie-backend-1 2>&1 | grep "User feedback applied" | \
  awk -F'strategy=' '{print $2}' | awk '{print $1}' | sort | uniq -c

# 输出:
#   5 graph
#   3 hybrid
#   2 iterative
```

### 查看反馈对权重的影响

```bash
# 反馈前
python scripts/manage_bandit_state.py view

# 用户提交反馈
curl -X POST ...

# 反馈后
python scripts/manage_bandit_state.py view

# 比较 Alpha/Beta 变化
```

---

## ⚙️ 配置

### .env 配置

```env
# 启用 bandit 学习 (默认 true)
SMART_RAG_BANDIT_ENABLED=true

# Latency budget (用于 latency_penalty 计算)
SMART_RAG_LATENCY_BUDGET_MS=8000

# Bandit 状态持久化文件
BANDIT_STATE_FILE=./cache/smart_bandit_state.json
```

### 前端集成示例

```javascript
// 1. 用户查询
const response = await fetch('/api/rag/ask-smart', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    question: userQuestion,
    top_k: 5
  })
});

const data = await response.json();
const queryId = data.query_id;
const answer = data.answer;

// 2. 显示答案 + 反馈按钮
// UI: [👍 满意] [😐 中立] [👎 不满意]

// 3. 用户点击 👎
const feedbackResponse = await fetch('/api/rag/feedback', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    query_id: queryId,
    rating: 0.0,
    comment: userComment
  })
});

// 4. 显示确认
// "感谢反馈！系统已更新学习权重。"
```

---

## 🔍 技术细节

### Beta Distribution 更新

**无反馈:**
```python
alpha_new = alpha_old + reward
beta_new = beta_old + (1 - reward)
```

**有反馈:**
```python
final_reward = 0.7 × user_rating + 0.3 × automated_reward
alpha_new = alpha_old + final_reward
beta_new = beta_old + (1 - final_reward)
```

### Thompson Sampling 采样

```python
for arm in available:
    sample = random.betavariate(alpha, beta)
    samples[arm] = sample + exploration_bonus

chosen_arm = max(samples, key=samples.get)
```

**用户反馈的影响:**
- 正面反馈 (rating=1.0) → alpha 增加更多 → 期望值提高 → 选中概率增加
- 负面反馈 (rating=0.0) → beta 增加更多 → 期望值降低 → 选中概率减少

---

## ⚠️ 注意事项

### 1. Query History 限制

- **只保留最近 1000 个查询**
- 用户反馈必须在查询后较短时间内提交
- 如果用户第二天才想反馈，query_id 可能已过期

**解决方案 (未来优化):**
- 将 query history 持久化到 Redis/数据库
- 增加 TTL (如 24 小时)

### 2. 反馈权重平衡

- **当前:** 70% user_rating + 30% automated_reward
- **可调整:** 根据实际使用调整权重比例

**调整建议:**
```python
# 如果用户反馈很少，降低权重避免过拟合
final_reward = 0.5 × user_rating + 0.5 × automated_reward

# 如果用户反馈很频繁且准确，提高权重
final_reward = 0.8 × user_rating + 0.2 × automated_reward
```

### 3. 恶意反馈防护

**当前实现:** 无防护

**未来优化:**
- 限制单个 IP/用户的反馈频率
- 检测异常反馈模式 (如全是 0 或全是 1)
- 加权可信用户的反馈

### 4. 多实例部署

**当前:** 单实例内存缓存，不支持多实例共享

**多实例部署需要:**
- 使用 Redis 存储 `_query_history`
- 或使用数据库 + session 管理

---

## 📋 测试清单

### 功能测试

- [ ] 提交正面反馈 (rating=1.0)，权重应增加
- [ ] 提交负面反馈 (rating=0.0)，权重应降低
- [ ] 提交中立反馈 (rating=0.5)，权重应轻微调整
- [ ] 无效 query_id 应返回 404 错误
- [ ] Comment 字段可选，省略时应正常工作
- [ ] 反馈应持久化到 bandit_state.json

### 集成测试

```bash
# 1. 查询
RESPONSE=$(curl -s -X POST http://localhost:8888/api/rag/ask-smart \
  -H "Content-Type: application/json" \
  -d '{"question": "Who wrote Pride and Prejudice?", "top_k": 3}')

QUERY_ID=$(echo $RESPONSE | jq -r '.query_id')
echo "Query ID: $QUERY_ID"

# 2. 查看初始权重
python scripts/manage_bandit_state.py view

# 3. 提交负面反馈
curl -X POST http://localhost:8888/api/rag/feedback \
  -H "Content-Type: application/json" \
  -d "{\"query_id\": \"$QUERY_ID\", \"rating\": 0.0, \"comment\": \"Test feedback\"}"

# 4. 查看更新后权重
python scripts/manage_bandit_state.py view

# 5. 验证权重变化
# Alpha 增加应小于 Beta 增加
```

---

## ✅ 总结

### 实现的功能

1. ✅ **Query ID 生成** - 每个 RAG 响应包含唯一 query_id
2. ✅ **Query History 跟踪** - 内存缓存最近 1000 个查询
3. ✅ **Feedback 端点** - POST /api/rag/feedback
4. ✅ **权重重新计算** - 用户反馈 70% 权重
5. ✅ **持久化** - 更新自动保存到 bandit_state.json
6. ✅ **日志监控** - 详细的反馈日志

### 解决的核心问题

**用户问题:** "怎么判断不满意结果 比如用户发现你选错了"

**解决方案:**
- 用户通过 query_id 提交反馈 (rating: 0.0-1.0)
- 系统重新计算 bandit 权重，用户评分占 70%
- 负面反馈降低策略选中概率
- 正面反馈提升策略选中概率
- 持久化保证下次启动生效

### 使用流程

```
1. 用户查询 → 获得 query_id
2. 用户判断答案质量
3. 提交反馈 (0.0/0.5/1.0)
4. Bandit 权重更新
5. 下次查询受益于用户反馈
```

---

**版本:** 1.0
**状态:** ✅ Production Ready
**最后更新:** 2025-12-04
**文档:** [USER_FEEDBACK_MECHANISM.md](./USER_FEEDBACK_MECHANISM.md)

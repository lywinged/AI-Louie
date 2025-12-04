# 用户反馈机制 - 快速上手

**问题:** "怎么判断不满意结果 比如用户发现你选错了"

**解决方案:** 用户反馈 API ✅

---

## 🚀 快速使用

### 1️⃣ 用户查询 (获取 query_id)

```bash
curl -X POST http://localhost:8888/api/rag/ask-smart \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Who wrote Pride and Prejudice?",
    "top_k": 3
  }'
```

**响应:**
```json
{
  "answer": "Jane Austen wrote Pride and Prejudice...",
  "query_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",  // ← 保存这个
  "selected_strategy": "Hybrid RAG",
  "confidence": 0.92,
  ...
}
```

---

### 2️⃣ 用户发现答案错误 → 提交反馈

**如果答案正确 (满意):**
```bash
curl -X POST http://localhost:8888/api/rag/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "query_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "rating": 1.0,
    "comment": "Perfect answer!"
  }'
```

**如果答案错误 (不满意):**
```bash
curl -X POST http://localhost:8888/api/rag/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "query_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "rating": 0.0,
    "comment": "Answer is wrong, incorrect author"
  }'
```

**如果答案一般 (中立):**
```bash
curl -X POST http://localhost:8888/api/rag/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "query_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "rating": 0.5,
    "comment": "Acceptable but could be better"
  }'
```

---

### 3️⃣ 系统自动更新权重

**反馈响应:**
```json
{
  "query_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "rating": 0.0,
  "strategy_updated": "hybrid",
  "bandit_updated": true,
  "message": "Feedback applied to hybrid strategy. Bandit weights updated."
}
```

**权重更新公式:**
```python
# 用户反馈占 70%，自动 reward 占 30%
final_reward = 0.7 × user_rating + 0.3 × automated_reward

# 例如: 自动 reward=0.9 (高)，但用户 rating=0.0 (不满意)
final_reward = 0.7 × 0.0 + 0.3 × 0.9 = 0.27  # 权重大幅降低
```

---

## 📊 评分标准

| Rating | 含义 | 使用场景 |
|--------|------|---------|
| `1.0` | 满意/正确 | 答案准确，策略选择正确 |
| `0.5` | 中立/可接受 | 答案可用但不完美 |
| `0.0` | 不满意/错误 | 答案错误，策略选择不当 |

---

## 🔍 实际案例

### 案例 1: 自动评分误判高分

**场景:**
- Graph RAG 返回答案
- 自动 confidence = 0.85 (高)
- 但用户知道答案是错的

**用户反馈:**
```bash
curl -X POST http://localhost:8888/api/rag/feedback \
  -d '{"query_id": "...", "rating": 0.0}'
```

**结果:**
- Graph RAG 权重从 0.85 降到 0.26
- 下次类似查询更可能选择其他策略

---

### 案例 2: 自动评分误判低分

**场景:**
- Iterative Self-RAG 用了 25秒 (超时)
- 自动 reward = 0.2 (低，因为延迟惩罚)
- 但答案非常详细准确

**用户反馈:**
```bash
curl -X POST http://localhost:8888/api/rag/feedback \
  -d '{"query_id": "...", "rating": 1.0, "comment": "Excellent detailed answer"}'
```

**结果:**
- Final reward = 0.7 × 1.0 + 0.3 × 0.2 = 0.76
- Iterative Self-RAG 权重提升
- 系统学习: 复杂查询值得牺牲延迟

---

## 🧪 测试脚本

```bash
# 运行完整测试套件
python scripts/test_user_feedback.py

# 测试正面反馈 (rating=1.0)
python scripts/test_user_feedback.py --test positive

# 测试负面反馈 (rating=0.0)
python scripts/test_user_feedback.py --test negative

# 测试中立反馈 (rating=0.5)
python scripts/test_user_feedback.py --test neutral
```

---

## 📈 监控反馈

### 查看反馈日志

```bash
docker logs ai-louie-backend-1 2>&1 | grep "User feedback applied"
```

**示例输出:**
```
User feedback applied query_id=a1b2... strategy=graph user_rating=0.0
  automated_reward=0.910 question_preview="Who wrote DADDY TAKE ME SKATING?"
  comment="Answer is incorrect"
```

### 查看权重变化

```bash
# 反馈前
python scripts/manage_bandit_state.py view

# 提交反馈
curl -X POST http://localhost:8888/api/rag/feedback -d '...'

# 反馈后
python scripts/manage_bandit_state.py view
```

---

## ⚠️ 注意事项

### 1. Query ID 有效期

- 系统只保留最近 **1000 个查询** 的 query_id
- 反馈必须在查询后 **较短时间内** 提交
- 如果 query_id 过期，会返回 404 错误

### 2. 反馈权重

- 用户反馈占 **70% 权重**
- 自动 reward 占 **30% 权重**
- 用户反馈主导 bandit 更新

### 3. 持久化

- Bandit 权重自动保存到 `./cache/smart_bandit_state.json`
- 重启后自动加载，无需重新预热

---

## 📚 完整文档

- **详细技术文档:** [USER_FEEDBACK_MECHANISM.md](./USER_FEEDBACK_MECHANISM.md)
- **Bandit 学习机制:** [SMART_RAG_BANDIT_LEARNING.md](./SMART_RAG_BANDIT_LEARNING.md)
- **Bandit 持久化:** [BANDIT_PERSISTENCE_GUIDE.md](./BANDIT_PERSISTENCE_GUIDE.md)
- **部署总结:** [DEPLOYMENT_SUMMARY.md](./DEPLOYMENT_SUMMARY.md)

---

**版本:** 1.0
**状态:** ✅ Production Ready
**最后更新:** 2025-12-04

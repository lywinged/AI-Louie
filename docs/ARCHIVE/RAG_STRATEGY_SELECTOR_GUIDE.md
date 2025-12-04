# RAG策略选择器使用指南

## 位置

在主聊天页面 http://localhost:18501 的 **左侧侧边栏**

## 查找步骤

1. **进入RAG模式**
   - 在聊天输入框输入任何关于文档的问题
   - 或者点击建议的"RAG Mode"

2. **查看左侧侧边栏**
   - 找到 **"🔧 RAG Controls"** 部分
   - 在这个部分的**第一个控件**就是 **"RAG Strategy"** 下拉菜单

3. **选择策略**
   - 点击下拉菜单
   - 选择以下之一：
     - 📝 Standard RAG (4 techniques)
     - 🔍 Hybrid Search (7 techniques)
     - 🔁 Iterative Self-RAG (6 techniques)
     - 🎯 Smart Auto-Select (3 techniques)

## 如果看不到选择器

### 方法1: 强制刷新浏览器
```
Windows: Ctrl + Shift + R
Mac: Cmd + Shift + R
```

### 方法2: 清除浏览器缓存
1. 打开浏览器开发者工具 (F12)
2. 右键点击刷新按钮
3. 选择 "Empty Cache and Hard Reload"

### 方法3: 重启Streamlit容器
```bash
docker-compose restart frontend
```

## 测试不同策略

### 测试Standard RAG (4项技术)
1. 选择 "📝 Standard RAG (4 techniques)"
2. 输入问题: "What is prop building?"
3. 观察显示的4项技术：
   ```
   1️⃣ 📊 Query Embedding
   2️⃣ 🔍 Vector Similarity Search
   3️⃣ 🎯 Cross-Encoder Reranking
   4️⃣ 🤖 LLM Answer Generation
   ```

### 测试Hybrid Search (7项技术)
1. 选择 "🔍 Hybrid Search (7 techniques)"
2. 输入问题: "What is prop building?"
3. 观察显示的7项技术：
   ```
   1️⃣ 🏷️ Query Classification
   2️⃣ 💾 Semantic Cache Lookup
   3️⃣ 📊 Query Embedding
   4️⃣ 🔍 Hybrid Search (BM25 + Vector融合)
   5️⃣ 🎯 Cross-Encoder Reranking
   6️⃣ 🤖 LLM Answer Generation
   7️⃣ 💾 Update Cache Strategy
   ```

### 测试Iterative Self-RAG (6项技术)
1. 选择 "🔁 Iterative Self-RAG (6 techniques)"
2. 输入复杂问题: "Explain the relationship between Sir Robert and Uncle Robert"
3. 观察显示的6项技术：
   ```
   1️⃣ 🏷️ Query Classification
   2️⃣ 📊 Initial Query Embedding
   3️⃣ 🔍 Hybrid Retrieval
   4️⃣ 🎯 Rerank Retrieved Chunks
   5️⃣ 🤖 Generate Initial Answer
   6️⃣ 🔁 Self-RAG Verification (迭代检查)
   ```

### 测试Smart Auto-Select (3项技术)
1. 选择 "🎯 Smart Auto-Select (3 techniques)"
2. 输入问题: "What is prop building?"
3. 观察显示的3项技术：
   ```
   1️⃣ 🏷️ Query Analysis
   2️⃣ 🎯 Strategy Selection (智能选择)
   3️⃣ ⚡ Execute Pipeline
   ```

## 验证代码已更新

如果仍然看不到选择器，运行以下命令验证容器中的代码：

```bash
# 检查RAG Strategy选择器是否在代码中
docker exec streamlit-ui grep -n "RAG Strategy" /app/app.py

# 应该看到输出：
# 431:    # RAG Strategy Selection
# 443:        "RAG Strategy",

# 检查策略配置
docker exec streamlit-ui grep -A 3 "strategy_config = {" /app/app.py | head -10

# 应该看到4种策略的配置
```

## 当前默认值

- **默认策略**: Standard RAG (4 techniques)
- **首次运行**: 会显示4项技术
- **切换策略**: 选择其他策略后，技术数量会改变

## 技术对比

| 策略 | 技术数 | 特点 | 适用场景 |
|------|--------|------|----------|
| Standard | 4 | 基础RAG流程 | 简单查询 |
| Hybrid | 7 | BM25+Vector融合，有缓存 | 关键词+语义查询 |
| Iterative | 6 | Self-RAG迭代验证 | 复杂推理查询 |
| Smart | 3 | 自动选择最优策略 | 不确定查询类型 |

## 预期行为

1. **选择策略** → 侧边栏下拉菜单
2. **显示当前选择** → 下方会显示 "Selected: hybrid" 等
3. **提问** → 显示对应数量的技术
4. **调用对应API** → /api/rag/ask-hybrid 等

## 故障排除

### 问题: 总是显示4项技术
**原因**: 可能没有选择其他策略，或浏览器缓存未更新
**解决**:
1. 强制刷新浏览器 (Ctrl+Shift+R)
2. 明确选择 "Hybrid Search (7 techniques)"
3. 输入新问题测试

### 问题: 看不到RAG Strategy选择器
**原因**: 可能不在RAG模式，或者侧边栏折叠了
**解决**:
1. 确认在RAG模式 (输入问题或点击RAG Mode)
2. 展开左侧侧边栏
3. 向下滚动到 "🔧 RAG Controls" 部分

### 问题: 选择后没有变化
**原因**: 需要输入新问题才会应用新策略
**解决**:
1. 选择新策略
2. 输入一个新问题 (不能重新提交旧问题)
3. 观察技术列表的变化

---

## 总结

✅ 代码已部署到容器
✅ RAG Strategy选择器在侧边栏
✅ 支持4种策略，显示不同数量的技术
✅ 自动调用对应的API endpoint

如果还是看不到，请：
1. 强制刷新浏览器 (Cmd/Ctrl + Shift + R)
2. 检查是否在RAG模式
3. 查看侧边栏的 "RAG Controls" 部分

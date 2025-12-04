# 🎯 AI-Louie RAG 策略完整指南

## 📊 所有可用的 RAG 策略端点

您的系统包含 **7 种不同的 RAG 策略**,每种都针对特定场景优化:

---

### 1️⃣ **基础 RAG** (`/api/rag/ask`)
**端点**: `POST /api/rag/ask`

**适用场景**:
- 简单问答查询
- 需要快速响应
- 标准文档检索

**特点**:
- ✅ 向量检索 + Reranking
- ✅ LLM 生成答案
- ✅ 支持自适应模型选择 (BGE/MiniLM)
- ✅ 带引用和置信度评分

**示例**:
```bash
curl -X POST http://localhost:8888/api/rag/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is prop building?",
    "top_k": 5
  }'
```

---

### 2️⃣ **混合搜索 RAG** (`/api/rag/ask-hybrid`)
**端点**: `POST /api/rag/ask-hybrid`

**适用场景**:
- 需要关键词匹配和语义理解结合
- 专业术语查询
- 需要精确匹配的场景

**特点**:
- ✅ BM25 关键词搜索 + 向量语义搜索
- ✅ 混合融合 (可调节 alpha 权重)
- ✅ 查询策略缓存 (90% token 节省)
- ✅ 查询分类优化参数

**参数**:
- `hybrid_alpha`: 向量搜索权重 (0-1),默认 0.7
  - 0.7 = 70% 向量 + 30% BM25

**示例**:
```bash
curl -X POST http://localhost:8888/api/rag/ask-hybrid \
  -H "Content-Type: application/json" \
  -d '{
    "question": "ONNX inference optimization techniques",
    "top_k": 5
  }'
```

---

### 3️⃣ **迭代自反思 RAG** (`/api/rag/ask-iterative`)
**端点**: `POST /api/rag/ask-iterative`

**适用场景**:
- 复杂多跳推理问题
- 需要多次检索补充信息
- 深度分析任务

**特点**:
- ✅ Self-RAG 迭代检索
- ✅ 置信度评估
- ✅ 自动补充缺失信息
- ✅ 增量上下文 (节省 tokens)

**配置** (.env):
```bash
ENABLE_SELF_RAG=true
SELF_RAG_CONFIDENCE_THRESHOLD=0.75  # 停止迭代的最低置信度
SELF_RAG_MAX_ITERATIONS=3           # 最大迭代次数
SELF_RAG_MIN_IMPROVEMENT=0.05       # 继续迭代的最小改进
```

**示例**:
```bash
curl -X POST http://localhost:8888/api/rag/ask-iterative \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Explain the complete prop building process from design to finish",
    "top_k": 10
  }'
```

---

### 4️⃣ **智能 RAG** (`/api/rag/ask-smart`) ⭐ **推荐**
**端点**: `POST /api/rag/ask-smart`

**适用场景**:
- **生产环境推荐使用**
- 自动选择最优策略
- 通用问答

**特点**:
- ✅ **自动策略选择**: LLM 分类查询类型
- ✅ 简单查询 → Hybrid RAG
- ✅ 复杂查询 → Iterative Self-RAG
- ✅ 关系查询 → Graph RAG
- ✅ 结构化查询 → Table RAG
- ✅ 答案缓存 (语义匹配)
- ✅ 详细 token breakdown

**决策逻辑**:
```
简单查询 (author, factual) → Hybrid Search
复杂查询 (analysis, reasoning) → Iterative Self-RAG
关系查询 (relationships, connections) → Graph RAG
列表/比较查询 (list, compare) → Table RAG
```

**响应包含**:
- `selected_strategy`: 选择的策略
- `strategy_reason`: 选择原因
- `token_breakdown`: 详细 token 使用分解

**示例**:
```bash
curl -X POST http://localhost:8888/api/rag/ask-smart \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What tools are needed for prop building?",
    "top_k": 5
  }'
```

---

### 5️⃣ **流式 RAG** (`/api/rag/ask-stream`)
**端点**: `POST /api/rag/ask-stream`

**适用场景**:
- 需要实时响应反馈
- 用户体验优化
- 长答案生成

**特点**:
- ✅ SSE (Server-Sent Events) 流式输出
- ✅ 逐词返回答案
- ✅ 答案缓存支持
- ✅ 实时进度反馈

**事件类型**:
- `retrieval`: 检索完成,返回引用
- `content`: LLM 响应流 (逐词)
- `metadata`: 最终元数据 (tokens, 耗时)
- `done`: 流结束
- `error`: 错误发生

**示例**:
```bash
curl -N -X POST http://localhost:8888/api/rag/ask-stream \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Describe the prop building workflow",
    "top_k": 5
  }'
```

---

### 6️⃣ **图谱 RAG** (`/api/rag/ask-graph`)
**端点**: `POST /api/rag/ask-graph`

**适用场景**:
- 关系查询 (人物关系、知识图谱)
- 实体连接分析
- 多跳推理

**特点**:
- ✅ JIT (Just-In-Time) 图谱构建
- ✅ 实体提取 + 关系抽取
- ✅ 图谱遍历 (可配置跳数)
- ✅ 结合向量检索
- ✅ 图谱缓存

**配置**:
```bash
GRAPH_MAX_JIT_CHUNKS=50  # JIT 构建的最大 chunks 数
```

**参数**:
- `top_k`: 向量检索数量
- `max_hops`: 图谱遍历深度 (默认 2)

**最佳查询类型**:
- "X 和 Y 的关系是什么?"
- "所有人物的关系网络"
- "X 如何影响 Y?"

**示例**:
```bash
curl -X POST http://localhost:8888/api/rag/ask-graph \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are the character relationships in the novel?",
    "top_k": 10
  }'
```

**响应包含**:
- `graph_context`: 实体和关系列表
- `jit_stats`: JIT 构建统计
- `query_entities`: 提取的查询实体

---

### 7️⃣ **表格 RAG** (`/api/rag/ask-table`)
**端点**: `POST /api/rag/ask-table`

**适用场景**:
- 结构化数据展示
- 比较分析
- 列表聚合
- Excel 数据分析

**特点**:
- ✅ 查询意图分析 (comparison/list/aggregation)
- ✅ 混合检索
- ✅ 数据结构化为表格
- ✅ **自动 Excel 工具调用** (反向用电量计算)
- ✅ 表格 + 答案生成
- ✅ 工具使用元数据

**工具集成**:
- 关键词触发: `反向用电`, `抄表`, `发电`, `kwh`, `电量`, `电表`, `excel`
- 自动分析 Excel 文件
- 计算反向用电量总和

**最佳查询类型**:
- "比较 X 和 Y"
- "列出所有工具"
- "反向用电量是多少 kWh?"

**示例**:
```bash
curl -X POST http://localhost:8888/api/rag/ask-table \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Compare all the tools mentioned for prop building",
    "top_k": 20
  }'
```

**响应包含**:
- `table_data`: 表格数据 (headers + rows + summary)
- `query_intent`: 查询意图分析
- `tool_usage`: 工具使用详情
  - `triggered`: 是否触发工具
  - `tool_name`: 工具名称
  - `execution_time_ms`: 执行时间
  - `status`: success/failed/not_triggered
  - `output`: 工具输出 (Excel 分析结果)

---

## 🎨 模型适配器选择

### 自适应模型切换

您的系统支持 **2 种嵌入模型**,根据查询难度自动切换:

#### **Primary: BGE-M3** (高精度)
- 模型: `bge-m3-embed-int8` + `bge-reranker-int8`
- 适用: 复杂/中等难度查询
- 特点: 关系理解、多概念查询、深度推理

#### **Fallback: MiniLM** (高速度)
- 模型: `minilm-embed-int8` + `minilm-reranker-onnx`
- 适用: 简单事实查询
- 特点: 快速推理、短查询、单一概念

### 手动切换模型

使用 `/api/rag/switch-mode` 端点:

```bash
# 切换到 BGE (高精度)
curl -X POST http://localhost:8888/api/rag/switch-mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "primary"}'

# 切换到 MiniLM (高速度)
curl -X POST http://localhost:8888/api/rag/switch-mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "fallback"}'
```

### 查询难度自动分类

**Simple** → MiniLM:
- 5 词以内
- 简单事实问题: "What is X?", "Who is Y?"

**Moderate** → BGE (如果可用):
- 6-15 词
- 多概念查询
- 上下文依赖

**Complex** → BGE (必须):
- 16+ 词
- 关系分析: "relationship", "compare", "difference"
- 深度推理: "explain why", "analyze"

---

## 📈 性能优化特性

### 缓存系统

#### 1. **查询策略缓存** (Query Strategy Cache)
- 缓存成功的检索策略
- 节省 90% classification tokens
- 语义相似度匹配 (0.85 阈值)
- TTL: 24 小时

#### 2. **答案缓存** (Answer Cache) - **3 层混合**
- **Layer 1**: 精确匹配 (exact match)
- **Layer 2**: TF-IDF 关键词匹配 (0.30 阈值)
- **Layer 3**: 语义相似度匹配 (0.88 阈值)
- TTL: 72 小时 (3 天)
- LRU 淘汰,最多 1000 条

### 配置 (.env)

```bash
# 混合搜索
ENABLE_HYBRID_SEARCH=true
HYBRID_ALPHA=0.7              # 70% 向量 + 30% BM25

# 查询策略缓存
ENABLE_QUERY_CACHE=true
QUERY_CACHE_SIMILARITY_THRESHOLD=0.85
QUERY_CACHE_MAX_SIZE=1000

# 答案缓存
ENABLE_ANSWER_CACHE=true
ANSWER_CACHE_SIMILARITY_THRESHOLD=0.88
ANSWER_CACHE_TFIDF_THRESHOLD=0.30
ANSWER_CACHE_MAX_SIZE=1000
ANSWER_CACHE_TTL_HOURS=72

# Self-RAG
ENABLE_SELF_RAG=true
SELF_RAG_CONFIDENCE_THRESHOLD=0.75
SELF_RAG_MAX_ITERATIONS=3
```

---

## 🚀 推荐使用指南

### 选择哪个策略?

```
┌─────────────────────────────────────┐
│ 不确定? → /api/rag/ask-smart       │  ⭐ 最推荐
├─────────────────────────────────────┤
│ 需要流式输出? → /api/rag/ask-stream │
├─────────────────────────────────────┤
│ 关系查询? → /api/rag/ask-graph      │
├─────────────────────────────────────┤
│ 列表/比较? → /api/rag/ask-table     │
├─────────────────────────────────────┤
│ 关键词匹配? → /api/rag/ask-hybrid   │
├─────────────────────────────────────┤
│ 深度推理? → /api/rag/ask-iterative  │
├─────────────────────────────────────┤
│ 简单快速? → /api/rag/ask            │
└─────────────────────────────────────┘
```

### Token 优化建议

1. **使用 Smart RAG**: 自动选择最优策略
2. **启用缓存**: 查询缓存 + 答案缓存
3. **调整参数**:
   - 简单查询降低 `top_k` (3-5)
   - 复杂查询增加 `top_k` (10-20)
4. **使用流式**: 用户体验更好,token 相同

---

## 📊 监控指标

访问 Grafana: `http://localhost:3000`

**关键指标**:
- RAG 请求成功率
- 查询缓存命中率
- 答案缓存命中率
- 端点延迟分布
- Token 使用统计
- 模型切换频率

---

## 🎯 最佳实践

1. **生产环境**: 使用 `/api/rag/ask-smart`
2. **实时交互**: 使用 `/api/rag/ask-stream`
3. **批量查询**: 启用答案缓存
4. **知识图谱**: 提前上传文档,让 Graph RAG JIT 构建
5. **Excel 分析**: 确保上传文件到 `data/uploads/`
6. **性能调优**:
   - 简单查询 → MiniLM
   - 复杂查询 → BGE
   - 监控缓存命中率

---

**生成时间**: 2025-11-30
**版本**: 1.0

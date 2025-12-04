# 🔍 AI-Louie 监控系统设置指南

本文档介绍如何使用新增的监控和可观测性功能。

## 📊 新增功能概览

### 1. Prometheus + Grafana (指标可视化)
- **Prometheus**: 时序指标收集和存储
- **Grafana**: 实时可视化仪表板
- **访问地址**: http://localhost:3000 (默认密码: admin/admin)

### 2. OpenTelemetry (分布式追踪)
- **Jaeger UI**: 分布式追踪可视化
- **访问地址**: http://localhost:16686
- **功能**: 追踪完整请求链路 (FastAPI → LLM → Qdrant)

### 3. Evidently (数据质量监控)
- **数据漂移检测**: 自动检测输入/输出分布变化
- **API 端点**: `/api/monitoring/data-quality/*`

### 4. ragas (RAG 质量评估)
- **自动评估**: Faithfulness, Relevancy, Precision, Recall
- **API 端点**: `/api/monitoring/rag/*`

### 5. 统一 LLM Metrics
- **Token 计数**: 自动跟踪所有 LLM 调用的 token 使用
- **成本追踪**: 实时计算 API 调用成本
- **API 端点**: `/api/monitoring/llm/*`

---

## 🚀 快速启动

### 1. 启动所有服务

```bash
# 一键启动（包含所有监控服务）
./start.sh

# 或使用 docker-compose
docker-compose up -d
```

### 2. 验证服务状态

```bash
# 检查所有容器
docker ps

# 应该看到以下容器:
# - backend-api (FastAPI)
# - qdrant (向量数据库)
# - prometheus (指标收集)
# - grafana (可视化)
# - jaeger (分布式追踪)
# - streamlit-ui (前端)
# - inference-service (ONNX 推理)
```

### 3. 访问监控界面

| 服务 | URL | 默认凭据 | 功能 |
|------|-----|----------|------|
| **Grafana** | http://localhost:3000 | admin/admin | LLM & RAG 仪表板 |
| **Prometheus** | http://localhost:9090 | 无需认证 | 原始指标查询 |
| **Jaeger** | http://localhost:16686 | 无需认证 | 分布式追踪 |
| **FastAPI Docs** | http://localhost:8888/docs | 无需认证 | API 文档 |
| **Prometheus /metrics** | http://localhost:8888/metrics | 无需认证 | 原始指标导出 |

---

## 📈 Grafana 仪表板

### 预配置仪表板

已包含两个预配置仪表板：

#### 1. LLM Metrics Dashboard
- **LLM 请求速率**: 每秒请求数 (按模型/状态)
- **Token 使用量**: Prompt & Completion tokens
- **API 成本**: 实时成本追踪 (USD)
- **请求延迟**: P95 延迟分布
- **成功率**: 请求成功率仪表盘

#### 2. RAG Performance Dashboard
- **RAG 请求速率**: 检索操作频率
- **嵌入延迟**: 向量生成性能
- **重排序延迟**: 重排序性能
- **向量搜索延迟**: P50/P95/P99 分布
- **缓存命中率**: 嵌入缓存效率
- **端到端延迟**: 完整 RAG 流程延迟
- **重排序分数分布**: 热力图
- **错误率**: 推理服务错误监控
- **熔断器状态**: 服务健康监控

### 自定义仪表板

在 Grafana UI 中:
1. 点击 "+" → "Dashboard"
2. 添加 Panel
3. 选择 Prometheus 数据源
4. 使用以下指标:
   - `llm_token_usage_counter_total`
   - `llm_cost_counter_total`
   - `llm_request_duration_histogram_bucket`
   - `rag_operation_counter_total`
   - `embedding_duration_histogram_bucket`
   - `rerank_duration_histogram_bucket`

---

## 🔍 Jaeger 分布式追踪

### 查看追踪

1. 访问 http://localhost:16686
2. 从 "Service" 下拉菜单选择 `ai-louie-backend`
3. 点击 "Find Traces" 查看最近的追踪

### 追踪信息包含:

- **HTTP 请求**: FastAPI 路由
- **LLM 调用**: Token 数量、成本、延迟
- **数据库查询**: Qdrant 向量搜索
- **外部 HTTP 调用**: Azure OpenAI API

### 示例查询:

- 查找慢请求: `duration > 2s`
- 查找错误: `error=true`
- 按操作过滤: `operation=llm.chat_completion`

---

## 📊 监控 API 端点

### LLM Metrics API

```bash
# 获取 LLM 调用汇总
curl http://localhost:8888/api/monitoring/llm/summary

# 获取最近的 LLM 调用
curl "http://localhost:8888/api/monitoring/llm/recent-calls?limit=10"

# 按模型过滤
curl "http://localhost:8888/api/monitoring/llm/summary?model=gpt-4o-mini"
```

### 数据质量 API

```bash
# 获取数据质量摘要
curl "http://localhost:8888/api/monitoring/data-quality/summary?interaction_type=chat"

# 生成数据漂移报告
curl -X POST http://localhost:8888/api/monitoring/data-quality/drift-report \
  -H "Content-Type: application/json" \
  -d '{
    "interaction_type": "chat",
    "reference_window": 1000,
    "current_window": 100
  }'
```

### RAG 评估 API

```bash
# 评估 RAG 答案质量
curl -X POST http://localhost:8888/api/monitoring/rag/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is machine learning?",
    "answer": "Machine learning is a subset of AI...",
    "contexts": ["Context from document 1", "Context from document 2"],
    "ground_truth": "Optional ground truth answer"
  }'

# 获取评估摘要
curl http://localhost:8888/api/monitoring/rag/evaluation-summary

# 获取最近的评估
curl "http://localhost:8888/api/monitoring/rag/recent-evaluations?limit=10"
```

### 健康检查

```bash
# 监控系统健康
curl http://localhost:8888/api/monitoring/health

# 监控配置信息
curl http://localhost:8888/api/monitoring/config
```

---

## 🧪 测试监控功能

### 1. 测试 LLM Metrics

```bash
# 发送聊天请求
curl -X POST http://localhost:8888/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hello, how are you?",
    "stream": false
  }'

# 查看指标
curl http://localhost:8888/api/monitoring/llm/summary
```

### 2. 测试 RAG 评估

```bash
# 发送 RAG 查询
curl -X POST http://localhost:8888/api/rag/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is the capital of France?",
    "top_k": 5
  }'

# 查看 RAG 质量摘要
curl http://localhost:8888/api/monitoring/rag/evaluation-summary
```

### 3. 测试数据漂移检测

```bash
# 发送多个请求以累积数据
for i in {1..50}; do
  curl -X POST http://localhost:8888/api/chat/message \
    -H "Content-Type: application/json" \
    -d "{\"message\": \"Test message $i\", \"stream\": false}"
  sleep 0.5
done

# 生成漂移报告
curl -X POST http://localhost:8888/api/monitoring/data-quality/drift-report \
  -H "Content-Type: application/json" \
  -d '{
    "interaction_type": "chat",
    "reference_window": 30,
    "current_window": 20
  }'
```

---

## 📝 Prometheus 查询示例

在 Prometheus UI (http://localhost:9090) 或 Grafana 中使用:

```promql
# LLM Token 使用速率
rate(llm_token_usage_counter_total[5m])

# LLM 每秒成本
rate(llm_cost_counter_total[5m])

# P95 LLM 延迟
histogram_quantile(0.95, rate(llm_request_duration_histogram_bucket[5m]))

# RAG 操作速率
rate(rag_operation_counter_total[5m])

# 嵌入缓存命中率
sum(rate(embedding_counter_total{status="cache_hit"}[5m])) /
sum(rate(embedding_counter_total[5m]))

# LLM 成功率
sum(rate(llm_request_counter_total{status="success"}[5m])) /
sum(rate(llm_request_counter_total[5m]))
```

---

## 🔧 故障排查

### Grafana 无法连接 Prometheus

```bash
# 检查 Prometheus 是否运行
docker logs prometheus

# 验证 Prometheus 可访问
curl http://localhost:9090/-/healthy
```

### Jaeger 没有追踪数据

```bash
# 检查 backend 环境变量
docker exec backend-api env | grep OTLP

# 应该显示:
# OTLP_ENDPOINT=http://jaeger:4317
# ENABLE_TELEMETRY=true

# 检查 Jaeger 日志
docker logs jaeger
```

### ragas 评估失败

```bash
# 检查依赖是否安装
docker exec backend-api pip list | grep ragas

# 查看 backend 日志
docker logs backend-api | grep ragas
```

### Evidently 报告生成失败

```bash
# 检查是否有足够数据
curl http://localhost:8888/api/monitoring/data-quality/summary?interaction_type=chat

# total_interactions 应该 > reference_window + current_window
```

---

## 📊 指标说明

### LLM Metrics

| 指标名称 | 类型 | 描述 |
|---------|------|------|
| `llm_token_usage_counter_total` | Counter | Token 总使用量 |
| `llm_cost_counter_total` | Counter | API 调用总成本 (USD) |
| `llm_request_counter_total` | Counter | LLM 请求总数 |
| `llm_request_duration_histogram` | Histogram | LLM 请求延迟分布 |

### RAG Metrics

| 指标名称 | 类型 | 描述 |
|---------|------|------|
| `rag_operation_counter_total` | Counter | RAG 操作计数 |
| `embedding_duration_histogram` | Histogram | 嵌入生成延迟 |
| `rerank_duration_histogram` | Histogram | 重排序延迟 |
| `pgvector_query_duration_histogram` | Histogram | 向量搜索延迟 |
| `embedding_counter_total` | Counter | 嵌入请求计数 |
| `rerank_counter_total` | Counter | 重排序请求计数 |

### RAG Quality Metrics (ragas)

| 指标名称 | 类型 | 描述 |
|---------|------|------|
| `rag_faithfulness_score` | Gauge | 答案忠实度 (0-1) |
| `rag_answer_relevancy_score` | Gauge | 答案相关性 (0-1) |
| `rag_context_precision_score` | Gauge | 上下文精确度 (0-1) |
| `rag_context_recall_score` | Gauge | 上下文召回率 (0-1) |
| `rag_evaluation_duration_seconds` | Histogram | 评估耗时 |

---

## 🎯 最佳实践

### 1. 持续监控

- **每日检查 Grafana 仪表板**: 识别异常模式
- **设置告警**: 在 Prometheus 中配置告警规则
- **定期审查成本**: 监控 LLM API 成本趋势

### 2. 性能优化

- **查看 P95 延迟**: 识别慢请求
- **监控缓存命中率**: 优化嵌入缓存策略
- **追踪分布式调用**: 使用 Jaeger 定位瓶颈

### 3. 质量保证

- **定期运行 ragas 评估**: 确保 RAG 答案质量
- **监控数据漂移**: 检测输入分布变化
- **审查失败请求**: 分析错误模式

### 4. 成本管理

- **按模型追踪成本**: 比较不同模型的成本效益
- **监控 token 使用**: 优化提示词以减少 token
- **设置成本警报**: 避免意外超支

---

## 📚 相关文档

- **Prometheus**: https://prometheus.io/docs/
- **Grafana**: https://grafana.com/docs/
- **Jaeger**: https://www.jaegertracing.io/docs/
- **OpenTelemetry**: https://opentelemetry.io/docs/
- **Evidently**: https://docs.evidentlyai.com/
- **ragas**: https://docs.ragas.io/

---

## 🆘 获取帮助

- **问题反馈**: https://github.com/anthropics/claude-code/issues
- **API 文档**: http://localhost:8888/docs
- **监控配置**: http://localhost:8888/api/monitoring/config

---

**监控系统由 AI-Louie 团队维护**
最后更新: 2025-01-23

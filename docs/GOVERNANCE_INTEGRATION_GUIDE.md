# Governance Tracking Integration Guide

## 概述
此文档说明如何将 governance tracking 集成到 RAG endpoints 中。

## 已创建的文件
- `backend/backend/middleware/governance_middleware.py` - Governance tracking decorator

## 修改步骤

### 1. 在 `backend/backend/routers/rag_routes.py` 中添加 import

在文件顶部添加：
```python
from backend.middleware.governance_middleware import with_governance_tracking
```

### 2. 为主要 RAG endpoints 添加 decorator

对以下 endpoints 添加 `@with_governance_tracking()` decorator：

#### `/ask` endpoint (行 222):
```python
@router.post("/ask", response_model=RAGResponse)
@with_governance_tracking(operation_type="rag", risk_tier=RiskTier.R1)
async def ask_question(request: RAGRequest) -> RAGResponse:
    ...
```

#### `/ask-hybrid` endpoint (行 740):
```python
@router.post("/ask-hybrid", response_model=RAGResponse)
@with_governance_tracking(operation_type="rag", risk_tier=RiskTier.R1)
async def ask_question_hybrid_search(request: RAGRequest) -> RAGResponse:
    ...
```

#### `/ask-iterative` endpoint (行 828):
```python
@router.post("/ask-iterative", response_model=RAGResponse)
@with_governance_tracking(operation_type="rag", risk_tier=RiskTier.R1)
async def ask_question_iterative(request: RAGRequest) -> RAGResponse:
    ...
```

#### `/ask-smart` endpoint (行 1137):
```python
@router.post("/ask-smart", response_model=RAGResponse)
@with_governance_tracking(operation_type="rag", risk_tier=RiskTier.R1)
async def ask_question_smart(request: RAGRequest) -> RAGResponse:
    ...
```

#### `/ask-stream` endpoint (行 1519):
```python
@router.post("/ask-stream")
@with_governance_tracking(operation_type="rag", risk_tier=RiskTier.R1)
async def ask_stream(request: RAGRequest):
    ...
```

#### `/ask-graph` endpoint (行 1751):
```python
@router.post("/ask-graph")
@with_governance_tracking(operation_type="rag", risk_tier=RiskTier.R1)
async def ask_question_graph_rag(request: RAGRequest) -> Dict[str, Any]:
    ...
```

#### `/ask-table` endpoint (行 1910):
```python
@router.post("/ask-table")
@with_governance_tracking(operation_type="rag", risk_tier=RiskTier.R1)
async def ask_question_table_rag(request: RAGRequest) -> Dict[str, Any]:
    ...
```

## Decorator 自动跟踪的 Governance Checkpoints

### G3: Evidence Contract
- ✅ 输入日志记录（问题长度、top_k 参数）
- ✅ 输出日志记录（答案长度、检索的 chunks 数量）

### G5: Privacy Control
- ✅ 基本 PII 检测（email, phone, address 模式）
- ⚠️ 如检测到潜在 PII 会记录 warning 状态

### G7: Observability
- ✅ 为每个请求生成 trace_id
- ✅ 记录 endpoint 名称和开始时间

### G8: Evaluation System
- ✅ 延迟监控（< 2000ms SLO for R1）
- ⚠️ 如超过 SLO 会记录 warning 状态
- ❌ 如请求失败会记录 failed 状态

## Prometheus Metrics

Decorator 会自动通过 `governance_tracker.py` 导出以下 metrics：

```promql
# Governance checkpoint counter
governance_checkpoint_total{criteria="g3_evidence_contract", status="passed", operation_type="rag", risk_tier="external_customer_facing"}
governance_checkpoint_total{criteria="g5_privacy_control", status="passed", operation_type="rag", risk_tier="external_customer_facing"}
governance_checkpoint_total{criteria="g7_observability", status="passed", operation_type="rag", risk_tier="external_customer_facing"}
governance_checkpoint_total{criteria="g8_evaluation_system", status="passed", operation_type="rag", risk_tier="external_customer_facing"}
governance_checkpoint_total{criteria="g8_evaluation_system", status="warning", operation_type="rag", risk_tier="external_customer_facing"}
```

## 验证集成

### 1. 重启 backend 服务
```bash
docker-compose restart backend
```

### 2. 发送测试请求
```bash
curl -X POST http://localhost:8888/api/rag/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is Air NZ?", "top_k": 3}'
```

### 3. 检查 Prometheus metrics
```bash
curl -s http://localhost:8888/metrics | grep governance_checkpoint
```

应该看到类似输出：
```
# HELP governance_checkpoint_total Governance checkpoints by criteria and status
# TYPE governance_checkpoint_total counter
governance_checkpoint_total{criteria="g3_evidence_contract",operation_type="rag",risk_tier="external_customer_facing",status="passed"} 2.0
governance_checkpoint_total{criteria="g5_privacy_control",operation_type="rag",risk_tier="external_customer_facing",status="passed"} 1.0
governance_checkpoint_total{criteria="g7_observability",operation_type="rag",risk_tier="external_customer_facing",status="passed"} 1.0
governance_checkpoint_total{criteria="g8_evaluation_system",operation_type="rag",risk_tier="external_customer_facing",status="passed"} 1.0
```

### 4. 检查 Grafana dashboard
访问 http://localhost:3000/d/ai-governance-dashboard 应该看到：
- G3, G5, G8 面板开始显示数据（不再是 0）
- Governance Compliance Rate 开始计算
- All Governance Criteria Status 表格显示最新的 checkpoint 状态

## 下一步

1. ✅ 完成 middleware 创建
2. ⏳ 应用 decorator 到所有 RAG endpoints
3. ⏳ 测试并验证 metrics 导出
4. ⏳ 更新 Grafana dashboard 添加 G1, G2, G5, G6, G8, G10, G11 面板

## 注意事项

- Decorator 是**非侵入性的** - 不会改变 endpoint 的返回值或行为
- 如果 governance tracking 失败，不会影响正常的 RAG 功能
- 所有的 checkpoints 都会通过 structlog 记录到日志中
- Prometheus metrics 在每个 checkpoint 时实时更新

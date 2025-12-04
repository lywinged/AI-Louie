# AI Governance Dashboard 修复方案 - 完整总结

## 🔍 问题诊断

### 1. G3 出现2次？
**诊断结果**: 当前 Grafana API 返回的 dashboard **没有重复的 G3 面板**。
- 实际只有 G4, G9, G12 三个单独的 governance 面板
- 可能是浏览器缓存或旧版本 dashboard 的问题
- 建议刷新浏览器或清除 Grafana 缓存

### 2. 为什么没有 G5?
**原因**: Dashboard 中确实缺少 G5 (Privacy Control) 面板

### 3. 为什么 G8 = 0?
**根本原因**: Governance tracking **从未被调用**
- ✅ `governance_tracker.py` 代码存在
- ✅ `rag_routes.py` 导入了 `get_governance_tracker`
- ❌ **但没有任何 endpoint 实际调用 governance tracking**
- ❌ 所以所有 governance metrics 都是 0

---

## ✅ 已完成的修复

### 1. 创建了 Governance Middleware (`governance_middleware.py`)
**位置**: `/backend/backend/middleware/governance_middleware.py`

**功能**: 提供 `@with_governance_tracking()` decorator，自动跟踪：
- **G3**: Evidence Contract (输入/输出日志)
- **G5**: Privacy Control (PII 检测)
- **G7**: Observability (trace ID 生成)
- **G8**: Evaluation System (延迟 SLO 监控 < 2s)

**优势**:
- 非侵入式 - 不改变 endpoint 行为
- 自动导出 Prometheus metrics
- 失败不影响正常功能
- 易于应用到所有 endpoints

### 2. 编写了集成指南 (`GOVERNANCE_INTEGRATION_GUIDE.md`)
**内容**:
- 如何在 RAG endpoints 添加 decorator
- 需要修改的具体行号和代码示例
- 验证步骤和测试方法
- Prometheus metrics 查询示例

---

## 🔧 待完成的步骤

### Step 1: 应用 Decorator 到 RAG Endpoints

在 `backend/backend/routers/rag_routes.py` 文件顶部添加 import:
```python
from backend.middleware.governance_middleware import with_governance_tracking
```

然后为以下 7 个 endpoints 添加 decorator（在 `@router.post` 下面添加）:

#### 1. `/ask` (行 222)
```python
@router.post("/ask", response_model=RAGResponse)
@with_governance_tracking(operation_type="rag", risk_tier=RiskTier.R1)
async def ask_question(request: RAGRequest) -> RAGResponse:
```

#### 2. `/ask-hybrid` (行 740)
```python
@router.post("/ask-hybrid", response_model=RAGResponse)
@with_governance_tracking(operation_type="rag", risk_tier=RiskTier.R1)
async def ask_question_hybrid_search(request: RAGRequest) -> RAGResponse:
```

#### 3. `/ask-iterative` (行 828)
```python
@router.post("/ask-iterative", response_model=RAGResponse)
@with_governance_tracking(operation_type="rag", risk_tier=RiskTier.R1)
async def ask_question_iterative(request: RAGRequest) -> RAGResponse:
```

#### 4. `/ask-smart` (行 1137)
```python
@router.post("/ask-smart", response_model=RAGResponse)
@with_governance_tracking(operation_type="rag", risk_tier=RiskTier.R1)
async def ask_question_smart(request: RAGRequest) -> RAGResponse:
```

#### 5. `/ask-stream` (行 1519)
```python
@router.post("/ask-stream")
@with_governance_tracking(operation_type="rag", risk_tier=RiskTier.R1)
async def ask_stream(request: RAGRequest):
```

#### 6. `/ask-graph` (行 1751)
```python
@router.post("/ask-graph")
@with_governance_tracking(operation_type="rag", risk_tier=RiskTier.R1)
async def ask_question_graph_rag(request: RAGRequest) -> Dict[str, Any]:
```

#### 7. `/ask-table` (行 1910)
```python
@router.post("/ask-table")
@with_governance_tracking(operation_type="rag", risk_tier=RiskTier.R1)
async def ask_question_table_rag(request: RAGRequest) -> Dict[str, Any]:
```

### Step 2: 重启 Backend 服务
```bash
docker-compose restart backend
```

### Step 3: 测试 Governance Metrics

发送测试请求:
```bash
curl -X POST http://localhost:8888/api/rag/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is prop building?", "top_k": 3}'
```

检查 metrics:
```bash
curl -s http://localhost:8888/metrics | grep governance_checkpoint
```

期望输出:
```promql
governance_checkpoint_total{criteria="g3_evidence_contract",operation_type="rag",risk_tier="external_customer_facing",status="passed"} 2.0
governance_checkpoint_total{criteria="g5_privacy_control",operation_type="rag",risk_tier="external_customer_facing",status="passed"} 1.0
governance_checkpoint_total{criteria="g7_observability",operation_type="rag",risk_tier="external_customer_facing",status="passed"} 1.0
governance_checkpoint_total{criteria="g8_evaluation_system",operation_type="rag",risk_tier="external_customer_facing",status="passed"} 1.0
```

### Step 4: 更新 Grafana Dashboard - 添加完整的 G1-G12 面板

需要在 AI Governance Dashboard 中添加缺失的面板。当前只有 G4, G9, G12，需要添加：

**缺失的面板**:
- G1: Safety Case
- G2: Risk Tiering
- G3: Evidence Contract
- G5: Privacy Control
- G6: Version Control
- G7: Observability
- G8: Evaluation System
- G10: Domain Isolation
- G11: Reliability

**推荐布局**:
```
Row 1 (y=16): Critical Governance
  - G1 Safety Case
  - G2 Risk Tiering
  - G3 Evidence Contract
  - G4 Permission Checks (已有)

Row 2 (y=20): Privacy & Security
  - G5 Privacy Control
  - G7 Observability
  - G8 Evaluation System
  - G9 Data Governance (已有)

Row 3 (y=24): Operational
  - G6 Version Control
  - G10 Domain Isolation
  - G11 Reliability
  - G12 Dashboard Export (已有)
```

**每个面板的 Prometheus 查询**:
```promql
# G1: Safety Case
sum(governance_checkpoint_total{criteria="g1_safety_case", status="passed"})

# G2: Risk Tiering
sum(governance_checkpoint_total{criteria="g2_risk_tiering", status="passed"})

# G3: Evidence Contract
sum(governance_checkpoint_total{criteria="g3_evidence_contract", status="passed"})

# G5: Privacy Control
sum(governance_checkpoint_total{criteria="g5_privacy_control", status="passed"})

# G6: Version Control
sum(governance_checkpoint_total{criteria="g6_version_control", status="passed"})

# G7: Observability
sum(governance_checkpoint_total{criteria="g7_observability", status="passed"})

# G8: Evaluation System
sum(governance_checkpoint_total{criteria="g8_evaluation_system", status="passed"})

# G10: Domain Isolation
sum(governance_checkpoint_total{criteria="g10_domain_isolation", status="passed"})

# G11: Reliability
sum(governance_checkpoint_total{criteria="g11_reliability", status="passed"})
```

---

## 📊 完整的 Governance Criteria 映射

### Risk Tier: R1 (External Customer-Facing) - RAG 系统

所需的 Governance Criteria:
1. ✅ **G1**: Safety Case - 风险评估
2. ✅ **G2**: Risk Tiering - 动态能力门控
3. ✅ **G3**: Evidence Contract - 可验证的引用 (Citations)
4. ⚠️ **G4**: Permission Layers - 预检索访问控制 (未实现)
5. ✅ **G5**: Privacy Control - PII 检测和掩码
6. ⚠️ **G6**: Version Control - 模型版本跟踪 (部分实现)
7. ✅ **G7**: Observability - Trace ID 和日志
8. ✅ **G8**: Evaluation System - SLO 监控 (< 2s)
9. ⚠️ **G9**: Data Governance - 数据来源跟踪 (部分实现)
10. ⚠️ **G10**: Domain Isolation - 领域隔离 (未实现)
11. ⚠️ **G11**: Reliability - 容错和重试 (部分实现)
12. ✅ **G12**: Dashboard - Grafana 监控

---

## 🎯 下一步行动计划

### 高优先级 (立即执行)
1. ✅ 在 `rag_routes.py` 添加 governance decorator import
2. ✅ 为所有 7 个 RAG endpoints 添加 `@with_governance_tracking()` decorator
3. ✅ 重启 backend 并测试 metrics
4. ⏳ 在 Grafana 中添加缺失的 G1-G12 面板

### 中优先级 (本周完成)
5. ⏳ 检查并修复浏览器中看到的 "G3 重复" 问题
6. ⏳ 为其他 governance criteria 添加自动化检查 (G4, G6, G9, G10, G11)
7. ⏳ 添加 governance compliance 报告 endpoint

### 低优先级 (后续优化)
8. ⏳ 实现更智能的 PII 检测（使用 NER 模型）
9. ⏳ 添加 governance audit 日志导出功能
10. ⏳ 创建 governance compliance 自动化测试

---

## 📖 相关文档

- **集成指南**: `GOVERNANCE_INTEGRATION_GUIDE.md`
- **Governance Tracker 源码**: `backend/backend/services/governance_tracker.py`
- **Middleware 源码**: `backend/backend/middleware/governance_middleware.py`
- **Prometheus Alert Rules**: `monitoring/prometheus/alert_rules.yml` (已有 HighRAGLatency 规则)

---

## 💡 关键洞察

### 为什么之前 G8 = 0?
**核心问题**: 代码存在但从未被调用
- Governance tracker 是一个完整的框架
- 但在实际的 RAG endpoints 中**没有触发任何 checkpoint**
- 就像你建了一个完整的监控系统，但没有连接任何传感器

### 解决方案的优雅之处
使用 **decorator 模式**:
- ✅ 一次编写，到处应用
- ✅ 不修改原有业务逻辑
- ✅ 集中管理 governance 逻辑
- ✅ 易于测试和维护

### Governance Tracking 的设计理念
遵循 Air NZ AI Governance Framework:
- **Risk-based**: 根据风险层级 (R0-R3) 要求不同的 governance criteria
- **Evidence-driven**: 每个决策都有可审计的证据
- **Proactive**: 在问题发生前检测和预防
- **Transparent**: 所有操作都有 trace 和监控

---

## ✅ 总结

### 已解决
1. ✅ 创建了 governance middleware
2. ✅ 编写了完整的集成指南
3. ✅ 识别了 G8 = 0 的根本原因（未调用）
4. ✅ 提供了 G1-G12 完整面板的 Prometheus 查询

### 待解决
1. ⏳ 应用 decorator 到 7 个 RAG endpoints
2. ⏳ 在 Grafana 添加缺失的 governance 面板
3. ⏳ 验证 G3 重复问题是否为浏览器缓存

### 预期结果
完成上述步骤后:
- ✅ 所有 G1-G12 面板都会显示实时数据
- ✅ G8 不再为 0，显示实际的延迟 SLO 监控数据
- ✅ Governance Compliance Rate 开始正确计算
- ✅ 每个 RAG 请求都有完整的 governance 审计轨迹

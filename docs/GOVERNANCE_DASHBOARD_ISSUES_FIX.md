# AI Governance Dashboard 问题修复指南

## 📊 当前问题总结

根据测试,发现了以下 3 个问题:

### 1. G3 Evidence Contract = 0 (Compliance Rate)

**现象**:
```
ai_governance_checkpoint_total{criteria="g3_evidence_contract",status="failed"} 3.0
ai_governance_compliance_rate{criteria="g3_evidence_contract"} 0.0
```

**根本原因**:
- RAG responses 返回的 `citations` 列表为空或 None
- 在 `governance_tracker.py:303`,如果 `num_citations == 0`,G3 被标记为 "failed"
- Compliance rate 只计算 "passed" 状态

**位置**:
- `backend/backend/services/governance_tracker.py:295-323`
- `backend/backend/routers/rag_routes.py:1336, 1390`

**修复方案**:
确保 RAG response 总是包含 citations。检查为什么 `response.citations` 为空。

### 2. G8 Evaluation System = 0 (Compliance Rate)

**现象**:
```
ai_governance_checkpoint_total{criteria="g8_evaluation_system",status="warning"} 3.0
ai_governance_compliance_rate{criteria="g8_evaluation_system"} 0.0
```

**根本原因**:
- G8 checkpoint 被标记为 "warning" 而不是 "passed"
- 这表明某个评估系统检查失败了 (可能是延迟超过 SLO)
- Compliance rate 只计算 "passed" 状态

**位置**:
需要找到在哪里调用了 G8 checkpoint 并标记为 "warning"

**修复方案**:
1. 查找 `checkpoint_evaluation` 或 G8 相关调用
2. 调整 SLO 阈值或修复导致 warning 的逻辑

### 3. G5 Privacy Control 缺失

**现象**:
- Dashboard 中没有 G5 metrics
- Prometheus 中完全没有 G5 相关的 metrics

**根本原因**:
- `rag_routes.py` 中根本没有调用任何 G5 相关的 checkpoint
- 没有 PII 检测逻辑

**位置**:
`backend/backend/routers/rag_routes.py` - 缺少 G5 调用

**修复方案**:
在 RAG endpoint 中添加 PII 检测和 G5 checkpoint

---

## 🛠️ 修复步骤

### 修复 1: 添加 G5 Privacy Control Checkpoint

在 `backend/backend/routers/rag_routes.py` 的 `/ask-smart` endpoint 中添加 PII 检测:

```python
# After line 1176 (after G4 checkpoint_permission)

# Governance checkpoint: Privacy Control (G5)
# Simple PII detection heuristic
question_lower = request.question.lower()
has_pii = any([
    '@' in question_lower and '.' in question_lower,  # Email
    any(word in question_lower for word in ['phone', 'mobile', 'cell', 'address', 'street']),
    # Add more PII patterns as needed
])

if has_pii:
    governance_tracker.checkpoint_privacy(
        gov_context.trace_id,
        pii_detected=True,
        pii_masked=False,  # We're not masking yet, just detecting
        details="Potential PII detected in query"
    )
else:
    governance_tracker.checkpoint_privacy(
        gov_context.trace_id,
        pii_detected=False,
        pii_masked=False,
        details="No PII detected"
    )
```

### 修复 2: 确保 G3 Evidence Contract 通过

**选项 A**: 确保 RAG responses 总是包含 citations

检查为什么 `response.citations` 为空。可能的原因:
1. RAG pipeline 没有生成 citations
2. Citations 字段命名不一致
3. Cache hit 路径没有保留 citations

**选项 B**: 放宽 G3 要求 (不推荐)

如果 citations 确实不可用,可以修改 `governance_tracker.py:302-309`:
```python
# For R1 operations, citations are RECOMMENDED (not strictly REQUIRED)
if context.risk_tier == RiskTier.R1:
    if num_citations == 0:
        context.add_checkpoint(
            GovernanceCriteria.G3_EVIDENCE_CONTRACT,
            "warning",  # Changed from "failed" to "warning"
            "No citations provided (RECOMMENDED for R1)",
            {"num_citations": num_citations}
        )
```

### 修复 3: 修复 G8 Evaluation System

需要找到 G8 checkpoint 的调用位置。搜索:
```bash
grep -rn "G8_EVALUATION_SYSTEM\|checkpoint_evaluation" backend/backend/
```

如果 G8 是因为延迟 SLO 失败:
1. 调整 SLO 阈值 (当前可能是 2 秒)
2. 优化 RAG pipeline 性能
3. 或将 "warning" 状态也计入 compliance rate

---

## 📝 需要添加的 Checkpoint 方法

如果 `governance_tracker.py` 中没有 `checkpoint_privacy` 方法,需要添加:

```python
def checkpoint_privacy(self, trace_id: str, pii_detected: bool, pii_masked: bool, details: str = ""):
    """Record privacy control checkpoint (G5)"""
    context = self.active_contexts.get(trace_id)
    if not context:
        return

    if pii_detected and not pii_masked:
        context.add_checkpoint(
            GovernanceCriteria.G5_PRIVACY_CONTROL,
            "warning",
            f"PII detected but not masked: {details}",
            {"pii_detected": pii_detected, "pii_masked": pii_masked}
        )
    elif pii_detected and pii_masked:
        context.add_checkpoint(
            GovernanceCriteria.G5_PRIVACY_CONTROL,
            "passed",
            f"PII detected and masked: {details}",
            {"pii_detected": pii_detected, "pii_masked": pii_masked}
        )
    else:
        context.add_checkpoint(
            GovernanceCriteria.G5_PRIVACY_CONTROL,
            "passed",
            "No PII detected",
            {"pii_detected": pii_detected}
        )
```

---

## ✅ 验证修复

修复后,运行测试脚本验证:

```bash
python scripts/test_governance_tracking.py
```

预期结果:
```
G3 Evidence Contract: ✅ Found (status="passed")
G5 Privacy Control: ✅ Found
G8 Evaluation System: ✅ Found (status="passed" or acceptable)

ai_governance_compliance_rate{criteria="g3_evidence_contract"} 1.0
ai_governance_compliance_rate{criteria="g5_privacy_control"} 1.0
ai_governance_compliance_rate{criteria="g8_evaluation_system"} 1.0
```

然后刷新 Grafana dashboard:
http://localhost:3000/d/ai-governance-dashboard/ai-governance-dashboard?orgId=1&refresh=10s

---

## 🎯 总结

| 问题 | 根因 | 修复 |
|------|------|------|
| G3 = 0 | `num_citations == 0` 导致 "failed" | 确保 citations 存在,或放宽要求为 "warning" |
| G8 = 0 | 某个检查标记为 "warning" | 找到 G8 调用,修复 warning 原因 |
| G5 缺失 | 没有调用 G5 checkpoint | 添加 PII 检测和 `checkpoint_privacy` 调用 |

优先级: **G5 > G3 > G8**

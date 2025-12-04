# AI Governance Checkpoints Implementation Guide

**Created:** 2025-12-04
**Status:** ✅ Implemented

---

## 🎯 Overview

This guide covers the implementation of the three missing governance checkpoints (G4, G9, G12) for the AI-Louie system. These checkpoints ensure comprehensive AI governance compliance at the R1 (external_customer_facing) risk tier.

---

## 📋 Implemented Checkpoints

### 1. G4 Permission Layers (User Authorization)

**Purpose:** Verify user permissions and access control for AI operations.

**Implementation:**
- 3-tier permission model: `public` | `internal` | `admin`
- Default: All RAG queries start with `public` role
- Future: Extract user role from authentication token

**Code Location:**
- [`governance_tracker.py:346-372`](backend/backend/services/governance_tracker.py#L346-L372) - `checkpoint_permission()` method
- [`rag_routes.py:1168-1175`](backend/backend/routers/rag_routes.py#L1168-L1175) - Permission checkpoint call

**Usage:**
```python
governance_tracker.checkpoint_permission(
    trace_id=trace_id,
    user_role="public",  # Or "internal" / "admin"
    authorized=True,
    required_permissions=["rag:query"]
)
```

**Metrics:**
- `ai_governance_checkpoint_total{criteria="g4_permission_layers",status="passed|failed"}`

---

### 2. G9 Data Governance (Data Source & Compliance)

**Purpose:** Track data lineage, quality, and compliance status.

**Validates:**
1. **Data source lineage** - Where data comes from
2. **Data quality score** - Quality metrics (0.0-1.0)
3. **Compliance status** - GDPR, retention policies, etc.

**Implementation:**
- Approved data sources: `assessment_docs_minilm`, `knowledge_base`, `documents`
- Compliance threshold: quality_score ≥ 0.7
- Status: `passed` if all sources approved and compliant

**Code Location:**
- [`governance_tracker.py:374-409`](backend/backend/services/governance_tracker.py#L374-L409) - `checkpoint_data_governance()` method
- [`rag_routes.py:1177-1184`](backend/backend/routers/rag_routes.py#L1177-L1184) - Data governance checkpoint call

**Usage:**
```python
governance_tracker.checkpoint_data_governance(
    trace_id=trace_id,
    data_sources=["assessment_docs_minilm"],
    compliance_status="compliant",
    data_quality_score=1.0
)
```

**Metrics:**
- `ai_governance_checkpoint_total{criteria="g9_data_governance",status="passed|warning"}`
- Includes metadata: `data_sources`, `compliance_status`, `data_quality_score`

---

### 3. G12 Dashboard (Metrics Export)

**Purpose:** Confirm operational metrics are exported to monitoring dashboard (Grafana/Prometheus).

**Implementation:**
- Automatic Prometheus metrics export on each checkpoint
- Dashboard type: `grafana` (default)
- Metrics endpoint: `/metrics` (FastAPI Prometheus integration)

**Code Location:**
- [`governance_tracker.py:411-436`](backend/backend/services/governance_tracker.py#L411-L436) - `checkpoint_dashboard()` method
- [`rag_routes.py:1186-1192`](backend/backend/routers/rag_routes.py#L1186-L1192) - Dashboard checkpoint call
- [`metrics.py:3-29`](backend/backend/services/metrics.py#L3-L29) - Prometheus metrics definitions

**Usage:**
```python
governance_tracker.checkpoint_dashboard(
    trace_id=trace_id,
    metrics_exported=True,
    dashboard_type="grafana"
)
```

**Prometheus Metrics:**
```
# Checkpoint counter
ai_governance_checkpoint_total{criteria="g12_dashboard",status="passed|warning"}

# Operation counter
ai_governance_operation_total{operation_type="rag",risk_tier="external_customer_facing"}

# Latency histogram
ai_governance_latency_seconds{operation_type="rag",risk_tier="external_customer_facing"}

# Compliance gauge
ai_governance_compliance_rate{criteria="g12_dashboard",risk_tier="external_customer_facing"}
```

---

## 📊 Grafana Dashboard Integration

### Accessing Metrics

**Prometheus Endpoint:**
```
http://localhost:8888/metrics
```

**Sample Queries:**

1. **Checkpoint Success Rate:**
```promql
sum(rate(ai_governance_checkpoint_total{status="passed"}[5m])) by (criteria)
/
sum(rate(ai_governance_checkpoint_total[5m])) by (criteria)
```

2. **Operation Latency (P95):**
```promql
histogram_quantile(0.95, rate(ai_governance_latency_seconds_bucket[5m])) by (operation_type)
```

3. **Permission Check Failures:**
```promql
sum(ai_governance_checkpoint_total{criteria="g4_permission_layers",status="failed"})
```

4. **Data Governance Warnings:**
```promql
sum(ai_governance_checkpoint_total{criteria="g9_data_governance",status="warning"})
```

### Importing the Dashboard

1. **Copy the dashboard JSON:**
   ```bash
   cat monitoring/grafana-ai-governance-dashboard.json
   ```

2. **In Grafana UI:**
   - Navigate to **Dashboards** → **Import**
   - Paste the JSON or upload the file
   - Select your Prometheus data source
   - Click **Import**

3. **Dashboard Features:**
   - ✅ Real-time governance checkpoint monitoring
   - ✅ Compliance rate gauges for each criteria (G1-G12)
   - ✅ Operation latency histograms by risk tier
   - ✅ Permission check status (G4)
   - ✅ Data governance compliance (G9)
   - ✅ Metrics export confirmation (G12)

---

## 🧪 Testing

### 1. Test All Checkpoints

```bash
# Make a RAG query to trigger all checkpoints
curl -X POST http://localhost:8888/api/rag/ask-smart \
  -H "Content-Type: application/json" \
  -d '{"question":"Who wrote Pride and Prejudice?","top_k":3}' | jq '.governance_context'
```

**Expected Output:**
```json
{
  "active_criteria": [
    "g1_safety_case",
    "g2_risk_tiering",
    "g3_evidence_contract",
    "g4_permission_layers",    // ✅ NEW
    "g6_version_control",
    "g7_observability",
    "g8_evaluation_system",
    "g9_data_governance",      // ✅ NEW
    "g10_domain_isolation",
    "g11_reliability",
    "g12_dashboard"            // ✅ NEW
  ],
  "total_checkpoints": 12,     // Was 9, now 12
  "passed_checkpoints": 12,
  "failed_checkpoints": 0,
  "warnings": 0
}
```

### 2. Check Prometheus Metrics

```bash
# View all governance metrics
curl -s http://localhost:8888/metrics | grep ai_governance

# Expected output includes:
# ai_governance_checkpoint_total{criteria="g4_permission_layers",status="passed",risk_tier="external_customer_facing"} 1
# ai_governance_checkpoint_total{criteria="g9_data_governance",status="passed",risk_tier="external_customer_facing"} 1
# ai_governance_checkpoint_total{criteria="g12_dashboard",status="passed",risk_tier="external_customer_facing"} 1
# ai_governance_operation_total{operation_type="rag",risk_tier="external_customer_facing"} 1
# ai_governance_latency_seconds_bucket{operation_type="rag",risk_tier="external_customer_facing",le="1.0"} 1
```

### 3. Verify Grafana Dashboard

1. Open Grafana: `http://localhost:3000` (if you have Grafana running)
2. Navigate to **AI Governance Dashboard**
3. Verify panels show data:
   - ✅ G4 Permission Checks counter
   - ✅ G9 Data Governance status
   - ✅ G12 Dashboard metrics export confirmation
   - ✅ Compliance rate gauges show 100% for all criteria

---

## 🔧 Configuration

### Environment Variables

```bash
# Optional: Override data governance approved sources
export GOVERNANCE_APPROVED_SOURCES="assessment_docs_minilm,knowledge_base,documents"

# Optional: Set data quality threshold
export GOVERNANCE_DATA_QUALITY_THRESHOLD="0.7"

# Optional: Dashboard type
export GOVERNANCE_DASHBOARD_TYPE="grafana"  # or "prometheus", "custom"
```

### Adding New Permission Roles

Edit [`governance_tracker.py`](backend/backend/services/governance_tracker.py):

```python
# Add new role
def checkpoint_permission(self, trace_id: str, user_role: str = "public", ...):
    """
    Permission roles:
    - public: Read-only access to public documents
    - internal: Access to internal documentation
    - admin: Full access including sensitive data
    - contractor: Limited access to specific collections  # ← NEW ROLE
    """
```

---

## 📈 Monitoring Best Practices

### 1. Set Up Alerts

**Grafana Alert: Permission Failures**
```yaml
- alert: HighPermissionFailures
  expr: rate(ai_governance_checkpoint_total{criteria="g4_permission_layers",status="failed"}[5m]) > 0.1
  for: 5m
  annotations:
    summary: "High rate of permission check failures"
```

**Grafana Alert: Data Governance Warnings**
```yaml
- alert: DataGovernanceIssues
  expr: sum(ai_governance_checkpoint_total{criteria="g9_data_governance",status="warning"}) > 10
  for: 10m
  annotations:
    summary: "Multiple data governance warnings detected"
```

### 2. Regular Compliance Reviews

- Weekly: Review compliance rate trends in Grafana
- Monthly: Audit permission check logs
- Quarterly: Update approved data sources list

---

## 🚀 Next Steps

### Future Enhancements

1. **G4 Permission Layers:**
   - Integrate with OAuth/JWT for real user authentication
   - Implement role-based access control (RBAC)
   - Add API key validation for external API access

2. **G9 Data Governance:**
   - Automatic data quality scoring based on retrieval metrics
   - Integration with data cataloging tools
   - GDPR compliance auto-checks (PII detection)

3. **G12 Dashboard:**
   - Custom dashboard templates for different risk tiers
   - Real-time alerting integration (PagerDuty, Slack)
   - Compliance report generation

---

## 📚 Related Documentation

- [AI Governance Framework](docs/CONSOLIDATED/AI_GOVERNANCE_FRAMEWORK.md)
- [Bandit Auto-Loading](docs/BANDIT_AUTO_WARMUP.md)
- [Prometheus Metrics](backend/backend/services/metrics.py)
- [Grafana Dashboard JSON](monitoring/grafana-ai-governance-dashboard.json)

---

**Version:** 1.0
**Last Updated:** 2025-12-04
**Maintainer:** AI Team

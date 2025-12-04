# AI Governance Integration

## Overview

AI-Louie now includes a comprehensive AI governance framework inspired by aviation safety standards and the Air NZ AI Governance Platform. This integration provides real-time governance tracking, risk tier classification, and compliance monitoring for all AI operations.

## 🎯 Key Features

### 1. Risk Tier Classification (R0-R3)

Every AI operation is automatically classified into one of four risk tiers:

| Tier | Classification | Use Cases | Controls |
|------|---------------|-----------|----------|
| **🟢 R0** | Low Risk Internal | Code generation, statistics | Minimal controls, optional citations |
| **🟡 R1** | Customer Facing | RAG Q&A, chat agents | **Citations REQUIRED**, evidence validation, audit trails |
| **🟠 R2** | Decision Support | Operations support (future) | All R1 controls + human approval |
| **🔴 R3** | Automated Actions | Closed-loop automation (future) | All R2 controls + dual control + rollback |

**Current AI-Louie Mapping:**
- RAG Q&A Mode → **R1** (Customer-facing, citations required)
- Chat Agent Mode → **R1** (Customer-facing, citations required)
- Code Generation → **R0** (Internal productivity)
- Statistics Mode → **R0** (Internal analysis)

### 2. Governance Criteria (G1-G12)

Twelve governance criteria are tracked for each operation:

1. **G1 - AI Safety Case**: Hazard identification and risk assessment
2. **G2 - Risk Tiering**: Dynamic capability gates per risk tier
3. **G3 - Evidence Contract**: Verifiable citations with quality checks
4. **G4 - Permission Layers**: Pre-retrieval access control
5. **G5 - Privacy Control**: PII detection and masking (future)
6. **G6 - Version Control**: Model/prompt/policy versioning
7. **G7 - Observability**: Full audit trail with trace IDs
8. **G8 - Evaluation System**: SLO monitoring (latency < 2s for R1)
9. **G9 - Data Governance**: Quality and lineage tracking
10. **G10 - Domain Isolation**: Retrieval routing and filtering
11. **G11 - Reliability**: Circuit breakers and fallbacks
12. **G12 - Dashboard**: Operational governance visibility

### 3. Real-Time Governance Tracking

Every operation generates a unique `trace_id` and tracks governance checkpoints:

```
Operation Flow:
┌─────────────────────────────────────────────────────┐
│ 1. Start Operation (assign risk tier, create trace)│
├─────────────────────────────────────────────────────┤
│ 2. Policy Gate Check (G2)                          │
├─────────────────────────────────────────────────────┤
│ 3. Retrieval (G10 - Domain Isolation)              │
├─────────────────────────────────────────────────────┤
│ 4. Evidence Validation (G3 - Citations Required)   │
├─────────────────────────────────────────────────────┤
│ 5. LLM Generation (G6 - Version Control)           │
├─────────────────────────────────────────────────────┤
│ 6. Quality Check (G8 - SLO Monitoring)             │
├─────────────────────────────────────────────────────┤
│ 7. Audit Logging (G7 - Observability)              │
├─────────────────────────────────────────────────────┤
│ 8. Reliability Check (G11 - Circuit Breakers)      │
├─────────────────────────────────────────────────────┤
│ 9. Complete Operation (attach governance context)  │
└─────────────────────────────────────────────────────┘
```

### 4. Visual Governance Display

The UI displays governance status for every operation:

**Governance Status Panel:**
```
🛡️ AI Governance Status
━━━━━━━━━━━━━━━━━━━━━━━━━━
Risk Tier: 🟡 R1 - Customer Facing
Trace ID: abc12345...

Active Governance Controls:
✅ G1 Safety Case: Safety case activated: rag_external_customer_facing
✅ G2 Risk Tiering: Risk tier assigned: external_customer_facing
✅ G3 Evidence Contract: Evidence validated: 2 citation(s) - good
✅ G6 Version Control: Response generated: model=gpt-4o-mini, prompt=v1.0
✅ G7 Observability: Audit trail: logged (trace_id: abc12345...)
✅ G8 Evaluation System: Latency: 1234ms (SLO: <2000ms) - ✓
✅ G9 Data Governance: Retrieved 3 chunks from 1 collection(s)
✅ G11 Reliability: Smart RAG completed successfully: Hybrid RAG

Checkpoints: 8/8 passed
```

### 5. Governance Framework Info

Users can view the complete governance framework by clicking "📖 View Governance Framework" in the sidebar, which explains:
- Risk tier definitions
- Governance criteria descriptions
- Why governance matters (transparency, trust, compliance)
- Traceability and safety features

## 🏗️ Architecture

### Backend Components

#### 1. Governance Tracker Service
**File:** `backend/backend/services/governance_tracker.py`

Core service that:
- Assigns risk tiers to operations
- Tracks governance checkpoints
- Generates governance context summaries
- Provides trace IDs for full observability

**Key Classes:**
- `RiskTier`: Enum for R0-R3 classification
- `GovernanceCriteria`: Enum for G1-G12 criteria
- `GovernanceContext`: Context object with checkpoints
- `GovernanceTracker`: Main tracking service

**Usage Example:**
```python
from backend.services.governance_tracker import get_governance_tracker

# Start tracking
tracker = get_governance_tracker()
gov_context = tracker.start_operation(
    operation_type="rag",
    metadata={"question": "What is...?"}
)

# Add checkpoints
tracker.checkpoint_policy_gate(gov_context.trace_id, allowed=True, reason="...")
tracker.checkpoint_retrieval(gov_context.trace_id, num_chunks=5)
tracker.checkpoint_evidence(gov_context.trace_id, num_citations=2)
tracker.checkpoint_generation(gov_context.trace_id, model="gpt-4o-mini")
tracker.checkpoint_quality(gov_context.trace_id, latency_ms=1200)
tracker.checkpoint_audit(gov_context.trace_id, audit_logged=True)

# Complete and attach to response
tracker.complete_operation(gov_context.trace_id)
response.governance_context = gov_context.get_summary()
```

#### 2. Enhanced RAG Response Schema
**File:** `backend/backend/models/rag_schemas.py`

Added `governance_context` field to `RAGResponse`:
```python
class RAGResponse(BaseModel):
    # ... existing fields ...
    governance_context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="AI Governance context including risk tier, criteria, and checkpoints"
    )
```

#### 3. RAG Routes Integration
**File:** `backend/backend/routers/rag_routes.py`

- Import governance tracker
- Start governance tracking at operation start
- Add checkpoints throughout RAG pipeline
- Complete governance tracking and attach to response
- Handle failures gracefully

### Frontend Components

#### 1. Governance Display Components
**File:** `frontend/components/governance_display.py`

Provides UI components for displaying governance information:
- `display_governance_status()`: Shows governance panel with risk tier and active controls
- `display_governance_checkpoints()`: Shows detailed checkpoint log
- `display_governance_flowchart()`: Displays Mermaid flowcharts (future)
- `show_governance_info()`: Complete governance framework documentation

#### 2. Frontend Integration
**File:** `frontend/app.py`

- Import governance display components
- Display governance status after RAG responses
- Add "View Governance Framework" button in sidebar
- Modal for governance info display

### Governance Assets

#### Flowcharts
**Location:** `docs/governance/diagrams/`

Copied from Air NZ AI Governance project:
- `flow_r1_oscar_chatbot.png`: R1 (Customer-facing) flow
- `flow_r2_disruption_management.png`: R2 (Decision support) flow
- `flow_r3_maintenance_automation.png`: R3 (Automated actions) flow
- `flow_Cross_Risk_Tier-Complete_Governance_Coverage_Matrix.png`: Complete matrix

Each flowchart shows the complete governance flow with all G1-G12 checkpoints.

## 📊 SLO Targets

### R1 (Customer-Facing) - RAG Q&A
- **Latency**: < 2000ms (2 seconds) for 95th percentile
- **Citation Coverage**: ≥ 95% of answers must have citations
- **Evidence Quality**: ≥ 1 citation AND ≥ 1 retrieved chunk
- **Cache Hit Rate**: > 30% for repeated queries
- **Confidence Score**: ≥ 0.7 for answers

### R0 (Internal Productivity) - Code Generation
- **Latency**: < 5000ms (5 seconds)
- **Test Pass Rate**: ≥ 80% of generated code passes tests
- **Error Rate**: < 10% syntax/import errors

## 🔍 Monitoring & Observability

### Trace IDs
Every operation gets a unique UUID trace_id for:
- End-to-end request tracking
- Debugging failed operations
- Audit trail reconstruction
- Performance analysis

### Governance Logs
Backend logs all governance checkpoints:
```
INFO: Started governance tracking: abc123... - rag - external_customer_facing
INFO: Governance checkpoint: g2_risk_tiering - passed - Policy gate: R1 policy allows RAG queries
INFO: Governance checkpoint: g10_domain_isolation - passed - Retrieved 3 chunks from 1 collection(s)
INFO: Governance checkpoint: g3_evidence_contract - passed - Evidence validated: 2 citation(s)
INFO: Completed governance tracking: abc123... - 8 checkpoints
```

### Metrics Collection
- Total checkpoints per operation
- Passed/failed/warning checkpoint counts
- Average governance overhead (latency impact)
- SLO compliance rates

## 🚀 Future Enhancements

### Near-Term (Next Sprint)
1. **Code Generation Governance** (R0)
   - Track code generation operations
   - Monitor test pass rates
   - Version control for prompts

2. **Chat Agent Governance** (R1)
   - Full governance tracking for chat agents
   - Multi-turn conversation tracing
   - Citation validation for chat responses

### Medium-Term
1. **Policy Engine Integration**
   - Enforce capability gates (tool invocation, write operations)
   - Block operations that violate risk tier policies
   - Version control for policies with approval workflows

2. **Evidence Contract Enhancement**
   - SHA-256 hashing for citation verification
   - Document version tracking
   - Effective date validation

3. **Access Control**
   - Pre-retrieval filtering by user role
   - Multi-dimensional permissions (role, domain, sensitivity)
   - Prevent "see first then mask" leakage

### Long-Term
1. **Safety Case Registry**
   - Define hazards for each use case
   - Document controls and residual risks
   - Shutdown strategies

2. **Advanced SLO Monitoring**
   - Real-time compliance dashboards
   - Violation alerts and notifications
   - Automated remediation triggers

3. **R2/R3 Support**
   - Human approval workflows
   - Dual control mechanisms
   - Rollback capabilities
   - Audit replay functionality

## 📖 Usage Guide

### For Users

1. **Viewing Governance Status**
   - After any RAG query, scroll down to see "🛡️ AI Governance Status"
   - Expand to see detailed checkpoints
   - Risk tier is displayed at the top

2. **Understanding Risk Tiers**
   - 🟢 R0 = Internal tools (code, stats) - relaxed controls
   - 🟡 R1 = Customer-facing (RAG, chat) - citations required
   - Each tier has specific governance requirements

3. **Learning About Governance**
   - Click "📖 View Governance Framework" in sidebar
   - Read about risk tiers and governance criteria
   - Understand why governance matters

### For Developers

1. **Adding Governance to New Operations**
```python
# Start tracking
tracker = get_governance_tracker()
gov_context = tracker.start_operation(
    operation_type="code",  # or "rag", "chat", "statistics"
    metadata={"request": "details"}
)

try:
    # Your operation logic here
    # Add checkpoints as appropriate
    tracker.checkpoint_policy_gate(gov_context.trace_id, allowed=True, reason="...")

    # On success
    tracker.complete_operation(gov_context.trace_id)
    response.governance_context = gov_context.get_summary()
except Exception as e:
    # On failure
    tracker.checkpoint_reliability(
        gov_context.trace_id,
        status="failed",
        message=f"Operation failed: {str(e)}"
    )
    tracker.complete_operation(gov_context.trace_id)
    raise
```

2. **Customizing Governance Criteria**
   - Edit `RISK_TIER_CRITERIA` in `governance_tracker.py`
   - Add/remove criteria as needed
   - Update SLO targets in `checkpoint_quality()`

3. **Adding New Checkpoints**
   - Define new checkpoint method in `GovernanceTracker`
   - Call from operation code at appropriate points
   - Update frontend display if needed

## 🧪 Testing

### Manual Testing
1. Start services: `docker-compose up`
2. Open UI: http://localhost:8501
3. Enter RAG mode and ask a question
4. Verify governance status panel appears
5. Check trace_id in logs

### Automated Testing (Future)
- Unit tests for `governance_tracker.py`
- Integration tests for RAG endpoints
- E2E tests for UI display
- SLO compliance tests

## 📚 References

- **Air NZ AI Governance Platform**: `/Users/yilu/Documents/demo/airnz-ai-governance`
- **Governance Criteria Documentation**: `docs/governance/diagrams/`
- **Risk Tier Definitions**: Based on aviation SMS (Safety Management System) standards
- **Thompson Sampling**: Multi-armed bandit algorithm for Smart RAG strategy selection

## 🤝 Contributing

When adding new features:
1. Determine appropriate risk tier (R0-R3)
2. Identify applicable governance criteria (G1-G12)
3. Add governance tracking to backend
4. Update frontend display components
5. Document governance requirements
6. Update SLO targets if needed

---

**Version**: 1.0 (MVP)
**Last Updated**: 2025-12-04
**Status**: ✅ Active (RAG operations only)
**Next Steps**: Extend to Code and Chat operations

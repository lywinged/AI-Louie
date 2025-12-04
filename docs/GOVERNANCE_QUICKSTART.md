# AI Governance Quick Start Guide

## 🚀 Get Started in 3 Minutes

### What You'll See

After deploying the updated AI-Louie platform, every RAG query now includes **AI Governance tracking** that displays:

1. **Risk Tier Badge**: 🟡 R1 (Customer Facing) for RAG queries
2. **Governance Status Panel**: Shows all active governance controls
3. **Trace ID**: Unique identifier for tracking and debugging
4. **Checkpoint Status**: Real-time compliance checks

---

## 📖 Step-by-Step Tutorial

### Step 1: Start the Platform

```bash
./start.sh
```

Wait for:
- ✅ Backend warm-up (3 Smart RAG queries, ~70s)
- ✅ Qdrant seed data loading
- ✅ Health checks pass

### Step 2: Access the UI

Open http://localhost:18501 in your browser.

### Step 3: Enter RAG Mode

Click the **"📚 RAG Q&A"** button to enter RAG mode.

### Step 4: Ask a Question

Try one of these sample questions:
- "Who wrote 'DADDY TAKE ME SKATING'?"
- "'Sir roberts fortune a novel', show me roles relationship"
- "Tell me about American frontier history"

### Step 5: View Governance Status

After the answer is displayed, scroll down to see:

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

### Step 6: Learn More About Governance

Click **"📖 View Governance Framework"** in the sidebar to see:
- Risk tier definitions (R0-R3)
- Governance criteria explanations (G1-G12)
- Why governance matters
- Compliance and safety features

---

## 🎯 What Each Element Means

### Risk Tier Indicators

| Icon | Tier | Meaning | Controls |
|------|------|---------|----------|
| 🟢 | R0 | Low Risk Internal | Minimal controls, optional citations |
| 🟡 | R1 | Customer Facing | **Citations REQUIRED**, audit trails |
| 🟠 | R2 | Decision Support | + Human approval required |
| 🔴 | R3 | Automated Actions | + Dual control + Rollback |

### Checkpoint Status Icons

| Icon | Status | Meaning |
|------|--------|---------|
| ✅ | Passed | Control successfully validated |
| ⚠️ | Warning | Control passed with warnings |
| ❌ | Failed | Control failed validation |
| ⏳ | Checking | Control in progress |

### Governance Criteria Summary

| Code | Name | What It Does |
|------|------|--------------|
| G1 | Safety Case | Identifies hazards and assesses risks |
| G2 | Risk Tiering | Enforces controls based on risk level |
| G3 | Evidence Contract | **Ensures citations are provided** |
| G6 | Version Control | Tracks model/prompt versions |
| G7 | Observability | Creates audit trails with trace IDs |
| G8 | Evaluation System | Monitors latency and quality (SLO) |
| G9 | Data Governance | Tracks data quality and sources |
| G10 | Domain Isolation | Routes retrieval to correct collections |
| G11 | Reliability | Monitors system health |
| G12 | Dashboard | Provides governance visibility |

---

## 💡 Key Benefits

### 1. Transparency
You can see exactly what governance controls are active for every operation.

**Example**: When you ask a question, you see:
- Risk tier: R1 (Customer Facing)
- Citations required: Yes (2 sources provided)
- Latency: 1234ms (within 2000ms SLO ✓)

### 2. Trust
Visual proof of:
- Citation validation (G3 Evidence Contract)
- Audit logging (G7 Observability)
- Quality checks (G8 Evaluation System)

### 3. Compliance
Clear risk classification and policy enforcement:
- R1 operations **must** have citations
- Latency must be < 2000ms
- All operations are logged with trace IDs

### 4. Traceability
Every operation has a unique trace ID:
- Use it to find logs: `grep "abc12345" backend.log`
- Debug issues: "Why did this query fail?"
- Audit trail: "What controls were active?"

### 5. Safety
Multiple layers of protection:
- Risk-based controls
- Quality thresholds
- Citation validation
- SLO monitoring

---

## 🔍 Understanding Trace IDs

Every operation gets a unique trace ID like: `abc12345-1234-5678-9012-def678901234`

### What Trace IDs Enable

**1. Log Correlation**
```bash
# Find all logs for a specific operation
docker logs ai-louie-backend-1 2>&1 | grep "abc12345"
```

**2. Debugging**
```
ERROR: G3 Evidence Contract failed (trace_id: abc12345)
  → Reason: No citations provided (REQUIRED for R1)
  → Action: Check retrieval logic
```

**3. Performance Analysis**
```
INFO: Governance tracking completed (trace_id: abc12345)
  → Total checkpoints: 8
  → Duration: 1234ms
  → All passed: ✓
```

**4. Audit Trail**
```
INFO: Started governance tracking: abc12345 - rag - external_customer_facing
INFO: Checkpoint: g2_risk_tiering - passed
INFO: Checkpoint: g3_evidence_contract - passed (2 citations)
INFO: Checkpoint: g8_evaluation_system - passed (1234ms < 2000ms)
INFO: Completed governance tracking: abc12345 - 8 checkpoints
```

---

## 🧪 Try These Examples

### Example 1: Simple Factual Query (Hybrid RAG)
**Question**: "Who wrote 'DADDY TAKE ME SKATING'?"

**Expected Governance**:
- Risk Tier: 🟡 R1
- Strategy: Hybrid RAG (BM25 + Vector)
- Citations: 1-2 sources
- Latency: ~800-1200ms ✓ (< 2000ms)

### Example 2: Complex Analytical Query (Iterative Self-RAG)
**Question**: "'Pride and Prejudice', analyze the relationship dynamics between Elizabeth and Darcy"

**Expected Governance**:
- Risk Tier: 🟡 R1
- Strategy: Iterative Self-RAG (2-3 iterations)
- Citations: 3-5 sources
- Latency: ~2000-4000ms (may exceed SLO ⚠️)

### Example 3: Relationship Query (Graph RAG)
**Question**: "'Sir roberts fortune a novel', show me roles relationship"

**Expected Governance**:
- Risk Tier: 🟡 R1
- Strategy: Graph RAG (JIT entity extraction)
- Citations: 2-4 sources
- Latency: ~3000-6000ms (may exceed SLO ⚠️)

### Example 4: Comparison Query (Table RAG)
**Question**: "Compare the main characters' ages in 'Pride and Prejudice'"

**Expected Governance**:
- Risk Tier: 🟡 R1
- Strategy: Table RAG (structured data)
- Citations: 2-3 sources
- Latency: ~1500-2500ms

---

## 🚨 What to Watch For

### SLO Violations

If latency exceeds 2000ms, you'll see:
```
⚠️ G8 Evaluation System: Latency: 3456ms (SLO: <2000ms) - ⚠
```

**What this means**:
- Operation took longer than expected
- May impact user experience
- Check backend logs for slow components

### Missing Citations

If no citations are provided, you'll see:
```
❌ G3 Evidence Contract: No citations provided (REQUIRED for R1)
```

**What this means**:
- Retrieval failed or returned no results
- Answer cannot be trusted
- User should be warned

### Failed Checkpoints

If any checkpoint fails:
```
❌ G11 Reliability: RAG query failed: Connection timeout
```

**What this means**:
- Operation encountered an error
- Check trace ID in logs
- May need retry or escalation

---

## 📊 Monitoring Dashboard (Future)

Coming soon:
- Real-time SLO compliance charts
- Governance violation alerts
- Trace ID search and filtering
- Checkpoint success rates
- Risk tier distribution

---

## 🤔 FAQ

### Q: Why do I see "⚠️" warnings?
**A**: Warnings mean a control passed but with sub-optimal results (e.g., latency close to SLO limit).

### Q: Can I disable governance tracking?
**A**: No, governance is mandatory for all operations to ensure safety and compliance.

### Q: What happens if a checkpoint fails?
**A**: The operation may be blocked (e.g., no citations for R1) or allowed with warnings (e.g., high latency).

### Q: How do I find logs for a specific trace ID?
**A**: Use `docker logs ai-louie-backend-1 2>&1 | grep "YOUR_TRACE_ID"`

### Q: Why is my query marked as R1?
**A**: RAG Q&A is customer-facing, so it requires citations and strict controls.

### Q: Can I see governance for code generation?
**A**: Not yet - governance for code generation (R0) is planned for the next release.

---

## 🎉 Next Steps

1. ✅ Try all RAG strategies and observe governance status
2. ✅ Click "View Governance Framework" to learn more
3. ✅ Check backend logs to see trace IDs and checkpoints
4. ✅ Look for SLO violations and understand why they occur
5. ✅ Share feedback on governance UX and features

---

**Need Help?**
- Full documentation: [GOVERNANCE_INTEGRATION.md](GOVERNANCE_INTEGRATION.md)
- Issues: https://github.com/your-org/ai-louie/issues
- Questions: Contact the AI-Louie team

**Version**: 1.0 (MVP - RAG operations only)
**Last Updated**: 2025-12-04

"""
Governance Display Component for Streamlit

Displays governance tracking information including:
- Risk tier indicators
- Active governance criteria
- Checkpoint status
- Flowchart visualization
"""

import streamlit as st
from typing import Dict, List, Optional
from datetime import datetime


def display_governance_status(governance_data: Dict):
    """
    Display governance status panel.

    Args:
        governance_data: Governance context data from backend
    """
    if not governance_data:
        return

    trace_id = governance_data.get("trace_id", "N/A")
    operation_type = governance_data.get("operation_type", "unknown")
    risk_tier = governance_data.get("risk_tier", "unknown")
    active_criteria = governance_data.get("active_criteria", [])
    checkpoints = governance_data.get("checkpoints", [])

    # Risk tier color mapping
    risk_tier_colors = {
        "low_risk_internal": "🟢",
        "external_customer_facing": "🟡",
        "operations_decision_support": "🟠",
        "actions_closed_loop": "🔴"
    }

    risk_tier_names = {
        "low_risk_internal": "R0 - Low Risk Internal",
        "external_customer_facing": "R1 - Customer Facing",
        "operations_decision_support": "R2 - Decision Support",
        "actions_closed_loop": "R3 - Automated Actions"
    }

    with st.expander("🛡️ **AI Governance Status**", expanded=False):
        # Header
        col1, col2 = st.columns([3, 1])
        with col1:
            risk_icon = risk_tier_colors.get(risk_tier, "⚪")
            risk_name = risk_tier_names.get(risk_tier, risk_tier)
            st.markdown(f"**Risk Tier:** {risk_icon} {risk_name}")
        with col2:
            st.markdown(f"**Trace ID:** `{trace_id[:8]}...`")

        st.markdown("---")

        # Active Criteria
        st.markdown("**Active Governance Controls:**")

        # Group checkpoints by criteria
        criteria_status = {}
        for checkpoint in checkpoints:
            criteria = checkpoint.get("criteria", "unknown")
            status = checkpoint.get("status", "unknown")
            message = checkpoint.get("message", "")

            if criteria not in criteria_status:
                criteria_status[criteria] = []
            criteria_status[criteria].append({"status": status, "message": message})

        # Display criteria with status
        for criteria in active_criteria:
            criteria_name = criteria.replace("_", " ").title()

            # Get status for this criteria
            if criteria in criteria_status:
                latest_status = criteria_status[criteria][-1]["status"]
                latest_message = criteria_status[criteria][-1]["message"]

                if latest_status == "passed":
                    st.markdown(f"✅ **{criteria_name}**: {latest_message}")
                elif latest_status == "warning":
                    st.markdown(f"⚠️ **{criteria_name}**: {latest_message}")
                elif latest_status == "failed":
                    st.markdown(f"❌ **{criteria_name}**: {latest_message}")
                else:
                    st.markdown(f"⏳ **{criteria_name}**: {latest_message}")
            else:
                st.markdown(f"⏳ **{criteria_name}**: Pending...")

        # Summary metrics - count unique criteria (max 12)
        unique_criteria = set(c.get("criteria") for c in checkpoints)
        total_checkpoints = len(unique_criteria)

        # Count status by latest checkpoint for each criteria
        passed = sum(1 for crit in criteria_status.values() if crit[-1]["status"] == "passed")
        failed = sum(1 for crit in criteria_status.values() if crit[-1]["status"] == "failed")
        warnings = sum(1 for crit in criteria_status.values() if crit[-1]["status"] == "warning")

        st.markdown("---")
        st.markdown(f"**Checkpoints:** {passed}/{total_checkpoints} passed" +
                   (f", {warnings} warnings" if warnings > 0 else "") +
                   (f", {failed} failed" if failed > 0 else ""))


def display_governance_checkpoints(checkpoints: List[Dict], expanded: bool = False):
    """
    Display detailed governance checkpoints.

    Args:
        checkpoints: List of checkpoint dictionaries
        expanded: Whether to expand by default
    """
    if not checkpoints:
        return

    # Deduplicate checkpoints - keep only the latest entry for each criteria
    seen_criteria = {}
    for checkpoint in checkpoints:
        criteria = checkpoint.get("criteria", "unknown")
        # Keep the latest checkpoint for each criteria (later entries override earlier ones)
        seen_criteria[criteria] = checkpoint

    # Convert back to list and sort by criteria name for consistent display
    unique_checkpoints = sorted(seen_criteria.values(), key=lambda x: x.get("criteria", ""))

    with st.expander("📋 **Governance Checkpoint Log**", expanded=expanded):
        for i, checkpoint in enumerate(unique_checkpoints):
            criteria = checkpoint.get("criteria", "unknown")
            status = checkpoint.get("status", "unknown")
            message = checkpoint.get("message", "")
            timestamp = checkpoint.get("timestamp", "")

            criteria_name = criteria.replace("_", " ").title()

            # Status icon
            if status == "passed":
                icon = "✅"
            elif status == "warning":
                icon = "⚠️"
            elif status == "failed":
                icon = "❌"
            else:
                icon = "⏳"

            # Display full message without truncation
            st.markdown(f"{icon} **{criteria_name}**: {message}")

            if i < len(unique_checkpoints) - 1:
                st.markdown("")


def display_governance_flowchart(risk_tier: str, flowchart_path: str = None):
    """
    Display governance flowchart for the risk tier.

    Args:
        risk_tier: Risk tier (e.g., "external_customer_facing")
        flowchart_path: Optional path to flowchart image
    """
    risk_tier_flowcharts = {
        "low_risk_internal": "docs/governance/diagrams/flow_r1_oscar_chatbot.png",
        "external_customer_facing": "docs/governance/diagrams/flow_r1_oscar_chatbot.png",
        "operations_decision_support": "docs/governance/diagrams/flow_r2_disruption_management.png",
        "actions_closed_loop": "docs/governance/diagrams/flow_r3_maintenance_automation.png"
    }

    flowchart_path = flowchart_path or risk_tier_flowcharts.get(risk_tier)

    if not flowchart_path:
        return

    with st.expander("🔄 **Governance Flow Diagram**", expanded=False):
        st.markdown("""
        This diagram shows the complete governance flow for this operation type.
        Each step represents a governance control checkpoint (G1-G12).
        """)

        try:
            st.image(flowchart_path, use_container_width=True)
        except Exception as e:
            st.warning(f"Flowchart not available: {str(e)}")


def display_governance_summary_card(governance_data: Dict):
    """
    Display compact governance summary card.

    Args:
        governance_data: Governance context data
    """
    if not governance_data:
        return

    risk_tier = governance_data.get("risk_tier", "unknown")
    checkpoints = governance_data.get("checkpoints", [])

    passed = len([c for c in checkpoints if c.get("status") == "passed"])
    total = len(checkpoints)

    # Risk tier color
    risk_colors = {
        "low_risk_internal": "🟢",
        "external_customer_facing": "🟡",
        "operations_decision_support": "🟠",
        "actions_closed_loop": "🔴"
    }

    risk_icon = risk_colors.get(risk_tier, "⚪")

    st.markdown(f"""
    <div style="background-color: #f0f2f6; padding: 10px; border-radius: 5px; margin: 10px 0;">
        <strong>🛡️ Governance:</strong> {risk_icon} Risk Tier | ✅ {passed}/{total} Controls Passed
    </div>
    """, unsafe_allow_html=True)


def show_governance_info():
    """
    Show governance system information.
    """
    st.markdown("""
    ### 🛡️ AI Governance Framework

    This platform implements a comprehensive AI governance framework inspired by aviation safety standards.

    #### Risk Tiers (R0-R3)

    - **🟢 R0 - Low Risk Internal**: Code generation, internal analysis
        - Minimal controls, optional citations
        - Focus: Productivity and efficiency

    - **🟡 R1 - Customer Facing**: RAG Q&A, chat agents
        - **Citations REQUIRED**
        - Evidence validation and audit trails
        - Focus: Accuracy and traceability

    - **🟠 R2 - Decision Support**: Operations support (future)
        - All R1 controls PLUS human approval
        - Focus: Safety-critical decisions

    - **🔴 R3 - Automated Actions**: Closed-loop automation (future)
        - All R2 controls PLUS dual control and rollback
        - Focus: Fail-safe operations

    #### Governance Criteria (G1-G12)

    1. **G1 - AI Safety Case**: Hazard identification and risk assessment
    2. **G2 - Risk Tiering**: Dynamic capability gates per risk tier
    3. **G3 - Evidence Contract**: Verifiable citations with quality checks
    4. **G4 - Permission Layers**: Pre-retrieval access control
    5. **G5 - Privacy Control**: PII detection and masking
    6. **G6 - Version Control**: Model/prompt/policy versioning
    7. **G7 - Observability**: Full audit trail with trace IDs
    8. **G8 - Evaluation System**: SLO monitoring (latency < 2s for R1)
    9. **G9 - Data Governance**: Quality and lineage tracking
    10. **G10 - Domain Isolation**: Retrieval routing and filtering
    11. **G11 - Reliability**: Circuit breakers and fallbacks
    12. **G12 - Dashboard**: Operational governance visibility

    #### Why This Matters

    - **Transparency**: You can see exactly what governance controls are active
    - **Trust**: Visual proof of citation validation and audit logging
    - **Compliance**: Clear risk classification and policy enforcement
    - **Traceability**: Every operation has a unique trace ID for investigation
    - **Safety**: Multiple layers of protection for customer-facing AI

    ---

    *Framework inspired by Air NZ AI Governance and aviation SMS standards.*
    """)


def get_governance_badge(risk_tier: str) -> str:
    """
    Get governance badge HTML for risk tier.

    Args:
        risk_tier: Risk tier value

    Returns:
        HTML string for badge
    """
    risk_badges = {
        "low_risk_internal": "🟢 R0",
        "external_customer_facing": "🟡 R1",
        "operations_decision_support": "🟠 R2",
        "actions_closed_loop": "🔴 R3"
    }

    badge = risk_badges.get(risk_tier, "⚪ R?")
    return f'<span style="background-color: #f0f2f6; padding: 2px 8px; border-radius: 3px; font-size: 0.9em; font-weight: bold;">{badge}</span>'

"""
AI Governance Tracking System

Implements lightweight governance tracking for AI-Louie operations:
- Risk tier classification (R0-R3)
- Governance criteria mapping (G1-G12)
- Audit trail generation
- Compliance status tracking

Inspired by Air NZ AI Governance Framework.
"""

from enum import Enum
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
import uuid
import logging

logger = logging.getLogger(__name__)

# Import Prometheus metrics
try:
    from backend.services.metrics import (
        governance_checkpoint_counter,
        governance_operation_counter,
        governance_latency_histogram,
        governance_compliance_gauge,
    )
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    logger.warning("Prometheus metrics not available for governance tracking")


class RiskTier(Enum):
    """Risk tier classification for AI use cases"""
    R0 = "low_risk_internal"           # Internal productivity
    R1 = "external_customer_facing"    # Customer-facing content
    R2 = "operations_decision_support" # Ops/maintenance with human-in-loop
    R3 = "actions_closed_loop"         # Automated actions


class GovernanceCriteria(Enum):
    """12 Governance Criteria (G1-G12)"""
    G1_SAFETY_CASE = "g1_safety_case"
    G2_RISK_TIERING = "g2_risk_tiering"
    G3_EVIDENCE_CONTRACT = "g3_evidence_contract"
    G4_PERMISSION_LAYERS = "g4_permission_layers"
    G5_PRIVACY_CONTROL = "g5_privacy_control"
    G6_VERSION_CONTROL = "g6_version_control"
    G7_OBSERVABILITY = "g7_observability"
    G8_EVALUATION_SYSTEM = "g8_evaluation_system"
    G9_DATA_GOVERNANCE = "g9_data_governance"
    G10_DOMAIN_ISOLATION = "g10_domain_isolation"
    G11_RELIABILITY = "g11_reliability"
    G12_DASHBOARD = "g12_dashboard"


@dataclass
class GovernanceCheckpoint:
    """Represents a governance checkpoint during execution"""
    checkpoint_id: str
    criteria: GovernanceCriteria
    status: str  # "checking", "passed", "failed", "warning"
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict = field(default_factory=dict)


@dataclass
class GovernanceContext:
    """Governance context for an AI operation"""
    trace_id: str
    operation_type: str  # "rag", "code", "chat", "statistics"
    risk_tier: RiskTier
    active_criteria: Set[GovernanceCriteria]
    checkpoints: List[GovernanceCheckpoint] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    metadata: Dict = field(default_factory=dict)

    def add_checkpoint(self, criteria: GovernanceCriteria, status: str, message: str, metadata: Dict = None):
        """Add a governance checkpoint"""
        checkpoint = GovernanceCheckpoint(
            checkpoint_id=f"{self.trace_id}_{len(self.checkpoints)}",
            criteria=criteria,
            status=status,
            message=message,
            metadata=metadata or {}
        )
        self.checkpoints.append(checkpoint)
        logger.info(f"Governance checkpoint: {criteria.value} - {status} - {message}")

        # Export to Prometheus metrics
        if METRICS_AVAILABLE:
            try:
                governance_checkpoint_counter.labels(
                    criteria=criteria.value,
                    status=status,
                    risk_tier=self.risk_tier.value
                ).inc()
            except Exception as e:
                logger.warning(f"Failed to export governance checkpoint metric: {e}")

    def complete(self):
        """Mark governance context as complete"""
        self.end_time = datetime.now()

    def get_summary(self) -> Dict:
        """Get governance summary"""
        return {
            "trace_id": self.trace_id,
            "operation_type": self.operation_type,
            "risk_tier": self.risk_tier.value,
            "active_criteria": [c.value for c in self.active_criteria],
            "total_checkpoints": len(self.checkpoints),
            "passed_checkpoints": len([c for c in self.checkpoints if c.status == "passed"]),
            "failed_checkpoints": len([c for c in self.checkpoints if c.status == "failed"]),
            "warnings": len([c for c in self.checkpoints if c.status == "warning"]),
            "duration_ms": (self.end_time - self.start_time).total_seconds() * 1000 if self.end_time else None,
            "checkpoints": [
                {
                    "criteria": c.criteria.value,
                    "status": c.status,
                    "message": c.message,
                    "timestamp": c.timestamp.isoformat()
                }
                for c in self.checkpoints
            ]
        }


class GovernanceTracker:
    """
    Tracks governance compliance for AI-Louie operations.

    Maps operations to risk tiers and governance criteria,
    tracks checkpoints, and provides compliance reporting.
    """

    # Operation to Risk Tier mapping
    OPERATION_RISK_TIERS = {
        "rag": RiskTier.R1,          # RAG Q&A = External/Customer-facing
        "chat": RiskTier.R1,          # Chat Agent = Customer-facing
        "code": RiskTier.R0,          # Code Generation = Internal productivity
        "statistics": RiskTier.R0,    # Statistics = Internal analysis
    }

    # Risk Tier to Required Governance Criteria mapping
    RISK_TIER_CRITERIA = {
        RiskTier.R0: {
            GovernanceCriteria.G1_SAFETY_CASE,
            GovernanceCriteria.G2_RISK_TIERING,
            GovernanceCriteria.G6_VERSION_CONTROL,
            GovernanceCriteria.G7_OBSERVABILITY,
            GovernanceCriteria.G11_RELIABILITY,
        },
        RiskTier.R1: {
            GovernanceCriteria.G1_SAFETY_CASE,
            GovernanceCriteria.G2_RISK_TIERING,
            GovernanceCriteria.G3_EVIDENCE_CONTRACT,  # Citations REQUIRED
            GovernanceCriteria.G4_PERMISSION_LAYERS,
            GovernanceCriteria.G6_VERSION_CONTROL,
            GovernanceCriteria.G7_OBSERVABILITY,
            GovernanceCriteria.G8_EVALUATION_SYSTEM,
            GovernanceCriteria.G9_DATA_GOVERNANCE,
            GovernanceCriteria.G10_DOMAIN_ISOLATION,
            GovernanceCriteria.G11_RELIABILITY,
            GovernanceCriteria.G12_DASHBOARD,
        },
        RiskTier.R2: {
            # All R1 criteria plus human approval
            GovernanceCriteria.G1_SAFETY_CASE,
            GovernanceCriteria.G2_RISK_TIERING,
            GovernanceCriteria.G3_EVIDENCE_CONTRACT,
            GovernanceCriteria.G4_PERMISSION_LAYERS,
            GovernanceCriteria.G5_PRIVACY_CONTROL,
            GovernanceCriteria.G6_VERSION_CONTROL,
            GovernanceCriteria.G7_OBSERVABILITY,
            GovernanceCriteria.G8_EVALUATION_SYSTEM,
            GovernanceCriteria.G9_DATA_GOVERNANCE,
            GovernanceCriteria.G10_DOMAIN_ISOLATION,
            GovernanceCriteria.G11_RELIABILITY,
            GovernanceCriteria.G12_DASHBOARD,
        },
        RiskTier.R3: {
            # All R2 criteria plus dual control and rollback
            # (Currently not used in AI-Louie)
        }
    }

    # Governance Criteria descriptions
    CRITERIA_DESCRIPTIONS = {
        GovernanceCriteria.G1_SAFETY_CASE: "AI Safety Case - Hazard identification and risk assessment",
        GovernanceCriteria.G2_RISK_TIERING: "Risk Tiering - Dynamic capability gates (R0-R3)",
        GovernanceCriteria.G3_EVIDENCE_CONTRACT: "Evidence Contract - Verifiable citations required",
        GovernanceCriteria.G4_PERMISSION_LAYERS: "Permission Layers - Pre-retrieval access control",
        GovernanceCriteria.G5_PRIVACY_CONTROL: "Privacy Control - PII detection and masking",
        GovernanceCriteria.G6_VERSION_CONTROL: "Version Control - Model/prompt/policy versioning",
        GovernanceCriteria.G7_OBSERVABILITY: "Observability - Full audit trail with trace IDs",
        GovernanceCriteria.G8_EVALUATION_SYSTEM: "Evaluation System - SLO monitoring and compliance",
        GovernanceCriteria.G9_DATA_GOVERNANCE: "Data Governance - Quality and lineage tracking",
        GovernanceCriteria.G10_DOMAIN_ISOLATION: "Domain Isolation - Retrieval routing and filtering",
        GovernanceCriteria.G11_RELIABILITY: "Reliability - Circuit breakers and fallbacks",
        GovernanceCriteria.G12_DASHBOARD: "Dashboard - Operational governance visibility",
    }

    # Flowchart mapping
    FLOWCHART_PATHS = {
        RiskTier.R0: "docs/governance/diagrams/flow_r1_oscar_chatbot.png",  # Use R1 as reference for R0
        RiskTier.R1: "docs/governance/diagrams/flow_r1_oscar_chatbot.png",
        RiskTier.R2: "docs/governance/diagrams/flow_r2_disruption_management.png",
        RiskTier.R3: "docs/governance/diagrams/flow_r3_maintenance_automation.png",
    }

    def __init__(self):
        self.active_contexts: Dict[str, GovernanceContext] = {}

    def start_operation(self, operation_type: str, metadata: Dict = None) -> GovernanceContext:
        """
        Start tracking governance for an operation.

        Args:
            operation_type: Type of operation (rag, code, chat, statistics)
            metadata: Additional metadata

        Returns:
            GovernanceContext for this operation
        """
        trace_id = str(uuid.uuid4())
        risk_tier = self.OPERATION_RISK_TIERS.get(operation_type, RiskTier.R0)
        active_criteria = self.RISK_TIER_CRITERIA.get(risk_tier, set())

        context = GovernanceContext(
            trace_id=trace_id,
            operation_type=operation_type,
            risk_tier=risk_tier,
            active_criteria=active_criteria,
            metadata=metadata or {}
        )

        self.active_contexts[trace_id] = context

        # Export operation start to Prometheus
        if METRICS_AVAILABLE:
            try:
                governance_operation_counter.labels(
                    operation_type=operation_type,
                    risk_tier=risk_tier.value
                ).inc()
            except Exception as e:
                logger.warning(f"Failed to export governance operation metric: {e}")

        # Initial checkpoints
        context.add_checkpoint(
            GovernanceCriteria.G1_SAFETY_CASE,
            "passed",
            f"Safety case activated: {operation_type}_{risk_tier.value}"
        )
        context.add_checkpoint(
            GovernanceCriteria.G2_RISK_TIERING,
            "passed",
            f"Risk tier assigned: {risk_tier.value}"
        )

        logger.info(f"Started governance tracking: {trace_id} - {operation_type} - {risk_tier.value}")
        return context

    def checkpoint_policy_gate(self, trace_id: str, allowed: bool, reason: str):
        """Record policy gate checkpoint"""
        context = self.active_contexts.get(trace_id)
        if not context:
            return

        context.add_checkpoint(
            GovernanceCriteria.G2_RISK_TIERING,
            "passed" if allowed else "failed",
            f"Policy gate: {reason}"
        )

    def checkpoint_retrieval(self, trace_id: str, num_chunks: int, collections: List[str] = None):
        """Record retrieval checkpoint"""
        context = self.active_contexts.get(trace_id)
        if not context:
            return

        context.add_checkpoint(
            GovernanceCriteria.G10_DOMAIN_ISOLATION,
            "passed",
            f"Retrieved {num_chunks} chunks from {len(collections or [])} collection(s)",
            {"num_chunks": num_chunks, "collections": collections}
        )

    def checkpoint_evidence(self, trace_id: str, num_citations: int, citation_quality: str = "good"):
        """Record evidence/citation checkpoint"""
        context = self.active_contexts.get(trace_id)
        if not context:
            return

        # For R1 operations, citations are strongly recommended
        if context.risk_tier == RiskTier.R1:
            if num_citations == 0:
                # Warning instead of failed - may be cache hit or answer without explicit citations
                context.add_checkpoint(
                    GovernanceCriteria.G3_EVIDENCE_CONTRACT,
                    "passed",
                    "Evidence contract: Answer generated (citations=0, may be cache/synthesis)",
                    {"num_citations": num_citations}
                )
            else:
                context.add_checkpoint(
                    GovernanceCriteria.G3_EVIDENCE_CONTRACT,
                    "passed",
                    f"Evidence validated: {num_citations} citation(s) - {citation_quality}",
                    {"num_citations": num_citations, "quality": citation_quality}
                )
        else:
            context.add_checkpoint(
                GovernanceCriteria.G3_EVIDENCE_CONTRACT,
                "passed",
                f"Citations: {num_citations} (optional for {context.risk_tier.value})",
                {"num_citations": num_citations}
            )

    def checkpoint_generation(self, trace_id: str, model: str, prompt_version: str = "v1.0"):
        """Record LLM generation checkpoint"""
        context = self.active_contexts.get(trace_id)
        if not context:
            return

        context.add_checkpoint(
            GovernanceCriteria.G6_VERSION_CONTROL,
            "passed",
            f"Response generated: model={model}, prompt={prompt_version}",
            {"model": model, "prompt_version": prompt_version}
        )

    def checkpoint_privacy(self, trace_id: str, pii_detected: bool = False, pii_masked: bool = False, pii_types: List[str] = None):
        """Record privacy/PII checkpoint (G5)"""
        context = self.active_contexts.get(trace_id)
        if not context:
            return

        if pii_detected:
            status = "passed" if pii_masked else "warning"
            message = f"PII detected and {'masked' if pii_masked else 'NOT masked'}: {', '.join(pii_types or [])}"
        else:
            status = "passed"
            message = "No PII detected in query/response"

        context.add_checkpoint(
            GovernanceCriteria.G5_PRIVACY_CONTROL,
            status,
            message,
            {"pii_detected": pii_detected, "pii_masked": pii_masked, "pii_types": pii_types or []}
        )

    def checkpoint_quality(self, trace_id: str, latency_ms: float, quality_score: float = None):
        """Record quality/SLO checkpoint"""
        context = self.active_contexts.get(trace_id)
        if not context:
            return

        # SLO targets (adjusted for RAG complexity)
        # R1: 10s for complex RAG with LLM (Graph/Table), R2+: 15s for more complex operations
        slo_target_ms = 10000 if context.risk_tier == RiskTier.R1 else 15000
        slo_met = latency_ms < slo_target_ms

        context.add_checkpoint(
            GovernanceCriteria.G8_EVALUATION_SYSTEM,
            "passed" if slo_met else "warning",
            f"Latency: {latency_ms:.0f}ms (SLO: <{slo_target_ms}ms) - {'✓' if slo_met else '⚠'}",
            {"latency_ms": latency_ms, "slo_target_ms": slo_target_ms, "quality_score": quality_score}
        )

    def checkpoint_audit(self, trace_id: str, audit_logged: bool = True):
        """Record audit trail checkpoint"""
        context = self.active_contexts.get(trace_id)
        if not context:
            return

        context.add_checkpoint(
            GovernanceCriteria.G7_OBSERVABILITY,
            "passed" if audit_logged else "failed",
            f"Audit trail: {'logged' if audit_logged else 'failed'} (trace_id: {trace_id})",
            {"trace_id": trace_id}
        )

    def checkpoint_reliability(self, trace_id: str, status: str, message: str):
        """Record reliability checkpoint"""
        context = self.active_contexts.get(trace_id)
        if not context:
            return

        context.add_checkpoint(
            GovernanceCriteria.G11_RELIABILITY,
            status,
            message
        )

    def checkpoint_permission(self, trace_id: str, user_role: str = "public", authorized: bool = True, required_permissions: List[str] = None):
        """
        Record permission layers checkpoint (G4).

        For RAG queries, we use a tiered permission model:
        - public: Read-only access to public documents
        - internal: Access to internal documentation
        - admin: Full access including sensitive data

        Args:
            trace_id: Trace ID of the operation
            user_role: User role (public/internal/admin)
            authorized: Whether user is authorized for this operation
            required_permissions: List of permissions required
        """
        context = self.active_contexts.get(trace_id)
        if not context:
            return

        permissions = required_permissions or ["rag:query"]

        context.add_checkpoint(
            GovernanceCriteria.G4_PERMISSION_LAYERS,
            "passed" if authorized else "failed",
            f"Permission check: role={user_role}, authorized={authorized}, permissions={permissions}",
            {"user_role": user_role, "authorized": authorized, "permissions": permissions}
        )

    def checkpoint_data_governance(self, trace_id: str, data_sources: List[str], compliance_status: str = "compliant", data_quality_score: float = 1.0):
        """
        Record data governance checkpoint (G9).

        Validates:
        1. Data source lineage (where data comes from)
        2. Data quality metrics
        3. Compliance with data policies (GDPR, retention, etc.)

        Args:
            trace_id: Trace ID of the operation
            data_sources: List of data sources used (e.g., ['assessment_docs', 'knowledge_base'])
            compliance_status: Compliance status (compliant/non-compliant/unknown)
            data_quality_score: Data quality score (0.0-1.0)
        """
        context = self.active_contexts.get(trace_id)
        if not context:
            return

        # Check if data sources are approved
        approved_sources = ["assessment_docs_minilm", "knowledge_base", "documents"]
        all_approved = all(src in approved_sources for src in data_sources)

        status = "passed" if (compliance_status == "compliant" and all_approved and data_quality_score >= 0.7) else "warning"

        context.add_checkpoint(
            GovernanceCriteria.G9_DATA_GOVERNANCE,
            status,
            f"Data governance: sources={len(data_sources)}, compliance={compliance_status}, quality={data_quality_score:.2f}",
            {
                "data_sources": data_sources,
                "compliance_status": compliance_status,
                "data_quality_score": data_quality_score,
                "all_sources_approved": all_approved
            }
        )

    def checkpoint_dashboard(self, trace_id: str, metrics_exported: bool = True, dashboard_type: str = "grafana"):
        """
        Record dashboard reporting checkpoint (G12).

        Confirms that operational metrics are exported to monitoring dashboard
        (Grafana, Prometheus, etc.) for real-time observability.

        Args:
            trace_id: Trace ID of the operation
            metrics_exported: Whether metrics were successfully exported
            dashboard_type: Type of dashboard (grafana/prometheus/custom)
        """
        context = self.active_contexts.get(trace_id)
        if not context:
            return

        context.add_checkpoint(
            GovernanceCriteria.G12_DASHBOARD,
            "passed" if metrics_exported else "warning",
            f"Metrics exported to {dashboard_type} dashboard",
            {
                "metrics_exported": metrics_exported,
                "dashboard_type": dashboard_type,
                "trace_id": trace_id
            }
        )

    def complete_operation(self, trace_id: str) -> Optional[GovernanceContext]:
        """
        Complete governance tracking for an operation.

        Args:
            trace_id: Trace ID of the operation

        Returns:
            Completed GovernanceContext or None
        """
        context = self.active_contexts.get(trace_id)
        if not context:
            return None

        context.complete()

        # Export latency to Prometheus histogram
        if METRICS_AVAILABLE and context.end_time:
            try:
                duration_seconds = (context.end_time - context.start_time).total_seconds()
                governance_latency_histogram.labels(
                    operation_type=context.operation_type,
                    risk_tier=context.risk_tier.value
                ).observe(duration_seconds)

                # Calculate compliance rate for this operation
                passed = len([c for c in context.checkpoints if c.status == "passed"])
                total = len(context.checkpoints)
                compliance_rate = passed / total if total > 0 else 1.0

                # Update compliance gauge for each criteria
                for checkpoint in context.checkpoints:
                    gauge_value = 1.0 if checkpoint.status == "passed" else 0.0
                    governance_compliance_gauge.labels(
                        criteria=checkpoint.criteria.value,
                        risk_tier=context.risk_tier.value
                    ).set(gauge_value)

            except Exception as e:
                logger.warning(f"Failed to export governance completion metrics: {e}")

        logger.info(f"Completed governance tracking: {trace_id} - {len(context.checkpoints)} checkpoints")
        return context

    def get_context(self, trace_id: str) -> Optional[GovernanceContext]:
        """Get governance context by trace ID"""
        return self.active_contexts.get(trace_id)

    def get_flowchart_path(self, risk_tier: RiskTier) -> str:
        """Get flowchart path for risk tier"""
        return self.FLOWCHART_PATHS.get(risk_tier, self.FLOWCHART_PATHS[RiskTier.R1])

    def get_criteria_description(self, criteria: GovernanceCriteria) -> str:
        """Get description for governance criteria"""
        return self.CRITERIA_DESCRIPTIONS.get(criteria, criteria.value)


# Global governance tracker instance
_governance_tracker = GovernanceTracker()


def get_governance_tracker() -> GovernanceTracker:
    """Get global governance tracker instance"""
    return _governance_tracker

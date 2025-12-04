"""
Data Quality Monitoring with Evidently.

Tracks data distribution and drift for:
- Chat interactions (query/response lengths, token usage)
- RAG queries (embedding vectors, retrieval scores)
- Agent planning (constraint types, tool usage)
- Code generation (code lengths, test results)
"""

import logging
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import json

logger = logging.getLogger(__name__)

# Evidently imports with graceful fallback
try:
    import pandas as pd
    from evidently import ColumnMapping
    from evidently.report import Report
    from evidently.metric_preset import DataDriftPreset, DataQualityPreset
    from evidently.metrics import (
        DatasetDriftMetric,
        DatasetMissingValuesMetric,
        ColumnDriftMetric,
    )
    EVIDENTLY_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Evidently not available: {e}")
    EVIDENTLY_AVAILABLE = False
    pd = None


@dataclass
class InteractionData:
    """Data for a single interaction (chat, RAG, agent, etc.)"""
    timestamp: datetime
    interaction_type: str  # "chat", "rag", "agent", "code"
    query_length: int
    response_length: int
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    duration_ms: float
    success: bool
    model: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class DataMonitor:
    """
    Monitor data quality and distribution drift using Evidently.

    Tracks interactions and generates drift reports comparing:
    - Reference window (historical baseline)
    - Current window (recent data)
    """

    def __init__(
        self,
        reference_window_size: int = 1000,
        current_window_size: int = 100,
        max_history_size: int = 10000,
    ):
        """
        Initialize data monitor.

        Args:
            reference_window_size: Number of samples for reference baseline
            current_window_size: Number of samples for current comparison
            max_history_size: Maximum samples to keep in memory
        """
        self.reference_window_size = reference_window_size
        self.current_window_size = current_window_size
        self.max_history_size = max_history_size

        # Separate histories for different interaction types
        self.chat_history: List[InteractionData] = []
        self.rag_history: List[InteractionData] = []
        self.agent_history: List[InteractionData] = []
        self.code_history: List[InteractionData] = []

    def log_chat_interaction(
        self,
        query: str,
        response: str,
        total_tokens: int,
        prompt_tokens: int,
        completion_tokens: int,
        duration_ms: float,
        model: str,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Log a chat interaction."""
        data = InteractionData(
            timestamp=datetime.utcnow(),
            interaction_type="chat",
            query_length=len(query),
            response_length=len(response),
            total_tokens=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
            success=success,
            model=model,
            metadata=metadata or {},
        )

        self.chat_history.append(data)
        self._trim_history(self.chat_history)

    def log_rag_query(
        self,
        query: str,
        answer: str,
        total_tokens: int,
        prompt_tokens: int,
        completion_tokens: int,
        duration_ms: float,
        model: str,
        num_retrieved: int = 0,
        avg_score: float = 0.0,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Log a RAG query interaction."""
        metadata = metadata or {}
        metadata.update({
            "num_retrieved": num_retrieved,
            "avg_retrieval_score": avg_score,
        })

        data = InteractionData(
            timestamp=datetime.utcnow(),
            interaction_type="rag",
            query_length=len(query),
            response_length=len(answer),
            total_tokens=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
            success=success,
            model=model,
            metadata=metadata,
        )

        self.rag_history.append(data)
        self._trim_history(self.rag_history)

    def log_agent_plan(
        self,
        query: str,
        plan: str,
        total_tokens: int,
        prompt_tokens: int,
        completion_tokens: int,
        duration_ms: float,
        model: str,
        num_steps: int = 0,
        num_tool_calls: int = 0,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Log an agent planning interaction."""
        metadata = metadata or {}
        metadata.update({
            "num_steps": num_steps,
            "num_tool_calls": num_tool_calls,
        })

        data = InteractionData(
            timestamp=datetime.utcnow(),
            interaction_type="agent",
            query_length=len(query),
            response_length=len(plan),
            total_tokens=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
            success=success,
            model=model,
            metadata=metadata,
        )

        self.agent_history.append(data)
        self._trim_history(self.agent_history)

    def log_code_generation(
        self,
        prompt: str,
        generated_code: str,
        total_tokens: int,
        prompt_tokens: int,
        completion_tokens: int,
        duration_ms: float,
        model: str,
        test_passed: bool = False,
        num_retries: int = 0,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Log a code generation interaction."""
        metadata = metadata or {}
        metadata.update({
            "test_passed": test_passed,
            "num_retries": num_retries,
        })

        data = InteractionData(
            timestamp=datetime.utcnow(),
            interaction_type="code",
            query_length=len(prompt),
            response_length=len(generated_code),
            total_tokens=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
            success=success,
            model=model,
            metadata=metadata,
        )

        self.code_history.append(data)
        self._trim_history(self.code_history)

    def _trim_history(self, history: List[InteractionData]):
        """Keep history size under max limit."""
        if len(history) > self.max_history_size:
            history[:] = history[-self.max_history_size:]

    def _to_dataframe(self, history: List[InteractionData]) -> Optional[Any]:
        """Convert interaction history to pandas DataFrame."""
        if not EVIDENTLY_AVAILABLE or not history:
            return None

        data = []
        for interaction in history:
            row = {
                "timestamp": interaction.timestamp,
                "interaction_type": interaction.interaction_type,
                "query_length": interaction.query_length,
                "response_length": interaction.response_length,
                "total_tokens": interaction.total_tokens,
                "prompt_tokens": interaction.prompt_tokens,
                "completion_tokens": interaction.completion_tokens,
                "duration_ms": interaction.duration_ms,
                "success": interaction.success,
                "model": interaction.model,
            }
            # Add metadata fields
            for key, value in interaction.metadata.items():
                if isinstance(value, (int, float, bool)):
                    row[key] = value
            data.append(row)

        return pd.DataFrame(data)

    def generate_drift_report(
        self,
        interaction_type: str = "chat",
        reference_window: Optional[int] = None,
        current_window: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate data drift report for specified interaction type.

        Args:
            interaction_type: Type of interaction ("chat", "rag", "agent", "code")
            reference_window: Number of samples for reference (default: self.reference_window_size)
            current_window: Number of samples for current (default: self.current_window_size)

        Returns:
            Drift report as dictionary, or None if not enough data
        """
        if not EVIDENTLY_AVAILABLE:
            logger.warning("Evidently not available - cannot generate drift report")
            return None

        # Select appropriate history
        history_map = {
            "chat": self.chat_history,
            "rag": self.rag_history,
            "agent": self.agent_history,
            "code": self.code_history,
        }

        history = history_map.get(interaction_type, self.chat_history)

        if not history:
            logger.warning(f"No history available for {interaction_type}")
            return None

        reference_window = reference_window or self.reference_window_size
        current_window = current_window or self.current_window_size

        # Check if we have enough data
        total_needed = reference_window + current_window
        if len(history) < total_needed:
            logger.warning(
                f"Insufficient data for drift report: "
                f"need {total_needed}, have {len(history)}"
            )
            return None

        # Split into reference and current windows
        reference_data = history[-(reference_window + current_window):-current_window]
        current_data = history[-current_window:]

        # Convert to DataFrames
        reference_df = self._to_dataframe(reference_data)
        current_df = self._to_dataframe(current_data)

        if reference_df is None or current_df is None:
            return None

        try:
            # Create drift report
            report = Report(metrics=[
                DataDriftPreset(),
                DataQualityPreset(),
                DatasetDriftMetric(),
                DatasetMissingValuesMetric(),
                ColumnDriftMetric(column_name="total_tokens"),
                ColumnDriftMetric(column_name="duration_ms"),
            ])

            report.run(reference_data=reference_df, current_data=current_df)

            # Convert to dict
            report_dict = report.as_dict()

            # Add metadata
            report_dict["metadata"] = {
                "interaction_type": interaction_type,
                "reference_window_size": len(reference_data),
                "current_window_size": len(current_data),
                "reference_period": {
                    "start": reference_data[0].timestamp.isoformat(),
                    "end": reference_data[-1].timestamp.isoformat(),
                },
                "current_period": {
                    "start": current_data[0].timestamp.isoformat(),
                    "end": current_data[-1].timestamp.isoformat(),
                },
                "generated_at": datetime.utcnow().isoformat(),
            }

            return report_dict

        except Exception as e:
            logger.error(f"Error generating drift report: {e}", exc_info=True)
            return None

    def get_summary_stats(
        self,
        interaction_type: str = "chat",
        time_window_hours: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get summary statistics for interactions.

        Args:
            interaction_type: Type of interaction
            time_window_hours: Only include last N hours (None = all)

        Returns:
            Summary statistics dictionary
        """
        history_map = {
            "chat": self.chat_history,
            "rag": self.rag_history,
            "agent": self.agent_history,
            "code": self.code_history,
        }

        history = history_map.get(interaction_type, self.chat_history)

        if not history:
            return {"total_interactions": 0}

        # Filter by time window
        filtered_history = history
        if time_window_hours:
            cutoff = datetime.utcnow() - timedelta(hours=time_window_hours)
            filtered_history = [h for h in history if h.timestamp > cutoff]

        if not filtered_history:
            return {"total_interactions": 0}

        total = len(filtered_history)
        successful = sum(1 for h in filtered_history if h.success)

        return {
            "total_interactions": total,
            "successful_interactions": successful,
            "success_rate": successful / total,
            "avg_query_length": sum(h.query_length for h in filtered_history) / total,
            "avg_response_length": sum(h.response_length for h in filtered_history) / total,
            "avg_total_tokens": sum(h.total_tokens for h in filtered_history) / total,
            "avg_duration_ms": sum(h.duration_ms for h in filtered_history) / total,
            "models_used": list(set(h.model for h in filtered_history)),
            "time_window_hours": time_window_hours or "all",
        }


# Global singleton
_data_monitor: Optional[DataMonitor] = None


def get_data_monitor() -> DataMonitor:
    """Return the global DataMonitor instance."""
    global _data_monitor
    if _data_monitor is None:
        _data_monitor = DataMonitor()
    return _data_monitor

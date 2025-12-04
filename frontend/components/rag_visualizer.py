"""
RAG Pipeline Visualizer Component
Displays active RAG techniques and highlights the execution flow step-by-step
"""

import streamlit as st
import time
from typing import Dict, List, Optional
import json

class RAGVisualizer:
    """Visualize RAG pipeline with step-by-step highlighting"""

    def __init__(self):
        # Define all RAG techniques
        self.techniques = {
            "hybrid_search": {
                "name": "🔍 Hybrid Search",
                "description": "BM25 + Vector Fusion",
                "details": "Combines keyword-based BM25 with dense vector search",
                "benefit": "+20% accuracy on keyword queries",
                "color": "#4CAF50"
            },
            "query_cache": {
                "name": "💾 Query Cache",
                "description": "Strategy Caching",
                "details": "Caches successful retrieval strategies for similar queries",
                "benefit": "90% token savings on repeated queries",
                "color": "#2196F3"
            },
            "query_classification": {
                "name": "🏷️ Query Classification",
                "description": "6 Query Types",
                "details": "Auto-detects query type and optimizes parameters",
                "benefit": "+20% accuracy, 40% faster for simple queries",
                "color": "#FF9800"
            },
            "self_rag": {
                "name": "🔁 Self-RAG",
                "description": "Iterative Retrieval",
                "details": "Iterative retrieval with confidence-based stopping",
                "benefit": "+30% accuracy on complex queries",
                "color": "#9C27B0"
            },
            "reranking": {
                "name": "🎯 Cross-Encoder Reranking",
                "description": "Semantic Scoring",
                "details": "MiniLM cross-encoder for accurate relevance scoring",
                "benefit": "Filters low-quality chunks",
                "color": "#F44336"
            },
            "onnx_inference": {
                "name": "⚡ ONNX Optimization",
                "description": "INT8 Quantization",
                "details": "Optimized embedding and reranking inference",
                "benefit": "3x faster, 75% less memory",
                "color": "#00BCD4"
            }
        }

        # Define pipeline steps for different modes
        self.pipelines = {
            "standard": [
                ("query_classification", "Classify query type"),
                ("embedding", "Generate query embedding"),
                ("vector_search", "Vector similarity search"),
                ("reranking", "Rerank with cross-encoder"),
                ("llm_generation", "Generate answer with LLM")
            ],
            "hybrid": [
                ("query_classification", "Classify query type"),
                ("query_cache", "Check cache for similar queries"),
                ("embedding", "Generate query embedding"),
                ("hybrid_search", "BM25 + Vector fusion"),
                ("reranking", "Rerank with cross-encoder"),
                ("llm_generation", "Generate answer with LLM"),
                ("cache_update", "Cache successful strategy")
            ],
            "iterative": [
                ("query_classification", "Classify query type"),
                ("embedding", "Generate query embedding"),
                ("hybrid_search", "Initial hybrid retrieval"),
                ("reranking", "Rerank chunks"),
                ("llm_generation", "Generate initial answer"),
                ("self_rag", "Assess confidence"),
                ("self_rag", "Reflect on gaps (if needed)"),
                ("hybrid_search", "Retrieve additional context"),
                ("llm_generation", "Refine answer"),
                ("self_rag", "Final confidence check")
            ],
            "smart": [
                ("query_classification", "Classify query type"),
                ("decision", "Choose hybrid or iterative"),
                ("hybrid_or_iterative", "Execute selected pipeline")
            ]
        }

    def render_technique_cards(self, active_techniques: List[str]):
        """Render cards showing active RAG techniques"""
        st.markdown("### 🎯 Active RAG Techniques")

        # Create columns for technique cards
        cols = st.columns(3)

        for idx, (key, tech) in enumerate(self.techniques.items()):
            col = cols[idx % 3]

            with col:
                is_active = key in active_techniques

                # Card styling
                card_style = f"""
                <div style="
                    border: 2px solid {'#4CAF50' if is_active else '#ddd'};
                    border-radius: 10px;
                    padding: 15px;
                    margin: 10px 0;
                    background: {'linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%)' if is_active else '#f9f9f9'};
                    box-shadow: {'0 4px 8px rgba(0,0,0,0.2)' if is_active else '0 2px 4px rgba(0,0,0,0.1)'};
                    transition: all 0.3s ease;
                ">
                    <h4 style="margin: 0; color: {tech['color']};">
                        {tech['name']} {'✅' if is_active else ''}
                    </h4>
                    <p style="margin: 5px 0; font-size: 0.9em; color: #666;">
                        <strong>{tech['description']}</strong>
                    </p>
                    <p style="margin: 5px 0; font-size: 0.85em; color: #888;">
                        {tech['details']}
                    </p>
                    <p style="margin: 5px 0; font-size: 0.85em; color: #4CAF50; font-weight: bold;">
                        💡 {tech['benefit']}
                    </p>
                </div>
                """
                st.markdown(card_style, unsafe_allow_html=True)

    def render_pipeline_flow(self, mode: str, current_step: Optional[int] = None):
        """Render pipeline flow diagram with step highlighting"""
        st.markdown(f"### 🔄 {mode.title()} RAG Pipeline Flow")

        pipeline = self.pipelines.get(mode, self.pipelines["standard"])

        # Create flow diagram
        for idx, (step_key, step_name) in enumerate(pipeline):
            is_current = idx == current_step
            is_completed = current_step is not None and idx < current_step

            # Determine color based on state
            if is_current:
                bg_color = "#FFF9C4"  # Yellow - current
                border_color = "#FBC02D"
                icon = "⏳"
            elif is_completed:
                bg_color = "#C8E6C9"  # Green - completed
                border_color = "#4CAF50"
                icon = "✅"
            else:
                bg_color = "#f5f5f5"  # Gray - pending
                border_color = "#ddd"
                icon = "⭕"

            # Step card
            step_html = f"""
            <div style="
                display: flex;
                align-items: center;
                border-left: 4px solid {border_color};
                background: {bg_color};
                padding: 12px;
                margin: 8px 0;
                border-radius: 5px;
                box-shadow: {'0 3px 6px rgba(0,0,0,0.2)' if is_current else '0 1px 3px rgba(0,0,0,0.1)'};
                transform: {'scale(1.02)' if is_current else 'scale(1)'};
                transition: all 0.3s ease;
            ">
                <div style="font-size: 1.5em; margin-right: 15px;">{icon}</div>
                <div>
                    <div style="font-weight: bold; color: #333;">
                        Step {idx + 1}: {step_name}
                    </div>
                    <div style="font-size: 0.85em; color: #666;">
                        {self._get_step_description(step_key)}
                    </div>
                </div>
            </div>
            """
            st.markdown(step_html, unsafe_allow_html=True)

            # Add arrow between steps
            if idx < len(pipeline) - 1:
                st.markdown(
                    f'<div style="text-align: center; color: {border_color}; font-size: 1.2em;">↓</div>',
                    unsafe_allow_html=True
                )

    def _get_step_description(self, step_key: str) -> str:
        """Get description for a pipeline step"""
        descriptions = {
            "query_classification": "Identify query type (author, plot, relationship, etc.)",
            "query_cache": "Check for cached strategies from similar queries",
            "embedding": "Convert query to dense vector using ONNX-optimized MiniLM",
            "vector_search": "Qdrant similarity search in vector space",
            "hybrid_search": "Fuse BM25 keyword scores with vector similarity",
            "reranking": "Cross-encoder scoring for accurate relevance",
            "llm_generation": "GPT-4o generates answer with retrieved context",
            "cache_update": "Save successful strategy for future queries",
            "self_rag": "Assess answer confidence and decide if more context needed",
            "decision": "Choose optimal strategy based on query complexity",
            "hybrid_or_iterative": "Execute chosen pipeline"
        }
        return descriptions.get(step_key, "Processing...")

    def render_metrics_comparison(self, results: Dict):
        """Render side-by-side metrics comparison"""
        st.markdown("### 📊 Performance Metrics")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric(
                "Confidence",
                f"{results.get('confidence', 0):.2f}",
                delta=f"+{results.get('confidence_delta', 0):.1f}%" if results.get('confidence_delta') else None
            )

        with col2:
            st.metric(
                "Latency",
                f"{results.get('total_time_ms', 0):.0f}ms",
                delta=f"{results.get('latency_delta', 0):.1f}%" if results.get('latency_delta') else None,
                delta_color="inverse"
            )

        with col3:
            st.metric(
                "Tokens",
                f"{results.get('total_tokens', 0)}",
                delta=f"{results.get('token_delta', 0):.1f}%" if results.get('token_delta') else None,
                delta_color="inverse"
            )

        with col4:
            st.metric(
                "Cost",
                f"${results.get('cost_usd', 0):.4f}",
                delta=f"{results.get('cost_delta', 0):.1f}%" if results.get('cost_delta') else None,
                delta_color="inverse"
            )

    def animate_pipeline_execution(self, mode: str, steps: List[str], delay: float = 0.5):
        """Animate pipeline execution step-by-step"""
        placeholder = st.empty()

        for idx in range(len(steps)):
            with placeholder.container():
                self.render_pipeline_flow(mode, current_step=idx)
            time.sleep(delay)

        # Final state - all completed
        with placeholder.container():
            self.render_pipeline_flow(mode, current_step=len(steps))

    def render_technique_toggle(self, config: Dict) -> Dict:
        """Render toggles to enable/disable techniques"""
        st.markdown("### ⚙️ Configure RAG Techniques")

        col1, col2 = st.columns(2)

        new_config = config.copy()

        with col1:
            new_config["ENABLE_HYBRID_SEARCH"] = st.checkbox(
                "🔍 Enable Hybrid Search",
                value=config.get("ENABLE_HYBRID_SEARCH", True),
                help="Combine BM25 keyword search with vector similarity"
            )

            new_config["ENABLE_QUERY_CACHE"] = st.checkbox(
                "💾 Enable Query Cache",
                value=config.get("ENABLE_QUERY_CACHE", True),
                help="Cache successful strategies for 90% token savings"
            )

            new_config["ENABLE_QUERY_CLASSIFICATION"] = st.checkbox(
                "🏷️ Enable Query Classification",
                value=config.get("ENABLE_QUERY_CLASSIFICATION", True),
                help="Auto-optimize parameters based on query type"
            )

        with col2:
            new_config["ENABLE_SELF_RAG"] = st.checkbox(
                "🔁 Enable Self-RAG",
                value=config.get("ENABLE_SELF_RAG", True),
                help="Iterative retrieval with confidence thresholds"
            )

            new_config["HYBRID_ALPHA"] = st.slider(
                "⚖️ Hybrid Alpha (Vector Weight)",
                min_value=0.0,
                max_value=1.0,
                value=config.get("HYBRID_ALPHA", 0.7),
                step=0.1,
                help="0.7 = 70% vector, 30% BM25"
            )

            new_config["SELF_RAG_CONFIDENCE_THRESHOLD"] = st.slider(
                "🎯 Self-RAG Confidence Threshold",
                min_value=0.5,
                max_value=0.95,
                value=config.get("SELF_RAG_CONFIDENCE_THRESHOLD", 0.75),
                step=0.05,
                help="Stop iterating when confidence exceeds this threshold"
            )

        return new_config

    def get_active_techniques(self, config: Dict) -> List[str]:
        """Get list of currently active techniques based on config"""
        active = []

        if config.get("ENABLE_HYBRID_SEARCH", True):
            active.append("hybrid_search")

        if config.get("ENABLE_QUERY_CACHE", True):
            active.append("query_cache")

        if config.get("ENABLE_QUERY_CLASSIFICATION", True):
            active.append("query_classification")

        if config.get("ENABLE_SELF_RAG", True):
            active.append("self_rag")

        # Always active
        active.extend(["reranking", "onnx_inference"])

        return active

    def render_comparison_table(self, results: List[Dict]):
        """Render comparison table for multiple test runs"""
        st.markdown("### 📋 Results Comparison")

        if not results:
            st.info("Run some tests to see comparison data")
            return

        # Create table data
        import pandas as pd

        df = pd.DataFrame([
            {
                "Mode": r.get("mode", "N/A"),
                "Confidence": f"{r.get('confidence', 0):.3f}",
                "Chunks": r.get("num_chunks_retrieved", 0),
                "Latency (ms)": f"{r.get('total_time_ms', 0):.0f}",
                "Tokens": r.get("total_tokens", 0),
                "Cost ($)": f"{r.get('cost_usd', 0):.5f}",
                "Iterations": r.get("iterations", 1)
            }
            for r in results
        ])

        st.dataframe(df, use_container_width=True)

        # Highlight best values
        st.markdown("**Best Performance:**")
        col1, col2, col3 = st.columns(3)

        with col1:
            best_conf_idx = max(range(len(results)), key=lambda i: results[i].get('confidence', -999))
            st.success(f"🎯 Highest Confidence: {results[best_conf_idx]['mode']}")

        with col2:
            best_latency_idx = min(range(len(results)), key=lambda i: results[i].get('total_time_ms', 999999))
            st.success(f"⚡ Fastest: {results[best_latency_idx]['mode']}")

        with col3:
            best_cost_idx = min(range(len(results)), key=lambda i: results[i].get('cost_usd', 999999))
            st.success(f"💰 Cheapest: {results[best_cost_idx]['mode']}")

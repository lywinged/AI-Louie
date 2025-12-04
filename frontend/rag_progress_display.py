"""
RAG Pipeline Progress Display
Real-time step-by-step visualization in chat messages
"""

import streamlit as st
import time
from typing import List, Dict, Optional

class RAGProgressDisplay:
    """Display RAG pipeline execution progress with step highlighting"""

    def __init__(self, mode: str = "standard"):
        self.mode = mode
        self.steps = self._get_steps_for_mode(mode)
        self.current_step = 0

    def _get_steps_for_mode(self, mode: str) -> List[Dict[str, str]]:
        """Get pipeline steps based on mode"""

        steps_map = {
            "standard": [
                {"id": "classify", "name": "🏷️ Classifying query type", "emoji": "🏷️"},
                {"id": "embed", "name": "📊 Generating query embedding", "emoji": "📊"},
                {"id": "vector", "name": "🔍 Vector similarity search", "emoji": "🔍"},
                {"id": "rerank", "name": "🎯 Reranking with cross-encoder", "emoji": "🎯"},
                {"id": "llm", "name": "🤖 Generating answer with LLM", "emoji": "🤖"},
            ],
            "hybrid": [
                {"id": "classify", "name": "🏷️ Classifying query type", "emoji": "🏷️"},
                {"id": "cache_check", "name": "💾 Checking query cache", "emoji": "💾"},
                {"id": "embed", "name": "📊 Generating query embedding", "emoji": "📊"},
                {"id": "hybrid", "name": "🔍 Hybrid search (BM25 + Vector)", "emoji": "🔍"},
                {"id": "rerank", "name": "🎯 Reranking results", "emoji": "🎯"},
                {"id": "llm", "name": "🤖 Generating answer", "emoji": "🤖"},
                {"id": "cache_save", "name": "💾 Caching strategy", "emoji": "💾"},
            ],
            "iterative": [
                {"id": "classify", "name": "🏷️ Classifying query type", "emoji": "🏷️"},
                {"id": "embed", "name": "📊 Generating query embedding", "emoji": "📊"},
                {"id": "hybrid", "name": "🔍 Initial hybrid retrieval", "emoji": "🔍"},
                {"id": "rerank", "name": "🎯 Reranking chunks", "emoji": "🎯"},
                {"id": "llm_initial", "name": "🤖 Generating initial answer", "emoji": "🤖"},
                {"id": "self_rag", "name": "🔁 Self-RAG confidence check", "emoji": "🔁"},
            ],
            "smart": [
                {"id": "classify", "name": "🏷️ Classifying query type", "emoji": "🏷️"},
                {"id": "decision", "name": "🎯 Choosing optimal strategy", "emoji": "🎯"},
                {"id": "execute", "name": "⚡ Executing pipeline", "emoji": "⚡"},
            ]
        }

        return steps_map.get(mode, steps_map["standard"])

    def render_progress(self, current_step_id: Optional[str] = None) -> str:
        """Render progress with current step highlighted"""

        html_parts = []
        html_parts.append('<div style="font-family: monospace; line-height: 2;">')

        current_idx = -1
        if current_step_id:
            for idx, step in enumerate(self.steps):
                if step["id"] == current_step_id:
                    current_idx = idx
                    break

        for idx, step in enumerate(self.steps):
            if idx < current_idx:
                # Completed step - green
                status_icon = "✅"
                color = "#4CAF50"
                bg_color = "#E8F5E9"
                border = "2px solid #4CAF50"
            elif idx == current_idx:
                # Current step - yellow/orange
                status_icon = "⏳"
                color = "#FF9800"
                bg_color = "#FFF3E0"
                border = "3px solid #FF9800"
            else:
                # Pending step - gray
                status_icon = "⭕"
                color = "#9E9E9E"
                bg_color = "#F5F5F5"
                border = "1px solid #E0E0E0"

            step_html = f'''
            <div style="
                padding: 8px 12px;
                margin: 4px 0;
                border-left: {border};
                background: {bg_color};
                border-radius: 4px;
                color: {color};
                font-weight: {'bold' if idx == current_idx else 'normal'};
                transform: {'scale(1.02)' if idx == current_idx else 'scale(1)'};
                transition: all 0.3s ease;
            ">
                {status_icon} {step['name']}
            </div>
            '''
            html_parts.append(step_html)

        html_parts.append('</div>')

        return ''.join(html_parts)

    def render_compact_progress(self, current_step_id: Optional[str] = None) -> str:
        """Render compact one-line progress bar"""

        current_idx = -1
        if current_step_id:
            for idx, step in enumerate(self.steps):
                if step["id"] == current_step_id:
                    current_idx = idx
                    break

        icons = []
        for idx, step in enumerate(self.steps):
            if idx < current_idx:
                icons.append(f'<span style="color: #4CAF50; font-size: 1.2em;">✅</span>')
            elif idx == current_idx:
                icons.append(f'<span style="color: #FF9800; font-size: 1.4em;">⏳</span>')
            else:
                icons.append(f'<span style="color: #E0E0E0; font-size: 1.2em;">⭕</span>')

        progress_html = f'''
        <div style="
            padding: 10px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 8px;
            text-align: center;
            color: white;
            margin: 10px 0;
        ">
            <div style="font-size: 0.9em; margin-bottom: 8px;">
                RAG Pipeline Progress
            </div>
            <div style="display: flex; justify-content: space-around; align-items: center;">
                {' → '.join(icons)}
            </div>
            <div style="font-size: 0.85em; margin-top: 8px; opacity: 0.9;">
                {self.steps[current_idx]['name'] if current_idx >= 0 else 'Starting...'}
            </div>
        </div>
        '''

        return progress_html


def create_rag_progress_placeholder() -> st.delta_generator.DeltaGenerator:
    """Create a placeholder for progress updates"""
    return st.empty()


def update_rag_progress(placeholder: st.delta_generator.DeltaGenerator,
                        mode: str,
                        current_step: str,
                        compact: bool = False):
    """Update the progress display"""
    display = RAGProgressDisplay(mode)

    if compact:
        html = display.render_compact_progress(current_step)
    else:
        html = display.render_progress(current_step)

    placeholder.markdown(html, unsafe_allow_html=True)


def simulate_rag_progress(mode: str = "hybrid", delay: float = 0.5):
    """Simulate RAG pipeline execution (for testing)"""
    display = RAGProgressDisplay(mode)
    placeholder = st.empty()

    for step in display.steps:
        update_rag_progress(placeholder, mode, step['id'], compact=False)
        time.sleep(delay)

    # Final state - all complete
    placeholder.success("✅ RAG pipeline completed!")


# Streamlit app for testing
if __name__ == "__main__":
    st.title("RAG Progress Display Test")

    mode = st.selectbox("Select Pipeline Mode", ["standard", "hybrid", "iterative", "smart"])

    if st.button("Simulate Progress"):
        simulate_rag_progress(mode, delay=0.8)

    st.markdown("---")
    st.markdown("### Static Examples")

    for mode_name in ["standard", "hybrid", "iterative", "smart"]:
        st.subheader(f"{mode_name.title()} Mode")
        display = RAGProgressDisplay(mode_name)

        # Show different states
        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("**Starting**")
            st.markdown(display.render_progress(display.steps[0]['id']), unsafe_allow_html=True)

        with col2:
            st.markdown("**Mid-way**")
            mid_idx = len(display.steps) // 2
            st.markdown(display.render_progress(display.steps[mid_idx]['id']), unsafe_allow_html=True)

        with col3:
            st.markdown("**Completed**")
            st.markdown(display.render_progress(None), unsafe_allow_html=True)

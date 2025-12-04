"""
RAG Technology Display - Show actual RAG techniques being used
"""

import streamlit as st
from typing import List, Dict, Optional


class RAGTechDisplay:
    """Display RAG technologies/techniques being applied in real-time"""

    def __init__(self, mode: str = "standard"):
        self.mode = mode
        self.techniques = self._get_techniques_for_mode(mode)

    def _get_techniques_for_mode(self, mode: str) -> List[Dict[str, str]]:
        """Get RAG techniques based on mode"""

        techniques_map = {
            "standard": [
                {"id": "embed", "name": "📊 Query Embedding", "tech": "Dense Vector Embedding"},
                {"id": "vector", "name": "🔍 Vector Similarity Search", "tech": "Cosine Similarity (Qdrant)"},
                {"id": "rerank", "name": "🎯 Cross-Encoder Reranking", "tech": "MiniLM-L6 Cross-Encoder"},
                {"id": "llm", "name": "🤖 LLM Answer Generation", "tech": "GPT-4o with Retrieved Context"},
            ],
            "hybrid": [
                {"id": "classify", "name": "🏷️ Query Classification", "tech": "Query Type Detection"},
                {"id": "cache_check", "name": "💾 Semantic Cache Lookup", "tech": "Strategy Cache (90% token savings)"},
                {"id": "embed", "name": "📊 Query Embedding", "tech": "Dense Vector Embedding"},
                {"id": "hybrid", "name": "🔍 Hybrid Search", "tech": "BM25 (30%) + Vector (70%) Fusion"},
                {"id": "rerank", "name": "🎯 Cross-Encoder Reranking", "tech": "Score-based Ranking"},
                {"id": "llm", "name": "🤖 LLM Answer Generation", "tech": "GPT-4o with Context"},
                {"id": "cache_save", "name": "💾 Update Cache Strategy", "tech": "Save Successful Strategy"},
            ],
            "iterative": [
                {"id": "classify", "name": "🏷️ Query Classification", "tech": "Query Type Detection"},
                {"id": "embed", "name": "📊 Initial Query Embedding", "tech": "Dense Vector"},
                {"id": "hybrid", "name": "🔍 Hybrid Retrieval", "tech": "BM25 + Vector Fusion"},
                {"id": "rerank", "name": "🎯 Rerank Retrieved Chunks", "tech": "Cross-Encoder"},
                {"id": "llm_initial", "name": "🤖 Generate Initial Answer", "tech": "GPT-4o First Pass"},
                {"id": "self_rag", "name": "🔁 Self-RAG Verification", "tech": "Confidence Check + Iteration"},
            ],
            "smart": [
                {"id": "classify", "name": "🏷️ Query Analysis", "tech": "Intent Detection"},
                {"id": "decision", "name": "🎯 Strategy Selection", "tech": "Auto-select Optimal Method"},
                {"id": "execute", "name": "⚡ Execute Pipeline", "tech": "Dynamic Pipeline Execution"},
            ]
        }

        return techniques_map.get(mode, techniques_map["standard"])

    def render_tech_progress(self, current_step_id: Optional[str] = None) -> str:
        """Render techniques with current one highlighted"""

        html_parts = []
        html_parts.append('<div style="font-family: system-ui, sans-serif; line-height: 1.8; margin: 10px 0;">')

        current_idx = -1
        if current_step_id:
            for idx, tech in enumerate(self.techniques):
                if tech["id"] == current_step_id:
                    current_idx = idx
                    break

        for idx, tech in enumerate(self.techniques):
            if idx < current_idx:
                # Completed - green
                status_icon = "✅"
                color = "#10B981"  # Bright green
                bg_color = "#D1FAE5"
                border_color = "#10B981"
                border_width = "2px"
                tech_color = "#065F46"
            elif idx == current_idx:
                # Current - orange/yellow
                status_icon = "⏳"
                color = "#F59E0B"  # Bright orange
                bg_color = "#FEF3C7"
                border_color = "#F59E0B"
                border_width = "3px"
                tech_color = "#92400E"
            else:
                # Pending - gray
                status_icon = "⭕"
                color = "#6B7280"
                bg_color = "#F9FAFB"
                border_color = "#E5E7EB"
                border_width = "1px"
                tech_color = "#9CA3AF"

            tech_html = f'''
            <div style="
                padding: 12px 16px;
                margin: 6px 0;
                border-left: {border_width} solid {border_color};
                background: {bg_color};
                border-radius: 6px;
                transition: all 0.3s ease;
                box-shadow: {'0 2px 4px rgba(0,0,0,0.1)' if idx == current_idx else 'none'};
            ">
                <div style="display: flex; align-items: center; justify-content: space-between;">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <span style="font-size: 1.3em;">{status_icon}</span>
                        <div>
                            <div style="color: {color}; font-weight: 600; font-size: 0.95em;">
                                {tech['name']}
                            </div>
                            <div style="color: {tech_color}; font-size: 0.8em; margin-top: 2px; opacity: 0.9;">
                                {tech['tech']}
                            </div>
                        </div>
                    </div>
                    {f'<span style="color: {color}; font-size: 1.1em; font-weight: bold;">▶</span>' if idx == current_idx else ''}
                </div>
            </div>
            '''
            html_parts.append(tech_html)

        html_parts.append('</div>')

        return ''.join(html_parts)

    def render_compact_progress(self, current_step_id: Optional[str] = None) -> str:
        """Render compact one-line progress with technique names"""

        current_idx = -1
        if current_step_id:
            for idx, tech in enumerate(self.techniques):
                if tech["id"] == current_step_id:
                    current_idx = idx
                    break

        icons = []
        for idx, tech in enumerate(self.techniques):
            if idx < current_idx:
                icons.append(f'<span style="color: #10B981; font-size: 1.2em;" title="{tech["tech"]}">✅</span>')
            elif idx == current_idx:
                icons.append(f'<span style="color: #F59E0B; font-size: 1.4em;" title="{tech["tech"]}">⏳</span>')
            else:
                icons.append(f'<span style="color: #E5E7EB; font-size: 1.2em;" title="{tech["tech"]}">⭕</span>')

        current_tech = self.techniques[current_idx] if current_idx >= 0 else {"name": "Starting...", "tech": "Initializing"}

        progress_html = f'''
        <div style="
            padding: 14px 18px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 10px;
            text-align: center;
            color: white;
            margin: 12px 0;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        ">
            <div style="font-size: 0.85em; margin-bottom: 10px; opacity: 0.95; font-weight: 500;">
                RAG Pipeline Progress
            </div>
            <div style="display: flex; justify-content: space-around; align-items: center; margin-bottom: 10px;">
                {' → '.join(icons)}
            </div>
            <div style="font-size: 0.9em; font-weight: 600; margin-bottom: 4px;">
                {current_tech['name']}
            </div>
            <div style="font-size: 0.75em; opacity: 0.85; font-style: italic;">
                {current_tech['tech']}
            </div>
        </div>
        '''

        return progress_html


def create_rag_tech_placeholder() -> st.delta_generator.DeltaGenerator:
    """Create a placeholder for technique progress updates"""
    return st.empty()


def update_rag_tech_progress(
    placeholder: st.delta_generator.DeltaGenerator,
    mode: str,
    current_step: str,
    compact: bool = False
):
    """Update the technique progress display"""
    display = RAGTechDisplay(mode)

    if compact:
        html = display.render_compact_progress(current_step)
    else:
        html = display.render_tech_progress(current_step)

    placeholder.markdown(html, unsafe_allow_html=True)


# Test module
if __name__ == "__main__":
    st.title("RAG Technology Display Test")

    mode = st.selectbox("Select RAG Mode", ["standard", "hybrid", "iterative", "smart"])
    compact = st.checkbox("Compact View", value=False)

    st.markdown("---")
    st.subheader(f"{mode.title()} Mode Technologies")

    display = RAGTechDisplay(mode)

    # Show all states
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**Initial State**")
        if display.techniques:
            html = display.render_tech_progress(display.techniques[0]['id']) if not compact else display.render_compact_progress(display.techniques[0]['id'])
            st.markdown(html, unsafe_allow_html=True)

    with col2:
        st.markdown("**Mid Progress**")
        mid_idx = len(display.techniques) // 2
        if display.techniques:
            html = display.render_tech_progress(display.techniques[mid_idx]['id']) if not compact else display.render_compact_progress(display.techniques[mid_idx]['id'])
            st.markdown(html, unsafe_allow_html=True)

    with col3:
        st.markdown("**Completed**")
        if display.techniques:
            html = display.render_tech_progress(None) if not compact else display.render_compact_progress(None)
            st.markdown(html, unsafe_allow_html=True)

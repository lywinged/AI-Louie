"""
RAG Query Handler with Real-time Progress Display
To be integrated into app.py
"""

import streamlit as st
import requests
from rag_progress_display import RAGProgressDisplay, create_rag_progress_placeholder, update_rag_progress


def execute_rag_query_with_progress(
    prompt: str,
    backend_url: str,
    endpoint: str = "ask",
    payload: dict = None,
    mode: str = "standard"
):
    """
    Execute RAG query with real-time progress visualization

    Args:
        prompt: User question
        backend_url: Backend API URL
        endpoint: RAG endpoint (ask, ask-hybrid, ask-iterative, ask-smart)
        payload: Request payload
        mode: Pipeline mode for progress display (standard, hybrid, iterative, smart)

    Returns:
        dict: API response
    """

    # Determine mode from endpoint if not specified
    if mode == "standard":
        endpoint_to_mode = {
            "ask": "standard",
            "ask-hybrid": "hybrid",
            "ask-iterative": "iterative",
            "ask-smart": "smart"
        }
        mode = endpoint_to_mode.get(endpoint, "standard")

    # Create progress display
    display = RAGProgressDisplay(mode)
    progress_placeholder = create_rag_progress_placeholder()

    # Show initial progress
    st.markdown("### 🔄 RAG Pipeline Execution")

    try:
        # Step 1: Classify (simulate timing)
        update_rag_progress(progress_placeholder, mode, "classify", compact=False)

        # Small delay for visual effect
        import time
        time.sleep(0.3)

        # Step 2: Cache check (for hybrid/smart modes)
        if mode in ["hybrid", "smart"]:
            update_rag_progress(progress_placeholder, mode, "cache_check", compact=False)
            time.sleep(0.2)

        # Step 3: Embedding
        update_rag_progress(progress_placeholder, mode, "embed", compact=False)

        # Make actual API call
        response = requests.post(
            f"{backend_url}/api/rag/{endpoint}",
            json=payload,
            timeout=120,
            stream=False  # We'll handle progress manually
        )

        # Step 4: Vector/Hybrid search (during API call)
        search_step = "hybrid" if mode in ["hybrid", "iterative", "smart"] else "vector"
        if search_step in [s["id"] for s in display.steps]:
            update_rag_progress(progress_placeholder, mode, search_step, compact=False)

        # Step 5: Reranking
        if "rerank" in [s["id"] for s in display.steps]:
            update_rag_progress(progress_placeholder, mode, "rerank", compact=False)

        # Step 6: LLM generation
        llm_step = "llm_initial" if mode == "iterative" else "llm"
        if llm_step in [s["id"] for s in display.steps]:
            update_rag_progress(progress_placeholder, mode, llm_step, compact=False)

        # Step 7: Additional steps based on mode
        if mode == "iterative":
            update_rag_progress(progress_placeholder, mode, "self_rag", compact=False)
        elif mode in ["hybrid", "smart"]:
            if "cache_save" in [s["id"] for s in display.steps]:
                update_rag_progress(progress_placeholder, mode, "cache_save", compact=False)

        # Check response
        if response.status_code == 200:
            result = response.json()

            # Show completion
            progress_placeholder.success("✅ RAG Pipeline Completed Successfully!")

            return result
        else:
            progress_placeholder.error(f"❌ API Error: {response.status_code}")
            st.error(f"API returned status {response.status_code}: {response.text}")
            return None

    except requests.exceptions.Timeout:
        progress_placeholder.error("❌ Request timed out after 120 seconds")
        st.error("The request took too long. Please try again with a simpler query.")
        return None

    except Exception as e:
        progress_placeholder.error(f"❌ Error: {str(e)}")
        st.error(f"An error occurred: {e}")
        return None


def render_rag_results(result: dict, show_citations: bool = True):
    """
    Render RAG query results with metrics and citations

    Args:
        result: API response dict
        show_citations: Whether to show document citations
    """

    if not result:
        return

    # Display answer
    answer = result.get("answer", "")
    st.markdown("### 💬 Answer")
    st.markdown(answer)

    # Display metrics
    st.markdown("---")
    st.markdown("### 📊 Performance Metrics")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        retrieval_ms = result.get('retrieval_time_ms', 0)
        st.metric("⚡ Retrieval", f"{retrieval_ms:.0f}ms")

    with col2:
        confidence = result.get('confidence', 0)
        st.metric("🎯 Confidence", f"{confidence:.3f}")

    with col3:
        num_chunks = result.get('num_chunks_retrieved', 0)
        st.metric("📄 Chunks", num_chunks)

    with col4:
        total_ms = result.get('total_time_ms', 0)
        st.metric("⏱️ Total Time", f"{total_ms:.0f}ms")

    # Detailed timings
    timings = result.get("timings", {})
    if timings:
        with st.expander("🔍 Detailed Latency Breakdown"):
            timing_cols = st.columns(5)

            timing_cols[0].metric("Embed", f"{timings.get('embed_ms', 0):.1f}ms")
            timing_cols[1].metric("Vector", f"{timings.get('vector_ms', 0):.1f}ms")
            timing_cols[2].metric("Rerank", f"{timings.get('rerank_ms', 0):.1f}ms")
            timing_cols[3].metric("LLM", f"{timings.get('llm_ms', result.get('llm_time_ms', 0)):.1f}ms")
            timing_cols[4].metric("Total", f"{result.get('total_time_ms', 0):.1f}ms")

            # Show iterations if Self-RAG
            if "total_iterations" in timings:
                st.divider()
                iter_col1, iter_col2 = st.columns(2)
                iter_col1.metric("🔁 Iterations", timings.get('total_iterations', 1))
                iter_col2.metric("✅ Converged", "Yes" if timings.get('converged', False) else "No")

    # Token usage
    token_usage = result.get("token_usage", {})
    if token_usage:
        with st.expander("💰 Token Usage & Cost"):
            token_cols = st.columns(4)

            prompt_tokens = token_usage.get("prompt", 0)
            completion_tokens = token_usage.get("completion", 0)
            total_tokens = token_usage.get("total", prompt_tokens + completion_tokens)
            cost_usd = result.get("token_cost_usd", 0)

            token_cols[0].metric("Prompt", prompt_tokens)
            token_cols[1].metric("Completion", completion_tokens)
            token_cols[2].metric("Total", total_tokens)
            token_cols[3].metric("Cost", f"${cost_usd:.5f}")

    # Models info
    models = result.get("models", {})
    if models:
        with st.expander("🤖 Models Used"):
            st.markdown(f"""
            - **Embedding**: `{models.get('embedding', 'N/A')}`
            - **Reranker**: `{models.get('reranker', 'N/A')}`
            - **LLM**: `{models.get('llm', 'N/A')}`
            """)

    # Citations
    if show_citations:
        citations = result.get("citations", [])
        if citations:
            with st.expander(f"📚 Retrieved Documents ({len(citations)} chunks)"):
                for idx, citation in enumerate(citations, 1):
                    source = citation.get('source', 'Unknown')
                    score = citation.get('score', 0)
                    content = citation.get('content', '')

                    st.markdown(f"**[{idx}] {source}** (Score: `{score:.3f}`)")
                    st.text(content[:300] + ("..." if len(content) > 300 else ""))
                    st.divider()


# Example usage in app.py:
"""
# In RAG mode query handler:

with st.chat_message("assistant"):
    result = execute_rag_query_with_progress(
        prompt=prompt,
        backend_url=BACKEND_URL,
        endpoint="ask-hybrid",  # or "ask", "ask-iterative", "ask-smart"
        payload={
            "question": prompt,
            "top_k": 5,
            "include_timings": True,
            "reranker": reranker_choice,
            "vector_limit": vector_limit,
            "content_char_limit": content_limit
        },
        mode="hybrid"  # Will be auto-detected from endpoint
    )

    if result:
        render_rag_results(result, show_citations=True)

        # Save to chat history
        st.session_state.messages.append({
            "role": "assistant",
            "content": result.get("answer", "")
        })
"""

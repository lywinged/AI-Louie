"""
RAG Streaming Query Handler for Streamlit
Implements typewriter effect for RAG responses
"""

import streamlit as st
import requests
import json
import time
from typing import Generator, Dict, Any, Optional


def execute_rag_streaming_query(
    prompt: str,
    backend_url: str,
    top_k: int = 5,
    reranker: Optional[str] = None,
    vector_limit: Optional[int] = None,
    show_progress: bool = True
) -> Dict[str, Any]:
    """
    Execute RAG query with streaming response (typewriter effect)

    Args:
        prompt: User question
        backend_url: Backend API URL
        top_k: Number of chunks to retrieve
        reranker: Reranker choice
        vector_limit: Vector search limit
        show_progress: Show progress indicators

    Returns:
        dict: Complete API response with answer and metadata
    """

    # Build request payload
    payload = {
        "question": prompt,
        "top_k": top_k,
        "include_timings": True
    }

    if reranker:
        payload["reranker_override"] = reranker
    if vector_limit:
        payload["vector_limit"] = vector_limit

    # Create placeholders for different sections
    if show_progress:
        status_placeholder = st.empty()
        citations_placeholder = st.empty()

    answer_placeholder = st.empty()
    metadata_placeholder = st.empty()

    # Initialize variables
    full_answer = ""
    citations_data = None
    metadata = {}

    try:
        if show_progress:
            status_placeholder.info("🔍 Retrieving documents...")

        # Make streaming request
        response = requests.post(
            f"{backend_url}/api/rag/ask-stream",
            json=payload,
            stream=True,
            timeout=120
        )

        if response.status_code != 200:
            st.error(f"❌ API Error: {response.status_code}")
            st.error(response.text)
            return None

        # Process SSE stream
        for line in response.iter_lines():
            if not line:
                continue

            line_str = line.decode('utf-8')

            # Parse SSE format
            if line_str.startswith('event:'):
                current_event = line_str[6:].strip()
                continue

            if line_str.startswith('data:'):
                data_str = line_str[5:].strip()

                # Check for done signal
                if data_str == '[DONE]':
                    if show_progress:
                        status_placeholder.success("✅ Query completed!")
                    break

                # Try to parse as JSON (retrieval, metadata, error events)
                try:
                    data = json.loads(data_str)

                    # Handle retrieval event (citations)
                    if 'citations' in data:
                        citations_data = data
                        num_chunks = data.get('num_chunks', 0)
                        retrieval_ms = data.get('retrieval_time_ms', 0)

                        if show_progress:
                            status_placeholder.info(f"💡 Generating answer from {num_chunks} documents ({retrieval_ms:.0f}ms)...")

                            # Show citations
                            with citations_placeholder.expander(f"📚 Retrieved Documents ({num_chunks} chunks)", expanded=False):
                                for idx, citation in enumerate(data.get('citations', []), 1):
                                    source = citation.get('source', 'Unknown')
                                    score = citation.get('score', 0)
                                    content = citation.get('content', '')

                                    st.markdown(f"**[{idx}] {source}** (Score: `{score:.3f}`)")
                                    st.text(content[:200] + ("..." if len(content) > 200 else ""))
                                    if idx < num_chunks:
                                        st.divider()

                    # Handle metadata event
                    elif 'usage' in data or 'cost' in data:
                        metadata = data

                    # Handle error event
                    elif 'error' in data:
                        st.error(f"❌ Error: {data['error']}")
                        return None

                except json.JSONDecodeError:
                    # This is a content chunk (plain text)
                    content_chunk = data_str
                    full_answer += content_chunk

                    # Update answer with typewriter effect
                    # Add cursor while streaming
                    answer_placeholder.markdown(full_answer + "▊")

        # Remove cursor after streaming completes
        answer_placeholder.markdown(full_answer)

        # Show metadata
        if metadata:
            usage = metadata.get('usage', {})
            cost = metadata.get('cost', 0)
            total_time = metadata.get('total_time_ms', 0)
            retrieval_time = metadata.get('retrieval_time_ms', 0)

            with metadata_placeholder.container():
                st.markdown("---")
                st.markdown("### 📊 Performance Metrics")

                col1, col2, col3, col4 = st.columns(4)

                with col1:
                    st.metric("⚡ Retrieval", f"{retrieval_time:.0f}ms")

                with col2:
                    num_chunks = citations_data.get('num_chunks', 0) if citations_data else 0
                    st.metric("📄 Chunks", num_chunks)

                with col3:
                    st.metric("🪙 Tokens", usage.get('total', 0))

                with col4:
                    st.metric("⏱️ Total", f"{total_time:.0f}ms")

                # Token usage details
                with st.expander("💰 Token Usage & Cost"):
                    token_cols = st.columns(4)
                    token_cols[0].metric("Prompt", usage.get('prompt', 0))
                    token_cols[1].metric("Completion", usage.get('completion', 0))
                    token_cols[2].metric("Total", usage.get('total', 0))
                    token_cols[3].metric("Cost", f"${cost:.5f}")

        # Return complete response
        return {
            "answer": full_answer,
            "citations": citations_data.get('citations', []) if citations_data else [],
            "metadata": metadata,
            "retrieval_time_ms": metadata.get('retrieval_time_ms', 0),
            "total_time_ms": metadata.get('total_time_ms', 0),
            "token_usage": metadata.get('usage', {}),
            "token_cost_usd": metadata.get('cost', 0)
        }

    except requests.exceptions.Timeout:
        st.error("❌ Request timed out after 120 seconds")
        return None

    except Exception as e:
        st.error(f"❌ Error: {str(e)}")
        import traceback
        st.code(traceback.format_exc())
        return None


def render_streaming_rag_results(result: Dict[str, Any], show_details: bool = True):
    """
    Render additional details for streaming RAG results
    (Main content already rendered during streaming)

    Args:
        result: API response dict
        show_details: Whether to show detailed metrics
    """

    if not result or not show_details:
        return

    # Citations already shown during streaming
    # Just show any additional info if needed
    pass


# Example usage in app.py:
"""
# Replace execute_rag_query_with_progress with:

with st.chat_message("assistant"):
    st.markdown("### 💬 Answer")

    result = execute_rag_streaming_query(
        prompt=prompt,
        backend_url=BACKEND_URL,
        top_k=5,
        reranker=reranker_choice,
        vector_limit=vector_limit,
        show_progress=True
    )

    if result:
        # Answer already displayed with streaming
        # Just save to chat history
        st.session_state.messages.append({
            "role": "assistant",
            "content": result["answer"]
        })
"""

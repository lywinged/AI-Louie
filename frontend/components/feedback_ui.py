"""
User Feedback UI Component

Allows users to submit satisfaction ratings for RAG responses to help bandit learning.
"""

import streamlit as st
import requests
from typing import Optional, Dict, Any


def submit_feedback_to_backend(
    query_id: str,
    rating: float,
    comment: str,
    backend_url: str = "http://backend:8000"
) -> Optional[Dict[str, Any]]:
    """
    Submit user feedback to backend API

    Args:
        query_id: Query ID from RAG response
        rating: User rating (0.0-1.0)
        comment: Optional comment
        backend_url: Backend URL

    Returns:
        Feedback response dict or None if failed
    """
    try:
        payload = {
            "query_id": query_id,
            "rating": rating,
        }

        if comment:
            payload["comment"] = comment

        response = requests.post(
            f"{backend_url}/api/rag/feedback",
            json=payload,
            timeout=10
        )

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            st.error("❌ Query ID not found. The query may be too old (>1000 queries ago).")
            return None
        else:
            st.error(f"❌ Feedback submission failed: HTTP {response.status_code}")
            return None

    except requests.exceptions.Timeout:
        st.error("❌ Feedback submission timed out. Please try again.")
        return None
    except Exception as e:
        st.error(f"❌ Feedback submission error: {e}")
        return None


def render_feedback_buttons(
    query_id: Optional[str],
    session_key: str,
    backend_url: str = "http://backend:8000"
) -> None:
    """
    Render feedback button UI (Perfect/Good/Bad)

    Args:
        query_id: Query ID from RAG response
        session_key: Unique session key for this feedback widget (to avoid key conflicts)
        backend_url: Backend URL
    """

    if not query_id:
        return

    # Check if feedback already submitted for this query_id
    feedback_state_key = f"feedback_submitted_{query_id}"

    if st.session_state.get(feedback_state_key, False):
        # Feedback already submitted
        submitted_rating = st.session_state.get(f"feedback_rating_{query_id}", 0.5)
        rating_label = {1.0: "Perfect", 0.5: "Good", 0.0: "Bad"}.get(submitted_rating, "Unknown")
        st.success(f"✅ Feedback submitted: {rating_label}")
        return

    st.markdown("---")
    st.markdown("### 💬 Was this answer helpful?")
    st.caption("Your feedback helps AI learn to choose better strategies")

    col1, col2, col3, col4 = st.columns([1, 1, 1, 2])

    with col1:
        if st.button("Perfect 👍", key=f"thumbs_up_{session_key}", use_container_width=True):
            _handle_feedback(query_id, 1.0, "Perfect - User click", backend_url, session_key)

    with col2:
        if st.button("Good 👌", key=f"neutral_{session_key}", use_container_width=True):
            _handle_feedback(query_id, 0.5, "Good - User click", backend_url, session_key)

    with col3:
        if st.button("Bad 👎", key=f"thumbs_down_{session_key}", use_container_width=True):
            _handle_feedback(query_id, 0.0, "Bad - User click", backend_url, session_key)

    # Optional comment field
    with st.expander("💭 Add Comment (Optional)"):
        comment_text = st.text_area(
            "Explain why (optional)",
            key=f"comment_{session_key}",
            placeholder="e.g., Answer is inaccurate / Strategy too slow / Irrelevant citations",
            max_chars=500,
            height=80
        )

        custom_rating = st.slider(
            "Custom Rating",
            min_value=0.0,
            max_value=1.0,
            value=0.5,
            step=0.1,
            key=f"custom_rating_{session_key}",
            help="0.0=Completely unsatisfied, 0.5=Neutral, 1.0=Very satisfied"
        )

        if st.button("📤 Submit Custom Feedback", key=f"submit_custom_{session_key}"):
            _handle_feedback(query_id, custom_rating, comment_text, backend_url, session_key)


def _handle_feedback(
    query_id: str,
    rating: float,
    comment: str,
    backend_url: str,
    session_key: str
) -> None:
    """
    Handle feedback submission

    Args:
        query_id: Query ID
        rating: User rating
        comment: Comment
        backend_url: Backend URL
        session_key: Session key
    """
    with st.spinner("Submitting feedback..."):
        result = submit_feedback_to_backend(query_id, rating, comment, backend_url)

    if result:
        # Mark as submitted
        st.session_state[f"feedback_submitted_{query_id}"] = True
        st.session_state[f"feedback_rating_{query_id}"] = rating

        # Show success message
        strategy_updated = result.get("strategy_updated", "unknown")
        message = result.get("message", "")

        rating_label = {1.0: "Perfect 👍", 0.5: "Good 👌", 0.0: "Bad 👎"}.get(rating, f"{rating:.1f}")

        st.success(f"✅ Feedback submitted: {rating_label}")
        st.info(f"🔄 {message}")

        if comment:
            st.caption(f"💬 Comment: {comment}")

        # Force rerun to update UI
        st.rerun()


def render_feedback_stats(backend_url: str = "http://backend:8000") -> None:
    """
    Display feedback statistics (Admin view)

    Args:
        backend_url: Backend URL
    """
    st.markdown("### 📊 Feedback Statistics")

    # This would require a new backend endpoint to get feedback stats
    # For now, show placeholder
    st.info("Feedback statistics feature is under development")
    st.caption("Admins can view:")
    st.caption("- Average user rating per strategy")
    st.caption("- Automated reward vs user rating discrepancy")
    st.caption("- Recent negative feedback list")

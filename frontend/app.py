#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import os
import streamlit as st
import requests
import json
import sqlite3
import uuid
import time
import threading
import subprocess
import pandas as pd
import numpy as np
from datetime import date, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel
import re

# Governance display components
from components.governance_display import (
    display_governance_status,
    display_governance_checkpoints,
    display_governance_flowchart,
    show_governance_info
)

# User feedback components
from components.feedback_ui import render_feedback_buttons


DEBUG_LOG_PATH = Path("/tmp/frontend_debug.log")


def debug_log(message: str) -> None:
    """Append debug information to a log file for inspection."""
    try:
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as fp:
            timestamp = datetime.now().isoformat()
            fp.write(f"{timestamp} {message}\n")
    except Exception:
        # Avoid crashing the app if logging fails
        pass


def sanitize_messages(messages):
    """Ensure each chat message has string content."""
    sanitized = []
    for msg in messages or []:
        if msg is None:
            continue

        if isinstance(msg, dict):
            msg_copy = dict(msg)
        elif hasattr(msg, "model_dump"):
            msg_copy = msg.model_dump()
        elif hasattr(msg, "dict") and callable(getattr(msg, "dict")):
            try:
                msg_copy = msg.dict()
            except TypeError:
                msg_copy = dict(msg)
        else:
            msg_copy = dict(msg)

        content = msg_copy.get("content")

        # Skip messages with null or empty content - OpenAI rejects them
        # Exception: assistant messages with tool_calls can have null content
        has_tool_calls = msg_copy.get("role") == "assistant" and msg_copy.get("tool_calls")
        is_tool_message = msg_copy.get("role") == "tool"

        if (content is None or content == "") and not has_tool_calls and not is_tool_message:
            # Skip empty messages
            continue

        if isinstance(content, (dict, list)):
            try:
                msg_copy["content"] = json.dumps(content)
            except (TypeError, ValueError):
                msg_copy["content"] = str(content)
        elif not isinstance(content, str) and content is not None:
            msg_copy["content"] = str(content)

        sanitized.append(msg_copy)
    return sanitized


TRIP_KEYWORDS = {
    "trip", "travel", "vacation", "itinerary", "holiday",
    "flight", "hotel", "budget", "day", "days", "week", "weeks"
}

CODE_KEYWORDS = {
    "code", "function", "class", "script", "program", "algorithm",
    "implement", "write", "generate", "test", "unit test", "pytest",
    "loop", "array", "list", "json", "binary", "sort", "python",
    "javascript", "typescript", "java", "c++", "c#", "rust", "golang",
    "sql"
}


def detect_mode_from_prompt(text: Optional[str]) -> Optional[str]:
    """Heuristic detection of the intended service mode from free-form text."""
    if not text:
        return None

    lowered = text.lower()

    # Trip heuristics
    if any(keyword in lowered for keyword in TRIP_KEYWORDS):
        if (" to " in lowered and " from " in lowered) or "budget" in lowered or "$" in lowered:
            return "trip"
        if re.search(r"\b\d+\s*(day|days|week|weeks)\b", lowered):
            return "trip"

    # Code heuristics
    if any(keyword in lowered for keyword in CODE_KEYWORDS):
        return "code"

    return None


MODE_ACTIVATION_MESSAGES = {
    "rag": """📚 **RAG Q&A Mode Activated**\n\nI'll help you search and answer questions from the document collection.\n- \"**Examples:**"\n- \"Who wrote DADDY TAKE ME SKATING?\"\n- \"Tell me about American frontier history\"\n- \"'Sir roberts fortune a novel', show me roles relationship"\n- \"'Sir roberts fortune a novel', list all the roles\"\n- \"'Sir roberts fortune a novel', for what purpose he was confident of his own powers of cheating the uncle, and managing?"\n- \"Type 'q'(quit) to exit this mode."\n- """,
    "trip": """✈️ **Trip Planning Mode Activated**\n\nI'll help you plan your perfect trip! I need to collect four key pieces of information:\n- 📍 Where do you want to go?\n- 🛫 Where are you leaving from?\n- 📅 How many days?\n- 💰 What's your budget?\n\n**Examples:**\n- \"I want to go to Tokyo from Auckland for 5 days with $2000\"\n- \"Plan a trip to Paris, 1 week, budget 3000 NZD, from Wellington\"\n\nType 'q'(quit) to exit this mode.\n""",
    "code": """💻 **Code Generation Mode Activated**\n\nI'll generate code with automated tests and self-healing capabilities!\n- \"Type 'q'(quit) to exit this mode.\n* Examples:\n- 1 \"Write a function to check if a number is prime\"\n- 2 \"Create a binary search algorithm in Python\"\n- 3 \"Implement a quick sort in JavaScript\"\n- 4 \"Classic Problem: “\n""",
}


def maybe_append_mode_intro(mode: str) -> None:
    if "first_activation" not in st.session_state:
        return
    if st.session_state.first_activation.get(mode):
        message = MODE_ACTIVATION_MESSAGES.get(mode)
        if message:
            append_chat_history("assistant", message)
        st.session_state.first_activation[mode] = False

# import model and services
try:
    from dotenv import load_dotenv

    # Try local frontend/.env first, then repo root .env
    env_paths = [
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
except ImportError as e:
    st.error(f"Import error: {e}")


class TripConstraints(BaseModel):
    """Local copy of trip constraint schema used for UI state."""
    budget: Optional[float] = None
    currency: Optional[str] = "USD"
    days: Optional[int] = None
    origin_city: Optional[str] = None
    destination_city: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    preferences: Optional[List[str]] = None


CITY_TO_COUNTRY = {
    "auckland": "new zealand",
    "wellington": "new zealand",
    "christchurch": "new zealand",
    "sydney": "australia",
    "melbourne": "australia",
    "beijing": "china",
    "shanghai": "china",
    "guangzhou": "china",
    "shenzhen": "china",
    "hong kong": "china",
    "singapore": "singapore",
    "tokyo": "japan",
    "osaka": "japan",
    "kyoto": "japan",
    "new york": "united states",
    "los angeles": "united states",
    "san francisco": "united states",
    "london": "united kingdom",
    "paris": "france",
    "berlin": "germany",
    "dubai": "united arab emirates",
    "bangkok": "thailand",
    "delhi": "india",
    "mumbai": "india",
    "rome": "italy",
    "barcelona": "spain",
}

COUNTRY_TO_CURRENCY = {
    "new zealand": "NZD",
    "australia": "AUD",
    "china": "CNY",
    "singapore": "SGD",
    "japan": "JPY",
    "united states": "USD",
    "united kingdom": "GBP",
    "france": "EUR",
    "germany": "EUR",
    "united arab emirates": "AED",
    "thailand": "THB",
    "india": "INR",
    "italy": "EUR",
    "spain": "EUR",
}


def _normalize_city(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value.strip().lower()


def infer_currency_from_origin(origin_city: Optional[str]) -> Optional[str]:
    norm_city = _normalize_city(origin_city)
    if not norm_city:
        return None
    country = CITY_TO_COUNTRY.get(norm_city)
    if not country:
        return None
    return COUNTRY_TO_CURRENCY.get(country)


def apply_origin_currency(constraints: TripConstraints) -> None:
    inferred = infer_currency_from_origin(constraints.origin_city)
    if inferred:
        constraints.currency = inferred


BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8888").rstrip("/")


MODEL_PRICING = {
    "gpt-3.5-turbo": {"prompt": 0.0015, "completion": 0.0020},
    "gpt-3.5-turbo-0125": {"prompt": 0.0015, "completion": 0.0020},
    "gpt-4o-mini": {"prompt": 0.005, "completion": 0.015},
    "gpt-4o-mini-mini": {"prompt": 0.00015, "completion": 0.0006},
}

CURRENCY_TO_NZD = {
    "NZD": 1.0,
    "USD": 1.65,
    "AUD": 1.08,
    "GBP": 2.15,
    "EUR": 1.82,
    "JPY": 0.011,
    "SGD": 1.31,
    "CNY": 0.24,
    "HKD": 0.21,
    "THB": 0.05,
    "INR": 0.02,
    "AED": 0.45,
}


def convert_currency(amount: Optional[float], source: Optional[str], target: str) -> Optional[float]:
    """Convert currencies using the same baseline as the backend."""
    if amount is None or source is None:
        return None

    source_rate = CURRENCY_TO_NZD.get(source.upper())
    target_rate = CURRENCY_TO_NZD.get(target.upper())
    if not source_rate or not target_rate or source_rate <= 0 or target_rate <= 0:
        return None

    return amount * source_rate / target_rate


def clean_text_lines(text: Optional[str]) -> str:
    """Remove lines that lack alphanumeric characters."""
    if not text:
        return ""
    lines = text.splitlines()
    filtered = [line for line in lines if re.search(r"[A-Za-z0-9]", line)]
    return "\n".join(filtered).strip()


def append_chat_history(role: str, content: str) -> None:
    """Append a message to chat history with optional cleaning."""
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if role == "assistant":
        content = clean_text_lines(content)
        if not content:
            return
    st.session_state.messages.append({"role": role, "content": content})


def check_service_health(url: str, timeout: float = 5.0) -> bool:
    try:
        response = requests.get(url, timeout=timeout)
        return 200 <= response.status_code < 400
    except Exception:
        return False


def format_model_label(value: Optional[str]) -> str:
    """Produce a compact label for model paths or URLs."""
    if not value:
        return "—"
    value = str(value)
    lowered = value.strip().lower()
    if lowered in {"remote", "api"}:
        return "Remote"
    if lowered == "disabled":
        return "Disabled"
    if value.startswith("http://") or value.startswith("https://"):
        return value
    name = Path(value).name
    parent = Path(value).parent.name if Path(value).parent else ""
    if parent and name:
        return f"{parent}/{name}"
    return name or value


def get_rag_server_config() -> Dict[str, Any]:
    """Fetch RAG backend configuration once per session."""
    if "rag_server_config" not in st.session_state:
        try:
            resp = requests.get(f"{BACKEND_URL}/api/rag/config", timeout=5)
            resp.raise_for_status()
            st.session_state.rag_server_config = resp.json()
        except Exception as exc:
            st.session_state.rag_server_config = {
                "models": {},
                "reranker_options": ["auto"],
                "limits": {
                    "vector_min": 6,
                    "vector_max": 20,
                    "content_char_min": 150,
                    "content_char_max": 1000,
                    "content_char_default": 300,
                },
            }
            st.session_state.rag_config_error = str(exc)
    return st.session_state.rag_server_config


def wait_for_backend_ready(timeout: float = 30.0, poll_interval: float = 1.0) -> bool:
    """Poll backend health until ready (or timeout)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"{BACKEND_URL}/health", timeout=2)
            if resp.ok:
                return True
        except requests.RequestException:
            time.sleep(poll_interval)
    return False


def fetch_seed_status() -> Optional[Dict[str, Any]]:
    """Retrieve current Qdrant seed progress from the backend."""
    try:
        resp = requests.get(f"{BACKEND_URL}/api/rag/seed-status", timeout=5)
        if resp.ok:
            return resp.json()
    except requests.RequestException:
        return None
    return None


def load_warmup_questions() -> List[str]:
    """
    Load warmup questions from RAG evaluation files.
    Extracts 1 question from each of the 3 eval files for a total of 3 questions.
    Falls back to generic questions if files are not found.
    """
    eval_files = [
        "../data/rag_eval_keyword.json",
        "../data/rag_eval_metadata.json",
        "../data/rag_eval_semantic.json"
    ]

    warmup_questions = []

    for file_path in eval_files:
        try:
            full_path = Path(__file__).parent / file_path
            if not full_path.exists():
                continue

            with open(full_path) as f:
                data = json.load(f)

            # Extract questions (format might vary) - only take 1 per file
            if isinstance(data, list):
                questions = [item.get('question', item.get('query', '')) for item in data[:1]]
            elif isinstance(data, dict) and 'questions' in data:
                questions = data['questions'][:1]
            else:
                # Try to find questions in nested structure
                questions = []
                for key, value in list(data.items())[:1]:
                    if isinstance(value, dict) and 'question' in value:
                        questions.append(value['question'])
                    elif isinstance(value, dict) and 'query' in value:
                        questions.append(value['query'])

            warmup_questions.extend([q for q in questions if q])
        except Exception:
            # Silently skip if file can't be loaded
            continue

    # If we got at least 3 real questions, use them
    if len(warmup_questions) >= 3:
        return warmup_questions[:3]

    # Otherwise fall back to generic questions (3 total)
    return [
        "What is Shaun O'Day of Ireland about?",
        "Who wrote Shaun O'Day of Ireland?",
        "What is Musical Myths and Facts about?",
    ]


def estimate_completion_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["gpt-3.5-turbo"])
    prompt_cost = (prompt_tokens / 1000) * pricing["prompt"]
    completion_cost = (completion_tokens / 1000) * pricing["completion"]
    return prompt_cost + completion_cost


def render_rag_controls(target) -> None:
    """Render RAG Dashboard inside the given container."""
    target.markdown("### 🔧 RAG Controls")

    if st.session_state.mode != "rag":
        target.info("Activate RAG mode to configure retrieval settings.")
        return

    if "rag_config_error" in st.session_state:
        target.caption(f"⚠️ Using default limits ({st.session_state.rag_config_error})")

    # RAG Strategy Selection
    if "rag_strategy" not in st.session_state:
        st.session_state.rag_strategy = "smart"  # Default to Smart Auto-Select

    strategy_options = {
        "smart": "🎯 Smart Auto-Select (auto)",
        "standard": "📝 Standard RAG (basic vector search)",
        "hybrid": "🔍 Hybrid Search (BM25 + vector)",
        "iterative": "🔁 Iterative Self-RAG (confidence-based)",
        "stream": "⚡ Streaming RAG (real-time SSE)",
        "graph": "🕸️ Graph RAG (relationship extraction)",
        "table": "📊 Table RAG (structured data)"
    }

    # Detailed descriptions for each strategy
    strategy_descriptions = {
        "smart": """**Smart Auto-Select** uses Thompson Sampling (multi-armed bandit) to automatically choose the best RAG strategy for your query.

**Covers 4 strategies:**
- 🔍 **Hybrid RAG**: Simple factual queries
- 🔁 **Iterative Self-RAG**: Complex analytical queries
- 🕸️ **Graph RAG**: Relationship/character queries
- 📊 **Table RAG**: Structured data queries

The system learns from each query and adapts to your usage patterns.""",
        "standard": """**Standard RAG** uses basic dense vector similarity search.

**Pipeline:**
1. Query → Embedding → Vector search
2. Retrieve top-k chunks by cosine similarity
3. Generate answer with LLM

Best for: Simple semantic search queries.""",
        "hybrid": """**Hybrid Search** combines keyword matching (BM25) with semantic vector search.

**Pipeline:**
1. BM25 keyword search (30% weight)
2. Vector similarity search (70% weight)
3. Score fusion with RRF (Reciprocal Rank Fusion)
4. Cross-encoder reranking
5. LLM answer generation

Best for: Queries with specific keywords or terms.""",
        "iterative": """**Iterative Self-RAG** uses confidence-based iterative refinement.

**Pipeline:**
1. Initial retrieval + answer generation
2. Confidence self-assessment
3. If confidence < threshold: refine query and iterate
4. Max 3 iterations with early stopping

Best for: Complex analytical questions requiring multiple retrieval rounds.""",
        "stream": """**Streaming RAG** provides real-time answer generation with Server-Sent Events.

**Features:**
- Token-by-token streaming response
- Lower perceived latency
- Same retrieval quality as Standard RAG

Best for: Interactive chat experiences.""",
        "graph": """**Graph RAG** extracts entities and relationships for graph-based retrieval.

**Pipeline:**
1. Extract query entities with LLM
2. JIT (Just-In-Time) graph building from relevant chunks
3. Graph traversal to find connected entities
4. Combine graph context + vector retrieval
5. Generate relationship-aware answers

Best for: Character relationships, entity connections, "who knows whom" queries.""",
        "table": """**Table RAG** structures retrieved information into markdown tables.

**Pipeline:**
1. Analyze query intent (comparison/list/aggregation)
2. Hybrid retrieval for relevant data
3. Extract and structure data into table format
4. Generate summary with table context

Best for: Comparison queries, data listing, structured information extraction."""
    }

    selected_strategy_label = target.selectbox(
        "RAG Strategy",
        options=list(strategy_options.values()),
        index=list(strategy_options.keys()).index(st.session_state.rag_strategy),
        help="Choose which RAG pipeline to use. Select a strategy to see detailed description below.",
        key="rag_strategy_selector"
    )

    # Reverse map to get strategy key
    reverse_strategy_map = {v: k for k, v in strategy_options.items()}
    st.session_state.rag_strategy = reverse_strategy_map[selected_strategy_label]

    # Display detailed description for selected strategy
    current_strategy = st.session_state.rag_strategy
    if current_strategy in strategy_descriptions:
        target.info(strategy_descriptions[current_strategy])

    target.caption(f"Selected: {st.session_state.rag_strategy}")

    # Search Scope Selection (Multi-Collection Search)
    if "search_scope" not in st.session_state:
        st.session_state.search_scope = "all"  # Default to search all collections

    scope_options = {
        "all": "🌐 All Documents (system + uploads)",
        "user_only": "📁 My Uploads Only",
        "system_only": "📚 System Data Only"
    }

    selected_scope_label = target.selectbox(
        "Search Scope",
        options=list(scope_options.values()),
        index=list(scope_options.keys()).index(st.session_state.search_scope),
        help="Choose which data sources to search",
        key="search_scope_selector"
    )

    # Reverse map to get scope key
    reverse_scope_map = {v: k for k, v in scope_options.items()}
    st.session_state.search_scope = reverse_scope_map[selected_scope_label]

    target.caption(f"Searching: {st.session_state.search_scope}")

    vector_value = target.slider(
        "Vector Candidate Limit",
        min_value=vector_min,
        max_value=vector_max,
        value=int(st.session_state.rag_vector_limit),
        help="Number of candidate vectors retrieved before reranking",
        key="rag_vector_limit_slider",
    )
    st.session_state.rag_vector_limit = vector_value

    content_value = target.slider(
        "Chunk Character Limit",
        min_value=content_min,
        max_value=content_max,
        value=int(st.session_state.rag_content_limit),
        step=50,
        help="Truncate chunk text to control reranker input length",
        key="rag_content_limit_slider",
    )
    st.session_state.rag_content_limit = content_value

    labels_map = {
        "auto": "🔄 Auto (Adaptive - Query-based)",
        "primary": "🎯 BGE Models (High Accuracy)",
        "fallback": "⚡ MiniLM Models (Fast)",
        "remote": "☁️ Remote",
        "custom": "⚙️ Custom",
    }
    displayed_options = [labels_map.get(opt, opt.title()) for opt in reranker_options]
    current_choice = st.session_state.rag_reranker_choice
    if current_choice not in reranker_options:
        current_choice = reranker_options[0]
    current_index = reranker_options.index(current_choice)

    selected_label = target.selectbox(
        "Model Adapter (Embedding & Reranker)",
        displayed_options,
        index=current_index,
        help="Choose model quality/speed trade-off: Auto switches based on query difficulty, BGE for accuracy, MiniLM for speed",
        key="rag_reranker_choice_select",
    )
    reverse_map = {labels_map.get(opt, opt.title()): opt for opt in reranker_options}
    new_reranker_choice = reverse_map[selected_label]

    # Detect reranker change and trigger warm-up
    if "rag_last_reranker" not in st.session_state:
        st.session_state.rag_last_reranker = None

    if st.session_state.rag_last_reranker is not None and st.session_state.rag_last_reranker != new_reranker_choice:
        # Model adapter changed - call switch-mode endpoint if primary/fallback
        if new_reranker_choice in ["primary", "fallback"]:
            with st.spinner(f"🔄 Switching to {selected_label}..."):
                try:
                    switch_resp = requests.post(
                        f"{BACKEND_URL}/api/rag/switch-mode",
                        params={"mode": new_reranker_choice},
                        timeout=10
                    )
                    if switch_resp.ok:
                        switch_data = switch_resp.json()
                        st.success(
                            f"✅ Switched to {selected_label}\n\n"
                            f"Embedding: {switch_data.get('embedding', '—')}\n\n"
                            f"Reranker: {switch_data.get('reranker', '—')}"
                        )
                    else:
                        st.warning(f"⚠️ Mode switch failed: {switch_resp.text}")
                except Exception as e:
                    st.warning(f"⚠️ Mode switch failed: {e}")

        # Perform warm-up with 3 queries from eval data
        with st.spinner(f"🔥 Warming up {selected_label} (3 queries)..."):
            try:
                # Load real eval questions for warm-up
                warmup_questions = load_warmup_questions()

                for i, question in enumerate(warmup_questions, 1):
                    warmup_response = requests.post(
                        f"{BACKEND_URL}/api/rag/ask",
                        json={
                            "question": question,
                            "top_k": 3,
                            "include_timings": True,  # Use same code path as real queries
                            "reranker": new_reranker_choice,
                            "vector_limit": 5,
                            "content_char_limit": 300
                        },
                        timeout=30
                    )
                st.success(f"✅ {selected_label} fully warmed up!")
                time.sleep(0.5)
            except Exception as e:
                st.warning(f"⚠️ Warm-up failed: {e}")

    st.session_state.rag_reranker_choice = new_reranker_choice
    st.session_state.rag_last_reranker = new_reranker_choice

    model_info = rag_server_config.get("models", {})
    selected_label = labels_map.get(st.session_state.rag_reranker_choice, st.session_state.rag_reranker_choice.title())
    target.caption(
        f"Embedding: `{format_model_label(model_info.get('embedding_current'))}`  "
        f"• Default reranker: `{format_model_label(model_info.get('reranker_current'))}`  "
        f"• Currently selected: `{selected_label}`"
    )

    summary = st.session_state.get("rag_last_summary")
    if summary:
        timings = summary.get("timings") or {}
        models = summary.get("models") or {}
        target.markdown("**Last Query Timing**")
        columns = target.columns(5)
        columns[0].metric("Embed", f"{timings.get('embed_ms', 0.0):.1f}ms")
        columns[1].metric("Vector", f"{timings.get('vector_ms', 0.0):.1f}ms")
        columns[2].metric("Rerank", f"{timings.get('rerank_ms', 0.0):.1f}ms")
        columns[3].metric("LLM", f"{timings.get('llm_ms', 0.0):.1f}ms")
        columns[4].metric("Total", f"{timings.get('end_to_end_ms', 0.0):.1f}ms")

        extra = []
        if summary.get("vector_limit") is not None:
            extra.append(f"vector {summary['vector_limit']}")
        if summary.get("content_limit") is not None:
            extra.append(f"chars {summary['content_limit']}")
        if summary.get("reranker_mode"):
            extra.append(f"mode {summary['reranker_mode']}")
        if extra:
            target.caption(" | ".join(extra))

        usage = summary.get("token_usage") or {}
        cost_usd = float(summary.get("token_cost_usd") or 0.0)
        if usage or cost_usd:
            target.markdown("**Last Query Tokens**")
            token_cols = target.columns(4)
            token_cols[0].metric("Prompt", int(usage.get("prompt", 0) or 0))
            token_cols[1].metric("Completion", int(usage.get("completion", 0) or 0))
            token_cols[2].metric("Total", int(usage.get("total", 0) or 0))
            token_cols[3].metric("Token Cost (USD)", f"${cost_usd:.4f}")

        target.markdown("**Models Used (Last Query)**")
        target.markdown(
            f"- Embedding: `{format_model_label(models.get('embedding'))}`\n"
            f"- Reranker: `{format_model_label(models.get('reranker'))}`\n"
            f"- LLM: `{models.get('llm', '—')}`"
        )

    # Document Upload Section
    target.markdown("---")
    target.markdown("### 📤 Document Upload")

    # Initialize upload stats in session state
    if "upload_stats" not in st.session_state:
        st.session_state.upload_stats = {
            "total_files": 0,
            "total_chunks": 0,
            "last_upload": None
        }

    # Tab for file upload and text paste
    upload_tab, paste_tab = target.tabs(["📁 Upload File", "📝 Paste Text"])

    with upload_tab:
        uploaded_files = st.file_uploader(
            "Choose file(s)",
            type=["pdf", "txt", "docx", "xlsx", "xls", "csv"],
            help="Upload PDF, TXT, Word, Excel, or CSV files to add to the knowledge base",
            key="file_uploader",
            accept_multiple_files=True
        )
        use_separate_collection = st.checkbox(
            "Store uploads in a separate user collection",
            value=False,
            help="Leave unchecked to merge with the main collection so uploads are searchable with existing data.",
            key="use_separate_collection_checkbox",
        )

        if uploaded_files:
            # Show file list
            st.write(f"**{len(uploaded_files)} file(s) selected:**")
            for idx, file in enumerate(uploaded_files, 1):
                st.caption(f"{idx}. {file.name} ({file.size / 1024:.1f} KB)")

            if st.button("🚀 Upload and Vectorize All", key="upload_button"):
                progress_bar = st.progress(0)
                status_text = st.empty()

                total_chunks = 0
                successful_files = 0
                failed_files = []

                for idx, uploaded_file in enumerate(uploaded_files):
                    progress = (idx) / len(uploaded_files)
                    progress_bar.progress(progress)
                    status_text.text(f"Processing {idx + 1}/{len(uploaded_files)}: {uploaded_file.name}...")

                    try:
                        response = requests.post(
                            f"{BACKEND_URL}/api/rag/upload-file",
                            params={"use_separate_collection": str(use_separate_collection).lower()},
                            files={"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)},
                            timeout=120
                        )

                        if response.status_code == 200:
                            result = response.json()
                            collection = result.get("collection")

                            # Update stats
                            st.session_state.upload_stats["total_files"] += 1
                            total_chunks += result["total_chunks"]
                            st.session_state.upload_stats["total_chunks"] += result["total_chunks"]
                            st.session_state.upload_stats["last_upload"] = uploaded_file.name
                            successful_files += 1
                        else:
                            failed_files.append(f"{uploaded_file.name}: {response.text}")
                    except Exception as e:
                        failed_files.append(f"{uploaded_file.name}: {str(e)}")

                # Complete progress
                progress_bar.progress(1.0)
                status_text.text("Upload complete!")

                # Show results
                if successful_files > 0:
                    st.success(f"✅ Successfully processed {successful_files}/{len(uploaded_files)} file(s)")
                    st.info(f"📊 Created {total_chunks} total chunks")

                if failed_files:
                    st.error(f"❌ {len(failed_files)} file(s) failed:")
                    for error in failed_files:
                        st.caption(f"• {error}")

    with paste_tab:
        pasted_text = st.text_area(
            "Paste your text here",
            height=200,
            placeholder="Paste document content here...",
            help="Paste text content to add directly to the knowledge base",
            key="text_paste_area"
        )

        text_title = st.text_input(
            "Document title (optional)",
            placeholder="My Document",
            key="text_title_input"
        )

        if st.button("🚀 Add to Knowledge Base", key="paste_button"):
            if pasted_text.strip():
                with st.spinner("Processing pasted text..."):
                    try:
                        # Send text to backend via upload endpoint
                        title = text_title.strip() or "Pasted Document"
                        response = requests.post(
                            f"{BACKEND_URL}/api/rag/upload",
                            json={
                                "title": title,
                                "content": pasted_text,
                                "source": "user_paste",
                                "metadata": {}
                            },
                            timeout=60
                        )

                        if response.status_code in (200, 201):
                            result = response.json()

                            # Update stats
                            st.session_state.upload_stats["total_files"] += 1
                            st.session_state.upload_stats["total_chunks"] += result["num_chunks"]
                            st.session_state.upload_stats["last_upload"] = title

                            st.success(f"✅ Successfully added '{title}'")
                            st.info(f"📊 Created {result['num_chunks']} chunks")
                        else:
                            st.error(f"❌ Failed to add text: {response.text}")
                    except Exception as e:
                        st.error(f"❌ Error: {str(e)}")
            else:
                st.warning("⚠️ Please paste some text first")

    # Display upload statistics
    if st.session_state.upload_stats["total_files"] > 0:
        target.markdown("**Upload Statistics**")
        col_u1, col_u2 = target.columns(2)
        col_u1.metric("Files Uploaded", st.session_state.upload_stats["total_files"])
        col_u2.metric("Total Chunks", st.session_state.upload_stats["total_chunks"])
        if st.session_state.upload_stats["last_upload"]:
            target.caption(f"Last upload: {st.session_state.upload_stats['last_upload']}")

    # Example Questions Dropdown in Sidebar (below Upload section)
    target.markdown("---")
    target.markdown("### 💡 Example Questions")

    def on_sidebar_example_select():
        selected = st.session_state.get("sidebar_example_selectbox")
        if selected and selected != "Select a question...":
            append_chat_history("user", selected)
            st.session_state.pending_prompt = selected
            # Reset dropdown
            st.session_state["sidebar_example_selectbox"] = "Select a question..."

    target.selectbox(
        "Choose a question to get started:",
        options=["Select a question..."] + EXAMPLE_QUESTIONS_BOTTOM,
        key="sidebar_example_selectbox",
        on_change=on_sidebar_example_select
    )


# =====================================================================
# SessionManager 
# =====================================================================

class SessionManager:
    """SQLite database for managing session state and message history"""

    def __init__(self, db_path: str = "chat_sessions.sqlite3"):
        self.db_path = db_path
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure database tables exist"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_state (
                    session_id TEXT PRIMARY KEY,
                    constraints_json TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_message (
                    session_id TEXT,
                    role TEXT,
                    content TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def load_constraints(self, session_id: str) -> Optional[TripConstraints]:
        """Load constraints from database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT constraints_json FROM session_state WHERE session_id = ?",
                (session_id,)
            )
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    constraints = TripConstraints.model_validate_json(row[0])
                    apply_origin_currency(constraints)
                    return constraints
                except Exception:
                    return None
        return None

    def save_constraints(self, session_id: str, constraints: TripConstraints):
        """Save constraints to database"""
        constraints_json = constraints.model_dump_json()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO session_state (session_id, constraints_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """, (session_id, constraints_json))
            conn.commit()

    def add_message(self, session_id: str, role: str, content: str):
        """Add message to history"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO session_message (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content)
            )
            conn.commit()

    def load_messages(self, session_id: str, limit: int = 50) -> List[Dict[str, str]]:
        """Load message history"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """SELECT role, content FROM session_message
                   WHERE session_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (session_id, limit)
            )
            messages = [
                {"role": row[0], "content": row[1] or ""}  # Convert None to empty string
                for row in cursor.fetchall()
                if row[1]  # Skip messages with null content
            ]
            return list(reversed(messages))


# =====================================================================
# Constraint extraction functions 
# =====================================================================

def parse_constraints_from_text(text: str, existing: Optional[TripConstraints] = None) -> TripConstraints:
    """Extract constraint information from user input (regex approach)"""
    import re

    # Use a copy of existing constraints to avoid modifying the original
    constraints = existing.model_copy(deep=True) if existing else TripConstraints()

    # Extract budget
    money_patterns = [
        (r'(?P<currency>NZ)\s*\$\s*(?P<amount>\d+)', 'NZD'),
        (r'(?P<currency>NZD)\s*(?P<amount>\d+)', 'NZD'),
        (r'budget\s*(?:is|of)?\s*(?P<currency_word>NZD|NZ)\s*\$?\s*(?P<amount>\d+)', 'NZD'),
        (r'(?P<currency>USD|US)\s*\$?\s*(?P<amount>\d+)', 'USD'),
        (r'(?P<currency>AUD|AU)\s*\$?\s*(?P<amount>\d+)', 'AUD'),
        (r'£\s*(?P<amount>\d+)', 'GBP'),
        (r'€\s*(?P<amount>\d+)', 'EUR'),
        (r'budget\s*(?:is|of)?\s*\$?\s*(?P<amount>\d+)', None),
        (r'under\s*\$?\s*(?P<amount>\d+)', None),
        (r'\$\s*(?P<amount>\d+)', None),
        (r'with\s+(?P<amount>\d+)', None),
        (r'\b(?P<amount>\d{2,5})\b', None),
    ]

    for pattern, forced_currency in money_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            groups = match.groupdict()
            amount = groups.get("amount")
            if amount:
                constraints.budget = float(amount)
                if forced_currency:
                    constraints.currency = forced_currency
                else:
                    cur = groups.get("currency") or groups.get("currency_word")
                    if cur:
                        cur_upper = cur.upper()
                        if "NZ" in cur_upper:
                            constraints.currency = "NZD"
                        elif "US" in cur_upper:
                            constraints.currency = "USD"
                        elif "AU" in cur_upper:
                            constraints.currency = "AUD"
                    # If no currency in text, keep existing currency or default to USD
                    elif not constraints.currency:
                        # Prefer to keep the currency from existing constraints
                        if existing and existing.currency:
                            constraints.currency = existing.currency
                        else:
                            constraints.currency = "USD"
                break

    # Extract number of days
    day_patterns = [
        (r'(\d+)[-\s]days?', 1),
        (r'for\s+(\d+)\s+days?', 1),
        (r'(\d+)\s+day\s+trip', 1),
        (r'(\d+)[-\s]weeks?', 7),
        (r'for\s+(\d+)\s+weeks?', 7),
    ]
    for pattern, multiplier in day_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            constraints.days = int(match.group(1)) * multiplier
            break

    # Extract destination and departure
    common_cities = ['Auckland', 'Wellington', 'Christchurch', 'London', 'Paris', 'Tokyo',
                     'New York', 'Sydney', 'Singapore', 'Rome', 'Barcelona', 'Beijing',
                     'Shanghai', 'Guangzhou', 'Shenzhen', 'Hong Kong', 'Taipei', 'Zhuhai']

    for city in common_cities:
        if city.lower() in text.lower():
            if re.search(rf'\b(?:to|visit|in|go)\s+{city}', text, re.IGNORECASE):
                constraints.destination_city = city
            elif re.search(rf'\b(?:from|leaving|depart)\s+{city}', text, re.IGNORECASE):
                constraints.origin_city = city
            elif not constraints.destination_city and not constraints.origin_city:
                constraints.destination_city = city

    # Generic to/from pattern
    to_patterns = [
        r'\b(?:to|visit|visiting|in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
        r'\bgo\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
    ]
    for pattern in to_patterns:
        to_match = re.search(pattern, text)
        if to_match and not constraints.destination_city:
            city_name = to_match.group(1).strip()
            if city_name.lower() not in ['with', 'for', 'from', 'days', 'day', 'week', 'weeks']:
                constraints.destination_city = city_name
                break

    from_patterns = [
        r'\b(?:from|leaving|depart(?:ing)?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
        r'\b([A-Z][a-z]+)\s+to\s+[A-Z]',
    ]
    for pattern in from_patterns:
        from_match = re.search(pattern, text)
        if from_match and not constraints.origin_city:
            city_name = from_match.group(1).strip()
            if city_name.lower() not in ['with', 'for', 'to', 'days', 'day', 'week', 'weeks', 'go', 'plan']:
                constraints.origin_city = city_name
                break

    apply_origin_currency(constraints)
    return constraints

# 1) Place in utility functions section
def _is_quit(msg: Optional[str]) -> bool:
    return bool(msg) and msg.strip().lower() in {"q", "quit", "exit", "cancel"}

def _cleanup_mode_state(old_mode: str) -> None:
    """Clean up state when switching away from a mode"""
    if old_mode == "trip":
        st.session_state.trip_constraints = TripConstraints()
        st.session_state.trip_last_plan = None
        st.session_state.awaiting_confirmation = False
    elif old_mode == "code":
        st.session_state.code_last_request = None
        st.session_state.code_pending_auto = False
        st.session_state.code_force_language = None
    elif old_mode == "rag":
        # RAG doesn't have much state to clean, but reset awaiting_confirmation
        st.session_state.awaiting_confirmation = False

def has_potential_missing_info(text: str) -> bool:
    """Determine if text may contain unextracted city/location information"""
    import re

    capitalized_words = re.findall(r'\b[A-Z][a-z]+\b', text)
    common_words = {'I', 'The', 'A', 'An', 'My', 'We', 'He', 'She', 'It', 'They', 'This', 'That', 'From', 'To'}
    potential_cities = [w for w in capitalized_words if w not in common_words]

    if len(potential_cities) > 0:
        return True

    words = text.strip().split()
    if len(words) == 1 and words[0].isalpha() and len(words[0]) >= 3:
        common_lowercase = {'from', 'to', 'yes', 'no', 'ok', 'sure', 'go', 'the', 'and', 'or', 'but', 'for', 'with'}
        if words[0].lower() not in common_lowercase:
            return True

    return False


def llm_extract_constraints(text: str, existing: Optional[TripConstraints] = None) -> TripConstraints:
    """Use LLM to extract constraint information (fallback approach)"""
    try:
        from openai import OpenAI

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            st.info("💬 General AI Assistant Mode (local fallback)")
            local_reply = (
                "嗨！我已经收到你的消息啦 👋\n\n"
                "目前没有配置 OPENAI_API_KEY，所以先用本地兜底回复。\n"
                "你可以继续问我：\n"
                "- 输入 “trip …” 让我进入行程规划\n"
                "- 输入 “rag …” 让我查文档\n"
                "- 输入 “code …” 让我写代码\n"
            )
            st.markdown(local_reply)
            append_chat_history("assistant", local_reply)
            return existing or TripConstraints()

        client_kwargs = {"api_key": api_key}
        base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        if base_url:
            client_kwargs["base_url"] = base_url
        client = OpenAI(**client_kwargs)

        existing_json = existing.model_dump() if existing else {}

        missing_fields = []
        if not existing_json.get('destination_city'):
            missing_fields.append('destination')
        if not existing_json.get('origin_city'):
            missing_fields.append('origin')

        context_hint = ""
        if missing_fields:
            context_hint = f"\nContext: We are asking the user about: {', '.join(missing_fields)}"

        prompt = f"""Extract trip planning information from the user's message. Return ONLY a JSON object.

User message: "{text}"{context_hint}

Current information: {json.dumps(existing_json, ensure_ascii=False)}

Extract and return JSON with these fields (keep existing values if not mentioned):
{{
    "destination_city": "destination city name or null",
    "origin_city": "origin city name or null",
    "days": number of days or null,
    "budget": number or null,
    "currency": "USD/NZD/AUD/GBP/EUR or null"
}}

Rules:
- Any city name worldwide is valid (e.g., Zhuhai, Auckland, Beijing, Macau, etc.)
- If user provides a single city name when origin is missing, assume it's the origin city
- If user says "1 week", convert to days: 7
- Default currency is USD if $ is mentioned without specification
- Return null for missing information
- ONLY return the JSON object, no explanation"""

        messages = sanitize_messages([
            {"role": "user", "content": prompt}
        ])

        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=messages,
            temperature=0,
            max_tokens=200
        )

        result_text = response.choices[0].message.content.strip()

        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]

        extracted = json.loads(result_text)

        constraints = existing or TripConstraints()
        if extracted.get("destination_city"):
            constraints.destination_city = extracted["destination_city"]
        if extracted.get("origin_city"):
            constraints.origin_city = extracted["origin_city"]
        if extracted.get("days"):
            constraints.days = int(extracted["days"])
        if extracted.get("budget"):
            constraints.budget = float(extracted["budget"])
        if extracted.get("currency"):
            constraints.currency = extracted["currency"]

        apply_origin_currency(constraints)
        return constraints

    except Exception as e:
        return existing or TripConstraints()


def extract_constraints_hybrid(text: str, existing: Optional[TripConstraints] = None) -> tuple:
    """Hybrid extraction: try regex first, fallback to LLM if key information not found"""
    base_constraints = existing or TripConstraints()
    old_constraints = base_constraints.model_copy(deep=True)
    constraints = parse_constraints_from_text(text, base_constraints)

    new_dest = constraints.destination_city != old_constraints.destination_city
    new_origin = constraints.origin_city != old_constraints.origin_city
    has_new_city = new_dest or new_origin

    if not has_new_city and has_potential_missing_info(text):
        words = text.strip().split()
        if len(words) == 1 and words[0].isalpha():
            capitalized = words[0].capitalize()
            constraints = parse_constraints_from_text(capitalized, existing)
            new_dest = constraints.destination_city != old_constraints.destination_city
            new_origin = constraints.origin_city != old_constraints.origin_city
            if new_dest or new_origin:
                return constraints, False

        constraints = llm_extract_constraints(text, constraints)
        return constraints, True

    return constraints, False


def check_constraints_complete(constraints: TripConstraints) -> tuple:
    """Check if all four required elements are complete"""
    missing = []
    if not constraints.destination_city:
        missing.append("destination")
    if not constraints.origin_city:
        missing.append("origin")
    if not constraints.days or constraints.days < 1:
        missing.append("days")
    if not constraints.budget or constraints.budget < 0:
        missing.append("budget")

    return len(missing) == 0, missing


def validate_constraints(constraints: TripConstraints) -> tuple:
    """Validate if constraints are reasonable"""
    issues = []

    if constraints.days and (constraints.days < 1 or constraints.days > 30):
        issues.append(f"Trip duration {constraints.days} days seems unrealistic (should be 1-30)")

    if constraints.budget is not None:
        currency = constraints.currency or infer_currency_from_origin(constraints.origin_city) or "USD"
        budget_value = float(constraints.budget)
        budget_usd = convert_currency(budget_value, currency, "USD")
        if currency.upper() == "USD" and budget_usd is None:
            budget_usd = budget_value

        if budget_usd is not None:
            if budget_usd < 150:
                issues.append(
                    f"Budget {currency} {budget_value:.0f} seems too low (≈ USD {budget_usd:.0f})"
                )
            elif budget_usd > 25000:
                issues.append(
                    f"Budget {currency} {budget_value:.0f} seems exceptionally high (≈ USD {budget_usd:.0f})"
                )

    if constraints.origin_city and constraints.destination_city:
        if constraints.origin_city.lower().strip() == constraints.destination_city.lower().strip():
            issues.append("Origin and destination are the same")

    return len(issues) == 0, issues


def format_constraints_summary(constraints: TripConstraints) -> str:
    """Format constraint summary"""
    lines = []
    if constraints.destination_city:
        lines.append(f"📍 Destination: {constraints.destination_city}")
    if constraints.origin_city:
        lines.append(f"🛫 Origin: {constraints.origin_city}")
    if constraints.days:
        lines.append(f"📅 Duration: {constraints.days} days")
    if constraints.budget is not None:
        currency_label = constraints.currency or infer_currency_from_origin(constraints.origin_city) or "—"
        lines.append(f"💰 Budget: {currency_label} {constraints.budget:.2f}")
    if constraints.preferences:
        lines.append(f"❤️ Preferences: {', '.join(constraints.preferences)}")

    return "\n".join(lines) if lines else "No information collected yet"


def render_trip_plan_summary(plan: Dict[str, Any]) -> None:
    """Display a compact summary of the most recent trip plan."""
    itinerary = plan.get("itinerary") or {}
    destination = itinerary.get("destination", "Unknown")
    currency = (itinerary.get("currency") or "-").upper()
    total_cost = itinerary.get("total_cost")
    total_cost_usd = itinerary.get("total_cost_usd")
    days = len(itinerary.get("daily_plan") or [])

    st.markdown(f"**📍 Destination:** {destination}")
    st.markdown(f"**📅 Duration:** {days or '—'} days")
    if total_cost is not None:
        cost_line = f"**💵 Total:** {currency} {total_cost:.2f}"
        if total_cost_usd:
            cost_line += f" (≈ USD {total_cost_usd:.2f})"
        st.markdown(cost_line)

    flights = itinerary.get("flights") or []
    if flights:
        st.markdown("**✈️ Flights:**")
        for flight in flights[:2]:
            airline = flight.get("airline", "Unknown airline")
            number = flight.get("flight_number", "N/A")
            price = flight.get("price")
            flight_currency = (flight.get("currency") or currency).upper()
            line = f"- {airline} {number}"
            if price is not None:
                line += f" — {flight_currency} {price:.2f}"
            st.markdown(line)

    cost_breakdown = itinerary.get("cost_breakdown") or {}
    if cost_breakdown:
        st.markdown("**Cost Breakdown:**")
        for label, key in [("Flights", "flights"), ("Accommodation", "accommodation"), ("Meals", "meals"), ("Transport & Activities", "other")]:
            amount = cost_breakdown.get(key)
            if amount:
                st.markdown(f"- {label}: {currency} {float(amount):.2f}")

    token_usage = plan.get("llm_token_usage") or {}
    token_cost = plan.get("llm_cost_usd") or 0.0
    if token_usage or token_cost:
        st.markdown("**LLM Token Usage:**")
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("Prompt", int(token_usage.get("prompt", 0) or 0))
        col_b.metric("Completion", int(token_usage.get("completion", 0) or 0))
        col_c.metric("Total", int(token_usage.get("total", (token_usage.get("prompt", 0) or 0) + (token_usage.get("completion", 0) or 0))))
        col_d.metric("Token Cost", f"${float(token_cost):.4f}")

    currency_note = itinerary.get("currency_note")
    if currency_note:
        st.caption(currency_note)

    fx_rates = itinerary.get("fx_rates") or {}
    if fx_rates:
        fx_lines = []
        for key, value in fx_rates.items():
            if not isinstance(value, (int, float)):
                continue
            if "->" in key:
                src, tgt = key.split("->", 1)
                fx_lines.append(f"1 {src.upper()} ≈ {value:.4f} {tgt.upper()}")
            else:
                fx_lines.append(f"1 {key.upper()} ≈ {value:.4f} {currency}")
        if fx_lines:
            st.caption("FX rates: " + "; ".join(fx_lines))

# =====================================================================
# Streamlit UI Configuration
# =====================================================================

st.set_page_config(
    page_title="AI Assistant",
    page_icon="🤖",
    layout="wide"
)

st.markdown(
    """
    <style>
        div[data-testid="stMetricValue"] {
            font-size: 1.6rem;
        }
        div[data-testid="stMetricLabel"] {
            font-size: 0.85rem;
        }
        div[data-testid="stMetricDelta"] {
            font-size: 0.75rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# Initialize session state
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())[:8]

if "messages" not in st.session_state:
    st.session_state.messages = []

if "mode" not in st.session_state:
    st.session_state.mode = "general"  # Default to general assistant mode

if "trip_constraints" not in st.session_state:
    st.session_state.trip_constraints = TripConstraints()

if "session_mgr" not in st.session_state:
    st.session_state.session_mgr = SessionManager()

if "first_activation" not in st.session_state:
    st.session_state.first_activation = {"rag": True, "trip": True, "code": True}

if "awaiting_confirmation" not in st.session_state:
    st.session_state.awaiting_confirmation = False

# Mode activation messages
MODE_ACTIVATION_MESSAGES = {
    "rag": """📚 **RAG Q&A Mode Activated**

I'll help you search and answer questions from the document collection.

---

- **Examples:**

- "Who wrote DADDY TAKE ME SKATING?"
- "Tell me about American frontier history"
- "'Sir roberts fortune a novel', show me roles relationship"
- "'Sir roberts fortune a novel', list all the roles"
- "'Sir roberts fortune a novel', for what purpose he was confident of his own powers of cheating the uncle, and managing?"

---

- Type 'q'(quit) to exit this mode.
""",
    "trip": """✈️ **Trip Planning Mode Activated**

I'll help you plan your perfect trip! I need to collect four key pieces of information:
- 📍 Where do you want to go?
- 🛫 Where are you leaving from?
- 📅 How many days?
- 💰 What's your budget?

---

**Examples:**

- "I want to go to Tokyo from Auckland for 5 days with $2000"
- "Plan a trip to Paris, 1 week, budget 3000 NZD, from Wellington"

---

Type 'q'(quit) to exit this mode.
""",
    "code": """💻 **Code Generation Mode Activated**

I'll generate code with automated tests and self-healing capabilities!

---

**Examples:**

1. "Write a function to check if a number is prime"
2. "Create a binary search algorithm in Python"
3. "Implement a quick sort in JavaScript"
4. Classic Problem - Most Frequent Character:
   ```
   def most_frequent_char(s: str) -> str:
       # Return the character that appears most frequently in the string s.
       # If there are multiple characters with the same highest frequency,
       # return the one that comes first in alphabetical order.
   ```
   Example: `most_frequent_char("abracadabra")` → Expected: `a`

---

Type 'q'(quit) to exit this mode.
""",
}

def switch_mode(new_mode: str, always_show_message: bool = False):
    """Helper function to switch modes and optionally show activation message"""
    old_mode = st.session_state.mode
    _cleanup_mode_state(old_mode)
    st.session_state.mode = new_mode
    st.session_state.pending_prompt = "__MODE_ACTIVATED__"

    # Show message if it's first activation OR always_show_message is True
    if st.session_state.first_activation.get(new_mode, False) or always_show_message:
        if new_mode in MODE_ACTIVATION_MESSAGES:
            append_chat_history("assistant", MODE_ACTIVATION_MESSAGES[new_mode])
        if st.session_state.first_activation.get(new_mode, False):
            st.session_state.first_activation[new_mode] = False

# Show Smart RAG warm-up status only if weights are missing
def show_smart_status():
    try:
        resp = requests.get(f"{BACKEND_URL}/api/rag/smart-status", timeout=3)
        return resp.json()
    except Exception:
        return {}

smart_status = show_smart_status()

# Only show warm-up notifications if bandit state was cold-started (no weights found)
# Check if bandit state is using default uniform priors (cold start)
is_cold_start = smart_status.get("cold_start", False)

# Notify in main panel only if cold start AND warm-up completes
if "smart_warmup_notified" not in st.session_state:
    st.session_state.smart_warmup_notified = False

if is_cold_start and smart_status.get("enabled") and smart_status.get("done") and not st.session_state.smart_warmup_notified:
    st.session_state.smart_warmup_notified = True
    st.success("✅ Smart RAG warm-up completed - bandit weights are now available")
elif is_cold_start and smart_status.get("enabled") and smart_status.get("started") and not smart_status.get("done"):
    total = smart_status.get("total") or 0
    completed = smart_status.get("completed") or 0
    progress = f"{completed}/{total}" if total else f"{completed}"
    st.warning(f"⚠️ No bandit weights found - warm-up running in background... ({progress}). You can keep using the app.")

# Check Qdrant seed status and block RAG if not ready
def check_seed_status():
    try:
        resp = requests.get(f"{BACKEND_URL}/api/rag/seed-status", timeout=3)
        return resp.json()
    except Exception:
        return {"state": "error", "message": "Cannot connect to backend"}

seed_status = check_seed_status()
seed_state = seed_status.get("state", "unknown")

# Initialize seed notification flag
if "seed_ready_notified" not in st.session_state:
    st.session_state.seed_ready_notified = False

# Show blocking message if seed is not completed
if seed_state in ["checking", "counting", "initializing", "in_progress"]:
    seeded = seed_status.get("seeded", 0)
    total = seed_status.get("total", 1)
    message = seed_status.get("message", "")

    # Unified warm-up progress display (all stages with consistent yellow warning)
    st.warning(f"🔥 **Smart RAG Warm-up in Progress**")

    # Determine progress and stage message based on state
    if seed_state == "counting":
        progress_pct = 50  # Indeterminate for counting
        stage_message = "**Step 1/2: Counting vectors in seed file**"
        detail_message = f"{message}\n\n⏳ Please wait ~10-15 seconds while counting..."
    elif seed_state == "initializing":
        progress_pct = 75  # Indeterminate for batch prep
        stage_message = "**Step 1/2: Preparing batches for upload**"
        detail_message = f"{message}\n\n⏳ Please wait ~30 seconds while preparing batches..."
    else:  # in_progress or checking
        progress_pct = (seeded / total * 100) if total > 0 else 5
        stage_message = "**Step 2/2: Uploading vectors to Qdrant**"
        detail_message = f"Progress: **{seeded:,} / {total:,}** vectors ({progress_pct:.1f}%)"

    # Show progress bar
    st.progress(progress_pct / 100.0 if progress_pct > 0 else 0.01)

    # Show stage details
    st.markdown(f"""
    {stage_message}

    {detail_message}

    This is a one-time setup that happens on first startup.

    You can use other modes (Code, Trip Planning, Stats) in the meantime.
    """)

    # Store that seed is NOT ready
    st.session_state.seed_is_ready = False

    # Use st.empty() for smooth updates and auto-refresh
    time.sleep(2)
    st.rerun()

elif seed_state == "completed":
    # Seed is ready, now check warm-up status
    st.session_state.seed_is_ready = True

    # Check if warm-up is also complete
    if "warmup_ready_notified" not in st.session_state:
        st.session_state.warmup_ready_notified = False

    if not st.session_state.warmup_ready_notified:
        # Check warm-up status
        try:
            warmup_resp = requests.get(f"{BACKEND_URL}/api/rag/smart-status", timeout=3)
            if warmup_resp.ok:
                warmup_status = warmup_resp.json()
                warmup_enabled = warmup_status.get("enabled", False)
                warmup_done = warmup_status.get("done", False)
                warmup_total = warmup_status.get("total", 0)
                warmup_completed = warmup_status.get("completed", 0)
                warmup_error = warmup_status.get("last_error")

                if not warmup_enabled:
                    # Warm-up disabled, mark as ready
                    st.success("✅ Qdrant vector database is ready!")
                    st.info("ℹ️ Smart RAG warm-up disabled (WARM_SMART_RAG=0)")
                    st.session_state.warmup_ready_notified = True
                    st.session_state.seed_ready_notified = True
                elif warmup_error:
                    # Warm-up failed but continue
                    st.success("✅ Qdrant vector database is ready!")
                    st.warning(f"⚠️ Smart RAG warm-up failed: {warmup_error}")
                    st.session_state.warmup_ready_notified = True
                    st.session_state.seed_ready_notified = True
                elif not warmup_done:
                    # Warm-up in progress - BLOCK here
                    if warmup_total > 0:
                        progress = warmup_completed / warmup_total * 100
                        st.warning(f"🔥 **Smart RAG Warm-up in Progress**")
                        st.progress(progress / 100.0)
                        st.markdown(f"""
                        **Warming up RAG models for faster queries...**

                        Progress: **{warmup_completed} / {warmup_total}** queries ({progress:.0f}%)

                        ⏳ Please wait ~30-60 seconds for warm-up to complete.

                        This is a one-time process that happens after Qdrant seeding.
                        """)
                    else:
                        st.info("🔥 Warming up Smart RAG models...")

                    # Auto-refresh to check progress
                    time.sleep(2)
                    st.rerun()
                else:
                    # Warm-up complete!
                    st.success("✅ System fully initialized!")
                    st.success(f"🔥 Smart RAG models warmed up ({warmup_total} queries)")
                    st.session_state.warmup_ready_notified = True
                    st.session_state.seed_ready_notified = True
        except Exception as e:
            # Can't check warm-up status, just notify seed ready
            st.success("✅ Qdrant vector database is ready!")
            st.warning(f"⚠️ Could not check warm-up status: {e}")
            st.session_state.warmup_ready_notified = True
            st.session_state.seed_ready_notified = True

elif seed_state == "error":
    st.error(f"❌ Qdrant seeding failed: {seed_status.get('message', 'Unknown error')}")
    st.session_state.seed_is_ready = False

else:
    # Unknown state - assume ready to avoid blocking
    st.session_state.seed_is_ready = True

if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None

# Metrics tracking
if "metrics_history" not in st.session_state:
    st.session_state.metrics_history = {
        "timestamps": [],
        "latencies": [],
        "prompt_tokens": [],
        "completion_tokens": [],
        "costs": [],
        "services": []  # "rag", "trip", "code"
    }

if "rag_metrics" not in st.session_state:
    st.session_state.rag_metrics = {
        "embed_times": [],
        "rerank_times": [],
        "retrieval_times": [],
        "confidences": []
    }

if "agent_stats" not in st.session_state:
    st.session_state.agent_stats = {
        "success": 0,
        "failure": 0,
        "partial": 0
    }

if "trip_last_plan" not in st.session_state:
    st.session_state.trip_last_plan = None

if "rag_stats" not in st.session_state:
    st.session_state.rag_stats = {
        "total_queries": 0,
        "total_retrieval_ms": 0.0,
        "total_rerank_ms": 0.0,
        "total_llm_ms": 0.0,
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "avg_confidence": 0.0,
        "primary_reranker_count": 0,
        "fallback_reranker_count": 0,
    }

if "code_stats" not in st.session_state:
    st.session_state.code_stats = {
        "total_runs": 0,
        "passes": 0,
        "failures": 0,
        "errors": 0,
        "total_latency_ms": 0.0,
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "history": [],
    }

if "code_show_samples" not in st.session_state:
    st.session_state.code_show_samples = True

if "code_show_samples_prev" not in st.session_state:
    st.session_state.code_show_samples_prev = True

if "code_last_request" not in st.session_state:
    st.session_state.code_last_request: Optional[Dict[str, Any]] = None

if "code_pending_auto" not in st.session_state:
    st.session_state.code_pending_auto = False

# ---- EARLY ROUTING GUARD: consume pending before any UI can rerun ----
early_prompt = None
if st.session_state.get("pending_prompt") and st.session_state.get("mode") in {"rag", "trip", "code", "general"}:
    # Consume pending_prompt early to avoid interruption by startup prompt/buttons
    early_prompt = st.session_state.pending_prompt
    st.session_state.pending_prompt = None
    # Skip startup guide when pending exists, go directly to corresponding branch
    # BUT: Don't skip first_activation if pending is __MODE_ACTIVATED__ (mode just activated)
    if ("first_activation" in st.session_state and
        st.session_state.mode in st.session_state.first_activation and
        early_prompt != "__MODE_ACTIVATED__"):  # ✅ Don't skip startup when mode is activated
        st.session_state.first_activation[st.session_state.mode] = False
    debug_log(f"[guard] consumed pending for mode={st.session_state.mode} prompt={early_prompt!r}")
else:
    debug_log(f"[guard] no pending to consume (mode={st.session_state.get('mode')}, pending={st.session_state.get('pending_prompt')!r})")

# st.sidebar.caption(
#     f"DEBUG • mode={st.session_state.mode} "
#     f"pending={st.session_state.pending_prompt!r} "
#     f"await_confirm={st.session_state.awaiting_confirmation}"
# )
if "code_force_language" not in st.session_state:
    st.session_state.code_force_language: Optional[str] = None

rag_server_config = get_rag_server_config()
rag_limits = rag_server_config.get("limits", {})
vector_min = int(rag_limits.get("vector_min", 6))
vector_max = int(rag_limits.get("vector_max", 20))
content_min = int(rag_limits.get("content_char_min", 150))
content_max = int(rag_limits.get("content_char_max", 1000))
content_default = int(rag_limits.get("content_char_default", 300))
reranker_options = rag_server_config.get("reranker_options", ["auto"])

if "rag_vector_limit" not in st.session_state:
    st.session_state.rag_vector_limit = vector_min
else:
    st.session_state.rag_vector_limit = int(max(vector_min, min(vector_max, st.session_state.rag_vector_limit)))

if "rag_content_limit" not in st.session_state:
    st.session_state.rag_content_limit = content_default
else:
    st.session_state.rag_content_limit = int(max(content_min, min(content_max, st.session_state.rag_content_limit)))

if "rag_reranker_choice" not in st.session_state:
    # Default to fallback (MiniLM) for CPU performance
    st.session_state.rag_reranker_choice = "fallback" if "fallback" in reranker_options else (reranker_options[0] if reranker_options else "auto")
elif st.session_state.rag_reranker_choice not in reranker_options:
    st.session_state.rag_reranker_choice = "fallback" if "fallback" in reranker_options else (reranker_options[0] if reranker_options else "auto")

if "show_governance_info" not in st.session_state:
    st.session_state.show_governance_info = False

if "show_rag_examples_inline" not in st.session_state:
    st.session_state.show_rag_examples_inline = False


# =====================================================================
# Sidebar - Service Status and Evaluation Dashboard
# =====================================================================
with st.sidebar:
    st.title("🎛️ Dashboard")

    st.markdown("### 📊 Service Status")

    # Check service status
    try:
        rag_health = check_service_health(f"{BACKEND_URL}/api/rag/health")
    except:
        rag_health = False

    try:
        agent_health = check_service_health(f"{BACKEND_URL}/api/agent/health")
    except:
        agent_health = False

    try:
        code_health = check_service_health(f"{BACKEND_URL}/api/code/health")
    except:
        code_health = False

    # Display service status
    rag_status = "🟢" if rag_health else "🔴"
    agent_status = "🟢" if agent_health else "🔴"
    code_status = "🟢" if code_health else "🔴"

    rag_active = "✅" if st.session_state.mode == "rag" else ""
    agent_active = "✅" if st.session_state.mode == "trip" else ""
    code_active = "✅" if st.session_state.mode == "code" else ""

    st.markdown(f"{rag_status} **RAG Q&A** {rag_active}")
    st.markdown(f"{agent_status} **Trip Planning** {agent_active}")
    st.markdown(f"{code_status} **Code Generation** {code_active}")

    st.markdown("---")

    # AI Governance Info
    st.markdown("### 🛡️ AI Governance")
    if st.button("📖 View Governance Framework", use_container_width=True):
        st.session_state.show_governance_info = True

    # AI Governance Dashboard Link
    st.link_button(
        "📊 AI Governance Dashboard",
        "http://localhost:3000/d/ai-governance-dashboard/ai-governance-dashboard?orgId=1&refresh=10s",
        use_container_width=True
    )

    st.markdown("---")

    st.markdown("### 📈 Evaluation Dashboard")

    agent_metrics_data: Optional[Dict[str, Any]] = None
    try:
        metrics_resp = requests.get(f"{BACKEND_URL}/api/agent/metrics", timeout=2)
        if metrics_resp.status_code == 200:
            agent_metrics_data = metrics_resp.json()
    except Exception:
        agent_metrics_data = None

    # Basic statistics
    num_messages = len(st.session_state.messages)
    col1, col2 = st.columns(2)
    col1.metric("Messages", num_messages)

    if st.session_state.mode:
        col2.metric("Mode", st.session_state.mode.upper())
    else:
        col2.metric("Mode", "None")

    # Latency Latency & Cost Trends - Always display Cost Trends - Always display
    st.markdown("**⏱️ Latency Over Time**")
    if len(st.session_state.metrics_history["latencies"]) > 0:
        df = pd.DataFrame({
            "Request": range(1, len(st.session_state.metrics_history["latencies"]) + 1),
            "Latency (ms)": st.session_state.metrics_history["latencies"]
        })
        st.line_chart(df.set_index("Request"))

        # Display mean and median
        latencies = st.session_state.metrics_history["latencies"]
        avg_lat = np.mean(latencies)
        median_lat = np.median(latencies)
        col_a, col_b = st.columns(2)
        col_a.metric("Avg", f"{avg_lat:.0f}ms")
        col_b.metric("Median", f"{median_lat:.0f}ms")
    else:
        st.info("📊 No data yet - waiting for first request")

    # Cost Trends - Always display
    st.markdown("**💰 Token Cost Tracking**")
    if len(st.session_state.metrics_history["costs"]) > 0:
        total_cost = sum(st.session_state.metrics_history["costs"])
        st.metric("Total Token Cost", f"${total_cost:.4f}")

        df_cost = pd.DataFrame({
            "Request": range(1, len(st.session_state.metrics_history["costs"]) + 1),
            "Token Cost ($)": st.session_state.metrics_history["costs"]
        })
        st.line_chart(df_cost.set_index("Request"))
    else:
        col_c1, col_c2 = st.columns(2)
        col_c1.metric("Total Token Cost", "$0.0000")
        col_c2.metric("Requests", "0")

    # RAG Performance Metrics
    if len(st.session_state.rag_metrics["retrieval_times"]) > 0:
        st.markdown("**📚 RAG Performance**")

        retrieval_times = st.session_state.rag_metrics["retrieval_times"]
        confidences = st.session_state.rag_metrics["confidences"]

        # Retrieval time statistics
        if retrieval_times:
            avg_retrieval = np.mean(retrieval_times)
            median_retrieval = np.median(retrieval_times)
            col_r1, col_r2 = st.columns(2)
            col_r1.metric("Avg Retrieval", f"{avg_retrieval:.1f}ms")
            col_r2.metric("Median", f"{median_retrieval:.1f}ms")

        # Accuracy/Confidence trends
        if confidences:
            st.markdown("**Confidence Over Time**")
            df_conf = pd.DataFrame({
                "Query": range(1, len(confidences) + 1),
                "Confidence": confidences
            })
            st.line_chart(df_conf.set_index("Query"))

            avg_conf = np.mean(confidences)
            st.metric("Avg Confidence", f"{avg_conf:.3f}")
    st.markdown("---")

    # RAG Q&A Stats
    st.markdown("**📚 RAG Q&A Stats**")
    rag_stats = st.session_state.rag_stats
    total_rag_queries = rag_stats["total_queries"]

    if total_rag_queries > 0:
        # Use smaller font for sidebar metrics
        st.markdown("""
        <style>
        section[data-testid="stSidebar"] [data-testid="stMetricValue"] {
            font-size: 18px;
        }
        </style>
        """, unsafe_allow_html=True)

        col_rag1, col_rag2, col_rag3, col_rag4 = st.columns(4)
        col_rag1.metric("Total Queries", total_rag_queries)
        col_rag2.metric("Avg Confidence", f"{rag_stats['avg_confidence']:.3f}")
        col_rag3.metric("Primary Uses", rag_stats["primary_reranker_count"])
        col_rag4.metric("Fallback Uses", rag_stats["fallback_reranker_count"])

        # Average latencies
        avg_retrieval = rag_stats["total_retrieval_ms"] / total_rag_queries
        avg_rerank = rag_stats["total_rerank_ms"] / total_rag_queries
        avg_llm = rag_stats["total_llm_ms"] / total_rag_queries
        avg_total = (rag_stats["total_retrieval_ms"] + rag_stats["total_llm_ms"]) / total_rag_queries

        st.markdown("**Average Latency**")
        col_lat1, col_lat2, col_lat3, col_lat4 = st.columns(4)
        col_lat1.metric("Retrieval", f"{avg_retrieval:.1f}ms")
        col_lat2.metric("Rerank", f"{avg_rerank:.1f}ms")
        col_lat3.metric("LLM", f"{avg_llm:.1f}ms")
        col_lat4.metric("Total", f"{avg_total:.1f}ms")

        # Token usage and cost
        avg_tokens = rag_stats["total_tokens"] / total_rag_queries
        total_cost = rag_stats["total_cost_usd"]

        col_tok1, col_tok2 = st.columns(2)
        col_tok1.metric("Avg Tokens/Query", f"{avg_tokens:.0f}")
        col_tok2.metric("Total Cost (USD)", f"${total_cost:.4f}")
    else:
        st.caption("No RAG queries yet")

    st.markdown("---")
    # Agent Success Rate - Always display
    st.markdown("**✈️ Trip Agent Stats**")
    agent_stats = st.session_state.agent_stats
    total_attempts = agent_stats["success"] + agent_stats["failure"] + agent_stats["partial"]

    if agent_metrics_data:
        st.caption("Aggregated across all sessions")
        col_s1, col_s2, col_s3 = st.columns(3)
        col_s1.metric("✅", agent_metrics_data.get("success_plans", 0))
        col_s2.metric("⚠️", agent_metrics_data.get("partial_plans", 0))
        col_s3.metric("❌", agent_metrics_data.get("failed_plans", 0))

        col_rate, col_cost = st.columns(2)
        col_rate.metric("Success Rate", f"{agent_metrics_data.get('success_rate', 0.0):.1f}%")
        col_cost.metric("Token Cost (USD)", f"${agent_metrics_data.get('total_cost_usd', 0.0):.4f}")

        col_avg1, col_avg2 = st.columns(2)
        col_avg1.metric("Avg Planning Time", f"{agent_metrics_data.get('avg_planning_time_ms', 0.0):.0f}ms")
        col_avg2.metric("Avg Tool Calls", f"{agent_metrics_data.get('avg_tool_calls_per_plan', 0.0):.1f}")

        history_entries = agent_metrics_data.get("history") or []
        if history_entries:
            st.markdown("**Recent Runs**")
            recent_entries = history_entries[-3:]
            for entry in reversed(recent_entries):
                timestamp_str = entry.get("timestamp")
                display_time = timestamp_str
                if timestamp_str:
                    try:
                        display_time = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")).strftime("%H:%M:%S")
                    except Exception:
                        display_time = timestamp_str
                outcome = entry.get("outcome", "unknown").title()
                planning_ms = entry.get("planning_time_ms", 0.0)
                cost_usd = entry.get("token_cost_usd", entry.get("cost_usd", 0.0))
                st.caption(f"{display_time} • {outcome} • {planning_ms:.0f}ms • Token Cost ${cost_usd:.4f}")

        if total_attempts > 0:
            st.caption(
                f"This session: {agent_stats['success']} success / "
                f"{agent_stats['partial']} partial / {agent_stats['failure']} failure"
            )
    else:
        col_s1, col_s2, col_s3 = st.columns(3)
        col_s1.metric("✅", agent_stats["success"])
        col_s2.metric("⚠️", agent_stats["partial"])
        col_s3.metric("❌", agent_stats["failure"])

        if total_attempts > 0:
            success_rate = (agent_stats["success"] / total_attempts) * 100
            st.metric("Success Rate", f"{success_rate:.1f}%")
        else:
            st.metric("Success Rate", "N/A")
    st.markdown("---")

    # Trip Learning Dashboard
    st.markdown("**✈️ 🎓 Trip Learning Dashboard**")
    if "learning_history" in st.session_state and len(st.session_state.learning_history["rewards"]) > 0:
        learning_hist = st.session_state.learning_history

        # Overall statistics
        avg_reward = np.mean(learning_hist["rewards"])
        latest_reward = learning_hist["rewards"][-1]
        total_runs = len(learning_hist["rewards"])

        col_l1, col_l2 = st.columns(2)
        col_l1.metric("Total Runs", total_runs)
        col_l2.metric("Avg Reward", f"{avg_reward:.3f}")

        # Latest reward with trend
        if len(learning_hist["rewards"]) >= 2:
            prev_reward = learning_hist["rewards"][-2]
            reward_delta = latest_reward - prev_reward
            delta_text = f"{reward_delta:+.3f}" if reward_delta != 0 else "—"
        else:
            delta_text = None

        st.metric("Latest Reward", f"{latest_reward:.3f}", delta=delta_text)

        # Reward trend chart
        st.markdown("**Reward Trend**")
        df_reward = pd.DataFrame({
            "Run": range(1, len(learning_hist["rewards"]) + 1),
            "Reward": learning_hist["rewards"]
        })
        st.line_chart(df_reward.set_index("Run"))

        # Component breakdown (latest)
        if len(learning_hist["budget_rewards"]) > 0:
            st.markdown("**Latest Component Rewards**")
            latest_budget = learning_hist["budget_rewards"][-1]
            latest_quality = learning_hist["quality_rewards"][-1]
            latest_reliability = learning_hist["reliability_rewards"][-1]

            col_c1, col_c2, col_c3 = st.columns(3)
            col_c1.metric("💰", f"{latest_budget:.2f}")
            col_c2.metric("⭐", f"{latest_quality:.2f}")
            col_c3.metric("🔧", f"{latest_reliability:.2f}")

        # Strategy distribution
        strategy_counts = {}
        for strategy in learning_hist["strategies"]:
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1

        if strategy_counts:
            st.markdown("**Strategy Usage**")
            for strategy, count in sorted(strategy_counts.items(), key=lambda x: x[1], reverse=True):
                percentage = (count / total_runs) * 100
                st.caption(f"{strategy}: {count} times ({percentage:.1f}%)")

        # Show learning objectives progress (if we have targets)
        st.markdown("**📈 Learning Objectives**")

        # Calculate metrics for objectives
        if total_runs >= 3:
            recent_rewards = learning_hist["rewards"][-min(10, total_runs):]

            # Budget optimization (target: >0.7)
            avg_budget = np.mean(learning_hist["budget_rewards"][-min(10, total_runs):])
            budget_target = 0.7
            budget_progress = min(avg_budget / budget_target, 1.0)
            st.markdown(f"💰 Budget Optimization: {avg_budget:.2f} / {budget_target:.2f}")
            st.progress(budget_progress)

            # Quality (target: >0.7)
            avg_quality = np.mean(learning_hist["quality_rewards"][-min(10, total_runs):])
            quality_target = 0.7
            quality_progress = min(avg_quality / quality_target, 1.0)
            st.markdown(f"⭐ Quality: {avg_quality:.2f} / {quality_target:.2f}")
            st.progress(quality_progress)

            # Reliability (target: >0.8)
            avg_reliability = np.mean(learning_hist["reliability_rewards"][-min(10, total_runs):])
            reliability_target = 0.8
            reliability_progress = min(avg_reliability / reliability_target, 1.0)
            st.markdown(f"🔧 Reliability: {avg_reliability:.2f} / {reliability_target:.2f}")
            st.progress(reliability_progress)
        else:
            st.caption("Need at least 3 runs to show objectives")
    else:
        st.caption("No learning data yet - start planning trips!")

    st.markdown("---")
    st.markdown("**💻 Code Agent Stats**")
    code_stats = st.session_state.code_stats
    total_runs_code = code_stats["total_runs"]
    col_code1, col_code2, col_code3, col_code4 = st.columns(4)
    col_code1.metric("Runs", total_runs_code)
    col_code2.metric("Passes", code_stats["passes"])
    col_code3.metric("Failed Tests", code_stats["failures"])
    col_code4.metric("Errors", code_stats["errors"])

    if total_runs_code > 0:
        avg_latency = code_stats["total_latency_ms"] / total_runs_code
        avg_tokens = code_stats["total_tokens"] / total_runs_code
        avg_cost = code_stats["total_cost_usd"] / total_runs_code
    else:
        avg_latency = avg_tokens = avg_cost = 0.0

    col_code_avg1, col_code_avg2, col_code_avg3 = st.columns(3)
    col_code_avg1.metric("Avg Latency", f"{avg_latency:.0f}ms")
    col_code_avg2.metric("Avg Tokens", f"{avg_tokens:.0f}")
    col_code_avg3.metric("Avg Token Cost", f"${avg_cost:.4f}")

    code_history = code_stats.get("history", [])
    if code_history:
        st.markdown("**Recent Code Runs**")
        for entry in reversed(code_history[-3:]):
            ts = entry.get("timestamp")
            if isinstance(ts, datetime):
                display_time = ts.strftime("%H:%M:%S")
            elif isinstance(ts, str):
                display_time = ts
            else:
                display_time = "—"
            status = entry.get("status", "unknown").replace("_", " ").title()
            parts = [display_time, status]
            language = entry.get("language")
            if language:
                parts.append(language)
            latency_ms_entry = entry.get("latency_ms")
            if latency_ms_entry is not None:
                parts.append(f"{latency_ms_entry:.0f}ms")
            tokens_entry = entry.get("tokens")
            if tokens_entry is not None:
                parts.append(f"{tokens_entry} tok")
            cost_entry = entry.get("cost_usd")
            if cost_entry is not None:
                parts.append(f"${cost_entry:.4f}")
            exit_code_entry = entry.get("exit_code")
            if exit_code_entry is not None:
                parts.append(f"exit {exit_code_entry}")
            st.caption(" • ".join(parts))
            message = entry.get("message")
            if message:
                st.caption(f"Message: {message}")
    else:
        st.info("No code runs yet this session")

    st.markdown("---")

    # Code Generation Learning Dashboard
    st.markdown("**💻 🎓 Code Learning Dashboard**")
    if "codegen_learning_history" in st.session_state and len(st.session_state.codegen_learning_history["rewards"]) > 0:
        codegen_hist = st.session_state.codegen_learning_history

        # Overall statistics
        avg_reward_code = np.mean(codegen_hist["rewards"])
        latest_reward_code = codegen_hist["rewards"][-1]
        total_runs_code_learning = len(codegen_hist["rewards"])

        col_cl1, col_cl2 = st.columns(2)
        col_cl1.metric("Total Runs", total_runs_code_learning)
        col_cl2.metric("Avg Reward", f"{avg_reward_code:.3f}")

        # Latest reward with trend
        if len(codegen_hist["rewards"]) >= 2:
            prev_reward_code = codegen_hist["rewards"][-2]
            reward_delta_code = latest_reward_code - prev_reward_code
            delta_text_code = f"{reward_delta_code:+.3f}" if reward_delta_code != 0 else "—"
        else:
            delta_text_code = None

        st.metric("Latest Reward", f"{latest_reward_code:.3f}", delta=delta_text_code)

        # Reward trend chart
        st.markdown("**Reward Trend**")
        df_reward_code = pd.DataFrame({
            "Run": range(1, len(codegen_hist["rewards"]) + 1),
            "Reward": codegen_hist["rewards"]
        })
        st.line_chart(df_reward_code.set_index("Run"))

        # Component breakdown (latest)
        if len(codegen_hist["success_scores"]) > 0:
            st.markdown("**Latest Component Scores**")
            latest_success = codegen_hist["success_scores"][-1]
            latest_efficiency = codegen_hist["efficiency_scores"][-1]
            latest_quality = codegen_hist["quality_scores"][-1]
            latest_speed = codegen_hist["speed_scores"][-1]

            col_cc1, col_cc2 = st.columns(2)
            col_cc1.metric("✅ Success", f"{latest_success:.2f}")
            col_cc2.metric("⚡ Efficiency", f"{latest_efficiency:.2f}")

            col_cc3, col_cc4 = st.columns(2)
            col_cc3.metric("💎 Quality", f"{latest_quality:.2f}")
            col_cc4.metric("🚀 Speed", f"{latest_speed:.2f}")

        # Strategy distribution
        strategy_counts_code = {}
        for strategy in codegen_hist["strategies"]:
            strategy_counts_code[strategy] = strategy_counts_code.get(strategy, 0) + 1

        if strategy_counts_code:
            st.markdown("**Strategy Usage**")
            for strategy, count in sorted(strategy_counts_code.items(), key=lambda x: x[1], reverse=True):
                percentage = (count / total_runs_code_learning) * 100
                st.caption(f"{strategy}: {count} times ({percentage:.1f}%)")

        # Language distribution
        language_counts = {}
        for lang in codegen_hist["languages"]:
            language_counts[lang] = language_counts.get(lang, 0) + 1

        if language_counts:
            st.markdown("**Language Usage**")
            for lang, count in sorted(language_counts.items(), key=lambda x: x[1], reverse=True):
                percentage = (count / total_runs_code_learning) * 100
                st.caption(f"{lang}: {count} times ({percentage:.1f}%)")

        # Show learning objectives progress
        st.markdown("**📈 Learning Objectives**")

        if total_runs_code_learning >= 3:
            # Success rate (target: >0.8)
            avg_success = np.mean(codegen_hist["success_scores"][-min(10, total_runs_code_learning):])
            success_target = 0.8
            success_progress = min(avg_success / success_target, 1.0)
            st.markdown(f"✅ Test Success: {avg_success:.2f} / {success_target:.2f}")
            st.progress(success_progress)

            # Efficiency (target: >0.7)
            avg_efficiency = np.mean(codegen_hist["efficiency_scores"][-min(10, total_runs_code_learning):])
            efficiency_target = 0.7
            efficiency_progress = min(avg_efficiency / efficiency_target, 1.0)
            st.markdown(f"⚡ Efficiency: {avg_efficiency:.2f} / {efficiency_target:.2f}")
            st.progress(efficiency_progress)

            # Code quality (target: >0.7)
            avg_quality_code = np.mean(codegen_hist["quality_scores"][-min(10, total_runs_code_learning):])
            quality_target_code = 0.7
            quality_progress_code = min(avg_quality_code / quality_target_code, 1.0)
            st.markdown(f"💎 Code Quality: {avg_quality_code:.2f} / {quality_target_code:.2f}")
            st.progress(quality_progress_code)
        else:
            st.caption("Need at least 3 runs to show objectives")
    else:
        st.caption("No code learning data yet - start generating code!")

    st.markdown("---")
    st.text(f"Session: {st.session_state.session_id}")

    if st.button("🔄 Reset Session"):
        st.session_state.messages = []
        st.session_state.mode = "general"  # Reset to general mode
        st.session_state.trip_constraints = TripConstraints()
        st.session_state.awaiting_confirmation = False
        st.session_state.trip_last_plan = None
        st.session_state.code_stats = {
            "total_runs": 0,
            "passes": 0,
            "failures": 0,
            "errors": 0,
            "total_latency_ms": 0.0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "history": [],
        }
        st.session_state.code_show_samples = True
        st.session_state.code_show_samples_prev = True
        st.session_state.code_last_request = None
        st.session_state.code_pending_auto = False
        st.session_state.code_force_language = None
        # Reset metrics
        st.session_state.metrics_history = {
            "timestamps": [], "latencies": [], "prompt_tokens": [],
            "completion_tokens": [], "costs": [], "services": []
        }
        st.session_state.rag_metrics = {
            "embed_times": [], "rerank_times": [],
            "retrieval_times": [], "confidences": []
        }
        st.session_state.agent_stats = {"success": 0, "failure": 0, "partial": 0}
        try:
            requests.post(f"{BACKEND_URL}/api/agent/metrics/reset", timeout=3)
        except Exception:
            pass
        st.rerun()


# =====================================================================
# Main Interface
# =====================================================================

st.title("🤖 AI-Louie - Enterprise-Grade AI System with Governance")

st.markdown("""
Welcome to **AI-Louie**, an advanced AI system with enterprise-level capabilities:

### 🎯 Core Services
- 📚 **Smart RAG Q&A**: Multi-strategy retrieval (Hybrid, Iterative, Graph, Table) with Thompson Sampling optimization
- ✈️ **Trip Planning**: Intelligent itinerary generation with constraint-aware planning
- 💻 **Code Generation**: Self-healing code with automatic testing and validation

### 🛡️ AI Governance & Observability
- **12 Active Governance Criteria** (G1-G12) for Air NZ compliance
- Real-time **Prometheus metrics** & **Grafana dashboards**
- Distributed tracing with **Jaeger** for full request observability
- Privacy controls with PII detection & evidence contracts

### 🚀 Advanced Features
- **Answer caching** with semantic & TF-IDF matching
- **Query classification** for intelligent routing
- **ONNX-optimized inference** (INT8 quantization)
- **Multi-arm bandit** for strategy selection

Use the buttons below or chat naturally - I'll route your request intelligently!
""")

# =====================================================================
# Quick action buttons (3: RAG, Trip, Code) - Always at Top
# =====================================================================

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("📚 RAG Q&A", use_container_width=True):
        switch_mode("rag", always_show_message=False)
        st.rerun()

with col2:
    if st.button("✈️ Trip Planning", use_container_width=True):
        switch_mode("trip", always_show_message=False)
        st.rerun()

with col3:
    if st.button("💻 Code Generation", use_container_width=True):
        switch_mode("code", always_show_message=False)
        st.rerun()

st.markdown("---")

# =====================================================================
# Display chat history
# =====================================================================

# Example questions data (defined once for use below)
EXAMPLE_QUESTIONS_BOTTOM = [
    "Who wrote DADDY TAKE ME SKATING?",
    "Tell me about American frontier history",
    "'Sir roberts fortune a novel', show me roles relationship",
    "'Sir roberts fortune a novel', list all the roles",
    "'Sir roberts fortune a novel', for what purpose he was confident of his own powers of cheating the uncle, and managing?"
]

for idx, message in enumerate(st.session_state.messages):
    content = message.get("content", "")
    if message.get("role") == "assistant":
        content = clean_text_lines(content)
        if not content:
            continue

    # Check if this is a RAG assistant message
    is_rag_assistant = (message.get("role") == "assistant" and
                        st.session_state.mode == "rag")

    with st.chat_message(message["role"]):
        st.markdown(content)

        # Add example questions dropdown for RAG assistant messages (historical)
        if is_rag_assistant:
            # Use unique key based on message index
            dropdown_key = f"rag_example_history_{idx}"

            def on_history_example_select():
                selected = st.session_state.get(dropdown_key)
                if selected and selected != "Select a question...":
                    append_chat_history("user", selected)
                    st.session_state.pending_prompt = selected
                    st.session_state[dropdown_key] = "Select a question..."

            st.selectbox(
                "💡 Example Questions",
                options=["Select a question..."] + EXAMPLE_QUESTIONS_BOTTOM,
                key=dropdown_key,
                on_change=on_history_example_select
            )

# (Sidebar example questions removed - now using inline version above chat history)

# Auto-scroll to bottom of chat after new messages
# Use a unique key tied to message count to force re-execution
scroll_key = f"scroll_{len(st.session_state.messages)}_{id(st.session_state.messages)}"
st.markdown(
    f"""
    <script>
        // Scroll to bottom with multiple attempts for reliability
        function scrollToBottom() {{
            var containers = [
                window.parent.document.querySelector('section.main'),
                window.parent.document.querySelector('[data-testid="stAppViewContainer"]'),
                window.parent.document.querySelector('.main'),
                window.parent.document.querySelector('[data-testid="stApp"]')
            ];
            containers.forEach(function(container) {{
                if (container) {{
                    container.scrollTop = container.scrollHeight;
                    container.scrollTo({{top: container.scrollHeight, behavior: 'smooth'}});
                }}
            }});
            // Also scroll the window itself as a fallback
            window.scrollTo({{top: document.body.scrollHeight, behavior: 'smooth'}});
        }}

        // Run immediately and with staggered retries (covers rerun + slow renders)
        scrollToBottom();
        setTimeout(scrollToBottom, 80);
        setTimeout(scrollToBottom, 180);
        setTimeout(scrollToBottom, 350);
        setTimeout(scrollToBottom, 650);
        setTimeout(scrollToBottom, 1100);

        // Re-run after next paint to catch late-added elements
        requestAnimationFrame(scrollToBottom);
    </script>
    <!-- {scroll_key} -->
    """,
    unsafe_allow_html=True
)

last_trip_plan = st.session_state.get("trip_last_plan")
if last_trip_plan and st.session_state.mode != "trip":
    with st.expander("🧳 Last Trip Plan", expanded=False):
        render_trip_plan_summary(last_trip_plan)


# =====================================================================
# Chat input
# =====================================================================

# Code mode options - show before chat input when in code mode
if st.session_state.mode == "code":
    st.markdown("### ⚙️ Code Generation Options")

    prev_toggle = st.session_state.code_show_samples_prev
    samples_toggle = st.checkbox(
        "Show assertion outputs (slower)",
        value=st.session_state.code_show_samples,
        key="code_samples_checkbox_main",
        help="When enabled, print statements will be injected before assertions to show actual values"
    )
    st.session_state.code_show_samples = samples_toggle
    toggle_changed = samples_toggle != prev_toggle
    st.session_state.code_show_samples_prev = samples_toggle

    # Show re-run button only if there's a last successful request
    if st.session_state.get('code_last_request'):
        st.caption(f"📝 Last: {st.session_state.code_last_request.get('prompt', '')[:50]}...")
        if st.button("♻️ Re-run Last Request", key="code_rerun_button", use_container_width=True):
            st.session_state.pending_prompt = st.session_state.code_last_request.get("prompt")
            st.session_state.code_force_language = st.session_state.code_last_request.get("language")
            st.session_state.code_pending_auto = True
            st.rerun()
    else:
        st.caption("ℹ️ Submit a code request first")

    # If toggled and we have a last successful request, auto re-run
    if toggle_changed and st.session_state.code_last_request:
        st.info("♻️ Re-running last request with new settings...")
        st.session_state.pending_prompt = st.session_state.code_last_request.get("prompt")
        st.session_state.code_force_language = st.session_state.code_last_request.get("language")
        st.session_state.code_pending_auto = True
        st.rerun()

    st.divider()

# =====================================================================
# Input Bar (fixed at bottom): chat_input only
# =====================================================================
# Note: Example questions dropdown is shown at the end of each RAG response instead,
# since st.chat_input() is always fixed at the very bottom and pushes other widgets up

# Use native chat_input which is always fixed at bottom
prompt = early_prompt
user_input = st.chat_input("Type your message and press Enter to send...")

# DEBUG: Show input status on page
# if user_input:
    # st.sidebar.warning(f"🔍 DEBUG: user_input = {user_input!r}")
# st.sidebar.info(f"🔍 DEBUG: early_prompt = {early_prompt!r}, pending = {st.session_state.pending_prompt!r}")

# If early_prompt already provided prompt, use it directly
if prompt:
    debug_log(f"[early] using prompt from guard={prompt!r}")
# Otherwise check pending_prompt
elif st.session_state.pending_prompt:
    prompt = st.session_state.pending_prompt
    debug_log(f"[pending] reuse prompt={prompt!r}")
    st.session_state.pending_prompt = None  # Clear it
# Finally try user input
elif user_input:
    prompt = user_input
    print(f"📥 USER INPUT RECEIVED: {prompt!r}")
    debug_log(f"[input] new prompt={prompt!r}")

    # If user explicitly wants RAG mode, switch without using the text as a query
    rag_triggers = {"rag", "use rag", "rag mode", "enter rag", "switch to rag"}
    if prompt.strip().lower() in rag_triggers:
        switch_mode("rag", always_show_message=True)
        debug_log(f"[intent] rag activation via text prompt")
        st.rerun()

    # Display user message
    append_chat_history("user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)
    print(f"✅ User message displayed")

    detected_mode = detect_mode_from_prompt(prompt)
    if detected_mode and detected_mode not in {None, st.session_state.mode}:
        switch_mode(detected_mode, always_show_message=True)
        st.session_state.pending_prompt = prompt
        debug_log(f"[intent] detected={detected_mode} pending set")
        st.rerun()
else:
    prompt = None
    debug_log("[pending] no prompt available")

current_mode = st.session_state.mode
# st.sidebar.write(f"DEBUG • branch_gate: mode={current_mode}, prompt_truthy={bool(prompt)}, prompt={repr(prompt)[:80]}")

print(f"🎯 MODE={current_mode!r} PROMPT={prompt!r}")
debug_log(f"[mode] after prompt selection mode={current_mode} prompt={prompt!r}")
debug_log(
    f"[check] trip_condition={bool(st.session_state.mode == 'trip' and prompt)} "
    f"mode={current_mode} prompt_truthy={bool(prompt)}"
)

if current_mode == "rag":
    if prompt and _is_quit(prompt):
        _cleanup_mode_state("rag")
        st.session_state.mode = "general"
        append_chat_history("assistant", "👋 Exited RAG mode.")
        st.rerun()

    debug_log(f"[rag] branch start mode={current_mode} prompt={prompt!r}")
    st.markdown("---")
    rag_controls_container = st.container()
    render_rag_controls(rag_controls_container)
    st.markdown("---")

    # Warm-up is now handled at main page initialization (lines 1581-1645)
    # Just show a welcome message on first RAG access
    if "rag_first_access" not in st.session_state:
        st.session_state.rag_first_access = True
        with st.chat_message("assistant"):
            st.markdown("✅ **RAG system is ready!** All models have been warmed up during startup. Ask me anything about the documents.")
        st.session_state.awaiting_confirmation = False

    # =====================================================================
    # RAG Mode - Full replication of chat_rag.py
    # =====================================================================

    if current_mode == "rag" and prompt and prompt != "__MODE_ACTIVATED__":  # Only process if we have a real prompt
        used_streaming = False
        with st.chat_message("assistant"):
            try:
                # Get selected RAG strategy
                rag_strategy = st.session_state.get("rag_strategy", "standard")

                # Map strategy to endpoint and techniques
                strategy_config = {
                    "standard": {
                        "endpoint": "ask",
                        "techniques": [
                            ("📊 Query Embedding", "Dense Vector Embedding"),
                            ("🔍 Vector Similarity Search", "Cosine Similarity (Qdrant)"),
                            ("🎯 Cross-Encoder Reranking", "MiniLM-L6 Cross-Encoder"),
                            ("🤖 LLM Answer Generation", "GPT-4o with Retrieved Context")
                        ]
                    },
                    "hybrid": {
                        "endpoint": "ask-hybrid",
                        "techniques": [
                            ("🏷️ Query Classification", "Query Type Detection"),
                            ("💾 Semantic Cache Lookup", "Strategy Cache (90% token savings)"),
                            ("📊 Query Embedding", "Dense Vector Embedding"),
                            ("🔍 Hybrid Search", "BM25 (30%) + Vector (70%) Fusion"),
                            ("🎯 Cross-Encoder Reranking", "Score-based Ranking"),
                            ("🤖 LLM Answer Generation", "GPT-4o with Context"),
                            ("💾 Update Cache Strategy", "Save Successful Strategy")
                        ]
                    },
                    "iterative": {
                        "endpoint": "ask-iterative",
                        "techniques": [
                            ("🏷️ Query Classification", "Query Type Detection"),
                            ("📊 Initial Query Embedding", "Dense Vector"),
                            ("🔍 Hybrid Retrieval", "BM25 + Vector Fusion"),
                            ("🎯 Rerank Retrieved Chunks", "Cross-Encoder"),
                            ("🤖 Generate Initial Answer", "GPT-4o First Pass"),
                            ("🔁 Self-RAG Verification", "Confidence Check + Iteration")
                        ]
                    },
                    "smart": {
                        "endpoint": "ask-smart",
                        "techniques": [
                            ("🏷️ Query Analysis", "Intent Detection"),
                            ("🎯 Strategy Selection", "Bandit over Hybrid/Iterative/Graph/Table"),
                            ("⚡ Execute Pipeline", "Dynamic Pipeline Execution")
                        ]
                    },
                    "graph": {
                        "endpoint": "ask-graph",
                        "techniques": [
                            ("🔍 Extract Query Entities", "Entity Detection from Query"),
                            ("🕸️ JIT Graph Building", "On-demand Knowledge Graph Construction"),
                            ("🔗 Relationship Extraction", "Entity Relationship Mapping"),
                            ("📊 Graph Traversal", "Find Connected Entities"),
                            ("🔎 Hybrid Retrieval", "Graph Context + Vector Search"),
                            ("🤖 LLM Answer Generation", "GPT-4o with Graph Context")
                        ]
                    },
                    "table": {
                        "endpoint": "ask-table",
                        "techniques": [
                            ("🎯 Extract Query Intent", "Determine comparison/list/aggregation"),
                            ("🔍 Hybrid Retrieval", "Vector + BM25 Search"),
                            ("📊 Data Structuring", "Extract tabular information"),
                            ("📝 Table Generation", "Format as markdown table"),
                            ("🤖 LLM Answer Generation", "GPT-4o with table context")
                        ]
                    },
                    "stream": {
                        "endpoint": "ask-stream",
                        "techniques": [
                            ("📊 Query Embedding", "Dense Vector Embedding"),
                            ("🔍 Vector Similarity Search", "Cosine Similarity (Qdrant)"),
                            ("🎯 Cross-Encoder Reranking", "MiniLM-L6 Cross-Encoder"),
                            ("⚡ Streaming Generation", "Token-by-token SSE Response")
                        ]
                    }
                }

                config = strategy_config[rag_strategy]
                endpoint = config["endpoint"]
                techniques = config["techniques"]

                payload = {
                    "question": prompt,
                    "top_k": 5,
                    "include_timings": True,
                }

                # Add search scope to metadata
                search_scope = st.session_state.get("search_scope", "all")
                payload["metadata"] = {
                    "search_scope": search_scope,
                    "requested_strategy": rag_strategy,
                }

                # When searching user uploads (or both), use multi-collection endpoint
                # EXCEPT for smart strategy, which needs its own logic (bandit, graph cues, etc.)
                endpoint_override = None
                if search_scope in ("all", "user_only") and rag_strategy in {"standard", "hybrid", "iterative"}:
                    endpoint_override = "search-multi-collection"

                reranker_choice = st.session_state.get("rag_reranker_choice")
                if reranker_choice:
                    payload["reranker"] = reranker_choice

                vector_limit_payload = int(max(vector_min, min(vector_max, st.session_state.get("rag_vector_limit", vector_min))))
                payload["vector_limit"] = vector_limit_payload

                content_limit_payload = int(max(content_min, min(content_max, st.session_state.get("rag_content_limit", content_default))))
                payload["content_char_limit"] = content_limit_payload

                # For Smart and Graph modes, use non-streaming endpoint to get complete pipeline info
                if rag_strategy == "smart":
                    st.markdown("**1️⃣ 🏷️ Query Analysis**")
                    st.caption("Analyzing query intent and complexity")
                    time.sleep(0.3)

                    st.markdown("**2️⃣ 🎯 Strategy Selection**")
                    st.caption("Choosing optimal RAG pipeline...")
                    time.sleep(0.3)

                    # Call non-streaming API
                    response = requests.post(
                        f"{BACKEND_URL}/api/rag/{endpoint_override or 'ask-smart'}",
                        json=payload,
                        timeout=180
                    )
                elif rag_strategy == "graph":
                    # Display Graph RAG techniques
                    for idx, (tech_name, tech_detail) in enumerate(techniques, 1):
                        st.markdown(f"**{idx}️⃣ {tech_name}**")
                        st.caption(tech_detail)
                        time.sleep(0.3)

                    # Call Graph RAG API
                    response = requests.post(
                        f"{BACKEND_URL}/api/rag/{endpoint}",
                        json=payload,
                        timeout=180
                    )
                elif rag_strategy == "table":
                    # Display Table RAG techniques
                    for idx, (tech_name, tech_detail) in enumerate(techniques, 1):
                        st.markdown(f"**{idx}️⃣ {tech_name}**")
                        st.caption(tech_detail)
                        time.sleep(0.3)

                    # Call Table RAG API
                    response = requests.post(
                        f"{BACKEND_URL}/api/rag/{endpoint}",
                        json=payload,
                        timeout=180
                    )
                else:
                    # Announce chosen strategy (including multi-collection hint)
                    strategy_label = rag_strategy.title()
                    if endpoint_override == "search-multi-collection":
                        strategy_label += " (multi-collection)"
                    st.markdown(f"**📌 Strategy:** {strategy_label}")
                    time.sleep(0.2)

                    # For non-smart/non-graph modes, display techniques sequentially BEFORE API call
                    for idx, (tech_name, tech_detail) in enumerate(techniques, 1):
                        st.markdown(f"**{idx}️⃣ {tech_name}**")
                        st.caption(tech_detail)
                        time.sleep(0.3)

                    # Use streaming endpoint for real-time response unless multi-collection is requested
                    target_endpoint = endpoint_override or "ask-stream"
                    if target_endpoint == "search-multi-collection":
                        response = requests.post(
                            f"{BACKEND_URL}/api/rag/{target_endpoint}",
                            json=payload,
                            timeout=180
                        )
                        used_streaming = False
                    else:
                        response = requests.post(
                            f"{BACKEND_URL}/api/rag/ask-stream",
                            json=payload,
                            stream=True,
                            timeout=180
                        )
                        used_streaming = True

                if response.status_code == 200:
                    import json as json_module

                    # Handle non-streaming responses (Smart RAG, Graph RAG, Table RAG)
                    if rag_strategy in ["smart", "graph", "table"] or not used_streaming:
                        result = response.json()

                        # Display selected strategy with reason
                        selected_strategy = result.get("selected_strategy", "Hybrid RAG")
                        strategy_reason = result.get("strategy_reason", "")
                        cache_hit = result.get("cache_hit", False)

                        # Display cache status prominently
                        if cache_hit:
                            st.success("💾 **Cache HIT** - Answer retrieved from cache (0 tokens used)")
                        else:
                            st.info("🔍 **Cache MISS** - Generating fresh answer")

                        st.info(f"✅ Selected: **{selected_strategy}**")
                        if strategy_reason:
                            st.caption(f"💡 Reason: {strategy_reason}")
                        time.sleep(0.3)

                        # Display technique steps based on selected strategy (including multi-collection labels)
                        def _render_steps(strategy_key: str, start_index: int = 3) -> None:
                            step_list = strategy_config.get(strategy_key, {}).get("techniques", [])
                            for idx, (tech_name, tech_detail) in enumerate(step_list, start=start_index):
                                st.markdown(f"**{idx}️⃣ {tech_name}**")
                                st.caption(tech_detail)
                                time.sleep(0.3)

                        strategy_lower = (selected_strategy or "").lower()
                        # Map multi-collection labels back to core strategy keys
                        render_key = "hybrid"
                        if "graph" in strategy_lower:
                            render_key = "graph"
                        elif "table" in strategy_lower:
                            render_key = "table"
                        elif "iterative" in strategy_lower:
                            render_key = "iterative"
                        elif "standard" in strategy_lower:
                            render_key = "standard"
                        elif "hybrid" in strategy_lower:
                            render_key = "hybrid"

                        label_map = {
                            "hybrid": "Hybrid search",
                            "iterative": "Iterative Self-RAG",
                            "graph": "Graph RAG",
                            "table": "Table RAG",
                            "standard": "Standard RAG",
                        }
                        st.markdown(f"**RAG strategy:** {label_map.get(render_key, render_key.title())}")
                        _render_steps(render_key)

                        # Display answer
                        st.markdown("---")
                        st.markdown("### 💬 Answer")

                        # 🆕 Display cache indicator if answer is from cache
                        is_cached = result.get("cache_hit", False)
                        if is_cached:
                            st.caption("⚡ Answer from cache - If inaccurate, click 'Bad' to clear cache")

                        answer = result.get("answer", "")
                        st.markdown(answer)

                        # 🆕 User Feedback Buttons (for Smart RAG)
                        query_id = result.get("query_id")
                        if query_id:
                            backend_url = st.session_state.get("backend_url", "http://backend:8000")
                            session_key = f"smart_rag_{query_id}"
                            render_feedback_buttons(query_id, session_key, backend_url)

                        # Display metrics for Smart RAG
                        st.markdown("---")
                        st.markdown("### 📊 Performance Metrics")

                        # Get token usage from result
                        token_usage = result.get('token_usage', {})
                        # If answer cache hit, force tokens to 0 for display
                        cache_hit = result.get('cache_hit') or False
                        token_breakdown = result.get('token_breakdown') or {}
                        cache_stage = token_breakdown.get('answer_cache_lookup', {}) if isinstance(token_breakdown, dict) else {}
                        cache_hit = cache_hit or cache_stage.get('cache_hit', False)
                        total_tokens = 0 if cache_hit else (token_usage.get('total', 0) if token_usage else 0)

                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.metric("⚡ Total Time", f"{result.get('total_time_ms', 0):.0f}ms")
                        with col2:
                            st.metric("📄 Chunks", result.get('num_chunks_retrieved', 0))
                        with col3:
                            st.metric("🎯 Confidence", f"{result.get('confidence', 0):.3f}")
                        with col4:
                            st.metric("🪙 Tokens", total_tokens if total_tokens > 0 else "N/A")

                        # Token breakdown - detailed pipeline view
                        token_breakdown = token_breakdown or result.get('token_breakdown')
                        if token_breakdown:
                            with st.expander("🔍 Token Usage Breakdown (full details)", expanded=False):
                                st.markdown("### Pipeline Stages")

                                # Query Classification
                                qc = token_breakdown.get('query_classification', {})
                                st.markdown(f"""
                                **1️⃣ Query Classification**
                                - Tokens: `{qc.get('tokens', 0)}`
                                - Method: `{qc.get('method', 'N/A')}`
                                - LLM Used: `{'✅ Yes' if qc.get('llm_used') else '❌ No'}`
                                """)

                                # Cache Lookup
                                cache = token_breakdown.get('answer_cache_lookup', {})
                                cache_status = "✅ HIT" if cache.get('cache_hit') else "❌ MISS"
                                st.markdown(f"""
                                **2️⃣ Answer Cache Lookup**
                                - Tokens: `{cache.get('tokens', 0)}`
                                - Status: `{cache_status}`
                                - LLM Used: `{'✅ Yes' if cache.get('llm_used') else '❌ No'}`
                                """)

                                # Answer Generation
                                gen = token_breakdown.get('answer_generation', {})
                                st.markdown(f"""
                                **3️⃣ Answer Generation**
                                - Prompt Tokens: `{gen.get('prompt_tokens', 0)}`
                                - Completion Tokens: `{gen.get('completion_tokens', 0)}`
                                - Total: `{gen.get('tokens', 0)}`
                                - Cost: `${gen.get('cost', 0):.5f}`
                                - LLM Used: `{'✅ Yes' if gen.get('llm_used') else '❌ No'}`
                                """)

                                # Iteration details if available
                                iterations = gen.get('iterations')
                                if iterations and len(iterations) > 1:
                                    st.markdown("**📊 Iteration Details:**")
                                    for it in iterations:
                                        it_tokens = it.get('token_usage')
                                        if it_tokens:
                                            st.caption(f"   Iteration {it['iteration']}: {it_tokens['total']} tokens (${it_tokens['cost']:.5f}) | Confidence: {it['confidence']:.2f}")
                                        else:
                                            st.caption(f"   Iteration {it['iteration']}: N/A | Confidence: {it['confidence']:.2f}")

                                # Total
                                total = token_breakdown.get('total', {})
                                st.markdown("---")
                                st.markdown(f"""
                                **💰 Total**
                                - Total Tokens: `{total.get('tokens', 0)}`
                                - Total Cost: `${total.get('cost', 0):.5f}`
                                - LLM Calls: `{total.get('llm_calls', 0)}`
                                """)
                        elif token_usage and total_tokens > 0:
                            # Fallback to simple token details if no breakdown
                            with st.expander("💰 Token Usage Details"):
                                token_cols = st.columns(3)
                                token_cols[0].metric("Prompt", token_usage.get('prompt', 0))
                                token_cols[1].metric("Completion", token_usage.get('completion', 0))
                                token_cols[2].metric("Total", total_tokens)
                                if result.get('token_cost_usd'):
                                    st.caption(f"💵 Estimated cost: ${result.get('token_cost_usd', 0):.5f}")

                        # Display AI Governance Status
                        governance_context = result.get('governance_context')
                        if governance_context:
                            st.markdown("---")
                            display_governance_status(governance_context)

                        # Display Graph Context if Graph RAG was selected
                        if selected_strategy == "Graph RAG":
                            timings = result.get('timings', {})
                            graph_context = timings.get('graph_context')
                            if graph_context:
                                st.markdown("---")
                                st.markdown("### 🕸️ Knowledge Graph")

                                col1, col2 = st.columns(2)
                                with col1:
                                    st.metric("📍 Entities", graph_context.get("num_entities", 0))
                                with col2:
                                    st.metric("🔗 Relationships", graph_context.get("num_relationships", 0))

                                # Display entities grouped by type
                                entities = graph_context.get("entities", [])
                                if entities:
                                    with st.expander("📍 Entities (by type)", expanded=False):
                                        # Group entities by type
                                        from collections import defaultdict
                                        entities_by_type = defaultdict(list)
                                        for ent in entities[:30]:  # Show top 30
                                            ent_type = ent.get("type", "unknown")
                                            entities_by_type[ent_type].append(ent.get("name", ""))

                                        for ent_type, names in entities_by_type.items():
                                            st.markdown(f"**{ent_type.capitalize()}**: {', '.join(names[:15])}")

                                # Display relationships
                                relationships = graph_context.get("relationships", [])
                                if relationships:
                                    with st.expander("🔗 Key Relationships", expanded=False):
                                        for rel in relationships[:20]:  # Show top 20
                                            source = rel.get("source", "")
                                            target = rel.get("target", "")
                                            relation = rel.get("relation", "")
                                            conf = rel.get("confidence", 0)
                                            st.markdown(f"**{source}** → *{relation}* → **{target}** (conf: {conf:.2f})")

                                # ✨ Interactive Network Visualization with Plotly (show nodes even if no edges)
                                if entities:
                                    with st.expander("🌐 Interactive Graph Visualization", expanded=True):
                                        import plotly.graph_objects as go
                                        import networkx as nx

                                        G = nx.DiGraph()
                                        for ent in entities[:50]:
                                            G.add_node(ent['name'], type=ent.get('type', 'unknown'))
                                        for rel in relationships[:100]:
                                            source = rel.get('source', '')
                                            target = rel.get('target', '')
                                            if source in G.nodes and target in G.nodes:
                                                G.add_edge(source, target, relation=rel.get('relation', ''))

                                        pos = nx.spring_layout(G, k=0.5, iterations=50) if len(G.nodes) > 0 else {}

                                        edge_x, edge_y, edge_text = [], [], []
                                        for edge in G.edges():
                                            x0, y0 = pos[edge[0]]
                                            x1, y1 = pos[edge[1]]
                                            edge_x.extend([x0, x1, None])
                                            edge_y.extend([y0, y1, None])
                                            relation = G.edges[edge].get('relation', '')
                                            edge_text.append(f"{edge[0]} → {relation} → {edge[1]}")

                                        edge_trace = go.Scatter(
                                            x=edge_x, y=edge_y,
                                            line=dict(width=0.5, color='#888'),
                                            hoverinfo='text',
                                            text=edge_text if edge_text else None,
                                            mode='lines')

                                        node_x, node_y, node_text, node_color = [], [], [], []
                                        color_map = {
                                            'person': '#FF6B6B',
                                            'character': '#FF6B6B',
                                            'role': '#FF8C42',
                                            'place': '#4ECDC4',
                                            'concept': '#95E1D3',
                                            'skill': '#FFA07A',
                                            'tool': '#DDA15E',
                                            'event': '#BC6C25',
                                            'unknown': '#CCCCCC'
                                        }

                                        for node in G.nodes():
                                            x, y = pos.get(node, (0, 0))
                                            node_x.append(x)
                                            node_y.append(y)
                                            node_type = G.nodes[node].get('type', 'unknown')
                                            node_text.append(f"{node}<br>Type: {node_type}")
                                            node_color.append(color_map.get(node_type, '#CCCCCC'))

                                        node_trace = go.Scatter(
                                            x=node_x, y=node_y,
                                            mode='markers+text',
                                            hoverinfo='text',
                                            text=[n for n in G.nodes()],
                                            hovertext=node_text,
                                            textposition="top center",
                                            textfont=dict(size=8),
                                            marker=dict(
                                                showscale=False,
                                                color=node_color,
                                                size=15,
                                                line_width=2))

                                        fig = go.Figure(data=[edge_trace, node_trace],
                                            layout=go.Layout(
                                                title=dict(text='Knowledge Graph Network', x=0.5, xanchor='center'),
                                                titlefont_size=16,
                                                showlegend=False,
                                                hovermode='closest',
                                                margin=dict(b=0,l=0,r=0,t=40),
                                                xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                                                yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                                                height=600
                                            ))

                                        st.plotly_chart(fig, use_container_width=True)
                                        st.caption("🎨 **Entity Types**: " + " | ".join([f"{k}: {v}" for k, v in color_map.items() if k != 'unknown']))

                                # 📥 Export Functionality
                                if entities or relationships:
                                    st.markdown("---")
                                    st.markdown("### 📥 Export Knowledge Graph")

                                    col1, col2, col3 = st.columns(3)

                                    with col1:
                                        # Export as JSON
                                        import json
                                        graph_data = {
                                            "entities": entities,
                                            "relationships": relationships,
                                            "metadata": {
                                                "num_entities": graph_context.get("num_entities", 0),
                                                "num_relationships": graph_context.get("num_relationships", 0),
                                                "query": prompt,
                                                "timestamp": str(pd.Timestamp.now())
                                            }
                                        }
                                        json_str = json.dumps(graph_data, indent=2, ensure_ascii=False)
                                        st.download_button(
                                            label="📄 Download JSON",
                                            data=json_str,
                                            file_name="knowledge_graph.json",
                                            mime="application/json"
                                        )

                                    with col2:
                                        # Export as CSV (relationships)
                                        import pandas as pd
                                        if relationships:
                                            df_rels = pd.DataFrame(relationships)
                                            csv_str = df_rels.to_csv(index=False)
                                            st.download_button(
                                                label="📊 Download CSV",
                                                data=csv_str,
                                                file_name="relationships.csv",
                                                mime="text/csv"
                                            )

                                    with col3:
                                        # Export as GraphML (for Gephi, Cytoscape, etc.)
                                        if entities and relationships:
                                            import networkx as nx
                                            G_export = nx.DiGraph()

                                            # Add nodes with attributes
                                            for ent in entities:
                                                G_export.add_node(ent['name'],
                                                                type=ent.get('type', 'unknown'),
                                                                sources=ent.get('num_sources', 0))

                                            # Add edges with attributes
                                            for rel in relationships:
                                                G_export.add_edge(rel['source'], rel['target'],
                                                                relation=rel.get('relation', ''),
                                                                confidence=rel.get('confidence', 0))

                                            # Convert to GraphML
                                            from io import BytesIO
                                            graphml_buffer = BytesIO()
                                            nx.write_graphml(G_export, graphml_buffer)
                                            graphml_str = graphml_buffer.getvalue()

                                            st.download_button(
                                                label="🕸️ Download GraphML",
                                                data=graphml_str,
                                                file_name="knowledge_graph.graphml",
                                                mime="application/xml"
                                            )

                            # Display JIT Building Stats
                            jit_stats = timings.get('jit_stats')
                            if jit_stats:
                                st.markdown("---")
                                st.markdown("### 🔨 JIT Graph Building Stats")
                                col1, col2, col3 = st.columns(3)
                                with col1:
                                    st.metric("➕ Entities Added", jit_stats.get("entities_added", 0))
                                with col2:
                                    st.metric("➕ Relationships Added", jit_stats.get("relationships_added", 0))
                                with col3:
                                    st.metric("📄 Chunks Processed", jit_stats.get("chunks_processed", 0))

                                cache_hit = timings.get('cache_hit', False)
                                if cache_hit:
                                    st.success("✅ Cache Hit: Used existing graph data")
                                else:
                                    st.info("🔨 Built new graph segments for this query")

                        # Auto-scroll to bottom
                        st.markdown(
                            """
                            <script>
                            (function() {
                                var containers = [
                                    window.parent.document.querySelector('section.main'),
                                    window.parent.document.querySelector('[data-testid="stAppViewContainer"]')
                                ];
                                containers.forEach(function(c) {
                                    if (c) c.scrollTop = c.scrollHeight;
                                });
                            })();
                            </script>
                            """,
                            unsafe_allow_html=True
                        )

                        # Continue to show completion and metrics (skip streaming loop)
                    elif rag_strategy == "graph":
                        # Handle Graph RAG non-streaming response
                        result = response.json()

                        # Display answer
                        st.markdown("---")
                        st.markdown("### 💬 Answer")
                        answer = result.get("answer", "")
                        st.markdown(answer)

                        # Display Graph Context
                        graph_context = result.get("graph_context", {}) or result.get("timings", {}).get("graph_context", {})
                        if graph_context:
                            st.markdown("---")
                            st.markdown("### 🕸️ Knowledge Graph")

                            col1, col2 = st.columns(2)
                            with col1:
                                st.metric("📍 Entities", graph_context.get("num_entities", 0))
                            with col2:
                                st.metric("🔗 Relationships", graph_context.get("num_relationships", 0))

                            # Display entities grouped by type
                            entities = graph_context.get("entities", [])
                            if entities:
                                with st.expander("📍 Entities (by type)", expanded=False):
                                    # Group entities by type
                                    from collections import defaultdict
                                    entities_by_type = defaultdict(list)
                                    for ent in entities[:20]:  # Show top 20
                                        ent_type = ent.get("type", "unknown")
                                        entities_by_type[ent_type].append(ent.get("name", ""))

                                    for ent_type, names in entities_by_type.items():
                                        st.markdown(f"**{ent_type.capitalize()}**: {', '.join(names[:10])}")

                            # Display relationships
                            relationships = graph_context.get("relationships", [])
                            if relationships:
                                with st.expander("🔗 Key Relationships", expanded=True):
                                    for rel in relationships[:15]:  # Show top 15
                                        source = rel.get("source", "")
                                        target = rel.get("target", "")
                                        relation = rel.get("relation", "related_to")
                                        confidence = rel.get("confidence", 1.0)
                                        st.caption(f"**{source}** → *{relation}* → **{target}** (conf: {confidence:.2f})")

                            # Plotly graph (show nodes even if no edges)
                            if entities:
                                with st.expander("🌐 Interactive Graph Visualization", expanded=True):
                                    import plotly.graph_objects as go
                                    import networkx as nx

                                    G = nx.DiGraph()
                                    for ent in entities[:50]:
                                        G.add_node(ent['name'], type=ent.get('type', 'unknown'))
                                    for rel in relationships[:100]:
                                        s = rel.get('source', '')
                                        t = rel.get('target', '')
                                        if s in G.nodes and t in G.nodes:
                                            G.add_edge(s, t, relation=rel.get('relation', ''))

                                    pos = nx.spring_layout(G, k=0.5, iterations=50) if len(G.nodes) > 0 else {}

                                    edge_x, edge_y, edge_text = [], [], []
                                    for edge in G.edges():
                                        x0, y0 = pos[edge[0]]
                                        x1, y1 = pos[edge[1]]
                                        edge_x.extend([x0, x1, None])
                                        edge_y.extend([y0, y1, None])
                                        relation = G.edges[edge].get('relation', '')
                                        edge_text.append(f"{edge[0]} → {relation} → {edge[1]}")

                                    edge_trace = go.Scatter(
                                        x=edge_x, y=edge_y,
                                        line=dict(width=0.5, color='#888'),
                                        hoverinfo='text',
                                        text=edge_text if edge_text else None,
                                        mode='lines')

                                    node_x, node_y, node_text, node_color = [], [], [], []
                                    color_map = {
                                        'person': '#FF6B6B',
                                        'character': '#FF6B6B',
                                        'role': '#FF8C42',
                                        'place': '#4ECDC4',
                                        'concept': '#95E1D3',
                                        'skill': '#FFA07A',
                                        'tool': '#DDA15E',
                                        'event': '#BC6C25',
                                        'unknown': '#CCCCCC'
                                    }

                                    for node in G.nodes():
                                        x, y = pos.get(node, (0, 0))
                                        node_x.append(x)
                                        node_y.append(y)
                                        node_type = G.nodes[node].get('type', 'unknown')
                                        node_text.append(f"{node}<br>Type: {node_type}")
                                        node_color.append(color_map.get(node_type, '#CCCCCC'))

                                    node_trace = go.Scatter(
                                        x=node_x, y=node_y,
                                        mode='markers+text',
                                        hoverinfo='text',
                                        text=[n for n in G.nodes()],
                                        hovertext=node_text,
                                        textposition="top center",
                                        textfont=dict(size=8),
                                        marker=dict(
                                            showscale=False,
                                            color=node_color,
                                            size=15,
                                            line_width=2))

                                    fig = go.Figure(data=[edge_trace, node_trace],
                                        layout=go.Layout(
                                            title=dict(text='Knowledge Graph Network', x=0.5, xanchor='center'),
                                            titlefont_size=16,
                                            showlegend=False,
                                            hovermode='closest',
                                            margin=dict(b=0,l=0,r=0,t=40),
                                            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                                            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                                            height=600
                                        ))

                                    st.plotly_chart(fig, use_container_width=True)
                                    st.caption("🎨 **Entity Types**: " + " | ".join([f"{k}: {v}" for k, v in color_map.items() if k != 'unknown']))

                        # Display JIT building stats
                        jit_stats = result.get("jit_stats", {})
                        if jit_stats:
                            st.markdown("---")
                            st.markdown("### 🔨 JIT Graph Building")
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric("➕ Entities Added", jit_stats.get("entities_added", 0))
                            with col2:
                                st.metric("➕ Relationships Added", jit_stats.get("relationships_added", 0))
                            with col3:
                                st.metric("📄 Chunks Processed", jit_stats.get("chunks_processed", 0))

                            cache_hit = result.get("cache_hit", False)
                            if cache_hit:
                                st.success("✅ Cache Hit - Used existing graph data!")
                            else:
                                st.info("🔨 Built new graph segments on-demand")

                        # Display timing metrics
                        timings = result.get("timings", {})
                        if timings:
                            st.markdown("---")
                            st.markdown("### ⚡ Performance Metrics")
                            col1, col2, col3, col4 = st.columns(4)
                            with col1:
                                st.metric("Total", f"{timings.get('total_ms', 0):.0f}ms")
                            with col2:
                                st.metric("JIT Build", f"{timings.get('jit_build_ms', 0):.0f}ms")
                            with col3:
                                st.metric("Entity Extraction", f"{timings.get('entity_extraction_ms', 0):.0f}ms")
                            with col4:
                                st.metric("Graph Query", f"{timings.get('graph_query_ms', 0):.0f}ms")

                        # Display token usage and cost
                        token_usage = result.get("token_usage", {})
                        token_cost_usd = result.get("token_cost_usd", 0.0)
                        if token_usage:
                            st.markdown("---")
                            st.markdown("### 💰 Token Usage & Cost")
                            col1, col2, col3, col4 = st.columns(4)
                            with col1:
                                st.metric("Prompt Tokens", token_usage.get('prompt_tokens', 0))
                            with col2:
                                st.metric("Completion Tokens", token_usage.get('completion_tokens', 0))
                            with col3:
                                st.metric("Total Tokens", token_usage.get('total_tokens', 0))
                            with col4:
                                st.metric("Token Cost (USD)", f"${token_cost_usd:.4f}")

                    else:
                        if not used_streaming:
                            # Non-streaming flow (multi-collection)
                            result = response.json()
                            full_answer = result.get("answer", "")

                            if rag_strategy == "table":
                                excel_step = "4️⃣ Excel analysis (reverse energy tool)" if "Excel Analysis" in full_answer else "4️⃣ Excel analysis (skipped/no excel match)"
                                st.markdown("### 🧭 Table RAG Pipeline")
                                st.markdown(
                                    "\n".join([
                                        "- 1️⃣ Query intent extraction (entities/attributes)",
                                        "- 2️⃣ Hybrid retrieval (vector + BM25)",
                                        "- 3️⃣ Table structuring from context",
                                        f"- {excel_step}",
                                        "- 5️⃣ Answer generation with table + tool context",
                                    ])
                                )

                            st.markdown("---")
                            st.markdown("### 💬 Answer")
                            st.markdown(full_answer)

                            # Table RAG metrics and tool usage
                            if rag_strategy == "table":
                                timings = result.get("timings", {}) or {}
                                models_info = result.get("models", {}) or {}
                                token_usage = result.get("token_usage", {}) or {}
                                tool_info = result.get("tool_usage") or result.get("tool") or {}

                                st.markdown("---")
                                st.markdown("### ⚡ Performance Metrics (Table RAG)")
                                colm1, colm2, colm3, colm4 = st.columns(4)
                                colm1.metric("Retrieval", f"{timings.get('retrieval_ms', 0):.1f}ms")
                                colm2.metric("Structuring", f"{timings.get('structuring_ms', 0):.1f}ms")
                                colm3.metric("Answer Gen", f"{timings.get('answer_generation_ms', 0):.1f}ms")
                                colm4.metric("Total", f"{timings.get('total_ms', 0):.1f}ms")

                                st.markdown("### 🤖 Models Used")
                                st.markdown(
                                    f"- Embedding: `{models_info.get('embedding', '—')}`\n"
                                    f"- Reranker: `{models_info.get('reranker', '—')}`\n"
                                    f"- LLM: `{models_info.get('llm', '—')}`"
                                )

                                st.markdown("### 🪙 Tokens")
                                tc1, tc2, tc3 = st.columns(3)
                                tc1.metric("Prompt", int(token_usage.get("prompt", 0) or 0))
                                tc2.metric("Completion", int(token_usage.get("completion", 0) or 0))
                                tc3.metric("Total", int(token_usage.get("total", 0) or 0))

                                # Tool usage display
                                if tool_info:
                                    st.markdown("### 🛠️ Excel Tool")
                                    triggered = tool_info.get("triggered") or tool_info.get("excel_triggered")
                                    status = tool_info.get("status") or ("success" if tool_info.get("excel_success") else "failed")
                                    reason = tool_info.get("reason")
                                    st.caption(f"Triggered: {triggered}, Status: {status}, Time: {tool_info.get('execution_time_ms', 0):.1f}ms")
                                    if reason:
                                        st.caption(f"Reason: {reason}")
                                    output = tool_info.get("output")
                                    if not output:
                                        output = result.get("excel_result")
                                    if output:
                                        st.markdown("**Excel reverse energy analysis:**")
                                        st.caption(f"File: {output.get('uploaded_file')}")
                                        st.metric("Total (kWh)", f"{output.get('reverse_energy_kwh', 0):.2f}")
                                        rows = output.get("rows") or []
                                        if rows:
                                            with st.expander("Details by period", expanded=False):
                                                for r in rows:
                                                    st.markdown(f"- {r.get('label')}: start {r.get('start')}, end {r.get('end')}, delta {r.get('delta')}")
                        else:
                            # Process streaming response for non-smart modes
                            full_answer = ""
                            result = {}
                            answer_placeholder = None  # Will be created after retrieval event

                            for line in response.iter_lines():
                                if not line:
                                    continue

                                line_str = line.decode('utf-8')

                                # Parse SSE format
                                if line_str.startswith('data:'):
                                    # IMPORTANT: Only strip newlines, NOT spaces (for proper word spacing)
                                    data_str = line_str[5:].strip('\r\n')

                                    if data_str == '[DONE]':
                                        break

                                    # Backend sends " " (single space) tokens which represent \n
                                    # when they appear as TWO consecutive spaces
                                    if data_str == ' ':
                                        # Single space token - check if previous token was also a space
                                        if full_answer.endswith(' '):
                                            # Two consecutive spaces = newline
                                            full_answer = full_answer[:-1] + '\n'
                                            if answer_placeholder:
                                                answer_placeholder.markdown(full_answer + "▊")
                                        else:
                                            # First space, just add it
                                            full_answer += ' '
                                        continue

                                    # Empty data lines (no content after "data:")
                                    if not data_str:
                                        continue

                                    try:
                                        data = json_module.loads(data_str)

                                        # CRITICAL: Ensure data is a dict before using 'in' operator
                                        if not isinstance(data, dict):
                                            # Non-dict JSON data (int, string, etc.) - treat as content
                                            # Convert back to string and add to answer
                                            full_answer += str(data)
                                            # Update display with typing effect
                                            if answer_placeholder:
                                                answer_placeholder.markdown(full_answer + "▊")
                                            continue

                                        # Handle retrieval event (metadata)
                                        if 'citations' in data:
                                            num_chunks = data.get('num_chunks', 0)
                                            retrieval_ms = data.get('retrieval_time_ms', 0)
                                            result['citations'] = data.get('citations', [])
                                            result['num_chunks_retrieved'] = num_chunks
                                            result['retrieval_time_ms'] = retrieval_ms
                                            st.caption(f"📚 Retrieved {num_chunks} documents ({retrieval_ms:.0f}ms)")

                                            # For Smart mode, display final LLM generation step
                                            if answer_placeholder is None and rag_strategy == "smart":
                                                st.markdown("**3️⃣ 🤖 LLM Answer Generation**")
                                                st.caption("GPT-4o with Retrieved Context")

                                            # Create answer section AFTER retrieval and technique display
                                            if answer_placeholder is None:
                                                st.markdown("---")
                                                st.markdown("### 💬 Answer")
                                                answer_placeholder = st.empty()

                                        # Handle metadata event
                                        elif 'usage' in data or 'cost' in data or 'total_time_ms' in data:
                                            result['metadata'] = data
                                            result['token_usage'] = data.get('usage', {})
                                            result['token_cost_usd'] = data.get('cost', 0)
                                            result['total_time_ms'] = data.get('total_time_ms', 0)
                                            result['llm_time_ms'] = data.get('llm_time_ms', 0)
                                            result['retrieval_time_ms'] = data.get('retrieval_time_ms', 0)

                                            # Extract detailed timings if available
                                            if 'timings' in data:
                                                result['timings'] = data['timings']

                                        # Handle error
                                        elif 'error' in data:
                                            st.error(f"❌ Error: {data['error']}")
                                            result = None
                                            break

                                    except json_module.JSONDecodeError:
                                        # This is a content chunk (plain text)
                                        # If this is the first chunk, strip leading space (GPT tokenizer adds space at start)
                                        if not full_answer and data_str.startswith(' '):
                                            data_str = data_str[1:]  # Remove leading space from first chunk

                                        full_answer += data_str
                                        # Update display with typing effect
                                        if answer_placeholder:
                                            answer_placeholder.markdown(full_answer + "▊")

                            # Display complete answer after streaming finishes
                            if full_answer:
                                # Clean up markdown formatting issues (spaces between ** markers)
                                import re
                                # Fix "** Reason ing :**" -> "**Reasoning:**"
                                # Strategy: Remove ALL spaces between ** markers (for bold text)
                                # This handles cases like "**Reason ing:**" where GPT tokenizer splits words
                                # But KEEP newlines in the answer - don't replace them!
                                cleaned_answer = re.sub(
                                    r'\*\*([^*\n]+?)\*\*',  # Only match within single line (exclude \n)
                                    lambda m: '**' + m.group(1).replace(' ', '') + '**',
                                    full_answer
                                )

                                result['answer'] = cleaned_answer

                                # Remove cursor after streaming completes
                                if answer_placeholder:
                                    answer_placeholder.markdown(cleaned_answer)

                    # Show completion
                    st.success("✅ All RAG Techniques Applied Successfully!")

                    # Check if query was slow and auto-switch to fallback
                    # Type-safe extraction of total_ms
                    total_ms = result.get("total_time_ms", 0.0)
                    if not total_ms or total_ms == 0.0:
                        timings_data = result.get("timings", {})
                        if isinstance(timings_data, dict):
                            total_ms = timings_data.get("end_to_end_ms", 0.0)

                    current_reranker = st.session_state.get("rag_reranker_choice", "primary")

                    # Auto-switch to fallback if primary took > 300ms and not already on fallback
                    if total_ms > 300 and current_reranker == "primary" and "fallback" in reranker_options:
                        st.session_state.rag_reranker_choice = "fallback"
                        st.session_state.rag_last_reranker = "fallback"
                        st.warning(f"⚡ Query took {total_ms:.1f}ms (>300ms). Auto-switched to Fallback (MiniLM) for faster responses.")

                        # Warm up fallback with 3 queries from eval data
                        with st.spinner("🔥 Warming up Fallback reranker (3 queries)..."):
                            try:
                                # Load real eval questions for warm-up
                                warmup_questions = load_warmup_questions()

                                for i, question in enumerate(warmup_questions, 1):
                                    warmup_response = requests.post(
                                        f"{BACKEND_URL}/api/rag/ask",
                                        json={
                                            "question": question,
                                            "top_k": 3,
                                            "include_timings": True,  # Use same code path as real queries
                                            "reranker": "fallback",
                                            "vector_limit": 5,
                                            "content_char_limit": 300
                                        },
                                        timeout=30
                                    )
                                st.success("✅ Fallback reranker ready!")
                            except Exception as e:
                                st.warning(f"⚠️ Fallback warm-up failed: {e}")

                    # Answer already displayed during streaming (via answer_placeholder)
                    # No need to display again here

                    # Display metrics
                    st.markdown("---")

                    # Type-safe extraction with dict verification
                    timings = result.get("timings") or {}
                    if not isinstance(timings, dict):
                        timings = {}

                    models_info = result.get("models") or {}
                    if not isinstance(models_info, dict):
                        models_info = {}

                    llm_ms = timings.get("llm_ms", result.get("llm_time_ms", 0.0))
                    retrieval_ms = result.get('retrieval_time_ms', timings.get('total_ms', 0))

                    # Main metrics row
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Retrieval Time", f"{retrieval_ms:.1f}ms")
                    col2.metric("Confidence", f"{result.get('confidence', 0):.3f}")
                    col3.metric("Chunks", result.get('num_chunks_retrieved', 0))

                    # Always display detailed latency breakdown
                    st.markdown("**📊 Detailed Latency Breakdown**")

                    # Row 1: Embed, Vector, Candidate
                    row1_cols = st.columns(3)

                    # Extract timing metrics - handle both detailed and hybrid_search_ms formats
                    embed_ms = timings.get('embed_ms') or timings.get('embedding_ms', 0.0)
                    vector_ms = timings.get('vector_ms') or timings.get('vector_search_ms', 0.0)
                    candidate_ms = timings.get('candidate_prep_ms') or timings.get('candidate_ms', 0.0)

                    # If we don't have individual metrics but have hybrid_search_ms, split it
                    if (embed_ms == 0.0 and vector_ms == 0.0) and 'hybrid_search_ms' in timings:
                        hybrid_ms = timings['hybrid_search_ms']
                        embed_ms = hybrid_ms * 0.3  # Approximate: 30% for embedding
                        vector_ms = hybrid_ms * 0.7  # Approximate: 70% for vector search

                    row1_cols[0].metric("⚡ Embed", f"{embed_ms:.1f}ms")
                    row1_cols[1].metric("🔍 Vector", f"{vector_ms:.1f}ms")
                    row1_cols[2].metric("📝 Candidate", f"{candidate_ms:.1f}ms")

                    # Row 2: Rerank, LLM, Total
                    row2_cols = st.columns(3)
                    rerank_ms = timings.get('rerank_ms') or timings.get('reranking_ms', 0.0)
                    total_ms = timings.get('end_to_end_ms') or result.get('total_time_ms', 0.0)

                    row2_cols[0].metric("🎯 Rerank", f"{rerank_ms:.1f}ms")
                    row2_cols[1].metric("🤖 LLM", f"{llm_ms:.1f}ms")
                    row2_cols[2].metric("⏱️ Total", f"{total_ms:.1f}ms")

                    token_usage = result.get("token_usage") or {}
                    if not isinstance(token_usage, dict):
                        token_usage = {}

                    token_cost_usd = float(result.get("token_cost_usd") or 0.0)
                    prompt_tokens = int(token_usage.get("prompt", 0) or 0)
                    completion_tokens = int(token_usage.get("completion", 0) or 0)
                    total_tokens = int(token_usage.get("total", prompt_tokens + completion_tokens) or 0)

                    if token_usage or token_cost_usd:
                        st.markdown("**Token Usage & Cost**")
                        token_cols = st.columns(4)
                        token_cols[0].metric("Prompt Tokens", prompt_tokens)
                        token_cols[1].metric("Completion Tokens", completion_tokens)
                        token_cols[2].metric("Total Tokens", total_tokens)
                        token_cols[3].metric("Token Cost (USD)", f"${token_cost_usd:.4f}")

                    vector_used = result.get("vector_limit_used") or timings.get("vector_limit_used")
                    content_used = result.get("content_char_limit_used") or timings.get("content_char_limit_used")
                    reranker_mode = result.get("reranker_mode") or timings.get("reranker_mode")
                    capsule = []
                    if vector_used is not None:
                        capsule.append(f"vector limit {vector_used}")
                    if content_used:
                        capsule.append(f"content limit {content_used}")
                    else:
                        capsule.append("full content")
                    if reranker_mode:
                        capsule.append(f"reranker mode {reranker_mode}")
                    st.caption(" | ".join(capsule))

                    if models_info:
                        st.markdown("**Models Used**")
                        st.markdown(
                            f"- Embedding: `{format_model_label(models_info.get('embedding'))}`\n"
                            f"- Reranker: `{format_model_label(models_info.get('reranker'))}`\n"
                            f"- LLM: `{models_info.get('llm', '—')}`"
                        )

                    # Update RAG stats
                    retrieval_ms = result.get('retrieval_time_ms', 0.0)
                    rerank_ms = timings.get('rerank_ms', 0.0)
                    confidence = result.get('confidence', 0.0)
                    current_reranker_choice = st.session_state.get("rag_reranker_choice", "primary")

                    st.session_state.rag_stats["total_queries"] += 1
                    st.session_state.rag_stats["total_retrieval_ms"] += retrieval_ms
                    st.session_state.rag_stats["total_rerank_ms"] += rerank_ms
                    st.session_state.rag_stats["total_llm_ms"] += llm_ms
                    st.session_state.rag_stats["total_tokens"] += total_tokens
                    st.session_state.rag_stats["total_cost_usd"] += token_cost_usd

                    # Update average confidence
                    old_avg = st.session_state.rag_stats["avg_confidence"]
                    n = st.session_state.rag_stats["total_queries"]
                    st.session_state.rag_stats["avg_confidence"] = ((old_avg * (n - 1)) + confidence) / n

                    # Track reranker usage
                    if current_reranker_choice == "primary":
                        st.session_state.rag_stats["primary_reranker_count"] += 1
                    elif current_reranker_choice == "fallback":
                        st.session_state.rag_stats["fallback_reranker_count"] += 1

                    # Display citation sources
                    citations = result.get("citations", [])
                    if citations:
                        with st.expander("📎 View Sources"):
                            for i, citation in enumerate(citations, 1):
                                st.markdown(f"**[{i}] {citation.get('source', 'Unknown')}**")
                                st.markdown(f"- Score: {citation.get('score', 0):.3f}")
                                content = citation.get('content', '')
                                snippet = content[:200] + "..." if len(content) > 200 else content
                                st.markdown(f"- Content: {snippet}")
                                st.markdown("")

                    # Ask if continue with example questions
                    st.markdown("\n**Continue asking questions or type 'q'(quit) to exit RAG mode.**")

                    # Show example questions dropdown in the CURRENT (latest) RAG response only
                    # Use unique key based on message count to avoid widget conflicts
                    dropdown_key = f"rag_example_{len(st.session_state.messages)}"

                    def on_rag_example_select():
                        selected = st.session_state.get(dropdown_key)
                        if selected and selected != "Select a question...":
                            append_chat_history("user", selected)
                            st.session_state.pending_prompt = selected
                            # Reset this specific dropdown
                            st.session_state[dropdown_key] = "Select a question..."

                    st.selectbox(
                        "💡 Example Questions",
                        options=["Select a question..."] + EXAMPLE_QUESTIONS_BOTTOM,
                        key=dropdown_key,
                        on_change=on_rag_example_select
                    )

                    # Collect RAG metrics
                    st.session_state.rag_metrics["retrieval_times"].append(result.get('retrieval_time_ms', 0))
                    st.session_state.rag_metrics["confidences"].append(result.get('confidence', 0))

                    # Save to message history and display immediately
                    metrics_parts = [
                        f"Retrieval: {result.get('retrieval_time_ms', 0):.1f}ms",
                        f"Embed: {timings.get('embed_ms', 0.0):.1f}ms",
                        f"Vector: {timings.get('vector_ms', 0.0):.1f}ms",
                        f"Rerank: {timings.get('rerank_ms', 0.0):.1f}ms",
                        f"LLM: {llm_ms:.1f}ms",
                    ]
                    if prompt_tokens or completion_tokens:
                        metrics_parts.append(f"Tokens: {total_tokens}")
                    if token_cost_usd:
                        metrics_parts.append(f"Token Cost: ${token_cost_usd:.4f}")
                    metrics_summary = " | ".join(metrics_parts)
                    model_summary = (
                        f"Embedding: {format_model_label(models_info.get('embedding'))}, "
                        f"Reranker: {format_model_label(models_info.get('reranker'))}, "
                        f"LLM: {models_info.get('llm', '—')}"
                    )

                    # Save full answer with metrics to chat history
                    # Use result['answer'] which works for both streaming (cleaned_answer) and non-streaming (Smart RAG)
                    answer_text = result.get('answer', '')

                    full_response = (
                        f"**Answer:**\n\n{answer_text}\n\n---\n\n"
                        f"**Metrics:** {metrics_summary} | Confidence: {result.get('confidence', 0):.3f} "
                        f"| Chunks: {result.get('num_chunks_retrieved', 0)}\n"
                        f"**Models:** {model_summary}\n\n"
                        "**Continue asking questions or type 'q'(quit) to exit RAG mode.**"
                    )
                    append_chat_history("assistant", full_response)

                    stored_token_usage = None
                    if token_usage or prompt_tokens or completion_tokens:
                        stored_token_usage = {
                            "prompt": prompt_tokens,
                            "completion": completion_tokens,
                            "total": total_tokens,
                        }

                    st.session_state.metrics_history["timestamps"].append(datetime.now())
                    st.session_state.metrics_history["latencies"].append(total_ms)
                    st.session_state.metrics_history["prompt_tokens"].append(prompt_tokens)
                    st.session_state.metrics_history["completion_tokens"].append(completion_tokens)
                    st.session_state.metrics_history["costs"].append(token_cost_usd)
                    st.session_state.metrics_history["services"].append("rag")

                    st.session_state.rag_last_summary = {
                        "timings": {
                            "embed_ms": timings.get("embed_ms", 0.0),
                            "vector_ms": timings.get("vector_ms", 0.0),
                            "rerank_ms": timings.get("rerank_ms", 0.0),
                            "llm_ms": llm_ms,
                            "end_to_end_ms": total_ms,
                        },
                        "models": models_info,
                        "vector_limit": vector_used,
                        "content_limit": content_used,
                        "reranker_mode": reranker_mode,
                        "token_usage": stored_token_usage,
                        "token_cost_usd": token_cost_usd,
                    }

                else:
                    error_msg = f"❌ Error: {response.status_code}"
                    st.error(error_msg)
                    append_chat_history("assistant", error_msg)

            except Exception as e:
                error_msg = f"❌ Request failed: {e}"
                st.error(error_msg)
                append_chat_history("assistant", error_msg)

    # =====================================================================
    # Trip Planning Mode - Full replication of chat_agent.py
    # =====================================================================

elif current_mode == "trip" and prompt and prompt != "__MODE_ACTIVATED__":
    if prompt and _is_quit(prompt):
        _cleanup_mode_state("trip")
        st.session_state.mode = "general"
        append_chat_history("assistant", "👋 Exited Trip Planning mode.")
        st.rerun()


    constraints_state = st.session_state.get("trip_constraints")
    debug_log(f"[trip] constraints_state type={type(constraints_state)}")
    try:
        constraints_dump = constraints_state.model_dump(exclude_none=True)  # type: ignore[attr-defined]
    except AttributeError:
        constraints_dump = str(constraints_state)
    debug_log(
        f"[trip] prompt={prompt!r} awaiting={st.session_state.awaiting_confirmation} "
        f"constraints_type={type(constraints_state)} constraints={constraints_dump}"
    )
    with st.chat_message("assistant"):
        debug_log("[trip] entered assistant chat block")
        # Special command: status
        if prompt.lower() in ['status', 'info', 'show']:
            summary = format_constraints_summary(st.session_state.trip_constraints)
            is_complete, missing = check_constraints_complete(st.session_state.trip_constraints)

            st.markdown("📝 **Current trip information:**")
            st.code(summary)

            if not is_complete:
                st.warning(f"⚠️ Missing: {', '.join(missing)}")
            else:
                is_valid, issues = validate_constraints(st.session_state.trip_constraints)
                if not is_valid:
                    st.warning(f"⚠️ Issues: {', '.join(issues)}")
                else:
                    st.success("✅ All information complete and valid!")

            append_chat_history("assistant", "Status displayed")
            # st.stop() - removed to allow page to render

        # command：reset
        if prompt.lower() in ['reset', 'clear', 'restart']:
            st.session_state.trip_constraints = TripConstraints()
            st.session_state.session_mgr.save_constraints(
                st.session_state.session_id,
                st.session_state.trip_constraints
            )
            st.session_state.trip_last_plan = None
            st.success("🔄 Trip information cleared. Let's start fresh!")
            append_chat_history("assistant", "Reset complete")
            # st.stop() - removed to allow page to render

        # If waiting for confirmation
        if st.session_state.awaiting_confirmation:
            user_response = prompt.lower().strip()

            # Handle quit/exit
            if user_response in ['q', 'quit', 'exit', 'cancel']:
                st.info("👋 Trip planning cancelled. Feel free to start a new trip anytime!")
                append_chat_history("assistant", "Trip planning cancelled")
                st.session_state.awaiting_confirmation = False
                st.session_state.trip_constraints = TripConstraints()  # Reset

            # Handle re-create/restart
            elif user_response in ['r', 'recreate', 're-create', 'restart', 'start over']:
                st.info("🔄 Let's start over! Please tell me about your trip plans.")
                append_chat_history("assistant", "Restarting trip planning from scratch")
                st.session_state.awaiting_confirmation = False
                st.session_state.trip_constraints = TripConstraints()  # Reset all constraints

            # Handle confirmation to proceed
            elif user_response in ['yes', 'y', 'sure', 'ok', 'okay', 'go', 'proceed']:
                # Execute planning
                print("[Trip] Confirmation received, calling /api/agent/plan")
                with st.spinner("🔄 Planning your trip..."):
                    try:
                        # Fill start date
                        if not st.session_state.trip_constraints.start_date:
                            start = date.today() + timedelta(days=7)
                            st.session_state.trip_constraints.start_date = start.isoformat()
                            if st.session_state.trip_constraints.days:
                                end = start + timedelta(days=st.session_state.trip_constraints.days - 1)
                                st.session_state.trip_constraints.end_date = end.isoformat()

                        payload = {
                            "prompt": f"Plan a {st.session_state.trip_constraints.days}-day trip to {st.session_state.trip_constraints.destination_city}",
                            "constraints": st.session_state.trip_constraints.model_dump(exclude_none=True),
                            "max_iterations": 5,
                        }
                        plan_resp = requests.post(
                            f"{BACKEND_URL}/api/agent/plan",
                            json=payload,
                            timeout=120,
                        )
                        print(
                            f"[Trip] Plan response status={plan_resp.status_code} "
                            f"content_type={plan_resp.headers.get('content-type')}"
                        )
                        if plan_resp.status_code != 200:
                            raise RuntimeError(
                                f"Backend returned {plan_resp.status_code}: {plan_resp.text}"
                            )
                        response = plan_resp.json()
                        st.session_state.trip_last_plan = response

                        # result
                        st.success("✅ Here's your trip plan!")

                        itinerary = response.get("itinerary", {})
                        destination = itinerary.get("destination", "Unknown")
                        currency = itinerary.get("currency") or infer_currency_from_origin(
                            st.session_state.trip_constraints.origin_city
                        ) or "USD"
                        currency = currency.upper()
                        st.session_state.trip_constraints.currency = currency
                        st.markdown(f"**📍 Destination:** {destination}")

                        # flight
                        flights = itinerary.get("flights") or []
                        if flights:
                            st.markdown("**✈️ Flights:**")
                            for i, flight in enumerate(flights[:2], 1):
                                airline = flight.get("airline", "Unknown airline")
                                number = flight.get("flight_number", "N/A")
                                st.markdown(f"{i}. {airline} {number}")
                                st.markdown(f"   - {flight.get('departure_time', '?')} → {flight.get('arrival_time', '?')}")
                                flight_price = float(flight.get("price", 0.0))
                                display_currency = (flight.get("currency") or currency).upper()
                                st.markdown(f"   - Price: {display_currency} {flight_price:.2f}")
                                original_currency = flight.get("original_currency")
                                original_price = flight.get("original_price")
                                if (
                                    original_currency
                                    and original_price is not None
                                    and original_currency.upper() != display_currency
                                ):
                                    st.caption(
                                        f"     (~ {original_currency.upper()} {float(original_price):.2f} before conversion)"
                                    )
                                st.markdown(f"   - Duration: {flight.get('duration_hours', 0)} hours")

                        # weather
                        weather = itinerary.get("weather_forecast") or []
                        if weather:
                            st.markdown("**🌤️ Weather Forecast:**")
                            for day in weather[:3]:
                                st.markdown(
                                    f"   - {day.get('date', '?')}: {day.get('temperature_celsius', 0)}°C, {day.get('condition', '')}"
                                )

                        # landmark
                        attractions = itinerary.get("attractions") or []
                        if attractions:
                            st.markdown("**🎯 Top Attractions:**")
                            for i, attr in enumerate(attractions[:5], 1):
                                st.markdown(
                                    f"{i}. {attr.get('name', 'Attraction')} ({attr.get('category', '')}) - ⭐ {attr.get('rating', 0)}/5"
                                )
                                st.markdown(f"   - {attr.get('price_range', 'N/A')}")

                        # Cost
                        st.markdown("**💰 Cost Breakdown:**")
                        cost_breakdown = itinerary.get("cost_breakdown") or {}
                        if cost_breakdown:
                            flight_cost = float(cost_breakdown.get("flights", 0.0))
                            accommodation_cost = float(cost_breakdown.get("accommodation", 0.0))
                            meals_cost = float(cost_breakdown.get("meals", 0.0))
                            other_cost = float(cost_breakdown.get("other", 0.0))

                            if flight_cost > 0:
                                st.markdown(f"- Flights: {currency} {flight_cost:.2f}")
                            if accommodation_cost > 0:
                                st.markdown(f"- Accommodation: {currency} {accommodation_cost:.2f}")
                            if meals_cost > 0:
                                st.markdown(f"- Meals: {currency} {meals_cost:.2f}")
                            if other_cost > 0:
                                st.markdown(f"- Transport & Activities: {currency} {other_cost:.2f}")
                        else:
                            st.caption("Cost breakdown unavailable.")

                        total_cost = itinerary.get("total_cost")
                        total_cost_usd = itinerary.get("total_cost_usd")
                        llm_usage = response.get("llm_token_usage") or {}
                        llm_prompt_tokens = int(llm_usage.get("prompt", 0) or 0)
                        llm_completion_tokens = int(llm_usage.get("completion", 0) or 0)
                        llm_total_tokens = int(llm_usage.get("total", llm_prompt_tokens + llm_completion_tokens) or 0)
                        llm_cost_usd = float(response.get("llm_cost_usd") or 0.0)
                        if total_cost is not None:
                            st.markdown(f"**💵 Total: {currency} {total_cost:.2f}**")
                            if total_cost_usd is not None and total_cost_usd > 0:
                                st.caption(f"(≈ USD {total_cost_usd:.2f})")

                        currency_note = itinerary.get("currency_note")
                        if currency_note:
                            st.caption(currency_note)

                        if llm_total_tokens or llm_cost_usd:
                            st.markdown("**LLM Token Usage**")
                            token_cols = st.columns(4)
                            token_cols[0].metric("Prompt", llm_prompt_tokens)
                            token_cols[1].metric("Completion", llm_completion_tokens)
                            token_cols[2].metric("Total", llm_total_tokens)
                            token_cols[3].metric("Token Cost (USD)", f"${llm_cost_usd:.4f}")

                        fx_rates = itinerary.get("fx_rates") or {}
                        if fx_rates:
                            fx_lines = []
                            for key, value in fx_rates.items():
                                if not isinstance(value, (int, float)):
                                    continue
                                if "->" in key:
                                    src, tgt = key.split("->", 1)
                                    fx_lines.append(f"1 {src.upper()} ≈ {value:.4f} {tgt.upper()}")
                                else:
                                    fx_lines.append(f"1 {key.upper()} ≈ {value:.4f} {currency}")
                            if fx_lines:
                                st.caption("FX rates: " + "; ".join(fx_lines))

                        # Constraint satisfaction status
                        if response.get("constraints_satisfied", False):
                            st.success("✅ All constraints satisfied!")
                        else:
                            st.warning("⚠️ Constraint issues:")
                            for violation in response.get("constraint_violations", []):
                                st.markdown(f"- {violation}")

                        tool_calls = response.get("tool_calls") or []
                        st.markdown(f"\n🔧 Tools used: {len(tool_calls)} calls in {response.get('total_iterations', 0)} iterations")
                        st.markdown(f"⏱️ Planning time: {response.get('planning_time_ms', 0):.0f}ms")

                        # Learning system feedback display
                        learning = response.get("learning")
                        if learning:
                            st.markdown("---")
                            st.markdown("### 🎓 Learning System Feedback")

                            reward = learning.get("reward", 0.0)
                            success = learning.get("success", False)
                            strategy = learning.get("strategy", "unknown")

                            # Display reward with color coding
                            if reward >= 0.8:
                                reward_color = "🟢"
                                reward_text = "Excellent"
                            elif reward >= 0.6:
                                reward_color = "🟡"
                                reward_text = "Good"
                            elif reward >= 0.4:
                                reward_color = "🟠"
                                reward_text = "Fair"
                            else:
                                reward_color = "🔴"
                                reward_text = "Needs Improvement"

                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric("Overall Reward", f"{reward:.3f}", delta=reward_text)
                            with col2:
                                st.metric("Strategy Used", strategy)
                            with col3:
                                status_icon = "✅" if success else "⚠️"
                                st.metric("Success", status_icon)

                            # Reward breakdown
                            breakdown = learning.get("breakdown", {})
                            if breakdown:
                                st.markdown("**📊 Reward Breakdown:**")
                                breakdown_cols = st.columns(3)

                                budget_reward = breakdown.get("budget", 0.0)
                                quality_reward = breakdown.get("quality", 0.0)
                                reliability_reward = breakdown.get("reliability", 0.0)

                                with breakdown_cols[0]:
                                    st.markdown(f"💰 **Budget**: {budget_reward:.3f}")
                                    st.progress(min(budget_reward, 1.0))

                                with breakdown_cols[1]:
                                    st.markdown(f"⭐ **Quality**: {quality_reward:.3f}")
                                    st.progress(min(quality_reward, 1.0))

                                with breakdown_cols[2]:
                                    st.markdown(f"🔧 **Reliability**: {reliability_reward:.3f}")
                                    st.progress(min(reliability_reward, 1.0))

                            # Store learning history
                            if "learning_history" not in st.session_state:
                                st.session_state.learning_history = {
                                    "timestamps": [],
                                    "rewards": [],
                                    "strategies": [],
                                    "budget_rewards": [],
                                    "quality_rewards": [],
                                    "reliability_rewards": []
                                }

                            st.session_state.learning_history["timestamps"].append(datetime.now())
                            st.session_state.learning_history["rewards"].append(reward)
                            st.session_state.learning_history["strategies"].append(strategy)
                            st.session_state.learning_history["budget_rewards"].append(breakdown.get("budget", 0.0))
                            st.session_state.learning_history["quality_rewards"].append(breakdown.get("quality", 0.0))
                            st.session_state.learning_history["reliability_rewards"].append(breakdown.get("reliability", 0.0))

                        agent_stats = st.session_state.agent_stats
                        if response.get("constraints_satisfied", False):
                            agent_stats["success"] += 1
                        else:
                            agent_stats["partial"] += 1

                        planning_latency = response.get("planning_time_ms", 0.0)
                        token_cost_usd = llm_cost_usd

                        st.session_state.metrics_history["timestamps"].append(datetime.now())
                        st.session_state.metrics_history["latencies"].append(planning_latency)
                        st.session_state.metrics_history["prompt_tokens"].append(llm_prompt_tokens)
                        st.session_state.metrics_history["completion_tokens"].append(llm_completion_tokens)
                        st.session_state.metrics_history["costs"].append(token_cost_usd)
                        st.session_state.metrics_history["services"].append("trip")

                        st.markdown("\n**Would you like to make any changes to this plan? (or type 'q'(quit) to exit)**")

                        append_chat_history("assistant", "Trip plan created")
                        st.session_state.awaiting_confirmation = False

                    except Exception as e:
                        st.error(f"❌ Sorry, I encountered an error: {e}")
                        append_chat_history("assistant", f"Error: {e}")
                        st.session_state.agent_stats["failure"] += 1
                        st.session_state.awaiting_confirmation = False

            # Handle modifications/updates to constraints
            else:
                # The user provided modification text instead of y/r/q
                # Process it as a constraint update
                st.session_state.awaiting_confirmation = False
                # Set pending_prompt to re-process this input
                st.session_state.pending_prompt = prompt
                st.info("📝 Updating your trip information...")
                st.rerun()

        # Normal constraint collection flow
        else:
            # Thinking step: extract constraints
            print("[Trip] Extracting constraints from prompt")
            debug_log("[trip] extracting constraints")
            with st.spinner("🤔 Analyzing your request..."):
                old_constraints = st.session_state.trip_constraints.model_copy(deep=True)
                new_constraints, used_llm = extract_constraints_hybrid(
                    prompt,
                    st.session_state.trip_constraints
                )
                st.session_state.trip_constraints = new_constraints
                try:
                    new_dump = new_constraints.model_dump(exclude_none=True)
                except AttributeError:
                    new_dump = str(new_constraints)
                debug_log(
                    f"[trip] extracted constraints={new_dump} used_llm={used_llm}"
                )

                if used_llm:
                    st.info("🤖 Used LLM to understand city names")

            # Check if there is new information
            has_new_info = (
                new_constraints.destination_city != old_constraints.destination_city or
                new_constraints.origin_city != old_constraints.origin_city or
                new_constraints.days != old_constraints.days or
                new_constraints.budget != old_constraints.budget
            )

            # Display extracted information
            if has_new_info:
                st.session_state.session_mgr.save_constraints(
                    st.session_state.session_id,
                    new_constraints
                )
                st.success("✅ Got it! Here's what I understand:")
                st.code(format_constraints_summary(new_constraints))

            # Check completeness
            is_complete, missing = check_constraints_complete(new_constraints)

            if not is_complete:
                if not has_new_info:
                    st.info("🤔 I'd love to help! To plan your trip, I need some information.")

                st.warning(f"⚠️ Still need: {', '.join(missing)}")

                if "destination" in missing:
                    st.markdown("**Where would you like to go?**")
                elif "origin" in missing:
                    st.markdown("**Which city will you be departing from?**")
                elif "days" in missing:
                    st.markdown("**How many days will your trip last?**")
                elif "budget" in missing:
                    st.markdown("**What's your total budget?** (e.g., 500 NZD, $1000)")

                append_chat_history("assistant", f"Still need: {', '.join(missing)}")

            else:
                # Validate reasonableness
                is_valid, issues = validate_constraints(new_constraints)

                if not is_valid:
                    st.warning("⚠️ I noticed some potential issues:")
                    for issue in issues:
                        st.markdown(f"- {issue}")
                    st.markdown("\n**Would you like to proceed anyway, or update the information?**")
                    st.markdown("(Type 'y'(yes) to proceed, or provide updated information)")

                    append_chat_history("assistant", f"Issues found: {', '.join(issues)}")

                else:
                    # Information complete and reasonable, ask for confirmation
                    st.success("✅ Perfect! I have all the information:")
                    st.code(format_constraints_summary(new_constraints))
                    st.markdown("\n**Ready to create your trip plan?**")
                    st.markdown("**Options:**\n- 'y' (yes) - Create the trip plan\n- 'r' (re-create) - Start over from scratch\n- 'q' (quit) - Cancel trip planning\n- Or provide updated information to modify")

                    st.session_state.awaiting_confirmation = True
                    append_chat_history("assistant", "Awaiting confirmation")

# =====================================================================
# Code Generation Mode - 
# =====================================================================

elif current_mode == "code" and prompt and prompt != "__MODE_ACTIVATED__":
    print(
        f"[Code] prompt={prompt!r} "
        f"pending_auto={st.session_state.code_pending_auto} "
        f"force_lang={st.session_state.get('code_force_language')}"
    )
    if prompt and _is_quit(prompt):
        _cleanup_mode_state("code")
        st.session_state.mode = "general"
        append_chat_history("assistant", "👋 Exited Code Generation mode.")
        st.rerun()

    with st.chat_message("assistant"):
        # Detect language
        import re
        detected_lang = "python"  # default

        lang_patterns = {
            "bash": r'\b(bash|shell|sh script|bash script|echo|#!/bin/bash|#!/bin/sh)\b',
            "c": r'\b(in c\b|using c\b|c code|c language|#include|printf|main\(\))\b',
            "cpp": r'\b(c\+\+|cpp|in c\+\+|using c\+\+|std::|cout|#include <iostream>)\b',
            "csharp": r'\b(c#|csharp|c sharp|in c#|using c#|Console\.WriteLine|namespace)\b',
            "typescript": r'\b(typescript|ts|in ts|using typescript|\.ts\b|interface\s+\w+|type\s+\w+)\b',
            "rust": r'\b(rust|in rust|using rust|cargo)\b',
            "javascript": r'\b(javascript|js|in js|using javascript|node\.?js|console\.log|console log)\b',
            "python": r'\b(python|in python|using python|py|print\(|def )\b',
            "go": r'\b(golang|go lang|in go|using go|fmt\.print)\b',
            "java": r'\b(java|in java|using java|system\.out)\b'
        }

        prompt_lower = prompt.lower()
        for lang, pattern in lang_patterns.items():
            if re.search(pattern, prompt_lower):
                detected_lang = lang
                break

        if st.session_state.code_pending_auto and st.session_state.code_force_language:
            detected_lang = st.session_state.code_force_language

        st.info(f"🔤 Detected language: **{detected_lang}**")

        # Check and install necessary toolchain
        if detected_lang == "rust":
            st.markdown("**🔧 Checking Rust toolchain...**")
            check_result = subprocess.run(['which', 'cargo'], capture_output=True)

            if check_result.returncode != 0:
                st.warning("⚠️ Rust toolchain not found. Installing...")

                with st.spinner("📦 Installing Rust (this may take 2-3 minutes)..."):
                    install_cmd = 'curl --proto "=https" --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable'
                    install_result = subprocess.run(
                        install_cmd,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=300
                    )

                    if install_result.returncode == 0:
                        st.success("✅ Rust installed successfully!")
                        # Update PATH
                        os.environ['PATH'] = f"{os.path.expanduser('~/.cargo/bin')}:{os.environ.get('PATH', '')}"
                    else:
                        st.error(f"❌ Failed to install Rust: {install_result.stderr}")
                        st.stop()
            else:
                st.success("✅ Rust toolchain ready")

        # Pseudo-streaming progress display
        progress_bar = st.progress(0)
        status_text = st.empty()

        stages = [
            ("🔨 Generating initial code", 0.2),
            ("⏳ Waiting for LLM response", 0.4),
            ("✅ Code generated", 0.5),
            ("🧪 Running tests", 0.7),
            ("⏳ Executing test framework", 0.85),
        ]

        try:
            # Start progress animation
            for stage_text, progress in stages:
                status_text.text(stage_text)
                progress_bar.progress(progress)
                time.sleep(0.3)

            # Record start time
            start_time = time.time()

            # Actual API call
            print(f"[Code] Calling /api/code/generate with language={detected_lang}")
            response = requests.post(
                f"{BACKEND_URL}/api/code/generate",
                json={
                    "task": prompt,
                    "language": detected_lang,
                    "max_retries": 3,
                    "include_samples": bool(st.session_state.code_show_samples),
                },
                timeout=120
            )
            print(f"[Code] Response status={response.status_code}, bytes={len(response.content)}")

            # Calculate latency
            latency_ms = (time.time() - start_time) * 1000

            progress_bar.progress(1.0)
            status_text.text("✅ Done!")

            if response.status_code == 200:
                result = response.json()

                # Save request for re-run (save immediately after successful API call)
                st.session_state.code_last_request = {
                    "prompt": prompt,
                    "language": detected_lang,
                    "include_samples": bool(st.session_state.code_show_samples),
                }

                # Display status
                if result.get("test_passed"):
                    st.success("✅ All tests passed!")
                else:
                    st.error("❌ Tests failed after max retries")

                # Display metadata
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Language", result.get('language', 'python'))
                col2.metric("Retries", f"{result.get('total_retries', 0)}/{result.get('max_retries', 3)}")
                col3.metric("Time", f"{result.get('generation_time_ms', 0):.0f}ms")
                col4.metric("Tokens", result.get('tokens_used', 0))

                initial_plan_summary = result.get("initial_plan_summary")
                initial_plan_steps = result.get("initial_plan_steps") or []
                if initial_plan_summary or initial_plan_steps:
                    st.markdown("**🧠 Initial Plan:**")
                    if initial_plan_summary:
                        st.markdown(f"- {initial_plan_summary}")
                    if initial_plan_steps:
                        st.markdown("\n".join([f"  {step}" for step in initial_plan_steps]))

                # Display generated code
                st.markdown("**Generated Code:**")
                st.code(result.get("code", ""), language=result.get('language', 'python'))

                final_test = result.get("final_test_result", {})

                with st.expander("📊 Execution Output", expanded=False):
                    col_a, col_b = st.columns(2)
                    col_a.metric("Exit Code", final_test.get('exit_code', 'N/A'))
                    col_b.metric("Execution Time", f"{final_test.get('execution_time_ms', 0):.0f}ms")

                    stdout = clean_text_lines(final_test.get("stdout", ""))
                    if stdout:
                        st.markdown("**Program Output (print, logs, etc.):**")
                        st.code(stdout, language="text")
                    else:
                        st.info("No program output (no print statements or logs)")

                    stderr = clean_text_lines(final_test.get("stderr", ""))
                    if stderr:
                        st.markdown("**Errors/Warnings:**")
                        st.code(stderr, language="text")

                    samples = final_test.get("samples") or result.get("samples")
                    if samples:
                        st.markdown("**Sample Evaluations:**")
                        for sample in samples:
                            expr = sample.get("expression", "<expression>")
                            actual = sample.get("actual")
                            expected = sample.get("expected")
                            line = f"{expr} → {actual}"
                            if expected is not None:
                                line += f" (expected {expected})"
                            st.markdown(f"- {line}")

                retries = result.get("retry_attempts", [])
                if retries:
                    with st.expander("🔧 Self-Healing History", expanded=False):
                        for retry in retries:
                            st.markdown(f"**Attempt {retry.get('attempt_number')}:**")
                            st.markdown(f"- Fix Applied: {retry.get('fix_applied', 'N/A')}")
                            root_cause = retry.get('error_analysis')
                            if root_cause:
                                st.markdown(f"- Root Cause: {root_cause}")
                            plan_summary = retry.get('plan_summary')
                            if plan_summary:
                                st.markdown(f"- Plan Overview: {plan_summary}")
                            plan_steps = retry.get('plan_steps') or []
                            if plan_steps:
                                st.markdown("- Plan Steps:")
                                st.markdown("\n".join([f"{idx + 1}. {step}" for idx, step in enumerate(plan_steps)]))
                            retry_test = retry.get("test_result") or {}
                            st.markdown(f"- Exit Code: {retry_test.get('exit_code', 'N/A')}")
                            retry_stdout = clean_text_lines(retry_test.get("stdout", ""))
                            if retry_stdout:
                                st.markdown("- Output:")
                                st.code(retry_stdout, language="text")
                            retry_stderr = clean_text_lines(retry_test.get("stderr", ""))
                            if retry_stderr:
                                st.markdown("- Error:")
                                st.code(retry_stderr, language="text")
                            samples_retry = retry_test.get("samples") or []
                            if samples_retry:
                                st.markdown("- Samples:")
                                for sample in samples_retry:
                                    expr = sample.get("expression", "<expression>")
                                    actual = sample.get("actual")
                                    expected = sample.get("expected")
                                    line = f"{expr} → {actual}"
                                    if expected is not None:
                                        line += f" (expected {expected})"
                                    st.markdown(f"  • {line}")

                # LEARNING SYSTEM FEEDBACK
                learning = result.get("learning")
                if learning:
                    st.markdown("---")
                    st.markdown("### 🎓 Code Learning Feedback")

                    reward = learning.get("reward", 0.0)
                    success = learning.get("success", False)
                    strategy = learning.get("strategy", "unknown")
                    breakdown = learning.get("breakdown", {})

                    # Color code reward
                    if reward >= 0.8:
                        reward_color = "🟢"
                        reward_text = "Excellent"
                    elif reward >= 0.6:
                        reward_color = "🟡"
                        reward_text = "Good"
                    else:
                        reward_color = "🔴"
                        reward_text = "Needs Improvement"

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Overall Reward", f"{reward_color} {reward:.3f}", delta=reward_text)
                    with col2:
                        st.metric("Strategy Used", strategy)
                    with col3:
                        status_icon = "✅" if success else "⚠️"
                        st.metric("Learning Success", status_icon)

                    # Reward breakdown with progress bars
                    if breakdown:
                        st.markdown("**📊 Reward Breakdown:**")
                        breakdown_cols = st.columns(4)

                        success_score = breakdown.get("success", 0.0)
                        efficiency_score = breakdown.get("efficiency", 0.0)
                        quality_score = breakdown.get("quality", 0.0)
                        speed_score = breakdown.get("speed", 0.0)

                        with breakdown_cols[0]:
                            st.markdown(f"**✅ Success**: {success_score:.3f}")
                            st.progress(min(success_score, 1.0))
                            st.caption("Tests passed")

                        with breakdown_cols[1]:
                            st.markdown(f"**⚡ Efficiency**: {efficiency_score:.3f}")
                            st.progress(min(efficiency_score, 1.0))
                            st.caption("Fewer retries")

                        with breakdown_cols[2]:
                            st.markdown(f"**💎 Quality**: {quality_score:.3f}")
                            st.progress(min(quality_score, 1.0))
                            st.caption("Code conciseness")

                        with breakdown_cols[3]:
                            st.markdown(f"**🚀 Speed**: {speed_score:.3f}")
                            st.progress(min(speed_score, 1.0))
                            st.caption("Generation time")

                    # Store learning history in session state
                    if "codegen_learning_history" not in st.session_state:
                        st.session_state.codegen_learning_history = {
                            "timestamps": [],
                            "rewards": [],
                            "strategies": [],
                            "success_scores": [],
                            "efficiency_scores": [],
                            "quality_scores": [],
                            "speed_scores": [],
                            "languages": [],
                        }

                    st.session_state.codegen_learning_history["timestamps"].append(datetime.now())
                    st.session_state.codegen_learning_history["rewards"].append(reward)
                    st.session_state.codegen_learning_history["strategies"].append(strategy)
                    st.session_state.codegen_learning_history["success_scores"].append(success_score)
                    st.session_state.codegen_learning_history["efficiency_scores"].append(efficiency_score)
                    st.session_state.codegen_learning_history["quality_scores"].append(quality_score)
                    st.session_state.codegen_learning_history["speed_scores"].append(speed_score)
                    st.session_state.codegen_learning_history["languages"].append(result.get('language', 'python'))

                st.markdown("\n**Continue generating code or type 'q'(quit) to exit Code mode.**")

                # Collect Code metrics to dashboard
                st.session_state.metrics_history["timestamps"].append(datetime.now())
                st.session_state.metrics_history["latencies"].append(latency_ms)
                st.session_state.metrics_history["prompt_tokens"].append(result.get('tokens_used', 0) // 2)  # 估算
                st.session_state.metrics_history["completion_tokens"].append(result.get('tokens_used', 0) // 2)
                st.session_state.metrics_history["costs"].append(float(result.get('cost_usd', 0) or 0.0))
                st.session_state.metrics_history["services"].append("code")

                code_stats = st.session_state.code_stats
                code_stats["total_runs"] += 1
                code_stats["total_latency_ms"] += latency_ms
                tokens_used = result.get('tokens_used', 0)
                cost_usd = float(result.get('cost_usd', 0) or 0.0)
                code_stats["total_tokens"] += tokens_used
                code_stats["total_cost_usd"] += cost_usd
                if result.get('test_passed'):
                    code_stats["passes"] += 1
                    status_label = "success"
                else:
                    code_stats["failures"] += 1
                    status_label = "failed_tests"

                history_entry = {
                    "timestamp": datetime.now(),
                    "status": status_label,
                    "test_passed": bool(result.get('test_passed')),
                    "latency_ms": float(latency_ms),
                    "tokens": int(tokens_used),
                    "cost_usd": cost_usd,
                    "language": result.get('language'),
                    "exit_code": final_test.get('exit_code', 'N/A'),
                }
                if stdout:
                    history_entry["stdout"] = stdout
                if stderr:
                    history_entry["stderr"] = stderr
                code_stats["history"].append(history_entry)
                if len(code_stats["history"]) > 10:
                    code_stats["history"].pop(0)

                summary_sections: List[str] = []
                status_text = "Passed" if result.get('test_passed') else "Failed"
                summary_sections.append(f"**Status:** {status_text}")
                summary_sections.append(
                    f"**Metadata:** Language {result.get('language', 'python')} • Retries {result.get('total_retries', 0)}/{result.get('max_retries', 3)} "
                    f"• Time {result.get('generation_time_ms', 0):.0f} ms • Tokens {result.get('tokens_used', 0)} "
                    f"• Token Cost ${result.get('cost_usd', 0.0):.4f}"
                )

                if initial_plan_summary or initial_plan_steps:
                    plan_text = ""
                    if initial_plan_summary:
                        plan_text += f"Summary: {initial_plan_summary}\n"
                    if initial_plan_steps:
                        plan_text += "\n".join(initial_plan_steps)
                    summary_sections.append(f"**Initial Plan:**\n{plan_text.strip()}")

                generated_code = result.get("code", "")
                if generated_code:
                    summary_sections.append(
                        f"**Generated Code:**\n```{result.get('language', 'python')}\n{generated_code}\n```"
                    )

                if stdout:
                    summary_sections.append(
                        f"**Program Output:**\n```\n{stdout}\n```"
                    )
                else:
                    summary_sections.append("**Program Output:** _no output_")

                if stderr:
                    summary_sections.append(
                        f"**Errors/Warnings:**\n```\n{stderr}\n```"
                    )

                samples = final_test.get("samples") or result.get("samples") or []
                if samples:
                    sample_lines = []
                    for sample in samples:
                        expr = sample.get("expression", "<expression>")
                        actual = sample.get("actual")
                        expected = sample.get("expected")
                        line = f"{expr} → {actual}"
                        if expected is not None:
                            line += f" (expected {expected})"
                        sample_lines.append(line)
                    summary_sections.append(
                        "**Sample Evaluations:**\n" + "\n".join(f"- {line}" for line in sample_lines)
                    )

                if retries:
                    retry_lines: List[str] = []
                    for retry in retries:
                        line_parts = [f"Attempt {retry.get('attempt_number')}: {retry.get('fix_applied', 'N/A')}"]
                        root_cause = retry.get("error_analysis")
                        if root_cause:
                            line_parts.append(f"Root Cause: {root_cause}")
                        plan_summary_retry = retry.get("plan_summary")
                        if plan_summary_retry:
                            line_parts.append(f"Plan: {plan_summary_retry}")
                        plan_steps_retry = retry.get("plan_steps") or []
                        if plan_steps_retry:
                            numbered = " | ".join(
                                [f"{idx + 1}. {step}" for idx, step in enumerate(plan_steps_retry)]
                            )
                            line_parts.append(f"Steps: {numbered}")
                        test_result_retry = retry.get("test_result") or {}
                        exit_code_retry = test_result_retry.get("exit_code", "N/A")
                        line_parts.append(f"Exit Code: {exit_code_retry}")
                        stdout_retry = clean_text_lines(test_result_retry.get("stdout", ""))
                        stderr_retry = clean_text_lines(test_result_retry.get("stderr", ""))
                        if stdout_retry:
                            line_parts.append(f"Output: {stdout_retry}")
                        if stderr_retry:
                            line_parts.append(f"Error: {stderr_retry}")
                        samples_retry = test_result_retry.get("samples") or []
                        if samples_retry:
                            rendered = []
                            for sample in samples_retry:
                                expr = sample.get("expression", "<expression>")
                                actual = sample.get("actual")
                                expected = sample.get("expected")
                                frag = f"{expr} → {actual}"
                                if expected is not None:
                                    frag += f" (expected {expected})"
                                rendered.append(frag)
                            line_parts.append("Samples: " + " | ".join(rendered))
                        retry_lines.append("; ".join(line_parts))
                    if retry_lines:
                        summary_sections.append("**Self-Healing History:**\n" + "\n".join(f"- {line}" for line in retry_lines))

                append_chat_history("assistant", "\n\n".join(summary_sections))

                # Reset auto-run flags
                st.session_state.code_pending_auto = False
                st.session_state.code_force_language = None

            else:
                error_msg = f"❌ Error: {response.status_code}\n{response.text}"
                st.error(error_msg)
                code_stats = st.session_state.code_stats
                code_stats["errors"] += 1
                code_stats["history"].append({
                    "timestamp": datetime.now(),
                    "status": "error",
                    "message": error_msg,
                })
                if len(code_stats["history"]) > 10:
                    code_stats["history"].pop(0)
                append_chat_history("assistant", error_msg)
                st.session_state.code_pending_auto = False
                st.session_state.code_force_language = None

        except Exception as e:
            error_msg = f"❌ Request failed: {e}"
            st.error(error_msg)
            code_stats = st.session_state.code_stats
            code_stats["errors"] += 1
            code_stats["history"].append({
                "timestamp": datetime.now(),
                "status": "exception",
                "message": str(e),
            })
            if len(code_stats["history"]) > 10:
                code_stats["history"].pop(0)
            append_chat_history("assistant", error_msg)
            st.session_state.code_pending_auto = False
            st.session_state.code_force_language = None

# =====================================================================
# Automatic intent recognition (when no mode) - Use LLM to analyze intent
# =====================================================================

elif current_mode == "general" and prompt and prompt != "__MODE_ACTIVATED__":
    st.sidebar.success("✅ ENTERED GENERAL BRANCH!")
    print(f"💬 ENTERING GENERAL AI BRANCH")
    debug_log(f"[general] branch start mode={st.session_state.mode} prompt={prompt!r}")
    with st.chat_message("assistant"):
        with st.spinner("🤔 Understanding your request..."):
            try:
                from openai import OpenAI

                api_key = os.getenv("OPENAI_API_KEY")
                if not api_key:
                    # —— Local fallback: can respond even without OpenAI —— #
                    st.info("💬 General AI Assistant Mode (local fallback)")
                    local_reply = (
                        "Hi I got it without API 👋\n\n"
      
                    )
                    st.markdown(local_reply)
                    append_chat_history("assistant", local_reply)
                else:
                    client_kwargs = {"api_key": api_key}
                    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_BASE_URL")
                    if base_url:
                        client_kwargs["base_url"] = base_url
                    client = OpenAI(**client_kwargs)

                    # Use LLM to analyze intent
                    intent_prompt = f"""Analyze the user's request and classify it into one of these categories:

User request: "{prompt}"

Categories:
- "rag": Questions about documents, books, asking who/what someone or something is, requesting explanations about topics
- "trip": Trip planning, travel arrangements, flights, hotels, destinations, vacation planning
- "code": Code generation, writing functions, implementing algorithms, programming tasks
- "general": General questions, greetings, casual conversation, anything else not matching above

Respond with ONLY ONE WORD: rag, trip, code, or general"""

                    intent_messages = sanitize_messages([
                        {"role": "user", "content": intent_prompt}
                    ])

                    intent_response = client.chat.completions.create(
                        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                        messages=intent_messages,
                        temperature=0,
                        max_tokens=10
                    )

                    intent = intent_response.choices[0].message.content.strip().lower()
                    print(f"[Intent] classified intent={intent} for prompt={prompt!r}")

                    # Route based on intent
                    if intent == "rag":
                        switch_mode("rag", always_show_message=True)
                        st.session_state.pending_prompt = prompt
                        st.rerun()

                    elif intent == "trip":
                        switch_mode("trip", always_show_message=True)
                        st.session_state.pending_prompt = prompt
                        st.rerun()

                    elif intent == "code":
                        switch_mode("code", always_show_message=True)
                        st.session_state.pending_prompt = prompt
                        st.rerun()

                    else:
                        # General Assistant mode - Answer directly with LLM
                        st.info("💬 General AI Assistant Mode")

                        # Build conversation history (last 5 messages)
                        # Clean messages first - remove any with null/empty content
                        recent_messages = [
                            msg for msg in (st.session_state.messages[-10:] if len(st.session_state.messages) > 0 else [])
                            if msg.get("content") and str(msg.get("content")).strip()  # Skip null, empty, or whitespace-only
                        ]
                        conversation_history = [
                            {"role": msg["role"], "content": str(msg["content"])[:200]}  # Limit length, ensure characters串
                            for msg in recent_messages
                        ]

                        # Add system prompt
                        system_msg = {
                            "role": "system",
                            "content": """You are a helpful AI assistant. You provide three specialized services:
- 📚 RAG Q&A: Answer questions about documents in the knowledge base
- ✈️ Trip Planning: Help plan trips with flights, hotels, and itineraries
- 💻 Code Generation: Generate code with automated tests

For general questions not related to these services, provide helpful, concise answers.
If the user asks about trip planning, documents, or code, suggest they use the specialized services."""
                        }

                        messages = [system_msg] + conversation_history + [{"role": "user", "content": prompt}]
                        sanitized_messages = sanitize_messages(messages)

                        model_name = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo-0125")
                        request_start = time.time()
                        assistant_response = client.chat.completions.create(
                            model=model_name,
                            messages=sanitized_messages,
                            temperature=0.7,
                            max_tokens=500
                        )
                        latency_ms = (time.time() - request_start) * 1000

                        answer = assistant_response.choices[0].message.content

                        usage = getattr(assistant_response, "usage", None)
                        prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
                        completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
                        cost_usd = estimate_completion_cost(model_name, prompt_tokens, completion_tokens)

                        # Display response
                        st.markdown(answer)

                        # Display service hint
                        st.markdown("\n---")
                        st.markdown("**💡 Tip:** For specialized tasks, try:")
                        col1, col2, col3 = st.columns(3)
                        col1.markdown("📚 RAG Q&A")
                        col2.markdown("✈️ Trip Planning")
                        col3.markdown("💻 Code Gen")

                        metrics_cols = st.columns(4)
                        metrics_cols[0].metric("Latency", f"{latency_ms:.0f} ms")
                        metrics_cols[1].metric("Prompt Tokens", prompt_tokens)
                        metrics_cols[2].metric("Completion Tokens", completion_tokens)
                        metrics_cols[3].metric("Token Cost", f"${cost_usd:.4f}")

                        st.session_state.metrics_history["timestamps"].append(datetime.now())
                        st.session_state.metrics_history["latencies"].append(latency_ms)
                        st.session_state.metrics_history["prompt_tokens"].append(prompt_tokens)
                        st.session_state.metrics_history["completion_tokens"].append(completion_tokens)
                        st.session_state.metrics_history["costs"].append(cost_usd)
                        st.session_state.metrics_history["services"].append("chat")

                        # Save to history
                        append_chat_history(
                            "assistant",
                            answer + f"\n\n---\nLatency: {latency_ms:.0f} ms | Tokens: {prompt_tokens + completion_tokens} | Token Cost: ${cost_usd:.4f}"
                        )

            except Exception as e:
                error_msg = f"❌ Error: {e}"
                st.error(error_msg)
                append_chat_history("assistant", error_msg)

# Catch-all: if no branch matched
else:
    if prompt:
        st.sidebar.error(f"⚠️ NO BRANCH MATCHED! mode={current_mode!r}, prompt={prompt!r}")


# =====================================================================
# AI Governance Info Modal
# =====================================================================
if st.session_state.get("show_governance_info", False):
    with st.expander("🛡️ AI Governance Framework", expanded=True):
        show_governance_info()

        if st.button("Close", key="close_governance_info"):
            st.session_state.show_governance_info = False
            st.rerun()

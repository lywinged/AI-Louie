"""
Quick smoke test to verify Smart RAG routes relationship/role queries to Graph RAG.

Usage:
    BACKEND_URL=http://localhost:8888 python scripts/smart_rag_graph_smoke.py
"""
import os
import json
import requests


BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8888")
TIMEOUT = float(os.getenv("TIMEOUT_SEC", "60"))

QUERIES = [
    "List the roles and relationships between the main characters in 'Pride and Prejudice'.",
    "Describe the relationships among the characters in 'Sir Roberts Fortune a novel'.",
    "Map the connections between protagonists and supporting characters across the story.",
]


def run_query(q: str):
    resp = requests.post(
        f"{BACKEND_URL}/api/rag/ask-smart",
        json={"question": q, "top_k": 5, "include_timings": True},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    print(f"Backend: {BACKEND_URL}")
    for q in QUERIES:
        print("\n=== Query ===")
        print(q)
        try:
            result = run_query(q)
        except Exception as exc:
            print(f"❌ Request failed: {exc}")
            continue

        selected = result.get("selected_strategy")
        reason = result.get("strategy_reason")
        cache_hit = result.get("cache_hit")
        token_usage = result.get("token_usage")
        mode = result.get("_mode") or result.get("mode")

        print(f"Selected strategy: {selected} | mode: {mode}")
        print(f"Reason: {reason}")
        print(f"Cache hit: {cache_hit}")
        print(f"Token usage: {token_usage or 'N/A (cache hit)'}")

        timings = result.get("timings", {}) or {}
        if "graph_context" in timings:
            gc = timings["graph_context"] or {}
            print(f"Graph context: entities={gc.get('num_entities')} relationships={gc.get('num_relationships')}")
        else:
            print("Graph context not present.")

        print("Raw JSON:")
        print(json.dumps({k: v for k, v in result.items() if k not in ["citations", "iteration_details"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

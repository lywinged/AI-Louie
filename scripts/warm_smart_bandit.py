#!/usr/bin/env python3
"""
Warm up Smart RAG Thompson Sampling bandit with diverse queries.

给 Smart RAG bandit 提供足够的学习机会，让它快速学习:
- 哪些查询类型适合 Hybrid RAG (author queries, factual)
- 哪些查询类型适合 Graph RAG (relationships)
- 哪些查询类型适合 Self-RAG (complex analytical)
- 哪些查询类型适合 Table RAG (structured data)

Usage:
  python scripts/warm_smart_bandit.py --backend http://localhost:8888 --rounds 2
"""

import argparse
import json
import time
import requests
from typing import Dict, List
from collections import defaultdict

# Author/factual queries (expected: Hybrid RAG)
AUTHOR_FACTUAL_QUERIES = [
    "Who wrote 'DADDY TAKE ME SKATING'?",
    "Who is the author of Pride and Prejudice?",
    "When was the book 'Dorothy South' published?",
    "What year was 'The Great Gatsby' written?",
    "Who created the character Elizabeth Bennet?",
]

# Relationship queries (expected: Graph RAG)
RELATIONSHIP_QUERIES = [
    "'Sir roberts fortune a novel', show me the roles relationship",
    "List relationships between main characters in old-rose-and-silver",
    "Map the connections between characters and their roles in the story",
    "What is the relationship between Elizabeth and Darcy?",
    "How are the main characters connected in the novel?",
]

# Complex analytical queries (expected: Self-RAG/Iterative)
COMPLEX_ANALYTICAL_QUERIES = [
    "Compare the themes of two Victorian novels and summarize differences.",
    "Analyze how the protagonist's relationship evolves over the chapters.",
    "What are the main themes in Pride and Prejudice?",
    "How does the author explore class distinctions?",
    "Analyze the character development of Elizabeth Bennet",
]

# Table/structured queries (expected: Table RAG)
TABLE_QUERIES = [
    "List all the main characters in the novel",
    "Show me all the chapter titles",
    "What are the key events in chronological order?",
    "List all the locations mentioned in the book",
    "What are all the marriages that occur in the story?",
]

# General queries (baseline)
GENERAL_QUERIES = [
    "Tell me about Pride and Prejudice",
    "Summarize the main plot",
    "What happens in the American frontier story?",
    "Give me an overview of the Victorian novel",
]

QUERY_SETS = {
    "author_factual": AUTHOR_FACTUAL_QUERIES,
    "relationship": RELATIONSHIP_QUERIES,
    "complex_analytical": COMPLEX_ANALYTICAL_QUERIES,
    "table": TABLE_QUERIES,
    "general": GENERAL_QUERIES,
}


def run_queries(base_url: str, query_set_name: str, queries: List[str], stats: Dict):
    """Run a set of queries and collect statistics"""

    print(f"\n{'='*80}")
    print(f"Testing: {query_set_name.upper()} ({len(queries)} queries)")
    print('='*80)

    for idx, q in enumerate(queries, 1):
        payload = {"question": q, "top_k": 3, "include_timings": True}
        t0 = time.time()

        try:
            resp = requests.post(f"{base_url}/api/rag/ask-smart", json=payload, timeout=60)
            dt = (time.time() - t0) * 1000

            if resp.status_code != 200:
                print(f"  [{idx}/{len(queries)}] ❌ HTTP {resp.status_code} | {q[:50]}")
                stats["errors"] += 1
                continue

            data = resp.json()
            strategy = data.get("selected_strategy", data.get("strategy_used", "unknown"))
            latency = data.get("retrieval_time_ms", data.get("total_time_ms", dt))
            chunks = data.get("num_chunks_retrieved", 0)
            confidence = data.get("confidence", 0.0)

            print(f"  [{idx}/{len(queries)}] {q[:55]}")
            print(f"         → Strategy: {strategy} | Latency: {latency:.0f}ms | Chunks: {chunks} | Conf: {confidence:.2f}")

            # Update stats
            stats["total_queries"] += 1
            stats["strategies"][strategy] += 1
            stats["query_type_to_strategy"][query_set_name].append(strategy)
            stats["latencies"].append(latency)
            stats["chunks"].append(chunks)

        except Exception as e:
            print(f"  [{idx}/{len(queries)}] ❌ Error: {e}")
            stats["errors"] += 1

        time.sleep(0.5)  # Avoid overload


def print_summary(stats: Dict):
    """Print comprehensive statistics"""

    print("\n\n" + "="*80)
    print("BANDIT WARM-UP COMPLETE - SUMMARY")
    print("="*80)

    total = stats["total_queries"]
    print(f"\n📊 Total queries executed: {total}")
    print(f"❌ Errors: {stats['errors']}")

    # Strategy distribution
    print("\n📈 Strategy Selection Distribution:")
    print("-"*80)
    for strategy, count in sorted(stats["strategies"].items(), key=lambda x: x[1], reverse=True):
        pct = count / total * 100 if total > 0 else 0
        print(f"  {strategy:15s}: {count:3d} ({pct:5.1f}%)")

    # Performance metrics
    if stats["latencies"]:
        avg_latency = sum(stats["latencies"]) / len(stats["latencies"])
        p50_latency = sorted(stats["latencies"])[len(stats["latencies"]) // 2]
        p95_latency = sorted(stats["latencies"])[int(len(stats["latencies"]) * 0.95)]

        print(f"\n⏱️  Latency Metrics:")
        print(f"  Average: {avg_latency:.0f}ms")
        print(f"  P50:     {p50_latency:.0f}ms")
        print(f"  P95:     {p95_latency:.0f}ms")

    if stats["chunks"]:
        avg_chunks = sum(stats["chunks"]) / len(stats["chunks"])
        print(f"\n📚 Average chunks retrieved: {avg_chunks:.1f}")

    # Query type → Strategy mapping
    print("\n🎯 Query Type → Strategy Mapping:")
    print("-"*80)

    for query_type, strategies in stats["query_type_to_strategy"].items():
        if not strategies:
            continue

        strategy_counts = defaultdict(int)
        for s in strategies:
            strategy_counts[s] += 1

        print(f"\n  {query_type.upper()}:")
        for strategy, count in sorted(strategy_counts.items(), key=lambda x: x[1], reverse=True):
            pct = count / len(strategies) * 100
            print(f"    {strategy:15s}: {count}/{len(strategies)} ({pct:5.1f}%)")

    print("\n\n✅ Bandit Learning Complete!")
    print("\nNext steps:")
    print("1. Check backend logs for bandit updates:")
    print("   docker logs ai-louie-backend-1 2>&1 | grep 'Smart RAG bandit update' | tail -20")
    print("\n2. Bandit should now have learned optimal strategies for each query type")
    print("="*80)


def main():
    parser = argparse.ArgumentParser(description="Warm up Smart RAG bandit with diverse queries")
    parser.add_argument("--backend", default="http://localhost:8888", help="Backend base URL")
    parser.add_argument("--rounds", type=int, default=1, help="Number of rounds to run all queries")
    args = parser.parse_args()

    print("="*80)
    print("Smart RAG Thompson Sampling Bandit Warm-Up")
    print("="*80)

    total_queries = sum(len(queries) for queries in QUERY_SETS.values()) * args.rounds
    print(f"\nTotal queries to execute: {total_queries} ({args.rounds} rounds)")
    print(f"Backend: {args.backend}")

    # Initialize stats
    stats = {
        "total_queries": 0,
        "errors": 0,
        "strategies": defaultdict(int),
        "query_type_to_strategy": defaultdict(list),
        "latencies": [],
        "chunks": [],
    }

    # Run queries
    for round_num in range(1, args.rounds + 1):
        if args.rounds > 1:
            print(f"\n\n{'#'*80}")
            print(f"ROUND {round_num}/{args.rounds}")
            print('#'*80)

        for query_set_name, queries in QUERY_SETS.items():
            run_queries(args.backend, query_set_name, queries, stats)

    # Print summary
    print_summary(stats)


if __name__ == "__main__":
    main()

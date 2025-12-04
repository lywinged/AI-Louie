#!/usr/bin/env python3
"""
Test Smart RAG automatic selection with graph RAG
"""

import requests
import time

BACKEND_URL = "http://localhost:8888"

def test_smart_rag_selection():
    """Test that smart RAG can now select graph RAG automatically"""

    test_queries = [
        # Should trigger graph RAG (relationship queries)
        ("Analyze how the protagonist's relationship with other characters evolves.", "graph"),

        # Should use hybrid/iterative
        ("What is prop building?", "hybrid/iterative"),

        # Should use table RAG
        ("Show me the data table for character ages.", "table"),

        # General query
        ("Who wrote DADDY TAKE ME SKATING?", "any"),
    ]

    print("\n🧪 Testing Smart RAG Selection Mechanism")
    print("=" * 80)

    for i, (query, expected_strategy) in enumerate(test_queries, 1):
        print(f"\n{i}. Query: {query}")
        print(f"   Expected: {expected_strategy}")

        try:
            start = time.time()
            response = requests.post(
                f"{BACKEND_URL}/api/rag/ask-smart",
                json={"question": query, "top_k": 5},
                timeout=60
            )
            elapsed = (time.time() - start) * 1000

            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ Status: {response.status_code}")
                print(f"   Time: {elapsed:.0f}ms")
                print(f"   Citations: {len(data.get('citations', []))}")
                print(f"   Answer preview: {data.get('answer', '')[:100]}...")
            else:
                print(f"   ❌ Error: {response.status_code}")
                print(f"   Response: {response.text[:200]}")

        except Exception as e:
            print(f"   ❌ Exception: {e}")

        time.sleep(1)  # Rate limiting

    print("\n" + "=" * 80)
    print("\n📊 Checking Smart Bandit Status...")

    try:
        response = requests.get(f"{BACKEND_URL}/api/rag/smart-status", timeout=10)
        if response.status_code == 200:
            status = response.json()
            print(f"\n🎯 Bandit State:")
            for arm, params in status.get('bandit_state', {}).items():
                alpha = params.get('alpha', 0)
                beta = params.get('beta', 0)
                trials = alpha + beta - 2
                if trials > 0:
                    success_rate = alpha / (alpha + beta)
                    print(f"   {arm:12s}: α={alpha:.2f}, β={beta:.2f}, trials={trials:.0f}, success={success_rate:.2%}")
                else:
                    print(f"   {arm:12s}: α={alpha:.2f}, β={beta:.2f}, trials=0 (not explored yet)")

    except Exception as e:
        print(f"   ❌ Failed to get bandit status: {e}")

    print("\n✅ Test completed!")

if __name__ == "__main__":
    test_smart_rag_selection()

#!/usr/bin/env python3
"""
Test script for user feedback mechanism.

Demonstrates:
1. Submit query and get query_id
2. View automated bandit update
3. Submit user feedback (positive/negative)
4. View feedback-adjusted bandit update
5. Compare bandit weights before/after feedback
"""

import argparse
import json
import requests
import subprocess
import time
from typing import Dict, Any


BASE_URL = "http://localhost:8888"


def view_bandit_state() -> Dict[str, Dict[str, float]]:
    """View current bandit state using manage_bandit_state.py"""
    result = subprocess.run(
        ["python", "scripts/manage_bandit_state.py", "view"],
        capture_output=True,
        text=True
    )
    print(result.stdout)
    return {}


def submit_query(question: str) -> Dict[str, Any]:
    """Submit a RAG query and return response with query_id"""
    print("=" * 80)
    print(f"📝 Submitting query: {question}")
    print("=" * 80)

    payload = {
        "question": question,
        "top_k": 3,
        "include_timings": True
    }

    response = requests.post(f"{BASE_URL}/api/rag/ask-smart", json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()

    print(f"\n✅ Query successful!")
    print(f"Query ID: {data.get('query_id')}")
    print(f"Strategy: {data.get('selected_strategy')}")
    print(f"Confidence: {data.get('confidence', 0):.3f}")
    print(f"Latency: {data.get('total_time_ms', 0):.1f} ms")
    print(f"Answer preview: {data.get('answer', '')[:150]}...")
    print()

    return data


def submit_feedback(query_id: str, rating: float, comment: str = "") -> Dict[str, Any]:
    """Submit user feedback for a query"""
    print("=" * 80)
    print(f"💬 Submitting feedback: rating={rating}")
    print("=" * 80)

    payload = {
        "query_id": query_id,
        "rating": rating,
    }

    if comment:
        payload["comment"] = comment

    response = requests.post(f"{BASE_URL}/api/rag/feedback", json=payload, timeout=10)
    response.raise_for_status()
    data = response.json()

    print(f"\n✅ Feedback submitted!")
    print(f"Strategy updated: {data.get('strategy_updated')}")
    print(f"Bandit updated: {data.get('bandit_updated')}")
    print(f"Message: {data.get('message')}")
    print()

    return data


def test_positive_feedback():
    """Test positive feedback (rating=1.0)"""
    print("\n" + "=" * 80)
    print("Test 1: Positive Feedback (rating=1.0)")
    print("=" * 80)

    # 1. View initial state
    print("\n📊 Initial bandit state:")
    view_bandit_state()

    # 2. Submit query
    query_response = submit_query("Who is the author of Pride and Prejudice?")
    query_id = query_response.get("query_id")
    strategy = query_response.get("selected_strategy")

    # Wait a moment for bandit update
    time.sleep(1)

    # 3. Submit positive feedback
    submit_feedback(
        query_id=query_id,
        rating=1.0,
        comment="Perfect answer, correct strategy choice!"
    )

    # 4. View updated state
    print(f"\n📊 Bandit state after positive feedback for {strategy}:")
    view_bandit_state()


def test_negative_feedback():
    """Test negative feedback (rating=0.0)"""
    print("\n" + "=" * 80)
    print("Test 2: Negative Feedback (rating=0.0)")
    print("=" * 80)

    # 1. View initial state
    print("\n📊 Initial bandit state:")
    view_bandit_state()

    # 2. Submit query
    query_response = submit_query("Show me the relationship between characters in old-rose-and-silver")
    query_id = query_response.get("query_id")
    strategy = query_response.get("selected_strategy")

    # Wait a moment for bandit update
    time.sleep(1)

    # 3. Submit negative feedback
    submit_feedback(
        query_id=query_id,
        rating=0.0,
        comment="Answer is incorrect, strategy took too long"
    )

    # 4. View updated state
    print(f"\n📊 Bandit state after negative feedback for {strategy}:")
    view_bandit_state()


def test_neutral_feedback():
    """Test neutral feedback (rating=0.5)"""
    print("\n" + "=" * 80)
    print("Test 3: Neutral Feedback (rating=0.5)")
    print("=" * 80)

    # 1. View initial state
    print("\n📊 Initial bandit state:")
    view_bandit_state()

    # 2. Submit query
    query_response = submit_query("What are the main themes in American frontier literature?")
    query_id = query_response.get("query_id")
    strategy = query_response.get("selected_strategy")

    # Wait a moment for bandit update
    time.sleep(1)

    # 3. Submit neutral feedback
    submit_feedback(
        query_id=query_id,
        rating=0.5,
        comment="Answer is acceptable but could be better"
    )

    # 4. View updated state
    print(f"\n📊 Bandit state after neutral feedback for {strategy}:")
    view_bandit_state()


def test_invalid_query_id():
    """Test submitting feedback with invalid query_id"""
    print("\n" + "=" * 80)
    print("Test 4: Invalid Query ID (should return 404)")
    print("=" * 80)

    try:
        submit_feedback(
            query_id="invalid-uuid-12345",
            rating=1.0,
            comment="This should fail"
        )
    except requests.exceptions.HTTPError as e:
        print(f"\n✅ Expected error received:")
        print(f"Status: {e.response.status_code}")
        print(f"Detail: {e.response.json().get('detail')}")
        print()


def compare_scenarios():
    """Compare automated reward vs user-corrected reward"""
    print("\n" + "=" * 80)
    print("Test 5: Automated vs User-Corrected Reward Comparison")
    print("=" * 80)

    # Scenario A: High automated reward, low user rating
    print("\n🔹 Scenario A: High automated reward (0.9) + Low user rating (0.0)")
    print("Expected final reward: 0.7 × 0.0 + 0.3 × 0.9 = 0.27")

    # Scenario B: Low automated reward, high user rating
    print("\n🔹 Scenario B: Low automated reward (0.2) + High user rating (1.0)")
    print("Expected final reward: 0.7 × 1.0 + 0.3 × 0.2 = 0.76")

    print("\n💡 User feedback dominates (70% weight), correcting automated misjudgments")


def main():
    parser = argparse.ArgumentParser(description="Test user feedback mechanism")
    parser.add_argument("--test", choices=["positive", "negative", "neutral", "invalid", "compare", "all"],
                        default="all", help="Test scenario to run")

    args = parser.parse_args()

    print("\n" + "=" * 80)
    print("Smart RAG User Feedback Mechanism - Test Suite")
    print("=" * 80)

    try:
        if args.test == "positive" or args.test == "all":
            test_positive_feedback()

        if args.test == "negative" or args.test == "all":
            test_negative_feedback()

        if args.test == "neutral" or args.test == "all":
            test_neutral_feedback()

        if args.test == "invalid" or args.test == "all":
            test_invalid_query_id()

        if args.test == "compare" or args.test == "all":
            compare_scenarios()

        print("\n" + "=" * 80)
        print("✅ All tests completed!")
        print("=" * 80)

    except requests.exceptions.ConnectionError:
        print("\n❌ Error: Cannot connect to backend API")
        print("Make sure the backend is running: ./start.sh")
    except Exception as e:
        print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Test script for file-level BGE fallback retrieval.

Tests the strategy:
1. MiniLM retrieves (fast keyword search / file finder)
2. If low confidence, trigger BGE file-level fallback
3. Re-embed entire file with BGE and find best chunks
"""
import asyncio
import sys
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from backend.services.file_level_fallback import get_file_level_retriever


async def test_file_level_fallback():
    """Test file-level BGE fallback with sample queries."""

    print("=" * 80)
    print("File-Level BGE Fallback Retrieval Test")
    print("=" * 80)
    print()

    # Initialize retriever
    print("Initializing file-level fallback retriever...")
    retriever = get_file_level_retriever(confidence_threshold=0.65)
    print(f"✓ Retriever initialized (threshold: {retriever.confidence_threshold})")
    print()

    # Test queries
    test_queries = [
        {
            "query": "Who wrote 'DADDY TAKE ME SKATING'?",
            "description": "Simple factual query - expect HIGH confidence (no fallback)",
            "expect_fallback": False,
        },
        {
            "query": "What is the meaning of quantum entanglement?",
            "description": "Complex/out-of-domain query - expect LOW confidence (trigger fallback)",
            "expect_fallback": True,
        },
        {
            "query": "Tell me about American frontier history",
            "description": "Broad topical query - expect MODERATE confidence (may trigger fallback)",
            "expect_fallback": "maybe",
        },
    ]

    for idx, test_case in enumerate(test_queries, start=1):
        query = test_case["query"]
        description = test_case["description"]
        expect_fallback = test_case["expect_fallback"]

        print(f"Test {idx}/{ len(test_queries)}")
        print(f"Query: {query}")
        print(f"Description: {description}")
        print("-" * 80)

        try:
            # Retrieve
            results = await retriever.retrieve(query=query, top_k=3)

            if not results:
                print("❌ No results returned")
                print()
                continue

            # Check if fallback was triggered
            fallback_triggered = results[0].fallback_triggered

            print(f"Fallback triggered: {'YES ✓' if fallback_triggered else 'NO'}")

            if fallback_triggered:
                print(f"Fallback latency: {results[0].fallback_latency_ms:.1f}ms")

            print(f"Top-1 score: {results[0].score:.4f}")
            print(f"Top-1 file: {results[0].file_path}")
            print()

            print("Top 3 results:")
            for rank, result in enumerate(results[:3], start=1):
                print(f"  {rank}. Score: {result.score:.4f}")
                print(f"     File: {result.file_path}")
                print(f"     Text: {result.chunk_text[:100]}...")
                print()

            # Validate expectation
            if expect_fallback is True and not fallback_triggered:
                print("⚠️  Expected fallback but didn't trigger")
            elif expect_fallback is False and fallback_triggered:
                print("⚠️  Didn't expect fallback but triggered")
            else:
                print("✓ Result matches expectation")

        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

        print()
        print("=" * 80)
        print()

    print("Test completed!")


if __name__ == "__main__":
    asyncio.run(test_file_level_fallback())

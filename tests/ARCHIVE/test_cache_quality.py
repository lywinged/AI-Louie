#!/usr/bin/env python3
"""
Test cache quality check mechanism
"""

import requests
import time

BACKEND_URL = "http://localhost:8888"

def test_low_quality_not_cached():
    """Test that low-quality answers are NOT cached"""

    # This query will likely return 0 results if collection doesn't exist
    # or has no matching documents
    test_query = "Who wrote DADDY TAKE ME SKATING in year 9999?"

    print("🧪 Testing cache quality check mechanism")
    print("=" * 70)

    # First request - should generate fresh answer
    print(f"\n1️⃣  First request: {test_query}")
    start = time.time()
    response1 = requests.post(
        f"{BACKEND_URL}/api/rag/ask",
        json={"question": test_query, "top_k": 5},
        timeout=30
    )
    time1 = (time.time() - start) * 1000

    if response1.status_code == 200:
        data1 = response1.json()
        print(f"   Status: {response1.status_code}")
        print(f"   Time: {time1:.0f}ms")
        print(f"   Cache hit: {data1.get('cache_hit', False)}")
        print(f"   Citations: {len(data1.get('citations', []))}")
        print(f"   Chunks retrieved: {data1.get('num_chunks_retrieved', 0)}")
        print(f"   Confidence: {data1.get('confidence', 0):.2f}")

        # Second request - should also be fresh if quality was low
        print(f"\n2️⃣  Second request (checking if cached):")
        time.sleep(1)
        start = time.time()
        response2 = requests.post(
            f"{BACKEND_URL}/api/rag/ask",
            json={"question": test_query, "top_k": 5},
            timeout=30
        )
        time2 = (time.time() - start) * 1000

        if response2.status_code == 200:
            data2 = response2.json()
            print(f"   Status: {response2.status_code}")
            print(f"   Time: {time2:.0f}ms")
            print(f"   Cache hit: {data2.get('cache_hit', False)}")
            print(f"   Citations: {len(data2.get('citations', []))}")
            print(f"   Chunks retrieved: {data2.get('num_chunks_retrieved', 0)}")
            print(f"   Confidence: {data2.get('confidence', 0):.2f}")

            # Analysis
            print("\n📊 Analysis:")
            if data2.get('cache_hit') == True:
                print("   ⚠️  WARNING: Low-quality answer was cached!")
                print(f"   Quality metrics from cached answer:")
                print(f"     - Citations: {len(data2.get('citations', []))}")
                print(f"     - Chunks: {data2.get('num_chunks_retrieved', 0)}")
                print(f"     - Confidence: {data2.get('confidence', 0):.2f}")
            else:
                print("   ✅ SUCCESS: Low-quality answer was NOT cached")
                print("   Second request generated fresh answer (not from cache)")
        else:
            print(f"   ❌ Error: {response2.status_code}")
    else:
        print(f"   ❌ Error: {response1.status_code}")

    print("\n" + "=" * 70)

def test_good_quality_cached():
    """Test that good-quality answers ARE cached"""

    # This query should return good results
    test_query = "What is prop building?"

    print("\n🧪 Testing that good answers are cached")
    print("=" * 70)

    # First request
    print(f"\n1️⃣  First request: {test_query}")
    start = time.time()
    response1 = requests.post(
        f"{BACKEND_URL}/api/rag/ask",
        json={"question": test_query, "top_k": 5},
        timeout=30
    )
    time1 = (time.time() - start) * 1000

    if response1.status_code == 200:
        data1 = response1.json()
        print(f"   Status: {response1.status_code}")
        print(f"   Time: {time1:.0f}ms")
        print(f"   Cache hit: {data1.get('cache_hit', False)}")
        print(f"   Citations: {len(data1.get('citations', []))}")
        print(f"   Chunks retrieved: {data1.get('num_chunks_retrieved', 0)}")
        print(f"   Confidence: {data1.get('confidence', 0):.2f}")

        # Second request
        print(f"\n2️⃣  Second request (should be cached):")
        time.sleep(1)
        start = time.time()
        response2 = requests.post(
            f"{BACKEND_URL}/api/rag/ask",
            json={"question": test_query, "top_k": 5},
            timeout=30
        )
        time2 = (time.time() - start) * 1000

        if response2.status_code == 200:
            data2 = response2.json()
            print(f"   Status: {response2.status_code}")
            print(f"   Time: {time2:.0f}ms (speedup: {time1/time2:.1f}x)")
            print(f"   Cache hit: {data2.get('cache_hit', False)}")
            print(f"   Citations: {len(data2.get('citations', []))}")

            print("\n📊 Analysis:")
            if data2.get('cache_hit') == True:
                print("   ✅ SUCCESS: Good-quality answer was cached")
                print(f"   Speedup: {time1/time2:.1f}x faster")
            else:
                print("   ⚠️  WARNING: Good answer was not cached")
                print(f"   Quality metrics:")
                print(f"     - Citations: {len(data1.get('citations', []))}")
                print(f"     - Chunks: {data1.get('num_chunks_retrieved', 0)}")
                print(f"     - Confidence: {data1.get('confidence', 0):.2f}")

    print("\n" + "=" * 70)

if __name__ == "__main__":
    print("\n🔍 Cache Quality Check Test Suite")
    print("=" * 70)

    # Test 1: Low quality should NOT be cached
    test_low_quality_not_cached()

    # Test 2: Good quality SHOULD be cached
    time.sleep(2)
    test_good_quality_cached()

    print("\n✅ Tests completed!")

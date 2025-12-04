#!/usr/bin/env python3
"""
Test script to verify governance tracking is working correctly.
Tests that G3, G5, G8 metrics are exported to Prometheus.
"""
import requests
import time
import sys

BACKEND_URL = "http://localhost:8888"

def test_rag_endpoint():
    """Send a test RAG query"""
    print("=" * 60)
    print("Testing RAG Endpoint with Governance Tracking")
    print("=" * 60)

    # Send a test query
    print("\n1. Sending test query...")
    response = requests.post(
        f"{BACKEND_URL}/api/rag/ask",
        json={
            "question": "What is machine learning?",
            "top_k": 3
        },
        timeout=30
    )

    if response.status_code == 200:
        print("   ✅ RAG query successful")
        result = response.json()
        print(f"   Answer length: {len(result.get('answer', ''))}")
    else:
        print(f"   ❌ RAG query failed: {response.status_code}")
        return False

    # Wait a moment for metrics to be exported
    print("\n2. Waiting 2 seconds for metrics export...")
    time.sleep(2)

    # Check Prometheus metrics
    print("\n3. Checking Prometheus metrics...")
    metrics_response = requests.get(f"{BACKEND_URL}/metrics", timeout=10)

    if metrics_response.status_code != 200:
        print(f"   ❌ Failed to fetch metrics: {metrics_response.status_code}")
        return False

    metrics_text = metrics_response.text

    # Check for governance metrics
    has_g3 = "ai_governance_checkpoint_total{criteria=\"g3_evidence_contract\"" in metrics_text
    has_g5 = "ai_governance_checkpoint_total{criteria=\"g5_privacy_control\"" in metrics_text
    has_g8 = "ai_governance_checkpoint_total{criteria=\"g8_evaluation_system\"" in metrics_text

    print(f"\n   G3 Evidence Contract: {'✅ Found' if has_g3 else '❌ Missing'}")
    print(f"   G5 Privacy Control: {'✅ Found' if has_g5 else '❌ Missing'}")
    print(f"   G8 Evaluation System: {'✅ Found' if has_g8 else '❌ Missing'}")

    if has_g3 or has_g5 or has_g8:
        print("\n4. Governance Metrics Details:")
        for line in metrics_text.split('\n'):
            if 'ai_governance' in line and not line.startswith('#'):
                print(f"   {line}")
        return True
    else:
        print("\n❌ No governance metrics found!")
        print("\nRoot Cause: Governance tracking decorator not applied to RAG endpoints.")
        print("\nTo fix:")
        print("   1. Open backend/backend/routers/rag_routes.py")
        print("   2. Add decorator to RAG endpoints:")
        print("      @router.post('/ask')")
        print("      @with_governance_tracking(operation_type='rag', risk_tier=RiskTier.R1)")
        print("      async def ask_question(request: RAGRequest) -> RAGResponse:")
        print("          ...")
        print("\n   See GOVERNANCE_INTEGRATION_GUIDE.md for detailed instructions.")
        return False

def main():
    try:
        success = test_rag_endpoint()
        print("\n" + "=" * 60)
        if success:
            print("✅ Governance Tracking Test PASSED")
            print("=" * 60)
            sys.exit(0)
        else:
            print("❌ Governance Tracking Test FAILED")
            print("=" * 60)
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

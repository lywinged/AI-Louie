#!/usr/bin/env python3
"""
Test script to verify that code execution print outputs are displayed in UI
"""

import requests
import json

BACKEND_URL = "http://localhost:8888"

def test_code_generation_with_print():
    """Test code generation with print output"""

    # Test case: Generate code that should print output
    payload = {
        "task": "Write a function that takes a list of numbers and returns their sum. Include a test.",
        "language": "python",
        "max_retries": 3,
        "include_samples": True  # Enable print injection
    }

    print("📤 Sending request to /api/code/generate...")
    print(f"Payload: {json.dumps(payload, indent=2)}")

    response = requests.post(
        f"{BACKEND_URL}/api/code/generate",
        json=payload,
        timeout=120
    )

    print(f"\n✅ Response status: {response.status_code}")

    if response.status_code == 200:
        result = response.json()

        print("\n📝 Generated Code:")
        print("=" * 60)
        print(result.get("code", ""))
        print("=" * 60)

        print("\n📊 Test Result:")
        final_test = result.get("final_test_result", {})

        print(f"  • Test Passed: {final_test.get('passed', False)}")
        print(f"  • Exit Code: {final_test.get('exit_code', 'N/A')}")
        print(f"  • Execution Time: {final_test.get('execution_time_ms', 0):.0f}ms")

        stdout = final_test.get("stdout", "")
        stderr = final_test.get("stderr", "")

        if stdout:
            print("\n📤 STDOUT (Program Output):")
            print("-" * 60)
            print(stdout)
            print("-" * 60)
        else:
            print("\n⚠️  No stdout output")

        if stderr:
            print("\n⚠️  STDERR (Errors/Warnings):")
            print("-" * 60)
            print(stderr)
            print("-" * 60)

        # Check if samples are present
        samples = final_test.get("samples")
        if samples:
            print("\n🔍 Sample Evaluations:")
            for sample in samples:
                expr = sample.get("expression", "<expression>")
                actual = sample.get("actual")
                expected = sample.get("expected")
                print(f"  • {expr} → {actual} (expected: {expected})")

        return result
    else:
        print(f"\n❌ Error: {response.status_code}")
        print(response.text)
        return None

if __name__ == "__main__":
    print("🧪 Testing Code Generation with Print Output")
    print("=" * 60)
    test_code_generation_with_print()
    print("\n✅ Test completed!")

#!/usr/bin/env python3
import sys
import json
import subprocess

# Run curl command
result = subprocess.run([
    'curl', '-s', '-X', 'POST', 'http://localhost:8888/api/rag/ask-smart-stream',
    '-H', 'Content-Type: application/json',
    '-d', '{"question": "What are the relationships between Elizabeth and Darcy?", "top_k": 3}'
], capture_output=True, text=True)

# Parse SSE stream
for line in result.stdout.split('\n'):
    line = line.strip()
    if line.startswith('data: '):
        data_str = line[6:]
        if data_str:
            try:
                data = json.loads(data_str)
                if 'answer' in data:
                    print('\n=== FINAL RESULT ===')
                    print(f"Strategy: {data.get('strategy', 'unknown')}")
                    print(f"\n=== Token Usage ===")
                    token_usage = data.get('token_usage')
                    if token_usage:
                        print(json.dumps(token_usage, indent=2))
                    else:
                        print('null')
                    print(f"\n=== Token Cost ===")
                    print(f"USD: ${data.get('token_cost_usd', 0):.6f}")
                    print(f"\n=== Governance Context ===")
                    gov = data.get('governance_context', {})
                    if gov:
                        print(f"Risk Tier: {gov.get('risk_tier', 'unknown')}")
                        print(f"Trace ID: {gov.get('trace_id', 'unknown')}")
                        print(f"Num Checkpoints: {len(gov.get('checkpoints', []))}")
                        print(f"Active Criteria: {gov.get('active_criteria', [])}")
                    else:
                        print('Empty {}')
                    break
            except json.JSONDecodeError:
                pass

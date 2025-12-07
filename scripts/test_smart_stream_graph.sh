#!/bin/bash

echo "Testing Smart RAG Stream (Graph RAG) via SSE"
echo "============================================="
echo ""
echo "Sending query: 'What are the relationships between Elizabeth and Mr. Darcy?'"
echo ""

curl -N -X POST http://localhost:8888/api/rag/ask-smart-stream \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are the relationships between Elizabeth and Mr. Darcy?",
    "top_k": 3
  }' 2>/dev/null | \
  while IFS= read -r line; do
    if [[ $line == data:* ]]; then
      # Extract the data part
      data_line="${line#data: }"

      # Skip empty lines
      if [[ -z $data_line ]]; then
        continue
      fi

      # Parse JSON and extract relevant fields
      if echo "$data_line" | jq -e . >/dev/null 2>&1; then
        message=$(echo "$data_line" | jq -r '.message // empty')
        step=$(echo "$data_line" | jq -r '.metadata.step // empty')
        answer=$(echo "$data_line" | jq -r '.answer // empty')

        if [[ -n $message ]]; then
          if [[ -n $step ]]; then
            echo "[$step/6] $message"
          else
            echo "$message"
          fi
        fi

        if [[ -n $answer ]]; then
          echo ""
          echo "✅ Completed!"
          echo ""
          echo "Answer (first 300 chars):"
          echo "${answer:0:300}..."
          echo ""

          total_ms=$(echo "$data_line" | jq -r '.timings.total_ms // empty')
          tokens=$(echo "$data_line" | jq -r '.token_usage.total_tokens // empty')
          cost=$(echo "$data_line" | jq -r '.token_cost_usd // empty')

          if [[ -n $total_ms ]]; then
            echo "⏱️  Total time: ${total_ms}ms"
          fi

          if [[ -n $tokens ]]; then
            echo "💰 Tokens: $tokens (Cost: \$$cost)"
          fi
        fi
      fi
    fi
  done

echo ""
echo "============================================="
echo "Test completed!"

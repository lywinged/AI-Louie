#!/bin/bash

echo "Testing Graph RAG Progress Tracking via SSE"
echo "============================================="
echo ""
echo "Sending query: 'Who is Jane Austen?'"
echo ""

curl -N -X POST http://localhost:8888/api/rag/ask-graph-stream \
  -H "Content-Type: application/json" \
  -d '{"question": "Who is Jane Austen?", "top_k": 3}' 2>/dev/null | \
  while IFS= read -r line; do
    if [[ $line == data:* ]]; then
      # Extract the data part
      data_line="${line#data: }"

      # Skip empty lines and event: lines
      if [[ $data_line == event:* ]] || [[ -z $data_line ]]; then
        continue
      fi

      # Parse JSON and extract relevant fields
      if echo "$data_line" | jq -e . >/dev/null 2>&1; then
        event_type=$(echo "$line" | grep -o "event: [a-z]*" | cut -d' ' -f2 || echo "")

        if [[ $event_type == "progress" ]]; then
          step=$(echo "$data_line" | jq -r '.step // empty')
          message=$(echo "$data_line" | jq -r '.message // empty')

          if [[ -n $message ]]; then
            echo "[$step/6] $message"
          fi
        elif [[ $event_type == "result" ]]; then
          echo ""
          echo "✅ Completed!"
          echo ""
          answer=$(echo "$data_line" | jq -r '.answer[:200] // empty')
          total_ms=$(echo "$data_line" | jq -r '.timings.total_ms // empty')
          tokens=$(echo "$data_line" | jq -r '.token_usage.total_tokens // empty')
          cost=$(echo "$data_line" | jq -r '.token_cost_usd // empty')

          if [[ -n $answer ]]; then
            echo "Answer (first 200 chars):"
            echo "$answer..."
            echo ""
          fi

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

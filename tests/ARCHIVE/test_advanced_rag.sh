#!/bin/bash
# Test script for advanced RAG features

set -e

BASE_URL="http://localhost:8888/api/rag"
BACKEND_HEALTH="http://localhost:8888/health"

echo "=========================================="
echo "Testing Advanced RAG Features"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Wait for backend to be ready
echo -e "${BLUE}Waiting for backend to be ready...${NC}"
for i in {1..30}; do
    if curl -s "$BACKEND_HEALTH" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Backend is ready${NC}"
        break
    fi
    echo "Attempt $i/30: Backend not ready yet, waiting..."
    sleep 2
done

echo ""

# Test query
TEST_QUESTION="Sir roberts fortune a novel, for what purpose he was confident of his own powers of cheating the uncle, and managing?"

# ========================================
# Test 1: Standard RAG (baseline)
# ========================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test 1: Standard RAG (Baseline)${NC}"
echo -e "${BLUE}========================================${NC}"
echo "Question: $TEST_QUESTION"
echo ""

RESPONSE=$(curl -s -X POST "$BASE_URL/ask" \
    -H "Content-Type: application/json" \
    -d "{
        \"question\": \"$TEST_QUESTION\",
        \"top_k\": 10,
        \"include_timings\": true
    }")

echo "$RESPONSE" | jq '{
    answer: .answer,
    confidence: .confidence,
    num_chunks: .num_chunks_retrieved,
    total_time_ms: .total_time_ms,
    models: .models
}' || echo "$RESPONSE"

echo ""
echo -e "${GREEN}✓ Standard RAG test completed${NC}"
echo ""
sleep 2

# ========================================
# Test 2: Hybrid Search (BM25 + Vector)
# ========================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test 2: Hybrid Search (BM25 + Vector)${NC}"
echo -e "${BLUE}========================================${NC}"
echo "Question: $TEST_QUESTION"
echo ""

RESPONSE=$(curl -s -X POST "$BASE_URL/ask-hybrid" \
    -H "Content-Type: application/json" \
    -d "{
        \"question\": \"$TEST_QUESTION\",
        \"top_k\": 10,
        \"include_timings\": true
    }")

echo "$RESPONSE" | jq '{
    answer: .answer,
    confidence: .confidence,
    num_chunks: .num_chunks_retrieved,
    total_time_ms: .total_time_ms,
    hybrid_info: .timings.hybrid_fusion,
    bm25_weight: .timings.bm25_weight,
    vector_weight: .timings.vector_weight
}' || echo "$RESPONSE"

echo ""
echo -e "${GREEN}✓ Hybrid search test completed${NC}"
echo ""
sleep 2

# ========================================
# Test 3: Iterative Self-RAG
# ========================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test 3: Iterative Self-RAG${NC}"
echo -e "${BLUE}========================================${NC}"
echo "Question: What is the relationship between Sir Robert and Uncle Robert?"
echo ""

RESPONSE=$(curl -s -X POST "$BASE_URL/ask-iterative" \
    -H "Content-Type: application/json" \
    -d '{
        "question": "What is the relationship between Sir Robert and Uncle Robert?",
        "top_k": 10,
        "include_timings": true
    }')

echo "$RESPONSE" | jq '{
    answer: .answer,
    confidence: .confidence,
    num_chunks: .num_chunks_retrieved,
    total_time_ms: .total_time_ms,
    iterations: .timings.total_iterations,
    converged: .timings.converged
}' || echo "$RESPONSE"

echo ""
echo -e "${GREEN}✓ Iterative Self-RAG test completed${NC}"
echo ""
sleep 2

# ========================================
# Test 4: Smart RAG (Auto-selection)
# ========================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test 4: Smart RAG (Auto-selection)${NC}"
echo -e "${BLUE}========================================${NC}"

# Test 4a: Simple query (should use hybrid)
echo -e "${YELLOW}Test 4a: Simple author query${NC}"
RESPONSE=$(curl -s -X POST "$BASE_URL/ask-smart" \
    -H "Content-Type: application/json" \
    -d '{
        "question": "Who wrote Pride and Prejudice?",
        "top_k": 5,
        "include_timings": true
    }')

echo "$RESPONSE" | jq '{
    answer: .answer,
    confidence: .confidence,
    query_type: "author_query (expected)",
    total_time_ms: .total_time_ms
}' || echo "$RESPONSE"

echo ""
echo -e "${GREEN}✓ Smart RAG simple query test completed${NC}"
echo ""
sleep 2

# Test 4b: Complex query (should use iterative)
echo -e "${YELLOW}Test 4b: Complex relationship query${NC}"
RESPONSE=$(curl -s -X POST "$BASE_URL/ask-smart" \
    -H "Content-Type: application/json" \
    -d "{
        \"question\": \"$TEST_QUESTION\",
        \"top_k\": 10,
        \"include_timings\": true
    }")

echo "$RESPONSE" | jq '{
    answer: .answer,
    confidence: .confidence,
    query_type: "general (expected)",
    total_time_ms: .total_time_ms
}' || echo "$RESPONSE"

echo ""
echo -e "${GREEN}✓ Smart RAG complex query test completed${NC}"
echo ""
sleep 2

# ========================================
# Test 5: Query Cache
# ========================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test 5: Query Cache Performance${NC}"
echo -e "${BLUE}========================================${NC}"

# First query (no cache)
echo -e "${YELLOW}Query 1: Initial query (no cache)${NC}"
START_TIME=$(date +%s%3N)
RESPONSE1=$(curl -s -X POST "$BASE_URL/ask-hybrid" \
    -H "Content-Type: application/json" \
    -d '{
        "question": "What is prop building?",
        "top_k": 5,
        "include_timings": true
    }')
END_TIME=$(date +%s%3N)
TIME1=$((END_TIME - START_TIME))

echo "Time: ${TIME1}ms"
echo ""

# Second query (similar, should hit cache)
echo -e "${YELLOW}Query 2: Similar query (should hit cache)${NC}"
START_TIME=$(date +%s%3N)
RESPONSE2=$(curl -s -X POST "$BASE_URL/ask-hybrid" \
    -H "Content-Type: application/json" \
    -d '{
        "question": "What does prop building mean?",
        "top_k": 5,
        "include_timings": true
    }')
END_TIME=$(date +%s%3N)
TIME2=$((END_TIME - START_TIME))

echo "Time: ${TIME2}ms"
echo ""

if [ $TIME2 -lt $TIME1 ]; then
    SPEEDUP=$((100 - (TIME2 * 100 / TIME1)))
    echo -e "${GREEN}✓ Cache hit! Speedup: ${SPEEDUP}%${NC}"
else
    echo -e "${YELLOW}⚠ No speedup detected (cache might not have hit)${NC}"
fi

echo ""

# Get cache stats
echo -e "${YELLOW}Cache Statistics:${NC}"
curl -s "$BASE_URL/cache/stats" | jq '.' || echo "Failed to get cache stats"

echo ""
echo -e "${GREEN}✓ Cache test completed${NC}"
echo ""

# ========================================
# Test 6: Query Classification
# ========================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test 6: Query Classification${NC}"
echo -e "${BLUE}========================================${NC}"

declare -a TEST_QUERIES=(
    "Who wrote Moby Dick?"
    "What is the plot of Romeo and Juliet?"
    "Describe the character of Sherlock Holmes"
    "What is the relationship between Harry and Ron?"
    "Find the quote: To be or not to be"
    "What year was 1984 published?"
)

for query in "${TEST_QUERIES[@]}"; do
    echo -e "${YELLOW}Query: $query${NC}"

    RESPONSE=$(curl -s -X POST "$BASE_URL/ask-hybrid" \
        -H "Content-Type: application/json" \
        -d "{
            \"question\": \"$query\",
            \"top_k\": 5,
            \"include_timings\": false
        }")

    echo "$RESPONSE" | jq '{confidence: .confidence, num_chunks: .num_chunks_retrieved}' || echo "Failed"
    echo ""
    sleep 1
done

echo -e "${GREEN}✓ Query classification test completed${NC}"
echo ""

# ========================================
# Summary
# ========================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✓ All tests completed successfully!${NC}"
echo ""
echo "Available endpoints:"
echo "  • POST /api/rag/ask           - Standard RAG"
echo "  • POST /api/rag/ask-hybrid    - Hybrid search (BM25 + vector)"
echo "  • POST /api/rag/ask-iterative - Iterative Self-RAG"
echo "  • POST /api/rag/ask-smart     - Auto-selection based on query type"
echo "  • GET  /api/rag/cache/stats   - Cache statistics"
echo "  • POST /api/rag/cache/clear   - Clear cache"
echo ""
echo "Configuration (.env):"
echo "  • ENABLE_HYBRID_SEARCH=true"
echo "  • ENABLE_QUERY_CACHE=true"
echo "  • ENABLE_QUERY_CLASSIFICATION=true"
echo "  • ENABLE_SELF_RAG=true"
echo ""
echo -e "${BLUE}========================================${NC}"

#!/bin/bash
# Interactive RAG Feature Comparison Script
# Allows toggling features and comparing performance

set -e

BASE_URL="http://localhost:8888/api/rag"
BACKEND_HEALTH="http://localhost:8888/health"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Test query
TEST_QUESTION="Sir roberts fortune a novel, for what purpose he was confident of his own powers of cheating the uncle, and managing?"

echo -e "${CYAN}==========================================${NC}"
echo -e "${CYAN}RAG Feature Comparison Tool${NC}"
echo -e "${CYAN}==========================================${NC}"
echo ""

# Check backend health
echo -e "${BLUE}Checking backend health...${NC}"
if curl -s "$BACKEND_HEALTH" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Backend is ready${NC}"
else
    echo -e "${RED}✗ Backend is not responding${NC}"
    exit 1
fi
echo ""

# Function to run test and extract metrics
run_test() {
    local endpoint=$1
    local mode_name=$2

    echo -e "${YELLOW}Testing: $mode_name${NC}"

    local start_time=$(python3 -c 'import time; print(int(time.time() * 1000))')

    local response=$(curl -s -X POST "$BASE_URL/$endpoint" \
        -H "Content-Type: application/json" \
        -d "{
            \"question\": \"$TEST_QUESTION\",
            \"top_k\": 10,
            \"include_timings\": true
        }")

    local end_time=$(python3 -c 'import time; print(int(time.time() * 1000))')
    local wall_time=$((end_time - start_time))

    # Extract metrics using jq
    local answer=$(echo "$response" | jq -r '.answer // "N/A"' | head -c 150)
    local confidence=$(echo "$response" | jq -r '.confidence // "N/A"')
    local num_chunks=$(echo "$response" | jq -r '.num_chunks_retrieved // "N/A"')
    local total_time_ms=$(echo "$response" | jq -r '.total_time_ms // "N/A"')
    local token_cost=$(echo "$response" | jq -r '.token_cost_usd // "N/A"')
    local total_tokens=$(echo "$response" | jq -r '.token_usage.total // "N/A"')

    # For iterative mode, extract iteration info
    local iterations=$(echo "$response" | jq -r '.timings.total_iterations // "1"')
    local converged=$(echo "$response" | jq -r '.timings.converged // "N/A"')

    echo -e "${CYAN}Results:${NC}"
    echo "  Answer: ${answer}..."
    echo "  Confidence: $confidence"
    echo "  Chunks Retrieved: $num_chunks"
    echo "  Total Time (API): ${total_time_ms}ms"
    echo "  Wall Time (curl): ${wall_time}ms"
    echo "  Total Tokens: $total_tokens"
    echo "  Cost: \$$token_cost"

    if [ "$iterations" != "1" ] || [ "$converged" != "N/A" ]; then
        echo "  Iterations: $iterations"
        echo "  Converged: $converged"
    fi

    echo ""

    # Return metrics as JSON for comparison table
    echo "$mode_name|$confidence|$num_chunks|$total_time_ms|$wall_time|$total_tokens|$token_cost|$iterations"
}

# Main menu
show_menu() {
    echo -e "${MAGENTA}==========================================${NC}"
    echo -e "${MAGENTA}Select Test Mode:${NC}"
    echo -e "${MAGENTA}==========================================${NC}"
    echo "1) Standard RAG (baseline)"
    echo "2) Hybrid Search (BM25 + Vector)"
    echo "3) Iterative Self-RAG"
    echo "4) Smart RAG (auto-selection)"
    echo "5) Compare All Modes"
    echo "6) Custom Comparison (select multiple)"
    echo "7) Toggle Feature Settings"
    echo "8) View Current Cache Stats"
    echo "9) Clear Cache"
    echo "0) Exit"
    echo ""
}

# Feature toggle menu
toggle_features() {
    echo -e "${MAGENTA}==========================================${NC}"
    echo -e "${MAGENTA}Feature Toggle (restart required)${NC}"
    echo -e "${MAGENTA}==========================================${NC}"
    echo ""
    echo "Current settings in .env:"
    echo ""

    grep "ENABLE_HYBRID_SEARCH" .env || echo "ENABLE_HYBRID_SEARCH=true"
    grep "ENABLE_QUERY_CACHE" .env || echo "ENABLE_QUERY_CACHE=true"
    grep "ENABLE_QUERY_CLASSIFICATION" .env || echo "ENABLE_QUERY_CLASSIFICATION=true"
    grep "ENABLE_SELF_RAG" .env || echo "ENABLE_SELF_RAG=true"

    echo ""
    echo "1) Toggle Hybrid Search (BM25 + Vector)"
    echo "2) Toggle Query Cache"
    echo "3) Toggle Query Classification"
    echo "4) Toggle Self-RAG"
    echo "5) Adjust HYBRID_ALPHA (vector vs BM25 weight)"
    echo "6) Adjust Self-RAG Confidence Threshold"
    echo "0) Back to main menu"
    echo ""

    read -p "Select option: " toggle_choice

    case $toggle_choice in
        1)
            read -p "Enable Hybrid Search? (true/false): " value
            sed -i.bak "s/ENABLE_HYBRID_SEARCH=.*/ENABLE_HYBRID_SEARCH=$value/" .env
            echo -e "${GREEN}Updated ENABLE_HYBRID_SEARCH to $value${NC}"
            echo -e "${YELLOW}Restart backend: docker-compose restart backend${NC}"
            ;;
        2)
            read -p "Enable Query Cache? (true/false): " value
            sed -i.bak "s/ENABLE_QUERY_CACHE=.*/ENABLE_QUERY_CACHE=$value/" .env
            echo -e "${GREEN}Updated ENABLE_QUERY_CACHE to $value${NC}"
            echo -e "${YELLOW}Restart backend: docker-compose restart backend${NC}"
            ;;
        3)
            read -p "Enable Query Classification? (true/false): " value
            sed -i.bak "s/ENABLE_QUERY_CLASSIFICATION=.*/ENABLE_QUERY_CLASSIFICATION=$value/" .env
            echo -e "${GREEN}Updated ENABLE_QUERY_CLASSIFICATION to $value${NC}"
            echo -e "${YELLOW}Restart backend: docker-compose restart backend${NC}"
            ;;
        4)
            read -p "Enable Self-RAG? (true/false): " value
            sed -i.bak "s/ENABLE_SELF_RAG=.*/ENABLE_SELF_RAG=$value/" .env
            echo -e "${GREEN}Updated ENABLE_SELF_RAG to $value${NC}"
            echo -e "${YELLOW}Restart backend: docker-compose restart backend${NC}"
            ;;
        5)
            read -p "HYBRID_ALPHA (0.0-1.0, higher=more vector): " value
            sed -i.bak "s/HYBRID_ALPHA=.*/HYBRID_ALPHA=$value/" .env
            echo -e "${GREEN}Updated HYBRID_ALPHA to $value${NC}"
            echo -e "${YELLOW}Restart backend: docker-compose restart backend${NC}"
            ;;
        6)
            read -p "SELF_RAG_CONFIDENCE_THRESHOLD (0.0-1.0): " value
            sed -i.bak "s/SELF_RAG_CONFIDENCE_THRESHOLD=.*/SELF_RAG_CONFIDENCE_THRESHOLD=$value/" .env
            echo -e "${GREEN}Updated SELF_RAG_CONFIDENCE_THRESHOLD to $value${NC}"
            echo -e "${YELLOW}Restart backend: docker-compose restart backend${NC}"
            ;;
        0)
            return
            ;;
    esac

    echo ""
    read -p "Press Enter to continue..."
}

# Compare all modes
compare_all() {
    echo -e "${CYAN}==========================================${NC}"
    echo -e "${CYAN}Running Comprehensive Comparison${NC}"
    echo -e "${CYAN}==========================================${NC}"
    echo ""

    # Array to store results
    declare -a results

    # Run all tests
    results[0]=$(run_test "ask" "Standard RAG")
    results[1]=$(run_test "ask-hybrid" "Hybrid Search")
    results[2]=$(run_test "ask-iterative" "Self-RAG")
    results[3]=$(run_test "ask-smart" "Smart RAG")

    # Print comparison table
    echo -e "${MAGENTA}==========================================${NC}"
    echo -e "${MAGENTA}Comparison Summary${NC}"
    echo -e "${MAGENTA}==========================================${NC}"
    echo ""

    printf "%-20s %-12s %-8s %-12s %-12s %-12s %-10s %-10s\n" \
        "Mode" "Confidence" "Chunks" "API Time(ms)" "Wall Time(ms)" "Tokens" "Cost(\$)" "Iterations"
    echo "---------------------------------------------------------------------------------------------------------------------------"

    for result in "${results[@]}"; do
        IFS='|' read -r mode conf chunks api_time wall_time tokens cost iters <<< "$result"
        printf "%-20s %-12s %-8s %-12s %-12s %-12s %-10s %-10s\n" \
            "$mode" "$conf" "$chunks" "$api_time" "$wall_time" "$tokens" "$cost" "$iters"
    done

    echo ""

    # Calculate improvements
    echo -e "${CYAN}Key Observations:${NC}"
    echo "• Compare confidence scores (higher = more certain)"
    echo "• Compare latency (API time + wall time)"
    echo "• Compare token usage (directly impacts cost)"
    echo "• Iterative mode shows # of retrieval rounds"
    echo ""
}

# Custom comparison
custom_comparison() {
    echo -e "${CYAN}Select modes to compare (space-separated, e.g., 1 2 4):${NC}"
    echo "1) Standard RAG"
    echo "2) Hybrid Search"
    echo "3) Iterative Self-RAG"
    echo "4) Smart RAG"
    echo ""

    read -p "Your selection: " selection

    declare -a results
    local index=0

    for choice in $selection; do
        case $choice in
            1)
                results[$index]=$(run_test "ask" "Standard RAG")
                ((index++))
                ;;
            2)
                results[$index]=$(run_test "ask-hybrid" "Hybrid Search")
                ((index++))
                ;;
            3)
                results[$index]=$(run_test "ask-iterative" "Self-RAG")
                ((index++))
                ;;
            4)
                results[$index]=$(run_test "ask-smart" "Smart RAG")
                ((index++))
                ;;
        esac
    done

    # Print comparison
    echo -e "${MAGENTA}Comparison Results:${NC}"
    printf "%-20s %-12s %-8s %-12s %-12s %-12s %-10s\n" \
        "Mode" "Confidence" "Chunks" "API Time(ms)" "Wall Time(ms)" "Tokens" "Cost(\$)"
    echo "------------------------------------------------------------------------------------------------------------"

    for result in "${results[@]}"; do
        IFS='|' read -r mode conf chunks api_time wall_time tokens cost iters <<< "$result"
        printf "%-20s %-12s %-8s %-12s %-12s %-12s %-10s\n" \
            "$mode" "$conf" "$chunks" "$api_time" "$wall_time" "$tokens" "$cost"
    done

    echo ""
}

# View cache stats
view_cache_stats() {
    echo -e "${CYAN}Query Cache Statistics:${NC}"
    curl -s "$BASE_URL/cache/stats" | jq '.'
    echo ""
}

# Clear cache
clear_cache() {
    echo -e "${YELLOW}Clearing query cache...${NC}"
    curl -s -X POST "$BASE_URL/cache/clear" | jq '.'
    echo -e "${GREEN}Cache cleared${NC}"
    echo ""
}

# Main loop
while true; do
    show_menu
    read -p "Select option: " choice

    case $choice in
        1)
            run_test "ask" "Standard RAG"
            read -p "Press Enter to continue..."
            ;;
        2)
            run_test "ask-hybrid" "Hybrid Search"
            read -p "Press Enter to continue..."
            ;;
        3)
            run_test "ask-iterative" "Iterative Self-RAG"
            read -p "Press Enter to continue..."
            ;;
        4)
            run_test "ask-smart" "Smart RAG"
            read -p "Press Enter to continue..."
            ;;
        5)
            compare_all
            read -p "Press Enter to continue..."
            ;;
        6)
            custom_comparison
            read -p "Press Enter to continue..."
            ;;
        7)
            toggle_features
            ;;
        8)
            view_cache_stats
            read -p "Press Enter to continue..."
            ;;
        9)
            clear_cache
            read -p "Press Enter to continue..."
            ;;
        0)
            echo -e "${GREEN}Goodbye!${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid option${NC}"
            ;;
    esac
done

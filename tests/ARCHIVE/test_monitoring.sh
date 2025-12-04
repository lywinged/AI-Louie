#!/bin/bash

# AI-Louie 监控系统快速测试脚本
# 用于验证所有监控功能是否正常工作

set -e

API_URL="http://localhost:8888"
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================="
echo "  AI-Louie 监控系统测试"
echo "========================================="
echo ""

# 函数：检查服务健康
check_service() {
    local name=$1
    local url=$2

    echo -n "检查 $name... "
    if curl -s -f "$url" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ 运行中${NC}"
        return 0
    else
        echo -e "${RED}✗ 未运行${NC}"
        return 1
    fi
}

# 函数：测试 API 端点
test_api() {
    local name=$1
    local method=$2
    local url=$3
    local data=$4

    echo -n "测试 $name... "

    if [ "$method" == "GET" ]; then
        response=$(curl -s -w "\n%{http_code}" "$url")
    else
        response=$(curl -s -w "\n%{http_code}" -X POST "$url" \
            -H "Content-Type: application/json" \
            -d "$data")
    fi

    status_code=$(echo "$response" | tail -n1)

    if [ "$status_code" -eq 200 ]; then
        echo -e "${GREEN}✓ 通过 (HTTP $status_code)${NC}"
        return 0
    else
        echo -e "${RED}✗ 失败 (HTTP $status_code)${NC}"
        return 1
    fi
}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " 1. 检查核心服务"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

check_service "Backend API" "$API_URL/health"
check_service "Qdrant" "http://localhost:6333"
check_service "Prometheus" "http://localhost:9090/-/healthy"
check_service "Grafana" "http://localhost:3000/api/health"
check_service "Jaeger" "http://localhost:16686"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " 2. 测试监控 API 端点"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 监控健康检查
test_api "监控系统健康" "GET" "$API_URL/api/monitoring/health"

# 监控配置
test_api "监控配置" "GET" "$API_URL/api/monitoring/config"

# LLM metrics
test_api "LLM 调用摘要" "GET" "$API_URL/api/monitoring/llm/summary"
test_api "最近 LLM 调用" "GET" "$API_URL/api/monitoring/llm/recent-calls?limit=5"

# 数据质量
test_api "数据质量摘要" "GET" "$API_URL/api/monitoring/data-quality/summary?interaction_type=chat"

# RAG 评估
test_api "RAG 评估摘要" "GET" "$API_URL/api/monitoring/rag/evaluation-summary"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " 3. 生成测试数据"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "发送 5 个测试聊天请求..."
for i in {1..5}; do
    curl -s -X POST "$API_URL/api/chat/message" \
        -H "Content-Type: application/json" \
        -d "{\"message\": \"Test message $i\", \"stream\": false}" \
        > /dev/null
    echo -n "."
done
echo -e " ${GREEN}✓ 完成${NC}"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " 4. 验证 Prometheus Metrics"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo -n "检查 /metrics 端点... "
if curl -s "$API_URL/metrics" | grep -q "llm_token_usage_counter"; then
    echo -e "${GREEN}✓ LLM metrics 存在${NC}"
else
    echo -e "${RED}✗ LLM metrics 不存在${NC}"
fi

echo -n "检查 RAG metrics... "
if curl -s "$API_URL/metrics" | grep -q "rag_operation_counter"; then
    echo -e "${GREEN}✓ RAG metrics 存在${NC}"
else
    echo -e "${RED}✗ RAG metrics 不存在${NC}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " 5. 测试完整流程"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 测试 RAG 评估
echo "测试 RAG 质量评估..."
test_api "RAG 质量评估" "POST" "$API_URL/api/monitoring/rag/evaluate" \
    '{
        "question": "What is machine learning?",
        "answer": "Machine learning is a subset of artificial intelligence.",
        "contexts": ["Machine learning is a method of data analysis.", "AI enables computers to learn."],
        "model": "gpt-4o-mini"
    }'

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " 6. 访问链接总结"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo -e "${YELLOW}核心服务:${NC}"
echo "  • Backend API: $API_URL"
echo "  • API 文档: $API_URL/docs"
echo "  • Qdrant: http://localhost:6333/dashboard"
echo ""
echo -e "${YELLOW}监控服务:${NC}"
echo "  • Grafana: http://localhost:3000 (admin/admin)"
echo "  • Prometheus: http://localhost:9090"
echo "  • Jaeger: http://localhost:16686"
echo "  • Metrics: $API_URL/metrics"
echo ""
echo -e "${YELLOW}监控 API:${NC}"
echo "  • LLM Metrics: $API_URL/api/monitoring/llm/summary"
echo "  • Data Quality: $API_URL/api/monitoring/data-quality/summary"
echo "  • RAG Evaluation: $API_URL/api/monitoring/rag/evaluation-summary"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}  ✓ 测试完成!${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "详细文档请查看:"
echo "  • MONITORING_SETUP.md - 监控设置指南"
echo "  • IMPLEMENTATION_SUMMARY.md - 实施总结"
echo ""

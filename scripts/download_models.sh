#!/bin/bash
set -euo pipefail

# ==========================================
# Model Download Script for AI-Louie
# Downloads large BGE models on-demand
# ==========================================

MODELS_DIR="$(cd "$(dirname "$0")/../models" && pwd)"

echo "==========================================="
echo "🤖 AI-Louie Model Downloader"
echo "==========================================="
echo

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if model already exists
check_model_exists() {
    local model_dir="$1"
    local model_file="$2"

    if [[ -f "$model_dir/$model_file" ]]; then
        local size=$(du -h "$model_dir/$model_file" | cut -f1)
        echo -e "${GREEN}✓${NC} Already downloaded: $model_file ($size)"
        return 0
    else
        return 1
    fi
}

# Download BGE-M3 Embedding Model
download_bge_m3() {
    echo -e "${BLUE}📥 Downloading BGE-M3 Embedding Model (INT8)${NC}"
    echo "   Size: ~547MB"
    echo "   Purpose: High-accuracy embeddings for complex queries"
    echo

    MODEL_DIR="$MODELS_DIR/bge-m3-embed-int8"

    if check_model_exists "$MODEL_DIR" "model_int8.onnx"; then
        return 0
    fi

    # Create directory if not exists
    mkdir -p "$MODEL_DIR"

    echo "   Attempting to download from Hugging Face..."
    echo

    # Try wget first, then curl
    DOWNLOAD_URL="https://huggingface.co/louielunz/bge-embed/resolve/main/model_int8.onnx"

    if command -v wget >/dev/null 2>&1; then
        echo "   Using wget..."
        if wget -O "$MODEL_DIR/model_int8.onnx" "$DOWNLOAD_URL"; then
            echo -e "${GREEN}✓${NC} Download successful!"
            return 0
        fi
    elif command -v curl >/dev/null 2>&1; then
        echo "   Using curl..."
        if curl -L -o "$MODEL_DIR/model_int8.onnx" "$DOWNLOAD_URL"; then
            echo -e "${GREEN}✓${NC} Download successful!"
            return 0
        fi
    fi

    # Fallback to manual instructions
    echo -e "${YELLOW}⚠️  Automatic download failed. Please download manually:${NC}"
    echo "   1. Visit: https://huggingface.co/BAAI/bge-m3"
    echo "   2. Download the INT8 quantized ONNX model"
    echo "   3. Place in: $MODEL_DIR/model_int8.onnx"
    echo
    echo "   Or use Hugging Face CLI:"
    echo "   pip install huggingface_hub"
    echo "   huggingface-cli download BAAI/bge-m3 --local-dir $MODEL_DIR"
    echo
}

# Download BGE Reranker Model
download_bge_reranker() {
    echo -e "${BLUE}📥 Downloading BGE Reranker Model (INT8)${NC}"
    echo "   Size: ~287MB"
    echo "   Purpose: Cross-encoder reranking for better relevance"
    echo

    MODEL_DIR="$MODELS_DIR/bge-reranker-int8"

    if check_model_exists "$MODEL_DIR" "model_int8.onnx"; then
        return 0
    fi

    # Create directory if not exists
    mkdir -p "$MODEL_DIR"

    echo "   Attempting to download from Hugging Face..."
    echo

    # Try wget first, then curl
    DOWNLOAD_URL="https://huggingface.co/louielunz/bge-reranker/resolve/main/model_int8.onnx"

    if command -v wget >/dev/null 2>&1; then
        echo "   Using wget..."
        if wget -O "$MODEL_DIR/model_int8.onnx" "$DOWNLOAD_URL"; then
            echo -e "${GREEN}✓${NC} Download successful!"
            return 0
        fi
    elif command -v curl >/dev/null 2>&1; then
        echo "   Using curl..."
        if curl -L -o "$MODEL_DIR/model_int8.onnx" "$DOWNLOAD_URL"; then
            echo -e "${GREEN}✓${NC} Download successful!"
            return 0
        fi
    fi

    # Fallback to manual instructions
    echo -e "${YELLOW}⚠️  Automatic download failed. Please download manually:${NC}"
    echo "   1. Visit: https://huggingface.co/BAAI/bge-reranker-base"
    echo "   2. Download the INT8 quantized ONNX model"
    echo "   3. Place in: $MODEL_DIR/model_int8.onnx"
    echo
    echo "   Or use Hugging Face CLI:"
    echo "   pip install huggingface_hub"
    echo "   huggingface-cli download BAAI/bge-reranker-base --local-dir $MODEL_DIR"
    echo
}

# Check MiniLM models (should be in git)
check_minilm_models() {
    echo -e "${BLUE}🔍 Checking MiniLM Models (included in repo)${NC}"

    local minilm_embed="$MODELS_DIR/minilm-embed-int8/model_int8.onnx"
    local minilm_rerank="$MODELS_DIR/minilm-reranker-onnx/model_int8.onnx"

    if [[ -f "$minilm_embed" ]]; then
        echo -e "${GREEN}✓${NC} MiniLM Embedding model found (23MB)"
    else
        echo -e "${RED}✗${NC} MiniLM Embedding model missing!"
        echo "   This should be included in the git repository."
    fi

    if [[ -f "$minilm_rerank" ]]; then
        echo -e "${GREEN}✓${NC} MiniLM Reranker model found (23MB)"
    else
        echo -e "${RED}✗${NC} MiniLM Reranker model missing!"
        echo "   This should be included in the git repository."
    fi
    echo
}

# Main menu
show_menu() {
    echo "==========================================="
    echo "Which models do you want to download?"
    echo "==========================================="
    echo
    echo "1) Download BGE-M3 Embedding (~547MB)"
    echo "2) Download BGE Reranker (~287MB)"
    echo "3) Download both BGE models (~834MB total)"
    echo "4) Check all models status"
    echo "5) Exit"
    echo
    read -p "Enter choice [1-5]: " choice

    case $choice in
        1)
            download_bge_m3
            ;;
        2)
            download_bge_reranker
            ;;
        3)
            download_bge_m3
            echo
            download_bge_reranker
            ;;
        4)
            check_minilm_models
            download_bge_m3
            echo
            download_bge_reranker
            ;;
        5)
            echo "Exiting..."
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid choice!${NC}"
            exit 1
            ;;
    esac
}

# Main execution
main() {
    # Always check MiniLM first
    check_minilm_models

    # Show menu if no arguments
    if [[ $# -eq 0 ]]; then
        show_menu
    else
        # Command line arguments
        case "$1" in
            bge-m3)
                download_bge_m3
                ;;
            bge-reranker)
                download_bge_reranker
                ;;
            all)
                download_bge_m3
                echo
                download_bge_reranker
                ;;
            check)
                check_minilm_models
                download_bge_m3
                echo
                download_bge_reranker
                ;;
            *)
                echo "Usage: $0 [bge-m3|bge-reranker|all|check]"
                echo
                echo "Options:"
                echo "  bge-m3        Download BGE-M3 embedding model"
                echo "  bge-reranker  Download BGE reranker model"
                echo "  all           Download all BGE models"
                echo "  check         Check status of all models"
                echo "  (no args)     Show interactive menu"
                exit 1
                ;;
        esac
    fi

    echo
    echo -e "${GREEN}==========================================="
    echo "✅ Model check complete!"
    echo "==========================================${NC}"
    echo
    echo "📝 Notes:"
    echo "   - MiniLM models (46MB total) are included in git repo"
    echo "   - BGE models (834MB total) must be downloaded separately"
    echo "   - System uses MiniLM by default (faster, compatible)"
    echo "   - BGE models are used as fallback for complex queries"
    echo
}

main "$@"

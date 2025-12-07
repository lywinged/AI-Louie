#!/bin/bash
set -euo pipefail

# ===========================
# Docker Check & Auto-Start
# ===========================
check_and_start_docker() {
  echo "🐳 Checking Docker status..."

  # Check if docker command exists
  if ! command -v docker >/dev/null 2>&1; then
    echo "❌ Docker is not installed. Please install Docker first:"
    echo "   macOS: https://docs.docker.com/desktop/install/mac-install/"
    echo "   Linux: https://docs.docker.com/engine/install/"
    exit 1
  fi

  # Check if Docker daemon is running
  if ! docker info >/dev/null 2>&1; then
    echo "⚠️  Docker daemon is not running. Attempting to start..."

    case "$OSTYPE" in
      darwin*)
        # macOS: Start Docker Desktop
        echo "   Starting Docker Desktop..."
        open -a Docker
        echo "   Waiting for Docker to start (this may take 30-60 seconds)..."

        # Wait for Docker to be ready (max 120 seconds)
        for i in {1..60}; do
          if docker info >/dev/null 2>&1; then
            echo "   ✅ Docker is now running!"
            return 0
          fi
          sleep 2
          echo -n "."
        done
        echo
        echo "❌ Docker failed to start within 120 seconds. Please start Docker Desktop manually."
        exit 1
        ;;

      linux*)
        # Linux: Try to start Docker service
        echo "   Attempting to start Docker service..."

        # Try systemctl (most common on modern Linux)
        if command -v systemctl >/dev/null 2>&1; then
          if sudo systemctl start docker 2>/dev/null; then
            echo "   Waiting for Docker to start..."
            sleep 5
            if docker info >/dev/null 2>&1; then
              echo "   ✅ Docker is now running!"
              return 0
            fi
          fi
        fi

        # Try service command (older Linux)
        if command -v service >/dev/null 2>&1; then
          if sudo service docker start 2>/dev/null; then
            echo "   Waiting for Docker to start..."
            sleep 5
            if docker info >/dev/null 2>&1; then
              echo "   ✅ Docker is now running!"
              return 0
            fi
          fi
        fi

        echo "❌ Failed to start Docker automatically. Please start it manually:"
        echo "   sudo systemctl start docker"
        echo "   or"
        echo "   sudo service docker start"
        exit 1
        ;;

      *)
        echo "❌ Unsupported OS: $OSTYPE"
        echo "   Please start Docker manually and try again."
        exit 1
        ;;
    esac
  else
    echo "   ✅ Docker is already running"
  fi
}

# Run Docker check
check_and_start_docker
echo

# ===========================
# Config
# ===========================
DATA_ZIP="data.zip"
DATA_DIR="data"

FRONTEND_SERVICE="${FRONTEND_SERVICE:-frontend}"
BACKEND_SERVICE="${BACKEND_SERVICE:-backend}"
QDRANT_SERVICE="${QDRANT_SERVICE:-qdrant}"
INFERENCE_SERVICE="${INFERENCE_SERVICE:-inference}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-prometheus}"
GRAFANA_SERVICE="${GRAFANA_SERVICE:-grafana}"
JAEGER_SERVICE="${JAEGER_SERVICE:-jaeger}"

FRONTEND_INTERNAL_PORT="${FRONTEND_INTERNAL_PORT:-8501}"
BACKEND_INTERNAL_PORT="${BACKEND_INTERNAL_PORT:-8888}"
QDRANT_INTERNAL_PORT="${QDRANT_INTERNAL_PORT:-6333}"
INFERENCE_INTERNAL_PORT="${INFERENCE_INTERNAL_PORT:-8001}"
PROMETHEUS_INTERNAL_PORT="${PROMETHEUS_INTERNAL_PORT:-9090}"
GRAFANA_INTERNAL_PORT="${GRAFANA_INTERNAL_PORT:-3000}"
JAEGER_INTERNAL_PORT="${JAEGER_INTERNAL_PORT:-16686}"

OPEN_BROWSER="${OPEN_BROWSER:-1}"

# ===========================
# Helpers
# ===========================
echo_hr() { echo "=========================================="; }

DC() {
  if command -v docker-compose >/dev/null 2>&1; then docker-compose "$@"; else docker compose "$@"; fi
}

dc_port() {
  local svc="$1" internal="$2"
  local port
  port="$(DC port "$svc" "$internal" 2>/dev/null | awk -F: 'NF{print $NF; exit}')"
  echo "${port:-$internal}"
}

wait_http_ok() {
  local url="$1" tries="${2:-10}"
  for ((i=1;i<=tries;i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  return 1
}

open_url() {
  local url="$1"
  [[ "$OPEN_BROWSER" == "1" ]] || { echo "ℹ️  Open manually: $url"; return; }
  case "$OSTYPE" in
    darwin*) open "$url" ;;
    linux-gnu*) command -v xdg-open >/dev/null && xdg-open "$url" || command -v gnome-open >/dev/null && gnome-open "$url" || echo "ℹ️  Open manually: $url" ;;
    msys*|cygwin*) start "$url" ;;
    *) echo "ℹ️  Open manually: $url" ;;
  esac
}
# ===========================
# Step 0a: Download data.zip if not present
# ===========================
echo_hr
echo "📥 Checking for ${DATA_ZIP}"
echo_hr

DATA_URL="https://huggingface.co/datasets/louielunz/150books/resolve/main/data.zip"

if [[ ! -f "$DATA_ZIP" ]]; then
  echo "⚠️  ${DATA_ZIP} not found locally"
  echo "   Downloading from Hugging Face..."

  if command -v curl >/dev/null 2>&1; then
    if curl -L -o "$DATA_ZIP" "$DATA_URL" --progress-bar; then
      echo "   ✅ Downloaded ${DATA_ZIP} successfully"
      chmod 644 "$DATA_ZIP"
      echo "   ✅ Set file permissions"
    else
      echo "   ❌ Failed to download ${DATA_ZIP}"
      echo "   Please download manually from: $DATA_URL"
      exit 1
    fi
  elif command -v wget >/dev/null 2>&1; then
    if wget -O "$DATA_ZIP" "$DATA_URL"; then
      echo "   ✅ Downloaded ${DATA_ZIP} successfully"
      chmod 644 "$DATA_ZIP"
      echo "   ✅ Set file permissions"
    else
      echo "   ❌ Failed to download ${DATA_ZIP}"
      echo "   Please download manually from: $DATA_URL"
      exit 1
    fi
  else
    echo "   ❌ Neither curl nor wget found. Install one of them:"
    echo "      macOS: curl is pre-installed, or brew install wget"
    echo "      Ubuntu: sudo apt install curl"
    echo "   Or download manually from: $DATA_URL"
    exit 1
  fi
else
  echo "   ✅ ${DATA_ZIP} found locally"
fi
echo

# ===========================
# Step 0b: Extract data.zip → ./data (flatten)
# ===========================
echo_hr
echo "📦 Checking data directory"
echo_hr

# Check if data folder exists and has content
if [[ -d "$DATA_DIR" ]] && [[ -n "$(ls -A "$DATA_DIR" 2>/dev/null)" ]]; then
  echo "   ✅ Data folder already exists with content, skipping extraction"
  echo
elif [[ -f "$DATA_ZIP" ]]; then
  echo "   📦 Extracting ${DATA_ZIP} → ${DATA_DIR} (flatten 1-level)"

  if ! command -v unzip >/dev/null 2>&1; then
    echo "❌ 'unzip' not found. Install it first (macOS: brew install unzip, Ubuntu: sudo apt install unzip)."
    exit 1
  fi

  # Clean and extract to temp directory
  rm -rf "$DATA_DIR"
  mkdir -p "$DATA_DIR"
  TMP_DIR="$(mktemp -d)"
  if ! unzip -o -q "$DATA_ZIP" -d "$TMP_DIR"; then
    echo "❌ Failed to extract $DATA_ZIP"
    exit 1
  fi

  # Remove macOS junk files
  find "$TMP_DIR" -name "__MACOSX" -type d -prune -exec rm -rf {} + || true
  find "$TMP_DIR" -name ".DS_Store" -type f -delete || true

  # Flatten: merge top-level directory contents into data/, move top-level files directly
  shopt -s dotglob nullglob
  for entry in "$TMP_DIR"/*; do
    if [[ -d "$entry" ]]; then
      rsync -a "$entry"/ "$DATA_DIR"/
    elif [[ -f "$entry" ]]; then
      mv "$entry" "$DATA_DIR"/
    fi
  done
  shopt -u dotglob nullglob

  rm -rf "$TMP_DIR"
  echo "   ✓ Flattened into: $DATA_DIR"
  echo
else
  echo "ℹ️  '$DATA_ZIP' not found — skipping extraction. Existing '$DATA_DIR' will be used if present."
  mkdir -p "$DATA_DIR"
fi

# ===========================
# Step 1: Check and prompt for API key
# ===========================
echo_hr
echo "🔑 Checking OpenAI API Key"
echo_hr

# Create .env from .env.example if it doesn't exist
if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    echo "📋 Creating .env from .env.example..."
    cp .env.example .env
    echo "   ✓ Created .env file"
  else
    echo "⚠️  Neither .env nor .env.example found"
  fi
fi

# Initialize EXISTING_KEY as empty
EXISTING_KEY=""

# Load .env file if it exists
if [[ -f .env ]]; then
  # Extract OPENAI_API_KEY from .env (handle commented lines and empty values)
  EXISTING_KEY=$(grep -E "^OPENAI_API_KEY=" .env | cut -d'=' -f2- | tr -d '"' | tr -d "'" | xargs)
fi

# Check if API key is missing or empty
if [[ -z "$EXISTING_KEY" ]] || [[ "$EXISTING_KEY" == "your-openai-api-key-here" ]]; then
  echo "⚠️  No OpenAI API key found in .env file"
  echo
  echo "Please enter your OpenAI API key (or press Enter to skip):"
  read -r NEW_API_KEY

  if [[ -n "$NEW_API_KEY" ]]; then
    # Update or create .env file with the new API key
    if [[ -f .env ]]; then
      # Replace existing OPENAI_API_KEY line
      if grep -q "^OPENAI_API_KEY=" .env; then
        # Use | as delimiter to avoid issues with / in API keys
        sed -i.bak "s|^OPENAI_API_KEY=.*|OPENAI_API_KEY=$NEW_API_KEY|" .env && rm -f .env.bak
        echo "   ✓ Updated OPENAI_API_KEY in .env"
      else
        # Append if not found
        echo "OPENAI_API_KEY=$NEW_API_KEY" >> .env
        echo "   ✓ Added OPENAI_API_KEY to .env"
      fi
    else
      # Create new .env file
      echo "OPENAI_API_KEY=$NEW_API_KEY" > .env
      echo "   ✓ Created .env with OPENAI_API_KEY"
    fi
  else
    echo "   ⚠️  Skipping API key setup - services may fail without valid key"
  fi
else
  echo "   ✓ OpenAI API key found in .env"
fi
echo

# ===========================
# Step 2: Clean env
# ===========================
unset QDRANT_HOST
unset QDRANT_SEED_PATH

echo_hr
echo "🚀 Starting AI Assessment Platform"
echo_hr
echo "🧹 Environment cleaned:"
echo "   ✓ QDRANT_HOST unset"
echo "   ✓ QDRANT_SEED_PATH unset"
echo

# ===========================
# Step 3: Start containers
# ===========================
echo "🐳 Starting Docker containers..."
if ! DC up -d "$@"; then
  echo "❌ Docker startup failed! Check logs with: docker-compose logs (or docker compose logs)"
  exit 1
fi
echo "✅ Containers started successfully!"
echo

# ===========================
# Step 4: Detect mapped ports
# ===========================
FRONTEND_PORT="$(dc_port "$FRONTEND_SERVICE" "$FRONTEND_INTERNAL_PORT")"
BACKEND_PORT="$(dc_port "$BACKEND_SERVICE" "$BACKEND_INTERNAL_PORT")"
QDRANT_PORT="$(dc_port "$QDRANT_SERVICE" "$QDRANT_INTERNAL_PORT")"
INFERENCE_PORT="$(dc_port "$INFERENCE_SERVICE" "$INFERENCE_INTERNAL_PORT")"
PROMETHEUS_PORT="$(dc_port "$PROMETHEUS_SERVICE" "$PROMETHEUS_INTERNAL_PORT")"
GRAFANA_PORT="$(dc_port "$GRAFANA_SERVICE" "$GRAFANA_INTERNAL_PORT")"
JAEGER_PORT="$(dc_port "$JAEGER_SERVICE" "$JAEGER_INTERNAL_PORT")"

# ===========================
# Step 5: Health checks
# ===========================
echo "Waiting for services to start..."
sleep 5

echo "Checking backend API..."
if wait_http_ok "http://localhost:${BACKEND_PORT}/health"; then
  echo "   Backend API is ready"
else
  echo "   WARNING: Backend not responding"
fi

echo "Checking Qdrant..."
if wait_http_ok "http://localhost:${QDRANT_PORT}"; then
  echo "   Qdrant is ready"
else
  echo "   WARNING: Qdrant not responding"
fi

echo "Checking Inference Service..."
if wait_http_ok "http://localhost:${INFERENCE_PORT}/health"; then
  echo "   Inference Service is ready"
else
  echo "   WARNING: Inference Service not responding"
fi

echo "Checking Prometheus..."
if wait_http_ok "http://localhost:${PROMETHEUS_PORT}/-/ready"; then
  echo "   Prometheus is ready"
else
  echo "   WARNING: Prometheus not responding"
fi

echo "Checking Grafana..."
if wait_http_ok "http://localhost:${GRAFANA_PORT}/api/health"; then
  echo "   Grafana is ready"
else
  echo "   WARNING: Grafana not responding"
fi

# ===========================
# Step 5b: Wait for Qdrant seeding to complete
# ===========================
echo
echo_hr
echo "⏳ Waiting for Qdrant Collection Seeding"
echo_hr
COLLECTION_NAME="${QDRANT_COLLECTION:-assessment_docs_minilm}"
MAX_WAIT=600  # Maximum 10 minutes wait (for large parallel seeding)
WAIT_INTERVAL=5
EXPECTED_VECTORS=150000  # Expected vector count for 150 books
MIN_STABLE_VECTORS=140000  # Wait for ~93% completion (140k/150k) before stability check
STABLE_CHECKS_NEEDED=4  # Number of consecutive stable checks (20s)

echo "Collection: ${COLLECTION_NAME}"
echo "Checking every ${WAIT_INTERVAL}s (max ${MAX_WAIT}s)..."
echo

PREV_COUNT=0
STABLE_COUNT=0
START_TIME=$(date +%s)

for ((i=1; i<=MAX_WAIT/WAIT_INTERVAL; i++)); do
  # Check if collection exists and has vectors
  COLLECTION_INFO=$(curl -s "http://localhost:${QDRANT_PORT}/collections/${COLLECTION_NAME}" 2>/dev/null || echo "{}")
  VECTOR_COUNT=$(echo "$COLLECTION_INFO" | grep -o '"points_count":[0-9]*' | grep -o '[0-9]*' || echo "0")

  ELAPSED=$(($(date +%s) - START_TIME))

  if [[ "$VECTOR_COUNT" -gt 0 ]]; then
    # Calculate progress percentage
    PROGRESS=$((VECTOR_COUNT * 100 / EXPECTED_VECTORS))
    if [[ $PROGRESS -gt 100 ]]; then PROGRESS=100; fi

    # Create progress bar
    BAR_LENGTH=50
    FILLED=$((PROGRESS * BAR_LENGTH / 100))
    BAR=$(printf "%${FILLED}s" | tr ' ' '█')
    EMPTY=$(printf "%$((BAR_LENGTH - FILLED))s" | tr ' ' '░')

    # Calculate seeding rate
    if [[ $PREV_COUNT -gt 0 && $VECTOR_COUNT -gt $PREV_COUNT ]]; then
      RATE=$(( (VECTOR_COUNT - PREV_COUNT) / WAIT_INTERVAL ))
      RATE_STR="${RATE} vectors/sec"
      STABLE_COUNT=0  # Reset stability counter when still growing
    elif [[ $PREV_COUNT -gt 0 ]]; then
      RATE_STR="stable"
      STABLE_COUNT=$((STABLE_COUNT + 1))
    else
      RATE_STR="calculating..."
      STABLE_COUNT=0
    fi

    # Clear line and show progress
    printf "\r   [${BAR}${EMPTY}] ${PROGRESS}%% | ${VECTOR_COUNT} vectors | ${RATE_STR} | ${ELAPSED}s elapsed"

    PREV_COUNT=$VECTOR_COUNT

    # Check if seeding is complete:
    # 1. Must have minimum number of vectors (avoid false positives)
    # 2. Must be stable for STABLE_CHECKS_NEEDED consecutive checks
    if [[ $VECTOR_COUNT -ge $MIN_STABLE_VECTORS ]] && [[ $STABLE_COUNT -ge $STABLE_CHECKS_NEEDED ]]; then
      echo
      echo "   ✅ Seeding complete! Collection has ${VECTOR_COUNT} vectors (stable for ${STABLE_COUNT}x${WAIT_INTERVAL}s)"
      break
    fi

    sleep $WAIT_INTERVAL
  else
    # Still waiting for first vectors
    printf "\r   ⏳ Waiting for seeding to start... ${ELAPSED}s elapsed (attempt $i/$((MAX_WAIT/WAIT_INTERVAL)))"
    sleep $WAIT_INTERVAL
  fi
done

# Ensure newline after progress bar
echo

# Final check
FINAL_INFO=$(curl -s "http://localhost:${QDRANT_PORT}/collections/${COLLECTION_NAME}" 2>/dev/null || echo "{}")
FINAL_COUNT=$(echo "$FINAL_INFO" | grep -o '"points_count":[0-9]*' | grep -o '[0-9]*' || echo "0")

if [[ "$FINAL_COUNT" -eq 0 ]]; then
  echo
  echo "   ⚠️  WARNING: Qdrant collection '${COLLECTION_NAME}' has no vectors after ${MAX_WAIT}s"
  echo "      The RAG system may not work properly!"
  echo "      Check backend logs: docker-compose logs backend"
  echo
  read -p "   Continue anyway? (y/N): " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "   Exiting. Please check logs and try again."
    exit 1
  fi
else
  echo "   ✅ Ready to use! Collection has ${FINAL_COUNT} vectors"
fi

# ===========================
# Step 6: Smart RAG bandit warm-up (requires backend to be up)
# ===========================
echo
echo_hr
echo "🎯 Smart RAG Bandit Warm-up"
echo_hr

# Check if warm-up is needed
if [[ -f "cache/smart_bandit_state.json" ]] || [[ -f "config/default_bandit_state.json" ]]; then
  echo "   ✅ Bandit weights found - skipping warm-up"
  echo "      Using existing state file"
elif ! command -v python3 >/dev/null 2>&1; then
  echo "   ⚠️  python3 not found, skipping warm-up"
  echo "      Install Python 3 to enable bandit warm-up"
elif [[ ! -f ".venv/bin/activate" ]]; then
  echo "   ⚠️  .venv not found, skipping warm-up"
  echo "      Create virtual environment with: python3 -m venv .venv && .venv/bin/pip install requests"
else
  # Run warm-up with progress display
  echo "   Starting bandit warm-up (3 rounds of testing)..."
  echo "   This optimizes RAG strategy selection for better accuracy"
  echo

  (
    source .venv/bin/activate
    python scripts/warm_smart_bandit.py --backend "http://localhost:${BACKEND_PORT}" --rounds 3
  ) &

  WARMUP_PID=$!

  # Show progress while warm-up runs
  WARMUP_START=$(date +%s)
  SPIN_CHARS="⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

  while kill -0 $WARMUP_PID 2>/dev/null; do
    WARMUP_ELAPSED=$(($(date +%s) - WARMUP_START))
    for ((i=0; i<${#SPIN_CHARS}; i++)); do
      printf "\r   ${SPIN_CHARS:$i:1} Warming up bandit... ${WARMUP_ELAPSED}s elapsed"
      sleep 0.1
    done
  done

  wait $WARMUP_PID
  WARMUP_EXIT=$?

  echo
  if [[ $WARMUP_EXIT -eq 0 ]]; then
    echo "   ✅ Warm-up complete! Bandit weights saved to cache/"
  else
    echo "   ⚠️  Warm-up failed (check backend health/logs)"
  fi
fi

# ===========================
# Step 7: Summary
# ===========================
echo
echo_hr
echo "✅ AI Assessment Platform Started!"
echo_hr
echo
echo "Core Services:"
echo "   Frontend (Streamlit):    http://localhost:${FRONTEND_PORT}"
echo "   Backend API:             http://localhost:${BACKEND_PORT}"
echo "   API Docs (Swagger):      http://localhost:${BACKEND_PORT}/docs"
echo "   Qdrant Dashboard:        http://localhost:${QDRANT_PORT}/dashboard"
echo
echo "AI Inference:"
echo "   Inference Service:       http://localhost:${INFERENCE_PORT}"
echo "   Inference Health:        http://localhost:${INFERENCE_PORT}/health"
echo
echo "Monitoring & Observability:"
echo "   Prometheus:              http://localhost:${PROMETHEUS_PORT}"
echo "   Prometheus Targets:      http://localhost:${PROMETHEUS_PORT}/targets"
echo "   Prometheus Alerts:       http://localhost:${PROMETHEUS_PORT}/alerts"
echo "   Grafana Dashboards:      http://localhost:${GRAFANA_PORT} (admin/admin)"
echo "   Jaeger Tracing UI:       http://localhost:${JAEGER_PORT}"
echo
echo "Commands:"
if command -v docker-compose >/dev/null 2>&1; then
  echo "   Logs:      docker-compose logs -f"
  echo "   Stop:      docker-compose down"
  echo "   Restart:   docker-compose restart"
  echo "   Status:    docker-compose ps"
else
  echo "   Logs:      docker compose logs -f"
  echo "   Stop:      docker compose down"
  echo "   Restart:   docker compose restart"
  echo "   Status:    docker compose ps"
fi
echo

# ===========================
# Step 8: Open UI
# ===========================
FRONTEND_URL="http://localhost:${FRONTEND_PORT}"
GRAFANA_URL="http://localhost:${GRAFANA_PORT}/d/system-overview/ai-louie-system-overview?orgId=1&refresh=30s"

echo "Opening frontend: $FRONTEND_URL"
open_url "$FRONTEND_URL"
sleep 1

echo "Opening Grafana: $GRAFANA_URL"
open_url "$GRAFANA_URL"

echo
echo "Ready! If the browser didn't open, visit:"
echo "   Frontend: $FRONTEND_URL"
echo "   Grafana:  $GRAFANA_URL"
echo_hr

# ===========================
# Step 9: Auto-shutdown monitoring
# ===========================
# Cleanup function - runs docker-compose down when script exits
cleanup() {
  echo
  echo_hr
  echo "🛑 Shutting down AI-Louie platform..."
  echo_hr

  # Stop all containers gracefully
  if command -v docker-compose >/dev/null 2>&1; then
    docker-compose down
  else
    docker compose down
  fi

  echo "✅ All services stopped successfully"
  echo_hr
}

# Register cleanup function to run on script termination
# Triggers on: Ctrl+C (SIGINT), kill command (SIGTERM), or normal exit
trap cleanup EXIT INT TERM

echo
echo "💡 Press Ctrl+C to stop all services and exit"
echo

# Monitor frontend container - exit if it stops
echo "Monitoring frontend container..."
FRONTEND_CONTAINER="streamlit-ui"

while true; do
  # Check if frontend container is still running
  if ! docker ps --format '{{.Names}}' | grep -q "^${FRONTEND_CONTAINER}$"; then
    echo
    echo "⚠️  Frontend container stopped - triggering shutdown..."
    exit 0
  fi

  sleep 5
done

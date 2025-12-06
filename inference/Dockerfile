FROM python:3.10-slim

WORKDIR /app

ENV PYTHONPATH=/app:/app/backend/services
ENV ORT_NO_EXE_STACK_CHECK=1

# Install minimal OS dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgomp1 \
    patchelf \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
# Install core ONNX dependencies first (without deps to avoid conflicts)
# CRITICAL: numpy<2.0 required for onnxruntime compatibility
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir "numpy>=1.24.0,<2.0" && \
    pip install --no-cache-dir protobuf==3.20.3 && \
    pip install --no-cache-dir --no-deps onnxruntime==1.16.3 onnx==1.15.0 && \
    pip install --no-cache-dir \
    fastapi==0.104.1 \
    uvicorn==0.24.0 \
    pydantic==2.5.0 \
    pydantic-settings==2.1.0 \
    httpx==0.25.2 \
    python-dotenv==1.0.0 \
    structlog==23.2.0 \
    prometheus-client==0.19.0 \
    aiofiles==23.2.1 \
    tenacity==8.2.3 \
    transformers==4.35.2 \
    sentencepiece==0.1.99

# Copy only the ONNX inference files (not main.py to avoid Prometheus metric conflicts)
COPY backend/backend/services/inference/__init__.py /app/inference_service/__init__.py
COPY backend/backend/services/inference/config.py /app/inference_service/config.py
COPY backend/backend/services/inference/main_onnx.py /app/inference_service/main_onnx.py

# Ensure the models directory exists (host volume will mount here)
RUN mkdir -p /app/models

# Clear executable stack requirement for onnxruntime shared library
RUN patchelf --clear-execstack \
    /usr/local/lib/python3.10/site-packages/onnxruntime/capi/onnxruntime_pybind11_state.cpython-310-x86_64-linux-gnu.so

EXPOSE 8001

# Health check endpoint for the inference service
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Launch the ONNX inference API
CMD ["python", "-m", "inference_service.main_onnx"]

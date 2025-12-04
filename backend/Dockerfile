FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    libomp5 \
    patchelf \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
# Split into batches to avoid timeout
RUN pip install --no-cache-dir --upgrade pip &&  \
    pip install --no-cache-dir \
    pydantic==2.5.0 pydantic-settings==2.2.1 &&  \
    pip install --no-cache-dir \
    fastapi==0.104.1 uvicorn==0.24.0 && \
    pip install --no-cache-dir \
    openai==1.3.0 httpx==0.25.2 azure-identity==1.15.0 && \
    pip install --no-cache-dir \
    sqlalchemy==2.0.23 alembic==1.12.1 && \
    pip install --no-cache-dir \
    qdrant-client==1.15.1 onnxruntime==1.16.3 onnx==1.15.0 && \
    pip install --no-cache-dir \
    langchain==0.1.0 pypdf==3.17.1 huggingface-hub==0.16.4 transformers==4.35.0 sentencepiece==0.1.99 rank-bm25==0.2.2 scikit-learn==1.3.2 networkx==3.2.1 && \
    pip install --no-cache-dir \
    python-multipart==0.0.6 python-docx==1.1.0 beautifulsoup4==4.12.2 markdownify==0.11.6 openpyxl==3.1.2 && \
    pip install --no-cache-dir \
    aiofiles==23.2.1 python-dotenv==1.0.0 tenacity==8.2.3 numpy>=1.24.0 tiktoken==0.12.0 && \
    pip install --no-cache-dir \
    prometheus-client==0.19.0 structlog==23.2.0 && \
    pip install --no-cache-dir \
    opentelemetry-api==1.22.0 opentelemetry-sdk==1.22.0 \
    opentelemetry-instrumentation-fastapi==0.43b0 opentelemetry-instrumentation-sqlalchemy==0.43b0 \
    opentelemetry-instrumentation-httpx==0.43b0 opentelemetry-exporter-otlp==1.22.0 \
    opentelemetry-exporter-prometheus==0.43b0 && \
    pip install --no-cache-dir evidently==0.4.15 ragas==0.1.4 datasets==2.16.1 && \
    pip install --no-cache-dir \
    sse-starlette==1.8.2 pytest==7.4.3 pytest-asyncio==0.21.1 pytest-cov==4.1.0 pytest-mock==3.12.0 && \
    pip install --no-cache-dir --force-reinstall --no-deps pydantic==2.5.0 pydantic-core==2.14.1 pydantic-settings==2.2.1 && \
    pip install --no-cache-dir --force-reinstall huggingface-hub==0.16.4

# Resolve executable stack requirement for onnxruntime shared library
RUN patchelf --clear-execstack \
    /usr/local/lib/python3.10/site-packages/onnxruntime/capi/onnxruntime_pybind11_state.cpython-310-x86_64-linux-gnu.so

# Copy application code - keep backend structure
COPY backend/ /app/backend/

# Expose port
EXPOSE 8888

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8888/health || exit 1

# Run the application
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8888"]

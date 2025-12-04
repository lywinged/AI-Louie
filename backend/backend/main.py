"""
AI Assessment Project - FastAPI Main Application

Enterprise-grade AI platform with:
- Task 3.1: Conversational Chat with streaming
- Task 3.2: High-Performance RAG QA
- Task 3.3: Autonomous Planning Agent
- Task 3.4: Self-Healing Code Assistant
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx

# Load environment variables first
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from backend.config.settings import settings
from backend.services.qdrant_seed import ensure_seed_collection
from backend.services.telemetry import init_telemetry, shutdown_telemetry, get_telemetry_config
from backend.services.smart_bandit_state import (
    set_enabled as set_bandit_enabled,
    mark_started as mark_bandit_started,
    mark_done as mark_bandit_done,
    mark_error as mark_bandit_error,
    mark_total as mark_bandit_total,
    increment_completed as increment_bandit_completed,
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application lifespan manager"""
    logger.info("🚀 Starting AI Assessment API...")
    logger.info(f"📊 Metrics enabled: {settings.ENABLE_METRICS}")
    logger.info(f"🔧 ONNX Inference: {settings.USE_ONNX_INFERENCE}")
    logger.info(f"📈 INT8 Quantization: {settings.USE_INT8_QUANTIZATION}")

    # Initialize OpenTelemetry
    telemetry = init_telemetry(
        service_name="ai-louie-backend",
        service_version="1.0.0",
        enable_tracing=settings.ENABLE_TELEMETRY if hasattr(settings, 'ENABLE_TELEMETRY') else True,
        enable_metrics=settings.ENABLE_METRICS,
    )

    # Instrument HTTPX for outbound requests
    if telemetry:
        telemetry.instrument_httpx()
        logger.info("🔍 OpenTelemetry tracing enabled")

    loop = asyncio.get_event_loop()

    def _bootstrap_seed():
        try:
            summary = ensure_seed_collection()
            logger.info("📚 Qdrant seed summary: %s", summary)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("⚠️  Qdrant seed bootstrap skipped: %s", exc)

    loop.run_in_executor(None, _bootstrap_seed)

    async def _warm_smart_rag():
        enabled = os.getenv("WARM_SMART_RAG", "1") != "0"
        set_bandit_enabled(enabled)
        if not enabled:
            return
        mark_bandit_started()
        base_url = f"http://localhost:{getattr(settings, 'BACKEND_PORT', 8888)}"
        # Warm up queries (reduced to 3 for faster startup):
        # - 1 hybrid: simple factual query
        # - 1 graph: relationship query (most time-consuming, 40-60s)
        # - 1 table: structured data query
        queries = [
            "Who wrote 'DADDY TAKE ME SKATING'?",  # hybrid (simple factual)
            "List the roles and relationships between the main characters in 'Pride and Prejudice'.",  # graph (relationships)
            "Show me a table of character ages and occupations.",  # table (structured data)
        ]
        mark_bandit_total(len(queries))
        # Increased timeout for graph RAG queries which can take 40-60s on first run
        async with httpx.AsyncClient(timeout=120.0) as client:
            for q in queries:
                try:
                    resp = await client.post(
                        f"{base_url}/api/rag/ask-smart",
                        json={"question": q, "top_k": 5, "include_timings": True},
                    )
                    logger.info("Warm smart RAG: %s (status=%s)", q[:80], resp.status_code)
                except Exception as warm_err:
                    logger.warning("Warm smart RAG failed: %s (query: %s)", warm_err, q[:50])
                    mark_bandit_error(str(warm_err))
                finally:
                    increment_bandit_completed()
                    await asyncio.sleep(1)
        mark_bandit_done()

    loop.create_task(_warm_smart_rag())

    yield

    logger.info("👋 Shutting down AI Assessment API...")

    # Shutdown telemetry
    shutdown_telemetry()


# Create FastAPI application
app = FastAPI(
    title="AI Assessment API",
    description="Enterprise-grade AI platform with Chat, RAG, Agent, and Code Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Instrument FastAPI with OpenTelemetry
telemetry_config = get_telemetry_config()
if telemetry_config:
    telemetry_config.instrument_fastapi(app)


# Health check endpoint
@app.get("/health", tags=["system"])
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "onnx_enabled": settings.USE_ONNX_INFERENCE,
        "int8_enabled": settings.USE_INT8_QUANTIZATION,
    }


@app.get("/", tags=["system"])
async def root():
    """Root endpoint with API info"""
    return {
        "name": "AI Assessment API",
        "version": "1.0.0",
        "endpoints": {
            "chat": "/api/chat",
            "rag": "/api/rag",
            "agent": "/api/agent",
            "code": "/api/code",
            "metrics": "/metrics",
        },
        "docs": "/docs",
    }


# Mount Prometheus metrics endpoint
if settings.ENABLE_METRICS:
    # Import all metrics to register them with Prometheus
    from backend.services import metrics  # noqa: F401
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)


# Import and register API routers from new structure
try:
    from backend.routers import chat_routes
    app.include_router(chat_routes.router, prefix="/api/chat", tags=["chat"])
    logger.info("✅ Chat API registered")
except ImportError as e:
    logger.warning(f"⚠️  Chat API not available: {e}")

try:
    from backend.routers import rag_routes
    app.include_router(rag_routes.router, prefix="/api/rag", tags=["rag"])
    logger.info("✅ RAG API registered")
except ImportError as e:
    logger.warning(f"⚠️  RAG API not available: {e}")

try:
    from backend.routers import agent_routes
    app.include_router(agent_routes.router, prefix="/api/agent", tags=["agent"])
    logger.info("✅ Agent API registered")
except ImportError as e:
    logger.warning(f"⚠️  Agent API not available: {e}")

try:
    from backend.routers import code_routes
    app.include_router(code_routes.router, prefix="/api/code", tags=["code"])
    logger.info("✅ Code API registered")
except ImportError as e:
    logger.warning(f"⚠️  Code API not available: {e}")

try:
    from backend.routers import monitoring_routes
    app.include_router(monitoring_routes.router, prefix="/api/monitoring", tags=["monitoring"])
    logger.info("✅ Monitoring API registered")
except ImportError as e:
    logger.warning(f"⚠️  Monitoring API not available: {e}")


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if settings.LOG_LEVEL == "DEBUG" else "An error occurred",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.LOG_LEVEL.lower(),
    )

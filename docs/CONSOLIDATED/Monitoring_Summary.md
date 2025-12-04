# Monitoring & Observability Summary

Consolidates: `MONITORING_SETUP.md` and related progress docs.

## Components
- Prometheus (/metrics), Grafana (3000), Jaeger (16686), OpenTelemetry auto-instrumentation (FastAPI/HTTPX/SQLAlchemy).
- Optional: Evidently (data quality), ragas (RAG evaluation).

## Endpoints
- Grafana: prebuilt LLM/RAG dashboards.
- Jaeger: tracing to inspect RAG/LLM latency.
- Health check: `/health`; blackbox probes configured under `monitoring/`.

## Metrics
- Tokens/cost, RAG latency, cache hit rate, retrieval counts.
- Data quality/drift via monitoring APIs.

## Tuning
- Adjust OTel/Prom settings in `.env`; add custom metrics in `backend/services/metrics.py` as needed.

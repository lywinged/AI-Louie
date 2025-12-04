# Quick Start

## Prerequisites
- Docker Desktop running
- At least 8 GB RAM and 10 GB free disk space

## One-Command Launch
```bash
./start.sh
```
or directly:
```bash
docker-compose up -d
```

## Verify Services
- Containers: backend, frontend (streamlit-ui), qdrant, inference-service, prometheus, grafana, jaeger
- Health checks:
  - `curl http://localhost:8888/health`
  - `curl http://localhost:6333`

## Access
| Service   | URL                                |
|-----------|------------------------------------|
| Frontend  | http://localhost:18501             |
| Backend   | http://localhost:8888              |
| API Docs  | http://localhost:8888/docs         |
| Qdrant UI | http://localhost:6333/dashboard    |
| Grafana   | http://localhost:3000 (admin/admin)|
| Prometheus| http://localhost:9090              |
| Jaeger    | http://localhost:16686             |
| Metrics   | http://localhost:8888/metrics      |

## Stop
- Stop containers, keep data:
```bash
docker-compose down
```
- Full clean (removes volumes):
```bash
docker-compose down -v
```

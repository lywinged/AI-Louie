"""
Tests for monitoring API routes.

Tests all monitoring endpoints including:
- LLM metrics
- Data quality monitoring
- RAG evaluation
- Health checks
"""

import pytest
from fastapi.testclient import TestClient


def test_monitoring_health(client: TestClient):
    """Test monitoring system health endpoint."""
    response = client.get("/api/monitoring/health")
    assert response.status_code == 200

    data = response.json()
    assert "status" in data
    assert "components" in data
    assert data["status"] in ["healthy", "degraded"]


def test_monitoring_config(client: TestClient):
    """Test monitoring configuration endpoint."""
    response = client.get("/api/monitoring/config")
    assert response.status_code == 200

    data = response.json()
    assert "features" in data
    assert "llm_metrics" in data["features"]
    assert "data_quality" in data["features"]
    assert "rag_evaluation" in data["features"]


def test_llm_summary(client: TestClient):
    """Test LLM metrics summary endpoint."""
    response = client.get("/api/monitoring/llm/summary")
    assert response.status_code == 200

    data = response.json()
    assert "total_calls" in data
    assert isinstance(data["total_calls"], int)


def test_llm_recent_calls(client: TestClient):
    """Test LLM recent calls endpoint."""
    response = client.get("/api/monitoring/llm/recent-calls?limit=5")
    assert response.status_code == 200

    data = response.json()
    assert "calls" in data
    assert "total" in data
    assert isinstance(data["calls"], list)


def test_llm_summary_with_filters(client: TestClient):
    """Test LLM summary with model and endpoint filters."""
    response = client.get(
        "/api/monitoring/llm/summary?model=gpt-4o-mini&endpoint=chat&time_window_minutes=60"
    )
    assert response.status_code == 200

    data = response.json()
    assert "total_calls" in data


def test_data_quality_summary(client: TestClient):
    """Test data quality summary endpoint."""
    response = client.get("/api/monitoring/data-quality/summary?interaction_type=chat")
    assert response.status_code == 200

    data = response.json()
    assert "total_interactions" in data


def test_data_quality_summary_all_types(client: TestClient):
    """Test data quality summary for all interaction types."""
    for interaction_type in ["chat", "rag", "agent", "code"]:
        response = client.get(
            f"/api/monitoring/data-quality/summary?interaction_type={interaction_type}"
        )
        assert response.status_code == 200

        data = response.json()
        assert "total_interactions" in data


def test_data_drift_report_insufficient_data(client: TestClient):
    """Test drift report with insufficient data."""
    response = client.post(
        "/api/monitoring/data-quality/drift-report",
        json={
            "interaction_type": "chat",
            "reference_window": 10000,  # Too large
            "current_window": 100,
        },
    )

    # Should return error or empty result
    assert response.status_code in [200, 400]


def test_rag_evaluation(client: TestClient):
    """Test RAG answer evaluation endpoint."""
    response = client.post(
        "/api/monitoring/rag/evaluate",
        json={
            "question": "What is machine learning?",
            "answer": "Machine learning is a subset of AI that enables systems to learn from data.",
            "contexts": [
                "Machine learning is a method of data analysis.",
                "AI systems can learn from experience.",
            ],
            "model": "gpt-4o-mini",
        },
    )

    assert response.status_code == 200

    data = response.json()
    assert "question" in data
    assert "answer" in data
    # Note: ragas may not be installed in test environment


def test_rag_evaluation_with_ground_truth(client: TestClient):
    """Test RAG evaluation with ground truth."""
    response = client.post(
        "/api/monitoring/rag/evaluate",
        json={
            "question": "What is AI?",
            "answer": "AI is artificial intelligence.",
            "contexts": ["AI is a field of computer science."],
            "ground_truth": "Artificial intelligence is the simulation of human intelligence.",
            "model": "gpt-4o-mini",
        },
    )

    assert response.status_code == 200


def test_rag_evaluation_summary(client: TestClient):
    """Test RAG evaluation summary endpoint."""
    response = client.get("/api/monitoring/rag/evaluation-summary")
    assert response.status_code == 200

    data = response.json()
    assert "num_evaluations" in data


def test_rag_evaluation_summary_with_filters(client: TestClient):
    """Test RAG evaluation summary with time window and model filters."""
    response = client.get(
        "/api/monitoring/rag/evaluation-summary?time_window_hours=24&model=gpt-4o-mini"
    )
    assert response.status_code == 200

    data = response.json()
    assert "num_evaluations" in data


def test_rag_recent_evaluations(client: TestClient):
    """Test RAG recent evaluations endpoint."""
    response = client.get("/api/monitoring/rag/recent-evaluations?limit=10")
    assert response.status_code == 200

    data = response.json()
    assert "evaluations" in data
    assert "total" in data
    assert isinstance(data["evaluations"], list)


def test_rag_recent_evaluations_with_model_filter(client: TestClient):
    """Test RAG recent evaluations with model filter."""
    response = client.get(
        "/api/monitoring/rag/recent-evaluations?limit=5&model=gpt-4o-mini"
    )
    assert response.status_code == 200

    data = response.json()
    assert "evaluations" in data


def test_invalid_interaction_type(client: TestClient):
    """Test data quality summary with invalid interaction type."""
    response = client.get(
        "/api/monitoring/data-quality/summary?interaction_type=invalid"
    )
    # Should still return 200 but with 0 interactions
    assert response.status_code == 200


def test_negative_limit(client: TestClient):
    """Test endpoints with negative limit parameter."""
    # This should be handled gracefully
    response = client.get("/api/monitoring/llm/recent-calls?limit=-1")
    assert response.status_code in [200, 422]  # Either success or validation error


def test_large_limit(client: TestClient):
    """Test endpoints with very large limit parameter."""
    response = client.get("/api/monitoring/llm/recent-calls?limit=10000")
    assert response.status_code == 200

    data = response.json()
    assert "calls" in data


def test_monitoring_endpoints_cors(client: TestClient):
    """Test that monitoring endpoints support CORS."""
    # OPTIONS request
    response = client.options("/api/monitoring/health")
    assert response.status_code in [200, 204, 405]  # Depends on FastAPI CORS setup


def test_llm_summary_response_structure(client: TestClient):
    """Test LLM summary response has expected structure."""
    response = client.get("/api/monitoring/llm/summary")
    assert response.status_code == 200

    data = response.json()
    expected_fields = [
        "total_calls",
        "success_rate",
        "total_tokens",
        "total_cost",
        "avg_duration",
    ]

    # At least some fields should be present
    assert any(field in data for field in expected_fields)


def test_data_quality_summary_response_structure(client: TestClient):
    """Test data quality summary response structure."""
    response = client.get("/api/monitoring/data-quality/summary?interaction_type=chat")
    assert response.status_code == 200

    data = response.json()
    assert "total_interactions" in data

    if data["total_interactions"] > 0:
        # If there are interactions, check for additional fields
        expected_fields = [
            "avg_query_length",
            "avg_response_length",
            "avg_total_tokens",
        ]
        assert any(field in data for field in expected_fields)


def test_concurrent_monitoring_requests(client: TestClient):
    """Test that monitoring endpoints handle concurrent requests."""
    import concurrent.futures

    def make_request():
        return client.get("/api/monitoring/llm/summary")

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(make_request) for _ in range(10)]
        results = [f.result() for f in futures]

    # All requests should succeed
    assert all(r.status_code == 200 for r in results)


def test_monitoring_endpoints_idempotency(client: TestClient):
    """Test that GET endpoints are idempotent."""
    response1 = client.get("/api/monitoring/llm/summary")
    response2 = client.get("/api/monitoring/llm/summary")

    assert response1.status_code == response2.status_code
    # Data should be consistent (may not be identical due to time-based queries)


def test_rag_evaluation_missing_fields(client: TestClient):
    """Test RAG evaluation with missing required fields."""
    response = client.post(
        "/api/monitoring/rag/evaluate",
        json={
            "question": "Test",
            # Missing answer and contexts
        },
    )

    assert response.status_code == 422  # Validation error


def test_rag_evaluation_empty_contexts(client: TestClient):
    """Test RAG evaluation with empty contexts list."""
    response = client.post(
        "/api/monitoring/rag/evaluate",
        json={
            "question": "What is AI?",
            "answer": "AI is artificial intelligence.",
            "contexts": [],  # Empty list
        },
    )

    # Should either fail validation or handle gracefully
    assert response.status_code in [200, 422]

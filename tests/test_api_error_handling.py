"""
Tests for API error handling and edge cases.

Focus on testing:
- Invalid request payloads
- Missing required fields
- Type mismatches
- HTTP error responses
- Boundary conditions
"""
import pytest
from fastapi.testclient import TestClient


# =============================================================================
# RAG Routes Error Tests
# =============================================================================

def test_rag_ask_missing_question(client):
    """Test /ask endpoint with missing question field."""
    response = client.post("/api/rag/ask", json={})

    assert response.status_code == 422  # Unprocessable Entity
    assert "detail" in response.json()


def test_rag_ask_null_question(client):
    """Test /ask endpoint with null question."""
    response = client.post("/api/rag/ask", json={"question": None})

    assert response.status_code == 422
    assert "detail" in response.json()


def test_rag_ask_wrong_type_question(client):
    """Test /ask endpoint with wrong type for question."""
    response = client.post("/api/rag/ask", json={"question": 12345})

    assert response.status_code == 422


def test_rag_ask_wrong_type_top_k(client):
    """Test /ask endpoint with wrong type for top_k."""
    response = client.post("/api/rag/ask", json={
        "question": "test",
        "top_k": "five"  # Should be int
    })

    assert response.status_code == 422


def test_rag_ask_negative_top_k(client):
    """Test /ask endpoint with negative top_k."""
    response = client.post("/api/rag/ask", json={
        "question": "test",
        "top_k": -5
    })

    # Should either reject or handle gracefully
    assert response.status_code in [200, 400, 422]


def test_rag_ask_excessively_large_top_k(client):
    """Test /ask endpoint with unreasonably large top_k."""
    response = client.post("/api/rag/ask", json={
        "question": "test",
        "top_k": 99999
    })

    # Should either cap or reject
    assert response.status_code in [200, 400, 422]


def test_rag_ask_malformed_json(client):
    """Test /ask endpoint with malformed JSON."""
    response = client.post(
        "/api/rag/ask",
        data="{invalid json}",
        headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422


def test_rag_ask_empty_body(client):
    """Test /ask endpoint with empty request body."""
    response = client.post("/api/rag/ask", json=None)

    assert response.status_code == 422


def test_rag_ask_extra_unexpected_fields(client):
    """Test /ask endpoint with unexpected extra fields."""
    response = client.post("/api/rag/ask", json={
        "question": "test",
        "top_k": 5,
        "unexpected_field": "should be ignored",
        "another_field": 123
    })

    # FastAPI with Pydantic should ignore extra fields by default
    assert response.status_code == 200


# =============================================================================
# Chat Routes Error Tests
# =============================================================================

def test_chat_missing_message(client, dummy_chat_service):
    """Test /chat endpoint with missing message field."""
    response = client.post("/api/chat", json={})

    assert response.status_code == 422


def test_chat_null_message(client, dummy_chat_service):
    """Test /chat endpoint with null message."""
    response = client.post("/api/chat", json={"message": None})

    assert response.status_code == 422


def test_chat_wrong_type_message(client, dummy_chat_service):
    """Test /chat endpoint with wrong type for message."""
    response = client.post("/api/chat", json={"message": 123})

    assert response.status_code == 422


def test_chat_wrong_type_stream(client, dummy_chat_service):
    """Test /chat endpoint with wrong type for stream parameter."""
    response = client.post("/api/chat", json={
        "message": "test",
        "stream": "yes"  # Should be boolean
    })

    assert response.status_code == 422


def test_chat_extremely_long_message(client, dummy_chat_service):
    """Test /chat endpoint with extremely long message."""
    long_message = "x" * 100000  # 100K characters

    response = client.post("/api/chat", json={"message": long_message})

    # Should either accept or reject gracefully
    assert response.status_code in [200, 400, 413]  # 413 = Payload Too Large


# =============================================================================
# Code Routes Error Tests
# =============================================================================

def test_code_generate_missing_prompt(client, dummy_code_assistant):
    """Test /generate endpoint with missing prompt."""
    response = client.post("/api/code/generate", json={})

    assert response.status_code == 422


def test_code_generate_null_prompt(client, dummy_code_assistant):
    """Test /generate endpoint with null prompt."""
    response = client.post("/api/code/generate", json={"prompt": None})

    assert response.status_code == 422


def test_code_generate_invalid_language(client, dummy_code_assistant):
    """Test /generate endpoint with invalid language."""
    response = client.post("/api/code/generate", json={
        "prompt": "write hello world",
        "language": "invalid_lang"
    })

    # Should reject invalid enum value
    assert response.status_code == 422


def test_code_generate_wrong_type_language(client, dummy_code_assistant):
    """Test /generate endpoint with wrong type for language."""
    response = client.post("/api/code/generate", json={
        "prompt": "test",
        "language": 123
    })

    assert response.status_code == 422


# =============================================================================
# Agent Routes Error Tests
# =============================================================================

def test_agent_plan_missing_description(client, dummy_planning_agent):
    """Test /plan endpoint with missing description."""
    response = client.post("/api/agent/plan", json={})

    assert response.status_code == 422


def test_agent_plan_null_description(client, dummy_planning_agent):
    """Test /plan endpoint with null description."""
    response = client.post("/api/agent/plan", json={"description": None})

    assert response.status_code == 422


def test_agent_plan_empty_description(client, dummy_planning_agent):
    """Test /plan endpoint with empty description."""
    response = client.post("/api/agent/plan", json={"description": ""})

    # Should either accept or reject
    assert response.status_code in [200, 400, 422]


def test_agent_plan_invalid_constraints_type(client, dummy_planning_agent):
    """Test /plan endpoint with wrong type for constraints."""
    response = client.post("/api/agent/plan", json={
        "description": "test",
        "constraints": "should be object"
    })

    assert response.status_code == 422


# =============================================================================
# Edge Cases with Special Characters
# =============================================================================

@pytest.mark.parametrize("special_input", [
    "<script>alert('xss')</script>",
    "'; DROP TABLE users; --",
    "../../../etc/passwd",
    "\x00\x01\x02",  # Null bytes
    "🚀💡🎯" * 100,  # Many emojis
])
def test_rag_ask_special_characters(client, special_input):
    """Test /ask endpoint with various special characters."""
    response = client.post("/api/rag/ask", json={
        "question": special_input,
        "top_k": 3
    })

    # Should handle gracefully without crashing
    assert response.status_code in [200, 400]


@pytest.mark.parametrize("unicode_input", [
    "你好世界",  # Chinese
    "مرحبا بالعالم",  # Arabic
    "Здравствуй мир",  # Russian
    "こんにちは世界",  # Japanese
    "안녕하세요 세계",  # Korean
])
def test_rag_ask_unicode_support(client, unicode_input):
    """Test /ask endpoint with various Unicode inputs."""
    response = client.post("/api/rag/ask", json={
        "question": unicode_input,
        "top_k": 3
    })

    assert response.status_code == 200
    data = response.json()
    assert "answer" in data


# =============================================================================
# HTTP Method Tests
# =============================================================================

def test_rag_ask_wrong_method_get(client):
    """Test /ask endpoint with GET instead of POST."""
    response = client.get("/api/rag/ask")

    assert response.status_code == 405  # Method Not Allowed


def test_rag_ask_wrong_method_put(client):
    """Test /ask endpoint with PUT instead of POST."""
    response = client.put("/api/rag/ask", json={"question": "test"})

    assert response.status_code == 405


def test_chat_wrong_method_delete(client):
    """Test /chat endpoint with DELETE instead of POST."""
    response = client.delete("/api/chat")

    assert response.status_code == 405


# =============================================================================
# Content-Type Tests
# =============================================================================

def test_rag_ask_wrong_content_type(client):
    """Test /ask endpoint with wrong Content-Type."""
    response = client.post(
        "/api/rag/ask",
        data="question=test&top_k=5",
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )

    # Should reject or fail to parse
    assert response.status_code in [422, 415]  # 415 = Unsupported Media Type


def test_rag_ask_missing_content_type(client):
    """Test /ask endpoint without Content-Type header."""
    response = client.post("/api/rag/ask", content=b'{"question": "test"}')

    # FastAPI should handle this gracefully
    assert response.status_code in [200, 422]


# =============================================================================
# Response Validation Tests
# =============================================================================

def test_rag_ask_response_has_required_fields(client):
    """Test that successful /ask response has all required fields."""
    response = client.post("/api/rag/ask", json={
        "question": "test question",
        "top_k": 5
    })

    assert response.status_code == 200
    data = response.json()

    # Verify required fields
    assert "answer" in data
    assert "citations" in data
    assert "num_chunks_retrieved" in data
    assert "latency_ms" in data


def test_chat_response_has_required_fields(client, dummy_chat_service):
    """Test that successful /chat response has all required fields."""
    response = client.post("/api/chat", json={"message": "hello"})

    assert response.status_code == 200
    data = response.json()

    assert "message" in data
    assert "latency_ms" in data


# =============================================================================
# Concurrent Request Simulation
# =============================================================================

def test_multiple_concurrent_rag_requests(client):
    """Test handling multiple RAG requests (simulated concurrency)."""
    responses = []

    for i in range(5):
        response = client.post("/api/rag/ask", json={
            "question": f"test question {i}",
            "top_k": 3
        })
        responses.append(response)

    # All should succeed
    assert all(r.status_code == 200 for r in responses)


def test_multiple_concurrent_chat_requests(client, dummy_chat_service):
    """Test handling multiple chat requests."""
    responses = []

    for i in range(5):
        response = client.post("/api/chat", json={"message": f"message {i}"})
        responses.append(response)

    # All should succeed
    assert all(r.status_code == 200 for r in responses)


# =============================================================================
# Rate Limiting / Resource Tests (if applicable)
# =============================================================================

def test_rag_ask_with_minimal_top_k(client):
    """Test with minimum valid top_k."""
    response = client.post("/api/rag/ask", json={
        "question": "test",
        "top_k": 1
    })

    assert response.status_code == 200
    data = response.json()
    assert data["num_chunks_retrieved"] >= 0


def test_rag_ask_with_maximum_top_k(client):
    """Test with maximum reasonable top_k."""
    response = client.post("/api/rag/ask", json={
        "question": "test",
        "top_k": 20  # Max allowed by config
    })

    assert response.status_code == 200
    data = response.json()
    assert data["num_chunks_retrieved"] <= 20

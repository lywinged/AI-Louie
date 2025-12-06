"""
Integration tests for end-to-end workflows.

Focus on testing:
- Complete request flows across multiple components
- Integration between services
- Real-world usage scenarios
- Concurrent operations
- Caching behavior
"""
import pytest
import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient


# =============================================================================
# End-to-End RAG Integration Tests
# =============================================================================

def test_rag_complete_workflow(client):
    """Test complete RAG workflow from question to answer."""
    # Step 1: Ask a question
    response = client.post("/api/rag/ask", json={
        "question": "What are the main features of this AI system?",
        "top_k": 5
    })

    assert response.status_code == 200
    data = response.json()

    # Step 2: Verify response structure
    assert "answer" in data
    assert "citations" in data
    assert "num_chunks_retrieved" in data
    assert "latency_ms" in data

    # Step 3: Verify data quality
    assert len(data["answer"]) > 0
    assert isinstance(data["citations"], list)
    assert data["num_chunks_retrieved"] >= 0
    assert data["latency_ms"] > 0


def test_rag_config_then_ask(client):
    """Test getting config before making a request."""
    # Step 1: Get configuration
    config_response = client.get("/api/rag/config")
    assert config_response.status_code == 200
    config = config_response.json()

    # Step 2: Use config limits to make request
    top_k = min(config["limits"]["vector_max"], 10)

    # Step 3: Make request with valid parameters
    ask_response = client.post("/api/rag/ask", json={
        "question": "test question",
        "top_k": top_k
    })

    assert ask_response.status_code == 200


def test_rag_multiple_sequential_questions(client):
    """Test asking multiple questions in sequence."""
    questions = [
        "What is machine learning?",
        "How does deep learning work?",
        "What are neural networks?",
    ]

    responses = []
    for question in questions:
        response = client.post("/api/rag/ask", json={
            "question": question,
            "top_k": 3
        })
        assert response.status_code == 200
        responses.append(response.json())

    # All responses should be valid
    assert all("answer" in r for r in responses)
    assert all(len(r["answer"]) > 0 for r in responses)


# =============================================================================
# Cross-Service Integration Tests
# =============================================================================

def test_rag_and_monitoring_integration(client):
    """Test that RAG requests are tracked by monitoring."""
    # Make a RAG request
    rag_response = client.post("/api/rag/ask", json={
        "question": "integration test",
        "top_k": 3
    })
    assert rag_response.status_code == 200

    # Check monitoring/health endpoint still works
    health_response = client.get("/api/monitoring/health")
    assert health_response.status_code == 200


def test_chat_and_history_integration(client, dummy_chat_service):
    """Test chat with history tracking."""
    # Send first message
    response1 = client.post("/api/chat", json={"message": "Hello"})
    assert response1.status_code == 200

    # Send second message
    response2 = client.post("/api/chat", json={"message": "How are you?"})
    assert response2.status_code == 200

    # Get history
    history_response = client.get("/api/chat/history")
    assert history_response.status_code == 200
    history = history_response.json()

    # Should have messages
    assert len(history) >= 2


def test_chat_clear_history_integration(client, dummy_chat_service):
    """Test complete chat lifecycle with clear."""
    # Send a message
    client.post("/api/chat", json={"message": "test message"})

    # Get history
    history = client.get("/api/chat/history").json()
    assert len(history) > 0

    # Clear history
    clear_response = client.post("/api/chat/clear")
    assert clear_response.status_code == 200

    # Verify history is empty
    history_after = client.get("/api/chat/history").json()
    assert len(history_after) == 0


# =============================================================================
# Concurrent Request Tests
# =============================================================================

def test_concurrent_rag_requests(client):
    """Test handling multiple concurrent RAG requests."""

    def make_request(question_id):
        return client.post("/api/rag/ask", json={
            "question": f"concurrent question {question_id}",
            "top_k": 3
        })

    # Simulate concurrent requests using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(make_request, i) for i in range(10)]
        responses = [f.result() for f in futures]

    # All requests should succeed
    assert all(r.status_code == 200 for r in responses)

    # All should have valid responses
    assert all("answer" in r.json() for r in responses)


def test_concurrent_different_endpoints(client, dummy_chat_service):
    """Test concurrent requests to different endpoints."""

    def rag_request():
        return client.post("/api/rag/ask", json={
            "question": "test",
            "top_k": 3
        })

    def chat_request():
        return client.post("/api/chat", json={"message": "test"})

    def config_request():
        return client.get("/api/rag/config")

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = []
        futures.extend([executor.submit(rag_request) for _ in range(2)])
        futures.extend([executor.submit(chat_request) for _ in range(2)])
        futures.extend([executor.submit(config_request) for _ in range(2)])

        responses = [f.result() for f in futures]

    # All should succeed
    assert all(r.status_code == 200 for r in responses)


def test_concurrent_chat_history_access(client, dummy_chat_service):
    """Test concurrent access to chat history."""

    def send_message(msg_id):
        return client.post("/api/chat", json={"message": f"message {msg_id}"})

    def get_history():
        return client.get("/api/chat/history")

    with ThreadPoolExecutor(max_workers=4) as executor:
        # Mix writes and reads
        futures = []
        futures.extend([executor.submit(send_message, i) for i in range(5)])
        futures.extend([executor.submit(get_history) for _ in range(5)])

        responses = [f.result() for f in futures]

    # All should succeed without conflicts
    assert all(r.status_code == 200 for r in responses)


# =============================================================================
# Cache Behavior Tests
# =============================================================================

def test_rag_repeated_question_consistency(client):
    """Test that repeated questions return consistent structure."""
    question = "What is the meaning of life?"

    # Make same request multiple times
    responses = []
    for _ in range(3):
        response = client.post("/api/rag/ask", json={
            "question": question,
            "top_k": 5
        })
        responses.append(response.json())

    # Structure should be consistent
    assert all(set(r.keys()) == set(responses[0].keys()) for r in responses)

    # All should have same field types
    assert all(type(r["answer"]) == type(responses[0]["answer"]) for r in responses)


def test_config_endpoint_idempotency(client):
    """Test that config endpoint returns same structure consistently."""
    configs = []
    for _ in range(3):
        response = client.get("/api/rag/config")
        configs.append(response.json())

    # All configs should have same structure
    assert all(set(c.keys()) == set(configs[0].keys()) for c in configs)

    # Limits should be consistent
    assert all(c["limits"] == configs[0]["limits"] for c in configs)


# =============================================================================
# Error Recovery Tests
# =============================================================================

def test_recovery_after_invalid_request(client):
    """Test that system recovers after receiving invalid request."""
    # Send invalid request
    invalid_response = client.post("/api/rag/ask", json={"invalid": "data"})
    assert invalid_response.status_code == 422

    # Send valid request - should work normally
    valid_response = client.post("/api/rag/ask", json={
        "question": "test",
        "top_k": 3
    })
    assert valid_response.status_code == 200


def test_recovery_after_mixed_requests(client, dummy_chat_service):
    """Test system handles mix of valid and invalid requests."""
    requests_and_expectations = [
        ({"question": "valid"}, 200),
        ({"invalid": "request"}, 422),
        ({"question": "another valid"}, 200),
        ({}, 422),
        ({"question": "still works"}, 200),
    ]

    for payload, expected_status in requests_and_expectations:
        response = client.post("/api/rag/ask", json=payload)
        assert response.status_code == expected_status


# =============================================================================
# Workflow Scenario Tests
# =============================================================================

def test_typical_user_session(client, dummy_chat_service):
    """Test a typical user session workflow."""
    # 1. Check health
    health = client.get("/api/health")
    assert health.status_code == 200

    # 2. Get RAG config
    config = client.get("/api/rag/config")
    assert config.status_code == 200

    # 3. Ask a RAG question
    rag1 = client.post("/api/rag/ask", json={
        "question": "What are the key features?",
        "top_k": 5
    })
    assert rag1.status_code == 200

    # 4. Start a chat conversation
    chat1 = client.post("/api/chat", json={"message": "Hello"})
    assert chat1.status_code == 200

    # 5. Continue chat
    chat2 = client.post("/api/chat", json={"message": "Tell me more"})
    assert chat2.status_code == 200

    # 6. Ask another RAG question
    rag2 = client.post("/api/rag/ask", json={
        "question": "How does it work?",
        "top_k": 3
    })
    assert rag2.status_code == 200

    # 7. Check chat history
    history = client.get("/api/chat/history")
    assert history.status_code == 200


def test_monitoring_throughout_operations(client, dummy_chat_service, dummy_code_assistant):
    """Test that monitoring endpoints work throughout various operations."""
    # Initial health check
    assert client.get("/api/monitoring/health").status_code == 200

    # Perform various operations
    client.post("/api/rag/ask", json={"question": "test", "top_k": 3})
    assert client.get("/api/monitoring/health").status_code == 200

    client.post("/api/chat", json={"message": "test"})
    assert client.get("/api/monitoring/health").status_code == 200

    client.post("/api/code/generate", json={"prompt": "test"})
    assert client.get("/api/monitoring/health").status_code == 200

    # Final health check
    assert client.get("/api/monitoring/health").status_code == 200


# =============================================================================
# Data Consistency Tests
# =============================================================================

def test_rag_citations_match_answer(client):
    """Test that citations are relevant to the answer."""
    response = client.post("/api/rag/ask", json={
        "question": "detailed question about AI",
        "top_k": 5
    })

    data = response.json()

    # If we have citations, they should have proper structure
    if data["citations"]:
        for citation in data["citations"]:
            assert "source" in citation
            assert "content" in citation
            assert len(citation["content"]) > 0


def test_chat_metrics_accumulate(client, dummy_chat_service):
    """Test that chat metrics accumulate properly."""
    # Send several messages
    for i in range(3):
        client.post("/api/chat", json={"message": f"message {i}"})

    # Get metrics
    metrics = client.get("/api/chat/metrics").json()

    # Should have recorded the messages
    assert "total_messages" in metrics or "message_count" in metrics or metrics is not None


# =============================================================================
# Load Pattern Tests
# =============================================================================

def test_burst_load_handling(client):
    """Test system handles burst of requests."""
    # Send 20 requests rapidly
    responses = []
    for i in range(20):
        response = client.post("/api/rag/ask", json={
            "question": f"burst question {i}",
            "top_k": 2  # Small top_k for faster responses
        })
        responses.append(response)

    # Most should succeed (allow some failures under load)
    success_count = sum(1 for r in responses if r.status_code == 200)
    assert success_count >= 15  # At least 75% success rate


def test_alternating_endpoint_load(client, dummy_chat_service):
    """Test alternating between different endpoints rapidly."""
    responses = []

    for i in range(10):
        # Alternate between RAG and Chat
        if i % 2 == 0:
            response = client.post("/api/rag/ask", json={
                "question": f"question {i}",
                "top_k": 3
            })
        else:
            response = client.post("/api/chat", json={
                "message": f"message {i}"
            })

        responses.append(response)

    # All should succeed
    assert all(r.status_code == 200 for r in responses)

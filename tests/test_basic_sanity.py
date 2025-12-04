"""
Basic sanity tests that should always pass.
Tests core imports and basic functionality.
"""
import pytest


def test_imports_work():
    """Test that all core modules can be imported."""
    try:
        from backend.models import code_schemas, rag_schemas
        from backend.services import metrics
        assert True
    except ImportError as e:
        pytest.fail(f"Import failed: {e}")


def test_code_schemas_exist():
    """Test that code schemas are properly defined."""
    from backend.models.code_schemas import CodeResponse, CodeRequest, Language

    # Test that we can import the schemas
    assert CodeResponse is not None
    assert CodeRequest is not None

    # Test that Language enum has expected values
    assert Language.PYTHON == "python"
    assert Language.JAVASCRIPT == "javascript"


def test_governance_criteria_count():
    """Test that we have exactly 12 governance criteria."""
    try:
        from backend.services.governance_tracker import GovernanceCriteria
        criteria_count = len(GovernanceCriteria)
        assert criteria_count == 12, f"Expected 12 criteria, got {criteria_count}"
    except ImportError:
        pytest.skip("Governance tracker not available")


def test_basic_math():
    """Sanity check that pytest is working."""
    assert 1 + 1 == 2
    assert 2 * 3 == 6


def test_string_operations():
    """Test basic string operations."""
    test_str = "AI-Louie"
    assert "AI" in test_str
    assert test_str.lower() == "ai-louie"


@pytest.mark.parametrize("input,expected", [
    (0, 0),
    (1, 1),
    (2, 4),
    (3, 9),
])
def test_parametrized_square(input, expected):
    """Test parametrized fixture."""
    assert input ** 2 == expected


class TestBasicClass:
    """Test class-based tests work."""

    def test_class_method(self):
        """Test method in class."""
        assert True

    def test_another_method(self):
        """Another test method."""
        value = 42
        assert value == 42


def test_list_operations():
    """Test list operations."""
    test_list = [1, 2, 3, 4, 5]
    assert len(test_list) == 5
    assert sum(test_list) == 15
    assert max(test_list) == 5


def test_dict_operations():
    """Test dictionary operations."""
    test_dict = {"name": "AI-Louie", "version": "1.0", "active": True}
    assert test_dict["name"] == "AI-Louie"
    assert test_dict.get("version") == "1.0"
    assert test_dict["active"] is True


@pytest.fixture
def sample_data():
    """Sample fixture."""
    return {"test": "data", "count": 10}


def test_with_fixture(sample_data):
    """Test using fixture."""
    assert sample_data["test"] == "data"
    assert sample_data["count"] == 10

import pytest
from domain.state_machine import is_valid_transition, require_valid_transition, InvalidStateTransitionError

def test_valid_transitions():
    assert is_valid_transition("pending", "running") is True
    assert is_valid_transition("running", "completed") is True
    assert is_valid_transition("running", "failed") is True
    assert is_valid_transition("failed", "pending") is True
    assert is_valid_transition("awaiting_approval", "running") is True

def test_invalid_transitions():
    assert is_valid_transition("pending", "completed") is False
    assert is_valid_transition("completed", "running") is False
    assert is_valid_transition("failed", "completed") is False

def test_require_valid_transition():
    require_valid_transition("pending", "running")
    with pytest.raises(InvalidStateTransitionError):
        require_valid_transition("pending", "completed")

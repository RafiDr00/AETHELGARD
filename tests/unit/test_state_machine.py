"""Unit tests for domain/state_machine.py."""
import pytest

from domain.job import JobStatus
from domain.state_machine import (
    ALLOWED_TRANSITIONS,
    InvalidStateTransitionError,
    is_valid_transition,
    require_valid_transition,
)


def _enum_values() -> set[str]:
    return {s.value for s in JobStatus}


# ---------------------------------------------------------------------------
# Structural consistency: ALLOWED_TRANSITIONS ↔ JobStatus enum
# ---------------------------------------------------------------------------

def test_all_source_states_are_valid_enum_values():
    """Every key in ALLOWED_TRANSITIONS must correspond to a real JobStatus."""
    enum_values = _enum_values()
    for state in ALLOWED_TRANSITIONS:
        assert state in enum_values, (
            f"ALLOWED_TRANSITIONS source {state!r} has no matching JobStatus value"
        )


def test_all_target_states_are_valid_enum_values():
    """Every reachable target state in ALLOWED_TRANSITIONS must correspond to a real JobStatus."""
    enum_values = _enum_values()
    for source, targets in ALLOWED_TRANSITIONS.items():
        for target in targets:
            assert target in enum_values, (
                f"Transition {source!r} → {target!r}: target has no matching JobStatus value"
            )


def test_all_enum_values_have_a_transition_entry():
    """Every JobStatus value must appear as a source key in ALLOWED_TRANSITIONS."""
    for status in JobStatus:
        assert status.value in ALLOWED_TRANSITIONS, (
            f"JobStatus.{status.name} ({status.value!r}) is missing from ALLOWED_TRANSITIONS"
        )


# ---------------------------------------------------------------------------
# Transition logic
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("current,next_state", [
    ("pending", "running"),
    ("pending", "failed"),
    ("running", "completed"),
    ("running", "failed"),
    ("running", "awaiting_approval"),
    ("awaiting_approval", "running"),
    ("awaiting_approval", "failed"),
    ("failed", "pending"),
])
def test_valid_transitions_accepted(current, next_state):
    assert is_valid_transition(current, next_state) is True


@pytest.mark.parametrize("current,next_state", [
    ("completed", "running"),
    ("completed", "failed"),
    ("completed", "pending"),
    ("failed", "running"),
    ("failed", "completed"),
    ("pending", "completed"),
])
def test_invalid_transitions_rejected(current, next_state):
    assert is_valid_transition(current, next_state) is False


def test_require_valid_transition_raises_on_invalid():
    with pytest.raises(InvalidStateTransitionError, match="'completed'.*'running'"):
        require_valid_transition("completed", "running")


def test_require_valid_transition_passes_on_valid():
    require_valid_transition("pending", "running")  # must not raise

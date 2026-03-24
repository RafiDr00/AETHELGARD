from typing import Dict, List

class InvalidStateTransitionError(Exception):
    pass

ALLOWED_TRANSITIONS: Dict[str, List[str]] = {
    "pending": ["running", "failed"],
    "running": ["awaiting_approval", "completed", "failed"],
    "awaiting_approval": ["running", "failed"],
    "completed": [],
    "failed": ["pending", "retrying"], # pending for retry after restart/etc
    "retrying": ["running", "failed"]
}

def is_valid_transition(current_state: str, next_state: str) -> bool:
    """Validate if a transition from current_state to next_state is allowed."""
    return next_state in ALLOWED_TRANSITIONS.get(current_state, [])

def require_valid_transition(current_state: str, next_state: str) -> None:
    if not is_valid_transition(current_state, next_state):
        raise InvalidStateTransitionError(
            f"Invalid transition from '{current_state}' to '{next_state}'"
        )

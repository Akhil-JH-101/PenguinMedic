"""Deterministic retry policy for Agent 4.

A failed verification may trigger one fresh diagnostic and recovery cycle
in sandbox or explicitly selected live-recovery mode. The module contains no
model calls.
"""


def route_after_verification(state: dict) -> str:
    result = state.get("recovery_verification_result", {})
    if (
        isinstance(result, dict)
        and result.get("status") in {"success", "resolved"}
        and result.get("issue_resolved") is True
    ):
        return "stop"
    retry_mode_enabled = (
        state.get("sandbox_test_mode") is True
        or state.get("live_recovery_mode") is True
    )
    if not retry_mode_enabled:
        return "stop"
    attempts = state.get("recovery_attempt", 0)
    if type(attempts) is int and 0 <= attempts < 2:
        return "retry"
    return "stop"


def build_retry_reset_update() -> dict:
    """Clear stale evidence and permissions, preserving attempt count/history."""
    return {
        "diagnostic_request": {},
        "diagnostic_results": {},
        "diagnostic_report": {},
        "sanitized_report": {},
        "additional_diagnostic_results": {},
        "additional_diagnostic_errors": [],
        "requested_diagnostics": [],
        "executed_diagnostics": [],
        "investigation_round": 0,
        "sanitized_additional_results": {},
        "investigation_report": {},
        "recovery_plan": {},
        "validation_result": {},
        "human_approved": False,
        "authorized_steps": [],
        "execution_results": [],
        "clarification_questions": [],
        "user_clarification": "",
        "clarification_round": 0,
        "approval_id": "",
        "recovery_verification_result": {},
        "pending_live_verification": False,
        "errors": [],
    }

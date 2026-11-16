
from typing import TypedDict, Any


class PenguinMedicState(TypedDict, total=False):

    # Original user problem
    user_problem: str

    # Agent 1's initial diagnostic decisions
    diagnostic_request: dict

    # Results returned by Python diagnostic tools
    diagnostic_results: dict[str, Any]

    # Agent 1's final evidence-based report
    diagnostic_report: dict

    sanitized_report: dict

    # Additional diagnostic investigation
    additional_diagnostic_results: dict[str, Any]

    additional_diagnostic_errors: list[str]

    requested_diagnostics: list[str]

    executed_diagnostics: list[str]

    investigation_round: int

    sanitized_additional_results: dict[str, Any]

    # Agent 2
    investigation_report: dict

    # Agent 3
    recovery_plan: dict

    # Agent 4: validation and approval
    validation_result: dict

    human_approved: bool

    authorized_steps: list[dict]

    # Agent 4: command execution results
    execution_results: list[dict]

    # Human clarification loop
    clarification_questions: list[str]
    user_clarification: str
    clarification_round: int

    approval_id: str

    sandbox_test_mode: bool
    sandbox_scenario: str
    live_diagnostic_mode: bool
    live_recovery_mode: bool
    pending_live_verification: bool

    # Workflow errors
    errors: list[str]


    # Agent 4: independent post-recovery verification
    recovery_verification_result: dict


    # Agent 4: bounded recovery retry tracking
    recovery_attempt: int
    recovery_verification_history: list[dict]

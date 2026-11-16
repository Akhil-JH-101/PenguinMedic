from langgraph.types import interrupt

from tools.command_executor import generate_approval_id


def approval_node(state):
    validation = state.get("validation_result", {})

    approved_steps = validation.get("approved_steps", [])
    rejected_steps = validation.get("rejected_steps", [])
    recovery_plan = state.get("recovery_plan", {})

    # Never request approval for an invalid or empty plan.
    if not validation.get("execution_allowed") or len(approved_steps) != 1:
        return {
            "human_approved": False,
            "authorized_steps": [],
            "approval_id": "",
            "errors": [
                "Approval blocked: no single valid recovery operation was supplied."
            ],
        }

    # Fingerprint the exact validated step list. The executor recomputes it.
    approval_attempt = state.get("recovery_attempt", 0) + 1
    approval_id = generate_approval_id(
        approved_steps, attempt_number=approval_attempt
    )

    live_mode = state.get("live_recovery_mode", False)
    decision = interrupt({
        "message": (
            "PenguinMedic is requesting approval to execute one command on the live system."
            if live_mode
            else "PenguinMedic is requesting approval for one sandbox recovery operation."
        ),
        "approval_id": approval_id,
        "attempt_number": approval_attempt,
        "approved_steps": approved_steps,
        "rejected_steps": rejected_steps,
        "recovery_plan": {
            "problem_summary": recovery_plan.get("problem_summary", ""),
            "proposed_solution": recovery_plan.get("proposed_solution", ""),
            "plan_summary": recovery_plan.get("plan_summary", ""),
            "overall_risk": recovery_plan.get("overall_risk", ""),
            "prerequisites": recovery_plan.get("prerequisites", []),
            "warnings": recovery_plan.get("warnings", []),
        },
        "warning": (
            "LIVE SYSTEM: Approving executes the exact shell command shown above "
            "on this machine using the current user's permissions. If the command "
            "contains sudo, sudo will request authentication. Review every token; "
            "the command may modify or delete system data. A changed command or "
            "retry requires a new approval."
            if live_mode
            else "Approving executes exactly one validated operation inside the controlled sandbox."
        ),
    })

    # Approval is bound to the exact validated operation fingerprint.
    human_approved = (
        isinstance(decision, dict)
        and decision.get("approved") is True
        and decision.get("approval_id") == approval_id
    )

    authorized_steps = approved_steps if human_approved else []

    return {
        "human_approved": human_approved,
        "authorized_steps": authorized_steps,
        "approval_id": approval_id if human_approved else "",
    }

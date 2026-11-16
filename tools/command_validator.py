"""
Deterministic safety gate for PenguinMedic.

This registry contains recovery operations only. Read-only diagnostics
belong exclusively to the diagnostic tool registry.

Recovery plans use all-or-nothing validation: one malformed or unsupported
step blocks the complete plan. The current controlled demo intentionally
supports exactly one mutating recovery step per plan.
"""

# Exact fixed shell recovery command supported by the controlled demo.
ALLOWED_COMMANDS = {
    (
        "cp --remove-destination -- "
        "sandbox/fixtures/config_test/expected_app_config.json "
        "sandbox/fixtures/config_test/app_config.json"
    ): [
        "cp",
        "--remove-destination",
        "--",
        "sandbox/fixtures/config_test/expected_app_config.json",
        "sandbox/fixtures/config_test/app_config.json",
    ],
}

# Fixed operations implemented in trusted Python modules.
ALLOWED_OPERATIONS = {
    "restore_penguinmedic_test_file",
}

PLAN_FIELDS = {
    "decision",
    "decision_reason",
    "problem_summary",
    "evidence_basis",
    "missing_information",
    "questions_for_user",
    "proposed_solution",
    "prerequisites",
    "recovery_steps",
    "overall_risk",
    "warnings",
    "approval_required",
    "plan_summary",
}

STEP_FIELDS = {
    "step_number",
    "action",
    "command",
    "explanation",
    "risk_level",
    "requires_sudo",
    "expected_result",
    "rollback_notes",
}

ALLOWED_RISKS = {"low", "medium", "high"}


def _is_nonempty_string(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_string_list(value, field_name: str) -> str | None:
    if not isinstance(value, list):
        return f"{field_name} must be a list of strings."
    if any(not isinstance(item, str) for item in value):
        return f"{field_name} must contain only strings."
    return None


def validate_command(command: str) -> dict:
    """Validate an exact registered mutating recovery command."""

    if not isinstance(command, str) or not command.strip():
        return {
            "approved": False,
            "reason": "Empty or invalid command.",
        }

    # Recovery commands must match the registry byte-for-byte. Do not trim
    # or normalize user/model-provided command strings.
    if command not in ALLOWED_COMMANDS:
        return {
            "approved": False,
            "reason": "Command is not an exact match for the recovery-operation allowlist.",
        }

    return {
        "approved": True,
        "reason": "Command is explicitly registered for sandbox recovery.",
        "argv": ALLOWED_COMMANDS[command].copy(),
    }


def validate_recovery_plan(plan: dict, live_mode: bool = False) -> dict:
    """
    Validate the complete Agent 3 plan and every recovery step.

    Sandbox mode accepts only the existing registered fixture operations.
    Live mode accepts one exact shell command supplied by Agent 3. That command
    is not executed here: it is fingerprinted, shown verbatim to the user, and
    can run only after an explicit approval interrupt is resumed.
    """

    blocked_result = {
        "approved_steps": [],
        "rejected_steps": [],
        "execution_allowed": False,
    }

    if not isinstance(plan, dict):
        return {
            **blocked_result,
            "reason": "Recovery plan must be a dictionary.",
        }

    missing_plan_fields = PLAN_FIELDS - set(plan)
    extra_plan_fields = set(plan) - PLAN_FIELDS
    if missing_plan_fields or extra_plan_fields:
        details = []
        if missing_plan_fields:
            details.append("missing fields: " + ", ".join(sorted(str(field) for field in missing_plan_fields)))
        if extra_plan_fields:
            details.append("unexpected fields: " + ", ".join(sorted(str(field) for field in extra_plan_fields)))
        return {
            **blocked_result,
            "reason": "Recovery plan schema rejected (" + "; ".join(details) + ").",
        }

    if plan["decision"] != "RECOVERY_PLAN_READY":
        return {
            **blocked_result,
            "reason": "No recovery plan is ready.",
        }

    for field_name in (
        "decision_reason",
        "problem_summary",
        "proposed_solution",
        "plan_summary",
    ):
        if not _is_nonempty_string(plan[field_name]):
            return {
                **blocked_result,
                "reason": f"{field_name} must be a non-empty string.",
            }

    for field_name in (
        "evidence_basis",
        "missing_information",
        "questions_for_user",
        "prerequisites",
        "recovery_steps",
        "warnings",
    ):
        if not isinstance(plan[field_name], list):
            return {
                **blocked_result,
                "reason": f"{field_name} must be a list.",
            }

    for field_name in (
        "evidence_basis",
        "missing_information",
        "questions_for_user",
        "prerequisites",
        "warnings",
    ):
        error = _validate_string_list(plan[field_name], field_name)
        if error:
            return {**blocked_result, "reason": error}

    if not plan["evidence_basis"]:
        return {
            **blocked_result,
            "reason": "A recovery-ready plan must cite supporting evidence.",
        }

    if plan["approval_required"] is not True:
        return {
            **blocked_result,
            "reason": "Explicit human approval is required.",
        }

    if not isinstance(plan["overall_risk"], str) or plan["overall_risk"] not in ALLOWED_RISKS:
        return {
            **blocked_result,
            "reason": "overall_risk must be low, medium, or high.",
        }

    recovery_steps = plan["recovery_steps"]
    if not recovery_steps:
        return {
            **blocked_result,
            "reason": "Recovery plan must contain a non-empty list of steps.",
        }

    # Until multi-step rollback/compensation exists, permit one mutation only.
    if len(recovery_steps) != 1:
        return {
            **blocked_result,
            "reason": (
                "The current controlled recovery capability permits exactly "
                "one mutating step per plan."
            ),
        }

    step = recovery_steps[0]
    if not isinstance(step, dict):
        return {
            **blocked_result,
            "rejected_steps": [{
                "step_number": 1,
                "reason": "Recovery step must be a dictionary.",
            }],
            "reason": "Recovery plan rejected: malformed recovery step.",
        }

    missing_step_fields = STEP_FIELDS - set(step)
    extra_step_fields = set(step) - STEP_FIELDS
    if missing_step_fields or extra_step_fields:
        details = []
        if missing_step_fields:
            details.append("missing fields: " + ", ".join(sorted(str(field) for field in missing_step_fields)))
        if extra_step_fields:
            details.append("unexpected fields: " + ", ".join(sorted(str(field) for field in extra_step_fields)))
        return {
            **blocked_result,
            "rejected_steps": [{
                "step_number": 1,
                "reason": "Recovery step schema rejected (" + "; ".join(details) + ").",
            }],
            "reason": "Recovery plan rejected: incomplete or unexpected step fields.",
        }

    if type(step["step_number"]) is not int or step["step_number"] != 1:
        return {
            **blocked_result,
            "rejected_steps": [{
                "step_number": step["step_number"],
                "reason": "The single supported recovery step must have step_number 1.",
            }],
            "reason": "Recovery plan rejected: invalid step numbering.",
        }

    for field_name in (
        "action",
        "command",
        "explanation",
        "expected_result",
        "rollback_notes",
    ):
        if not _is_nonempty_string(step[field_name]):
            return {
                **blocked_result,
                "rejected_steps": [{
                    "step_number": 1,
                    "reason": f"{field_name} must be a non-empty string.",
                }],
                "reason": f"Recovery plan rejected: invalid {field_name}.",
            }

    if not isinstance(step["risk_level"], str) or step["risk_level"] not in ALLOWED_RISKS:
        return {
            **blocked_result,
            "rejected_steps": [{
                "step_number": 1,
                "reason": "risk_level must be low, medium, or high.",
            }],
            "reason": "Recovery plan rejected: invalid step risk level.",
        }

    risk_rank = {"low": 1, "medium": 2, "high": 3}
    if risk_rank[plan["overall_risk"]] < risk_rank[step["risk_level"]]:
        return {
            **blocked_result,
            "rejected_steps": [{
                "step_number": 1,
                "reason": "Overall plan risk cannot be lower than the step risk.",
            }],
            "reason": "Recovery plan rejected: overall risk understates step risk.",
        }

    if type(step["requires_sudo"]) is not bool:
        return {
            **blocked_result,
            "rejected_steps": [{
                "step_number": 1,
                "reason": "requires_sudo must be a boolean.",
            }],
            "reason": "Recovery plan rejected: invalid privilege declaration.",
        }

    command = step["command"]

    if live_mode:
        # Live mode deliberately allows Agent 3 to propose an unfamiliar shell
        # command. The exact command is displayed and approval-fingerprinted;
        # this validator never executes or rewrites it.
        if not isinstance(command, str) or not command.strip():
            return {
                **blocked_result,
                "rejected_steps": [{
                    "step_number": 1,
                    "reason": "Live shell command must be a non-empty string.",
                }],
                "reason": "Recovery plan rejected: empty live command.",
            }
        if len(command) > 12000 or "\x00" in command:
            return {
                **blocked_result,
                "rejected_steps": [{
                    "step_number": 1,
                    "reason": "Command exceeds the supported length or contains a NUL byte.",
                }],
                "reason": "Recovery plan rejected: invalid live command encoding or length.",
            }

        approved_step = dict(step)
        approved_step.update({
            "execution_mode": "live_shell",
            "reason": (
                "Live shell command accepted for exact human review. "
                "No execution has occurred."
            ),
        })
        return {
            "approved_steps": [approved_step],
            "rejected_steps": [],
            "execution_allowed": True,
            "reason": (
                "The live recovery plan passed structural validation. "
                "The exact command still requires explicit human approval."
            ),
        }

    if step["requires_sudo"]:
        return {
            **blocked_result,
            "rejected_steps": [{
                "step_number": 1,
                "reason": "Privileged execution is not permitted in sandbox mode.",
            }],
            "reason": "Recovery plan rejected: privileged execution is not permitted in sandbox mode.",
        }
    if command in ALLOWED_OPERATIONS:
        approved_step = dict(step)
        approved_step.update({
            "operation_id": command,
            "reason": "Predefined sandbox recovery operation approved.",
        })
    else:
        command_result = validate_command(command)
        if not command_result["approved"]:
            return {
                **blocked_result,
                "rejected_steps": [{
                    **step,
                    "reason": command_result["reason"],
                }],
                "reason": (
                    "Recovery plan rejected: operation is not registered. "
                    "No steps are authorized."
                ),
            }

        approved_step = dict(step)
        approved_step.update({
            "argv": command_result["argv"],
            "reason": command_result["reason"],
        })

    return {
        "approved_steps": [approved_step],
        "rejected_steps": [],
        "execution_allowed": True,
        "reason": (
            "The complete plan and its single sandbox recovery operation "
            "passed deterministic validation. Human approval is still required."
        ),
    }

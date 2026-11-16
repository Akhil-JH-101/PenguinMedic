"""
Controlled command executor for PenguinMedic.

Executes only one exact, human-approved, fingerprint-verified sandbox
recovery operation. Diagnostic commands are never executable here.
"""

import hashlib
import json
import subprocess

from tools.command_validator import (
    ALLOWED_COMMANDS,
    ALLOWED_OPERATIONS,
)
from tools.sandbox_recovery import (
    PROJECT_ROOT,
    restore_penguinmedic_test_file,
    validate_config_shell_repair_preconditions,
    verify_config_shell_repair,
)


TIMEOUT_SECONDS = 15
MAX_OUTPUT_LENGTH = 5000

RECOVERY_OPERATIONS = {
    "restore_penguinmedic_test_file": restore_penguinmedic_test_file,
}

CONFIG_REPAIR_COMMAND = (
    "cp --remove-destination -- "
    "sandbox/fixtures/config_test/expected_app_config.json "
    "sandbox/fixtures/config_test/app_config.json"
)

REQUIRED_APPROVED_STEP_FIELDS = {
    "step_number",
    "action",
    "command",
    "explanation",
    "risk_level",
    "requires_sudo",
    "expected_result",
    "rollback_notes",
    "reason",
}


def generate_approval_id(
    steps: list[dict],
    attempt_number: int | None = None,
) -> str:
    """Fingerprint exact steps; workflow approvals are also bound to an attempt."""
    payload = (
        {"steps": steps, "attempt_number": attempt_number}
        if attempt_number is not None
        else steps
    )
    serialized = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _blocked(reason: str) -> list[dict]:
    return [{"status": "blocked", "reason": reason}]


def execute_authorized_steps(
    authorized_steps: list[dict],
    human_approved: bool,
    approval_id: str,
    attempt_number: int | None = None,
    sandbox_scenario: str = "",
) -> list[dict]:
    """Execute only one verified, human-approved sandbox recovery step."""

    if human_approved is not True:
        return _blocked("Human approval was not granted.")

    if not isinstance(authorized_steps, list) or len(authorized_steps) != 1:
        return _blocked(
            "Exactly one validated sandbox recovery step is required."
        )

    try:
        expected_approval_id = generate_approval_id(
            authorized_steps, attempt_number=attempt_number
        )
    except (TypeError, ValueError):
        return _blocked("Authorized recovery steps could not be fingerprinted.")
    if not isinstance(approval_id, str) or approval_id != expected_approval_id:
        return _blocked("Approval fingerprint verification failed.")

    step = authorized_steps[0]
    if not isinstance(step, dict):
        return _blocked("Authorized recovery step is malformed.")

    missing = REQUIRED_APPROVED_STEP_FIELDS - set(step)
    if missing:
        return _blocked(
            "Authorized recovery step is missing required fields: "
            + ", ".join(sorted(missing))
        )

    if type(step.get("step_number")) is not int or step["step_number"] != 1:
        return _blocked("Invalid recovery step number.")

    for field in (
        "action",
        "command",
        "explanation",
        "expected_result",
        "rollback_notes",
        "reason",
    ):
        if not isinstance(step.get(field), str) or not step[field].strip():
            return _blocked(f"Invalid or empty recovery step field: {field}.")

    if not isinstance(step.get("risk_level"), str) or step["risk_level"] not in {"low", "medium", "high"}:
        return _blocked("Invalid recovery risk level.")

    if type(step.get("requires_sudo")) is not bool or step["requires_sudo"]:
        return _blocked("Privileged execution is not permitted.")

    command = step["command"]
    operation_id = step.get("operation_id")

    # Predefined Python operation: exact identifier, no shell argv.
    if operation_id is not None:
        expected_fields = REQUIRED_APPROVED_STEP_FIELDS | {"operation_id"}
        if (
            set(step) != expected_fields
            or operation_id not in ALLOWED_OPERATIONS
            or not isinstance(operation_id, str)
            or operation_id not in RECOVERY_OPERATIONS
            or command != operation_id
        ):
            return _blocked("Recovery operation failed execution verification.")

        # Controlled presentation scenario: deliberately fail the first
        # approved attempt without touching the fixture. The existing retry
        # graph then gathers fresh evidence and requires a second approval.
        if (
            sandbox_scenario == "retry_demo"
            and attempt_number == 1
            and operation_id == "restore_penguinmedic_test_file"
        ):
            return [{
                "step_number": 1,
                "status": "failed",
                "operation": operation_id,
                "reason": (
                    "Simulated one-time sandbox failure: the first approved "
                    "attempt was intentionally not applied for the retry demonstration."
                ),
            }]

        try:
            operation_result = RECOVERY_OPERATIONS[operation_id]()
            result = {
                "step_number": 1,
                **operation_result,
            }
            if result.get("status") != "success":
                result.setdefault("status", "failed")
            return [result]
        except Exception as error:
            return [{
                "step_number": 1,
                "status": "failed",
                "reason": str(error),
            }]

    # Exact allowlisted shell recovery command.
    expected_fields = REQUIRED_APPROVED_STEP_FIELDS | {"argv"}
    if set(step) != expected_fields:
        return _blocked("Approved shell recovery step contains unexpected fields.")

    expected_argv = ALLOWED_COMMANDS.get(command)
    if expected_argv is None:
        return _blocked("Command is not in the recovery-operation allowlist.")

    if step.get("argv") != expected_argv:
        return _blocked("Command arguments failed verification.")

    if command != CONFIG_REPAIR_COMMAND:
        return _blocked("No execution handler is registered for this command.")

    preflight = validate_config_shell_repair_preconditions()
    if preflight.get("status") != "ready":
        return [{
            "step_number": 1,
            "command": command,
            "status": "blocked",
            "reason": preflight.get(
                "reason", "Configuration preflight failed."
            ),
        }]

    try:
        completed = subprocess.run(
            expected_argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
            cwd=str(PROJECT_ROOT),
        )

        result_entry = {
            "step_number": 1,
            "command": command,
            "status": "success" if completed.returncode == 0 else "failed",
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-MAX_OUTPUT_LENGTH:],
            "stderr": completed.stderr[-MAX_OUTPUT_LENGTH:],
        }

        if completed.returncode != 0:
            return [result_entry]

        verification = verify_config_shell_repair()
        if verification.get("status") != "success":
            result_entry["status"] = "failed"
            result_entry["reason"] = verification.get(
                "reason", "Post-repair verification failed."
            )
            return [result_entry]

        result_entry["verification"] = verification["verification"]
        result_entry["target"] = verification["target"]
        return [result_entry]

    except subprocess.TimeoutExpired:
        return [{
            "step_number": 1,
            "command": command,
            "status": "timeout",
            "reason": f"Command exceeded {TIMEOUT_SECONDS} seconds.",
        }]
    except FileNotFoundError:
        return [{
            "step_number": 1,
            "command": command,
            "status": "failed",
            "reason": "Required executable was not found.",
        }]
    except OSError as error:
        return [{
            "step_number": 1,
            "command": command,
            "status": "failed",
            "reason": str(error),
        }]

"""
Independent, deterministic verification of PenguinMedic sandbox recoveries.

These checks run after the executor and do not trust its success message.
Only fixed, registered sandbox scenarios are supported. No model-generated
commands, paths, or verification code are accepted.
"""

import json
from pathlib import Path

from tools.command_validator import ALLOWED_COMMANDS, ALLOWED_OPERATIONS
from tools.sandbox_recovery import (
    PROJECT_ROOT,
    SANDBOX_DIR,
    EXPECTED_FILE,
    TARGET_FILE,
    CONFIG_SANDBOX_DIR,
    EXPECTED_CONFIG_FILE,
    TARGET_CONFIG_FILE,
)

CONFIG_REPAIR_COMMAND = (
    "cp --remove-destination -- "
    "sandbox/fixtures/config_test/expected_app_config.json "
    "sandbox/fixtures/config_test/app_config.json"
)


def _regular_file(path: Path) -> bool:
    return not path.is_symlink() and path.is_file()


def _verify_missing_file() -> dict:
    if SANDBOX_DIR.is_symlink() or not SANDBOX_DIR.is_dir():
        return {"status": "failed", "reason": "Sandbox directory is missing or invalid."}
    if not _regular_file(EXPECTED_FILE):
        return {"status": "failed", "reason": "Reference file is missing or invalid."}
    if not _regular_file(TARGET_FILE):
        return {"status": "failed", "reason": "Recovered target file is missing or invalid."}

    expected = EXPECTED_FILE.read_bytes()
    actual = TARGET_FILE.read_bytes()
    if actual != expected:
        return {"status": "failed", "reason": "Recovered file content does not match the reference."}

    return {
        "status": "success",
        "issue_resolved": True,
        "verification": "The recovered file exists and matches the reference byte-for-byte.",
        "target": str(TARGET_FILE.relative_to(PROJECT_ROOT)),
    }


def _verify_broken_config() -> dict:
    if SANDBOX_DIR.is_symlink() or not SANDBOX_DIR.is_dir():
        return {"status": "failed", "reason": "Sandbox directory is missing or invalid."}
    if CONFIG_SANDBOX_DIR.is_symlink() or not CONFIG_SANDBOX_DIR.is_dir():
        return {"status": "failed", "reason": "Configuration sandbox directory is missing or invalid."}
    if not _regular_file(EXPECTED_CONFIG_FILE):
        return {"status": "failed", "reason": "Reference configuration is missing or invalid."}
    if not _regular_file(TARGET_CONFIG_FILE):
        return {"status": "failed", "reason": "Repaired configuration is missing or invalid."}

    try:
        expected_bytes = EXPECTED_CONFIG_FILE.read_bytes()
        actual_bytes = TARGET_CONFIG_FILE.read_bytes()
        expected_data = json.loads(expected_bytes)
        actual_data = json.loads(actual_bytes)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        return {"status": "failed", "reason": f"Configuration could not be read or parsed: {error}"}

    if not isinstance(expected_data, (dict, list)):
        return {"status": "failed", "reason": "Reference configuration is not a JSON object or array."}
    if actual_data != expected_data or actual_bytes != expected_bytes:
        return {"status": "failed", "reason": "Repaired configuration does not exactly match the valid reference."}

    return {
        "status": "success",
        "issue_resolved": True,
        "verification": "The repaired configuration is valid JSON and matches the reference exactly.",
        "target": str(TARGET_CONFIG_FILE.relative_to(PROJECT_ROOT)),
    }


# Keys are exact registered recovery identifiers, never model-provided callables.
VERIFICATION_REGISTRY = {
    "restore_penguinmedic_test_file": _verify_missing_file,
    CONFIG_REPAIR_COMMAND: _verify_broken_config,
}


def verify_recovery(authorized_steps: list[dict], execution_results: list[dict]) -> dict:
    """
    Independently inspect the fixed sandbox after one approved operation.

    A successful filesystem check is necessary but not sufficient: the
    executor must also report successful completion for this attempt.
    """
    if not isinstance(authorized_steps, list) or len(authorized_steps) != 1:
        return {
            "status": "blocked",
            "issue_resolved": False,
            "reason": "Verification requires exactly one approved recovery step.",
        }

    step = authorized_steps[0]
    if not isinstance(step, dict):
        return {
            "status": "blocked",
            "issue_resolved": False,
            "reason": "Approved recovery step is malformed.",
        }

    operation_id = step.get("operation_id")
    command = step.get("command")
    if operation_id is not None:
        if (
            not isinstance(operation_id, str)
            or operation_id not in ALLOWED_OPERATIONS
            or command != operation_id
        ):
            return {
                "status": "blocked",
                "issue_resolved": False,
                "reason": "Approved recovery operation identity is invalid.",
            }
        operation_key = operation_id
    else:
        if not isinstance(command, str) or command not in ALLOWED_COMMANDS:
            return {
                "status": "blocked",
                "issue_resolved": False,
                "reason": "Approved recovery command is not registered.",
            }
        operation_key = command

    verifier = VERIFICATION_REGISTRY.get(operation_key)
    if verifier is None:
        return {
            "status": "blocked",
            "issue_resolved": False,
            "reason": "No independent verifier is registered for this recovery operation.",
        }

    # Confirm the key still belongs to the deterministic recovery allowlist.
    if operation_key not in ALLOWED_OPERATIONS and operation_key not in ALLOWED_COMMANDS:
        return {
            "status": "blocked",
            "issue_resolved": False,
            "reason": "Recovery operation is not registered.",
        }

    independent_result = verifier()

    if not isinstance(execution_results, list) or len(execution_results) != 1:
        return {
            **independent_result,
            "status": "failed",
            "issue_resolved": False,
            "reason": "Executor did not return exactly one result for the approved operation.",
            "independent_check": independent_result,
        }

    execution_result = execution_results[0]
    if not isinstance(execution_result, dict) or execution_result.get("status") != "success":
        return {
            **independent_result,
            "status": "failed",
            "issue_resolved": False,
            "reason": "Executor did not report successful completion.",
            "independent_check": independent_result,
        }

    if independent_result.get("status") != "success":
        return {
            **independent_result,
            "issue_resolved": False,
            "independent_check": independent_result,
        }

    return {
        **independent_result,
        "status": "success",
        "issue_resolved": True,
        "independent_check": independent_result,
        "executor_status": "success",
        "message": "Recovery execution completed and the independent issue-specific verification passed.",
    }

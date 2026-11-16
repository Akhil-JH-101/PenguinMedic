"""
PenguinMedic controlled sandbox scenarios and recovery operations.

All fixture preparation and recovery are restricted to fixed paths
inside sandbox/fixtures/. No user or system configuration paths
are accepted.
"""

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

SANDBOX_DIR = PROJECT_ROOT / "sandbox" / "fixtures"

EXPECTED_FILE = SANDBOX_DIR / "expected_content.txt"
TARGET_FILE = SANDBOX_DIR / "important_file.txt"

CONFIG_SANDBOX_DIR = SANDBOX_DIR / "config_test"
EXPECTED_CONFIG_FILE = CONFIG_SANDBOX_DIR / "expected_app_config.json"
TARGET_CONFIG_FILE = CONFIG_SANDBOX_DIR / "app_config.json"


def _validate_sandbox_directory() -> dict | None:
    if SANDBOX_DIR.is_symlink() or not SANDBOX_DIR.is_dir():
        return {
            "status": "blocked",
            "reason": "Sandbox directory is missing or invalid."
        }
    return None


def prepare_sandbox_scenario(scenario: str) -> dict:
    """
    Prepare a known test condition before the workflow starts.

    This intentionally resets only the selected fixed test fixture.
    It does not accept paths or content from an LLM.
    """

    directory_error = _validate_sandbox_directory()
    if directory_error:
        return directory_error

    if scenario in {"missing_file", "retry_demo"}:
        if EXPECTED_FILE.is_symlink() or not EXPECTED_FILE.is_file():
            return {
                "status": "blocked",
                "reason": "Expected content file is missing or invalid."
            }

        if TARGET_FILE.is_symlink():
            return {
                "status": "blocked",
                "reason": "Sandbox target is a symbolic link."
            }

        if TARGET_FILE.exists():
            if not TARGET_FILE.is_file():
                return {
                    "status": "blocked",
                    "reason": "Sandbox target exists but is not a regular file."
                }
            TARGET_FILE.unlink()

        return {
            "status": "success",
            "scenario": scenario,
            "message": "Missing-file test fixture is ready."
        }

    if scenario == "broken_config":
        if CONFIG_SANDBOX_DIR.is_symlink():
            return {
                "status": "blocked",
                "reason": "Configuration sandbox directory is a symbolic link."
            }

        if CONFIG_SANDBOX_DIR.exists() and not CONFIG_SANDBOX_DIR.is_dir():
            return {
                "status": "blocked",
                "reason": "Configuration sandbox path is not a directory."
            }

        CONFIG_SANDBOX_DIR.mkdir(exist_ok=True)

        if EXPECTED_CONFIG_FILE.is_symlink() or TARGET_CONFIG_FILE.is_symlink():
            return {
                "status": "blocked",
                "reason": "A configuration fixture is a symbolic link."
            }

        if EXPECTED_CONFIG_FILE.exists() and not EXPECTED_CONFIG_FILE.is_file():
            return {
                "status": "blocked",
                "reason": "Expected configuration path is not a regular file."
            }

        if TARGET_CONFIG_FILE.exists() and not TARGET_CONFIG_FILE.is_file():
            return {
                "status": "blocked",
                "reason": "Target configuration path is not a regular file."
            }

        expected_content = (
            '{\n'
            '  "service": "penguinmedic",\n'
            '  "port": 8080,\n'
            '  "enabled": true\n'
            '}\n'
        ).encode("utf-8")

        # Deliberately malformed: the final closing brace is missing.
        broken_content = (
            '{\n'
            '  "service": "penguinmedic",\n'
            '  "port": 8080,\n'
            '  "enabled": true\n'
        ).encode("utf-8")

        EXPECTED_CONFIG_FILE.write_bytes(expected_content)
        TARGET_CONFIG_FILE.write_bytes(broken_content)

        return {
            "status": "success",
            "scenario": scenario,
            "message": "Broken-configuration test fixture is ready."
        }

    if scenario == "cannot_proceed_demo":
        # This branch uses synthetic contradictory evidence only. It does not
        # create, delete, or modify any fixture or real system file.
        return {
            "status": "success",
            "scenario": scenario,
            "message": "Conflicting-evidence sandbox decision test is ready. No files were modified.",
        }

    return {
        "status": "blocked",
        "reason": f"Unknown sandbox scenario: {scenario}"
    }


def restore_penguinmedic_test_file() -> dict:
    """Restore the fixed test file if it is missing."""

    try:
        directory_error = _validate_sandbox_directory()
        if directory_error:
            return directory_error

        if EXPECTED_FILE.is_symlink() or not EXPECTED_FILE.is_file():
            return {
                "status": "blocked",
                "reason": "Expected content file is missing or invalid."
            }

        if TARGET_FILE.exists() or TARGET_FILE.is_symlink():
            return {
                "status": "blocked",
                "reason": "Target file already exists. Refusing to overwrite."
            }

        expected_content = EXPECTED_FILE.read_bytes()

        with TARGET_FILE.open("xb") as file:
            file.write(expected_content)

        actual_content = TARGET_FILE.read_bytes()

        if actual_content != expected_content:
            TARGET_FILE.unlink(missing_ok=True)
            return {
                "status": "failed",
                "reason": "Restored file failed content verification."
            }

        return {
            "status": "success",
            "operation": "restore_penguinmedic_test_file",
            "target": str(TARGET_FILE.relative_to(PROJECT_ROOT)),
            "verification": "Restored contents match expected contents."
        }

    except OSError as error:
        return {
            "status": "failed",
            "reason": str(error)
        }



def validate_config_shell_repair_preconditions() -> dict:
    """Validate the fixed sandbox paths before the allowlisted cp command."""

    try:
        directory_error = _validate_sandbox_directory()
        if directory_error:
            return directory_error

        if CONFIG_SANDBOX_DIR.is_symlink() or not CONFIG_SANDBOX_DIR.is_dir():
            return {
                "status": "blocked",
                "reason": "Configuration sandbox directory is missing or invalid.",
            }

        if EXPECTED_CONFIG_FILE.is_symlink() or not EXPECTED_CONFIG_FILE.is_file():
            return {
                "status": "blocked",
                "reason": "Expected configuration file is missing or invalid.",
            }

        if TARGET_CONFIG_FILE.is_symlink() or not TARGET_CONFIG_FILE.is_file():
            return {
                "status": "blocked",
                "reason": "Target configuration file is missing or invalid.",
            }

        expected_data = json.loads(EXPECTED_CONFIG_FILE.read_bytes())
        try:
            json.loads(TARGET_CONFIG_FILE.read_bytes())
            return {
                "status": "blocked",
                "reason": "Target configuration is already valid JSON. Refusing to overwrite.",
            }
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        if not isinstance(expected_data, (dict, list)):
            return {
                "status": "blocked",
                "reason": "Reference configuration must contain a JSON object or array.",
            }

        return {"status": "ready"}

    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        return {"status": "blocked", "reason": str(error)}


def verify_config_shell_repair() -> dict:
    """Verify the shell command repaired the fixed config from its reference."""

    try:
        directory_error = _validate_sandbox_directory()
        if directory_error:
            return directory_error

        if CONFIG_SANDBOX_DIR.is_symlink() or not CONFIG_SANDBOX_DIR.is_dir():
            return {
                "status": "failed",
                "reason": "Configuration sandbox directory became invalid.",
            }

        if EXPECTED_CONFIG_FILE.is_symlink() or not EXPECTED_CONFIG_FILE.is_file():
            return {
                "status": "failed",
                "reason": "Expected configuration file became invalid.",
            }

        if TARGET_CONFIG_FILE.is_symlink() or not TARGET_CONFIG_FILE.is_file():
            return {
                "status": "failed",
                "reason": "Repaired target is missing or is a symbolic link.",
            }

        expected_bytes = EXPECTED_CONFIG_FILE.read_bytes()
        repaired_bytes = TARGET_CONFIG_FILE.read_bytes()
        expected_data = json.loads(expected_bytes)
        repaired_data = json.loads(repaired_bytes)

        if repaired_bytes != expected_bytes or repaired_data != expected_data:
            return {
                "status": "failed",
                "reason": "Shell repair did not reproduce the exact reference configuration.",
            }

        return {
            "status": "success",
            "target": str(TARGET_CONFIG_FILE.relative_to(PROJECT_ROOT)),
            "verification": "Shell command restored valid JSON matching the reference file.",
        }

    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        return {"status": "failed", "reason": str(error)}

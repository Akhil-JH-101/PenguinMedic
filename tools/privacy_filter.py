
import ipaddress
import re


# Fields that Agent 2 is permitted to receive.
ALLOWED_REPORT_FIELDS = {
    "issue_category",
    "problem_summary",
    "confirmed_observations",
    "possible_explanations",
    "missing_information",
    "handoff_summary",
}


# Detect common sensitive information.
EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

IP_PATTERN = re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
)

MAC_PATTERN = re.compile(
    r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b"
)

HOME_PATH_PATTERN = re.compile(
    r"(?<!\w)/home/[^/\s]+"
)

SECRET_PATTERN = re.compile(
    r"""(?i)\b(password|passwd|token|api_key|api-key|secret|
    access_key|authorization)\b(\s*[:=]\s*)(["']?)[^\s,;}"']+\3"""
    .replace("\n", "")
)

BEARER_PATTERN = re.compile(
    r"(?i)\bBearer\s+\S+"
)

SERIAL_PATTERN = re.compile(
    r"(?i)\b(serial(?:\s+number)?|machine-id)\s*[:=]\s*[A-Za-z0-9-]+"
)


def redact_ip(match):
    value = match.group(0)

    try:
        ipaddress.ip_address(value)
        return "[REDACTED_IP]"
    except ValueError:
        return value


def sanitize_text(value: str) -> str:
    """Remove common sensitive information from diagnostic text."""

    value = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", value)

    value = IP_PATTERN.sub(redact_ip, value)

    value = MAC_PATTERN.sub("[REDACTED_MAC]", value)

    value = HOME_PATH_PATTERN.sub("/home/[USER]", value)

    value = BEARER_PATTERN.sub("Bearer [REDACTED]", value)

    value = SECRET_PATTERN.sub(
        lambda match: match.group(1) + match.group(2)
        + "[REDACTED]",
        value
    )

    value = SERIAL_PATTERN.sub(
        lambda match: match.group(1) + "=[REDACTED]",
        value
    )

    return value


def sanitize_value(value):
    """Recursively sanitize strings inside lists and dictionaries."""

    if isinstance(value, str):
        return sanitize_text(value)

    if isinstance(value, list):
        return [sanitize_value(item) for item in value]

    if isinstance(value, dict):
        return {
            key: sanitize_value(item)
            for key, item in value.items()
        }

    return value


def sanitize_diagnostic_report(report: dict) -> dict:
    """
    Create a minimized, sanitized report for cloud investigation.

    Unknown fields are excluded.
    Original report is not modified.
    """

    sanitized = {}

    for key in ALLOWED_REPORT_FIELDS:
        if key in report:
            sanitized[key] = sanitize_value(report[key])

    return sanitized


def sanitize_additional_results(results: dict) -> dict:
    """
    Sanitize additional diagnostic results before cloud transmission.
    Only explicitly approved fields are retained.
    """

    sanitized = {}

    for tool_name, result in results.items():

        if not isinstance(result, dict):
            continue

        if tool_name == "get_system_info":
            allowed_fields = {
                "distribution",
                "kernel",
                "architecture",
                "python_version",
                "root_disk_total_gb",
                "root_disk_free_gb",
                "root_disk_used_percent",
                "root_disk_check_success",
                "cpu",
                "cpu_usage",
                "load_average",
                "memory",
            }

        elif tool_name == "inspect_pacman_logs":
            allowed_fields = {
                "success",
                "log_exists",
                "entries_reviewed",
                "transaction_started_count",
                "transaction_completed_count",
                "transaction_interrupted_marker_count",
                "warning_count",
                "error_count",
                "package_event_count",
                "warning_entries",
                "error_entries",
                "interrupted_transaction_entries",
                "package_events",
                "relevant_entries",
                "transaction_health_interpretation",
                "error",
            }

        elif tool_name == "inspect_system_journal":
            allowed_fields = {
                "success", "recent_journal_success", "current_boot_success",
                "entries_reviewed", "relevant_entries",
                "recent_warning_count", "recent_error_count",
                "current_boot_entries_reviewed", "current_boot_relevant_entries",
                "current_boot_warning_count", "current_boot_error_count", "error"
            }

        elif tool_name == "inspect_failed_services":
            allowed_fields = {
                "success", "failed_service_count", "services",
                "services_truncated", "error"
            }

        elif tool_name == "inspect_systemd_unit":
            allowed_fields = {
                "success", "unit_name", "properties_success", "properties",
                "properties_error", "journal_success", "journal_entries",
                "journal_error", "journal_return_code", "command_file_checks",
                "error",
            }

        elif tool_name == "requested_file_inspection":
            allowed_fields = {
                "success", "path", "exists", "is_file", "is_symlink",
                "readable_by_current_process", "inspection", "error",
            }

        elif tool_name == "inspect_disk_usage":
            allowed_fields = {
                "success", "mountpoint", "total_gb", "used_gb",
                "free_gb", "used_percent", "error",
                "mount_inventory_success", "mounted_filesystem_count",
                "mounted_filesystems", "mount_inventory_error",
                "block_devices_success", "block_devices", "block_devices_error"
            }

        elif tool_name == "inspect_pacman_config":
            allowed_fields = {
                "success", "config_exists", "repositories", "options", "error"
            }

        elif tool_name == "inspect_mirror_status":
            allowed_fields = {
                "success", "mirrorlist_exists", "active_mirror_count",
                "unique_mirror_hosts_count", "duplicate_entries_count",
                "network_reachability_tested", "error"
            }

        elif tool_name == "inspect_package_database":

            sanitized[tool_name] = sanitize_value({
                "installed_packages": {
                    key: value
                    for key, value in result.get("installed_packages", {}).items()
                    if key in {"success", "package_count", "error"}
                },
                "orphan_check": {
                    key: value
                    for key, value in result.get("orphan_check", {}).items()
                    if key in {"success", "status", "orphan_count", "error"}
                },
                "database_check": {
                    key: value
                    for key, value in result.get("database_check", {}).items()
                    if key in {"success", "status", "output", "reported_problem_lines", "error"}
                },
                "package_cache": {
                    key: value
                    for key, value in result.get("package_cache", {}).items()
                    if key in {"success", "cache_exists", "archive_count", "total_size_gib", "error"}
                },
            })

            continue
        else:
            continue

        filtered_result = {
            key: value
            for key, value in result.items()
            if key in allowed_fields
        }

        sanitized[tool_name] = sanitize_value(filtered_result)

    return sanitized


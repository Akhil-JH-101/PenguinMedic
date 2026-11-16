
AVAILABLE_DIAGNOSTICS = {
    "get_system_info",
    "inspect_package_database",
    "inspect_pacman_logs",
    "inspect_system_journal",
    "inspect_failed_services",
    "inspect_disk_usage",
    "inspect_pacman_config",
    "inspect_mirror_status",
    "inspect_systemd_unit",
}


def validate_diagnostic_requests(requested):
    """
    Validate diagnostic tool requests from Agent 2.

    Returns accepted and rejected tool names.
    Does not execute anything.
    """

    if not isinstance(requested, list):
        raise TypeError("Diagnostic requests must be a list.")

    accepted = []
    rejected = []

    for tool_name in requested:

        if not isinstance(tool_name, str):
            rejected.append(str(tool_name))
            continue

        if tool_name not in AVAILABLE_DIAGNOSTICS:
            rejected.append(tool_name)
            continue

        if tool_name not in accepted:
            accepted.append(tool_name)

    return {
        "accepted": accepted,
        "rejected": rejected
    }


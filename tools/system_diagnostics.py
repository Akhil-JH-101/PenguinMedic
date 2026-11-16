"""Read-only system diagnostics for Arch Linux and systemd."""

import json
import os
import re
import shlex
import shutil

from tools.diagnostics import run_read_only_command


JOURNAL_KEYWORDS = (
    "error", "failed", "failure", "warning", "pacman",
    "network", "dependency", "timeout", "kernel", "systemd",
)


def _filter_relevant(lines: list[str], limit: int = 60) -> list[str]:
    return [
        line for line in lines
        if any(word in line.lower() for word in JOURNAL_KEYWORDS)
    ][-limit:]


def inspect_system_journal() -> dict:
    """Inspect recent and current-boot journal entries, emphasizing failures."""
    recent = run_read_only_command(
        ["journalctl", "--no-pager", "-n", "300", "-o", "short-iso"],
        timeout=15,
    )
    current_boot = run_read_only_command(
        ["journalctl", "--no-pager", "-b", "-n", "300", "-o", "short-iso"],
        timeout=15,
    )

    if not recent["success"] and not current_boot["success"]:
        return {
            "success": False,
            "recent_journal_success": False,
            "current_boot_success": False,
            "entries_reviewed": 0,
            "relevant_entries": [],
            "current_boot_entries_reviewed": 0,
            "current_boot_relevant_entries": [],
            "error": (
                recent["stderr"] or current_boot["stderr"]
                or "Unable to read system journal"
            ),
        }

    recent_lines = recent["stdout"].splitlines() if recent["success"] else []
    boot_lines = current_boot["stdout"].splitlines() if current_boot["success"] else []

    return {
        "success": recent["success"] or current_boot["success"],
        "recent_journal_success": recent["success"],
        "current_boot_success": current_boot["success"],
        "entries_reviewed": len(recent_lines),
        "relevant_entries": _filter_relevant(recent_lines, 60),
        "recent_warning_count": sum("warning" in line.lower() for line in recent_lines),
        "recent_error_count": sum(
            any(token in line.lower() for token in ("error", "failed", "failure"))
            for line in recent_lines
        ),
        "current_boot_entries_reviewed": len(boot_lines),
        "current_boot_relevant_entries": _filter_relevant(boot_lines, 60),
        "current_boot_warning_count": sum(
            "warning" in line.lower() for line in boot_lines
        ),
        "current_boot_error_count": sum(
            any(token in line.lower() for token in ("error", "failed", "failure"))
            for line in boot_lines
        ),
        "error": (
            recent["stderr"] if not recent["success"]
            else current_boot["stderr"] if not current_boot["success"]
            else ""
        ),
    }


def inspect_failed_services() -> dict:
    """List failed systemd service units, not every failed unit type."""
    result = run_read_only_command(
        ["systemctl", "--failed", "--no-legend", "--plain", "--type=service"],
        timeout=10,
    )

    if not result["success"]:
        return {
            "success": False,
            "failed_service_count": None,
            "services": [],
            "error": result["stderr"] or "Unable to inspect failed services",
        }

    services = []
    for line in result["stdout"].splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().endswith("loaded units listed."):
            continue
        services.append(stripped)

    return {
        "success": True,
        "failed_service_count": len(services),
        "services": services[:50],
        "services_truncated": len(services) > 50,
        "error": "",
    }


def _parse_findmnt_tree(node: dict, found: list[dict]):
    """Flatten findmnt's JSON tree into source/target/filesystem records."""
    record = {
        "source": node.get("source"),
        "mountpoint": node.get("target"),
        "filesystem": node.get("fstype"),
    }
    if record["mountpoint"]:
        found.append(record)
    for child in node.get("children", []) or []:
        _parse_findmnt_tree(child, found)


def inspect_disk_usage() -> dict:
    """Inspect root and real mounted filesystems plus block-device layout."""
    try:
        root_usage = shutil.disk_usage("/")
        root_total = root_usage.total
        root_used = root_total - root_usage.free
        root_result = {
            "success": True,
            "mountpoint": "/",
            "total_gb": round(root_total / (1024 ** 3), 2),
            "used_gb": round(root_used / (1024 ** 3), 2),
            "free_gb": round(root_usage.free / (1024 ** 3), 2),
            "used_percent": round((root_used / root_total) * 100, 1) if root_total else 0,
            "error": "",
        }
    except OSError as exc:
        root_result = {
            "success": False,
            "mountpoint": "/",
            "total_gb": None,
            "used_gb": None,
            "free_gb": None,
            "used_percent": None,
            "error": str(exc),
        }

    mount_result = run_read_only_command(
        ["findmnt", "--json", "--real", "--output", "SOURCE,TARGET,FSTYPE"],
        timeout=10,
    )
    mounted_filesystems = []
    mount_inventory_success = False
    mount_inventory_error = ""

    if mount_result["success"]:
        try:
            tree = json.loads(mount_result["stdout"])
            records = []
            for item in tree.get("filesystems", []):
                _parse_findmnt_tree(item, records)
            seen = set()
            for record in records:
                mountpoint = record["mountpoint"]
                if mountpoint in seen:
                    continue
                seen.add(mountpoint)
                try:
                    usage = shutil.disk_usage(mountpoint)
                    total = usage.total
                    used = total - usage.free
                    mounted_filesystems.append({
                        **record,
                        "total_gb": round(total / (1024 ** 3), 2),
                        "used_gb": round(used / (1024 ** 3), 2),
                        "free_gb": round(usage.free / (1024 ** 3), 2),
                        "used_percent": round((used / total) * 100, 1) if total else 0,
                    })
                except OSError as exc:
                    mounted_filesystems.append({
                        **record,
                        "usage_available": False,
                        "error": str(exc),
                    })
                if len(mounted_filesystems) >= 30:
                    break
            mount_inventory_success = True
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            mount_inventory_error = f"Could not parse findmnt output: {exc}"
    else:
        mount_inventory_error = mount_result["stderr"] or "findmnt command unavailable"

    block_result = run_read_only_command(
        [
            "lsblk", "--json", "--bytes",
            "--output", "NAME,PATH,TYPE,SIZE,FSTYPE,MOUNTPOINTS,RO,RM,MODEL",
        ],
        timeout=10,
    )
    block_devices = []
    block_devices_success = False
    block_devices_error = ""
    if block_result["success"]:
        try:
            block_data = json.loads(block_result["stdout"])
            block_devices = block_data.get("blockdevices", [])[:40]
            block_devices_success = True
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            block_devices_error = f"Could not parse lsblk output: {exc}"
    else:
        block_devices_error = block_result["stderr"] or "lsblk command unavailable"

    return {
        **root_result,
        "mount_inventory_success": mount_inventory_success,
        "mounted_filesystem_count": len(mounted_filesystems),
        "mounted_filesystems": mounted_filesystems,
        "mount_inventory_error": mount_inventory_error,
        "block_devices_success": block_devices_success,
        "block_devices": block_devices,
        "block_devices_error": block_devices_error,
    }


def _parse_systemd_show_properties(raw: str) -> dict:
    """Convert systemctl show's KEY=VALUE lines into a structured mapping."""
    parsed = {}
    for line in raw.splitlines():
        key, separator, value = line.partition("=")
        if separator and key:
            parsed[key] = value
    return parsed


def _inspect_cat_file_arguments(exec_start: str) -> list[dict]:
    """
    Read-only existence/readability checks for /tmp and /var/tmp file
    arguments passed to cat. Does not read file contents or follow symlinks.
    """
    match = re.search(r"argv\[\]=([^;}]+)", exec_start or "")
    if not match:
        return []

    try:
        argv = shlex.split(match.group(1).strip())
    except ValueError:
        return []

    if not argv or os.path.basename(argv[0]) != "cat":
        return []

    checks = []
    for candidate in argv[1:]:
        if candidate.startswith("-") or not os.path.isabs(candidate):
            continue
        normalized = os.path.normpath(candidate)
        if not (
            normalized.startswith("/tmp/")
            or normalized.startswith("/var/tmp/")
        ):
            continue

        record = {
            "path": normalized,
            "exists": False,
            "is_symlink": False,
            "is_regular_file": False,
            "readable": False,
            "error": "",
        }
        try:
            metadata = os.lstat(normalized)
            record["exists"] = True
            record["is_symlink"] = os.path.islink(normalized)
            record["is_regular_file"] = os.path.isfile(normalized)
            if not record["is_symlink"] and record["is_regular_file"]:
                try:
                    descriptor = os.open(
                        normalized,
                        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    )
                    os.close(descriptor)
                    record["readable"] = True
                except OSError as exc:
                    record["error"] = str(exc)
        except FileNotFoundError:
            record["error"] = "File does not exist."
        except OSError as exc:
            record["error"] = str(exc)

        checks.append(record)

    return checks


def inspect_systemd_unit(unit_name: str) -> dict:
    """Inspect a named systemd service's runtime properties and journal.

    Supports transient units created by systemd-run, which may not have a
    persistent unit file on disk. Uses fixed read-only commands and argv lists.
    """
    if (
        not isinstance(unit_name, str)
        or len(unit_name) > 255
        or not re.fullmatch(r"[A-Za-z0-9:_.@-]+\.service", unit_name)
    ):
        return {
            "success": False,
            "unit_name": "",
            "properties_success": False,
            "properties": {},
            "journal_success": False,
            "journal_entries": [],
            "command_file_checks": [],
            "error": "A valid systemd .service unit name was not supplied.",
        }

    property_names = (
        "Id,Description,LoadState,ActiveState,SubState,Result,Type,User,"
        "Group,WorkingDirectory,ExecStart,ExecMainCode,ExecMainStatus,"
        "ExecMainStartTimestamp,ExecMainExitTimestamp,FragmentPath,"
        "SourcePath,Transient,UnitFileState,After,Requires,Wants"
    )
    properties = run_read_only_command([
        "systemctl", "show", "--no-pager",
        f"--property={property_names}",
        unit_name,
    ], timeout=10)

    journal = run_read_only_command([
        "journalctl", "--no-pager", "--unit", unit_name,
        "--lines=100", "--output=short-iso",
    ], timeout=15)

    property_text = properties["stdout"] if properties["success"] else ""
    property_values = _parse_systemd_show_properties(property_text)
    journal_lines = journal["stdout"].splitlines() if journal["success"] else []
    command_file_checks = _inspect_cat_file_arguments(
        property_values.get("ExecStart", "")
    )

    return {
        "success": properties["success"] or journal["success"],
        "unit_name": unit_name,
        "properties_success": properties["success"],
        # Keep both structured properties and the original systemctl output.
        # Structured values survive downstream evidence compaction.
        "properties": property_values,
        "properties_raw": property_text[:10000],
        "properties_error": properties["stderr"] if not properties["success"] else "",
        "journal_success": journal["success"],
        "journal_entries": journal_lines[-100:],
        "journal_error": journal["stderr"] if not journal["success"] else "",
        "journal_return_code": journal["return_code"],
        "command_file_checks": command_file_checks,
        "error": "" if properties["success"] or journal["success"] else (
            "Unable to inspect unit properties or its journal."
        ),
    }


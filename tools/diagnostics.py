"""Read-only system and pacman diagnostics for PenguinMedic."""

import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path


PACMAN_LOG_PATH = Path("/var/log/pacman.log")
PACMAN_CACHE_PATH = Path("/var/cache/pacman/pkg")


def run_read_only_command(command: list[str], timeout: int = 10) -> dict:
    """Run a fixed, application-selected read-only diagnostic command.

    This helper must only be called with commands defined by PenguinMedic.
    It is not an interface for agent-generated shell commands.
    """
    if not command:
        return {
            "success": False,
            "stdout": "",
            "stderr": "No command was supplied",
            "return_code": -1,
        }

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout[:12000],
            "stderr": result.stderr[:3000],
            "return_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds",
            "return_code": -1,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Command not found: {command[0]}",
            "return_code": -1,
        }
    except PermissionError:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Permission denied while running: {command[0]}",
            "return_code": -1,
        }
    except OSError as exc:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Could not run {command[0]}: {exc}",
            "return_code": -1,
        }


def _read_meminfo(meminfo_path: Path = Path("/proc/meminfo")) -> dict:
    """Parse Linux memory counters from /proc/meminfo."""
    values_kb = {}
    try:
        for line in meminfo_path.read_text(errors="replace").splitlines():
            match = re.match(r"^([A-Za-z_()]+):\s+(\d+)\s+kB$", line)
            if match:
                values_kb[match.group(1)] = int(match.group(2))
    except OSError as exc:
        return {"success": False, "error": str(exc)}

    total = values_kb.get("MemTotal")
    available = values_kb.get("MemAvailable")
    if available is None and total is not None:
        available = (
            values_kb.get("MemFree", 0)
            + values_kb.get("Buffers", 0)
            + values_kb.get("Cached", 0)
        )

    swap_total = values_kb.get("SwapTotal")
    swap_free = values_kb.get("SwapFree")

    if total is None:
        return {
            "success": False,
            "error": "MemTotal was not present in /proc/meminfo",
        }

    used = max(total - (available or 0), 0)
    memory = {
        "success": True,
        "total_gib": round(total / (1024 ** 2), 2),
        "available_gib": round((available or 0) / (1024 ** 2), 2),
        "used_gib_estimate": round(used / (1024 ** 2), 2),
        "used_percent_estimate": round((used / total) * 100, 1) if total else None,
    }

    if swap_total is not None and swap_free is not None:
        swap_used = max(swap_total - swap_free, 0)
        memory["swap"] = {
            "total_gib": round(swap_total / (1024 ** 2), 2),
            "used_gib": round(swap_used / (1024 ** 2), 2),
            "free_gib": round(swap_free / (1024 ** 2), 2),
            "used_percent": (
                round((swap_used / swap_total) * 100, 1)
                if swap_total else 0.0
            ),
        }
    else:
        memory["swap"] = {
            "available": False,
            "reason": "Swap counters were not present in /proc/meminfo",
        }

    return memory


def _read_cpu_usage(stat_path: Path = Path("/proc/stat"), interval: float = 0.15) -> dict:
    """Estimate total CPU busy percentage from two /proc/stat samples."""
    def read_sample():
        first_line = stat_path.read_text(errors="replace").splitlines()[0]
        parts = first_line.split()
        if not parts or parts[0] != "cpu" or len(parts) < 5:
            raise ValueError("Aggregate CPU counters were not available")
        counters = [int(value) for value in parts[1:]]
        idle = counters[3] + (counters[4] if len(counters) > 4 else 0)
        total = sum(counters[:8])
        return total, idle

    try:
        total_before, idle_before = read_sample()
        time.sleep(interval)
        total_after, idle_after = read_sample()
        total_delta = total_after - total_before
        idle_delta = idle_after - idle_before
        if total_delta <= 0:
            return {
                "success": False,
                "error": "CPU counters did not advance during the sample",
            }
        busy_percent = (1 - (idle_delta / total_delta)) * 100
        return {
            "success": True,
            "busy_percent": round(max(0.0, min(100.0, busy_percent)), 1),
            "sample_interval_seconds": interval,
            "method": "Two-sample aggregate /proc/stat estimate",
        }
    except (OSError, ValueError, IndexError) as exc:
        return {"success": False, "error": str(exc)}


def _read_cpu_identity(cpuinfo_path: Path = Path("/proc/cpuinfo")) -> dict:
    """Read CPU model and logical processor count without shell commands."""
    try:
        content = cpuinfo_path.read_text(errors="replace")
    except OSError as exc:
        return {"success": False, "error": str(exc)}

    model = None
    logical_count = 0
    for line in content.splitlines():
        if line.startswith(("model name", "Hardware", "Processor")) and ":" in line:
            if model is None:
                model = line.split(":", 1)[1].strip()
        elif re.match(r"^processor\s*:", line):
            logical_count += 1

    if logical_count == 0:
        logical_count = os.cpu_count() or 0

    return {
        "success": bool(model or logical_count),
        "model": model or "Unknown",
        "logical_processor_count": logical_count,
        "error": "",
    }


def get_system_info() -> dict:
    """Collect OS identity, CPU, memory, swap, load and root filesystem basics."""
    os_release = {}
    try:
        for line in Path("/etc/os-release").read_text(errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os_release[key] = value.strip().strip('"').strip("'")
        os_release_error = ""
    except OSError as exc:
        os_release_error = str(exc)

    result = {
        "distribution": os_release.get("PRETTY_NAME", "Unknown"),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
    }
    if os_release_error:
        result["os_release_error"] = os_release_error

    result["cpu"] = _read_cpu_identity()
    result["cpu_usage"] = _read_cpu_usage()
    try:
        load_averages = os.getloadavg()
        result["load_average"] = {
            "1_minute": round(load_averages[0], 2),
            "5_minutes": round(load_averages[1], 2),
            "15_minutes": round(load_averages[2], 2),
        }
    except (AttributeError, OSError):
        result["load_average"] = {
            "available": False,
            "reason": "Load averages are unavailable on this platform",
        }

    result["memory"] = _read_meminfo()

    try:
        disk = shutil.disk_usage("/")
        result.update({
            "root_disk_total_gb": round(disk.total / (1024 ** 3), 2),
            "root_disk_free_gb": round(disk.free / (1024 ** 3), 2),
            "root_disk_used_percent": round(
                ((disk.total - disk.free) / disk.total) * 100, 1
            ) if disk.total else None,
            "root_disk_check_success": True,
        })
    except OSError as exc:
        result.update({
            "root_disk_check_success": False,
            "root_disk_error": str(exc),
        })
    return result


def inspect_pacman_logs(log_path: Path = PACMAN_LOG_PATH) -> dict:
    """Summarize pacman transaction, package and warning/error log events."""
    try:
        if not log_path.is_file():
            return {
                "success": False,
                "log_exists": False,
                "error": "Pacman log file not found",
                "entries_reviewed": 0,
                "relevant_entries": [],
            }
        lines = log_path.read_text(errors="replace").splitlines()
    except PermissionError:
        return {
            "success": False,
            "log_exists": True,
            "error": "Permission denied while reading Pacman logs",
            "entries_reviewed": 0,
            "relevant_entries": [],
        }
    except OSError as exc:
        return {
            "success": False,
            "log_exists": True,
            "error": f"Could not read Pacman log: {exc}",
            "entries_reviewed": 0,
            "relevant_entries": [],
        }

    transaction_started = sum(
        "[alpm] transaction started" in line.lower() for line in lines
    )
    transaction_completed = sum(
        "[alpm] transaction completed" in line.lower() for line in lines
    )
    interrupted_markers = [
        line for line in lines if "transaction interrupted" in line.lower()
    ]
    warnings = [line for line in lines if re.search(r"\bwarning\b", line, re.I)]
    errors = [
        line for line in lines
        if re.search(r"\berror\b|\bfatal\b", line, re.I)
    ]
    package_events = [
        line for line in lines
        if any(marker in line.lower() for marker in (
            "[alpm] installed ", "[alpm] upgraded ", "[alpm] downgraded ",
            "[alpm] reinstalled ", "[alpm] removed ",
        ))
    ]
    relevant = [
        line for line in lines
        if (
            "[alpm] transaction " in line.lower()
            or any(marker in line.lower() for marker in (
                "[alpm] installed ", "[alpm] upgraded ", "[alpm] downgraded ",
                "[alpm] reinstalled ", "[alpm] removed ",
            ))
            or re.search(r"\bwarning\b|\berror\b|\bfatal\b", line, re.I)
        )
    ]

    return {
        "success": True,
        "log_exists": True,
        "log_path": str(log_path),
        "entries_reviewed": len(lines),
        "transaction_started_count": transaction_started,
        "transaction_completed_count": transaction_completed,
        "transaction_interrupted_marker_count": len(interrupted_markers),
        "warning_count": len(warnings),
        "error_count": len(errors),
        "package_event_count": len(package_events),
        "warning_entries": warnings[-20:],
        "error_entries": errors[-20:],
        "interrupted_transaction_entries": interrupted_markers[-10:],
        "package_events": package_events[-30:],
        "relevant_entries": relevant[-60:],
        "transaction_health_interpretation": (
            "Explicit interrupted-transaction marker(s) found; inspect context."
            if interrupted_markers else
            "Start/completion counts are informational; a mismatch alone does "
            "not prove an interrupted transaction."
        ),
    }


def _inspect_pacman_cache(cache_path: Path = PACMAN_CACHE_PATH) -> dict:
    """Summarize package archive count and size without deleting cache files."""
    try:
        if cache_path.is_symlink() or not cache_path.is_dir():
            return {
                "success": False,
                "cache_exists": False,
                "archive_count": None,
                "total_size_gib": None,
                "error": "Pacman cache directory is missing, invalid, or a symlink",
            }

        archive_suffix = ".pkg.tar."
        archives = [
            entry for entry in cache_path.iterdir()
            if entry.is_file() and not entry.is_symlink()
            and re.search(r"\.pkg\.tar\.(?:zst|xz|gz|bz2|lzo|lrz|Z)$", entry.name)
        ]
        total_bytes = sum(entry.stat().st_size for entry in archives)
        return {
            "success": True,
            "cache_exists": True,
            "cache_path": str(cache_path),
            "archive_count": len(archives),
            "total_size_gib": round(total_bytes / (1024 ** 3), 3),
            "largest_archives": [
                {"filename": entry.name, "size_mib": round(entry.stat().st_size / (1024 ** 2), 1)}
                for entry in sorted(archives, key=lambda item: item.stat().st_size, reverse=True)[:5]
            ],
            "error": "",
        }
    except OSError as exc:
        return {
            "success": False,
            "cache_exists": True,
            "archive_count": None,
            "total_size_gib": None,
            "error": str(exc),
        }


def inspect_package_database() -> dict:
    """Inspect installed packages, orphan candidates, DB checks and cache usage."""
    installed = run_read_only_command(["pacman", "-Q"])
    orphans = run_read_only_command(["pacman", "-Qtdq"])
    database = run_read_only_command(["pacman", "-Dk"])

    package_lines = [
        line.strip() for line in installed["stdout"].splitlines() if line.strip()
    ] if installed["success"] else []
    package_sample = [
        {"name": line.split()[0], "version": line.split()[1] if len(line.split()) > 1 else "Unknown"}
        for line in package_lines[:50]
    ]

    if orphans["return_code"] == 1 and not orphans["stdout"].strip():
        orphan_check = {
            "success": True,
            "status": "No orphan packages found",
            "orphan_count": 0,
            "output": "",
            "error": "",
        }
    elif orphans["success"]:
        orphan_lines = [
            line.strip() for line in orphans["stdout"].splitlines() if line.strip()
        ]
        orphan_check = {
            "success": True,
            "status": "Orphan package candidates found",
            "orphan_count": len(orphan_lines),
            "output": "\n".join(orphan_lines[:200]),
            "error": "",
        }
    else:
        orphan_check = {
            "success": False,
            "status": "Orphan check unavailable or failed",
            "orphan_count": None,
            "output": orphans["stdout"][:3000],
            "error": orphans["stderr"],
            "return_code": orphans["return_code"],
        }

    database_output = database["stdout"][:5000]
    problem_lines = [
        line for line in database_output.splitlines()
        if re.search(r"\b(error|warning|missing|mismatch|invalid)\b", line, re.I)
    ]
    database_check = {
        "success": database["success"],
        "status": (
            "Database consistency command completed; inspect reported output"
            if database["success"] else
            "Database consistency check failed or unavailable"
        ),
        "output": database_output,
        "reported_problem_lines": problem_lines[:30],
        "error": database["stderr"],
        "return_code": database["return_code"],
    }

    return {
        "installed_packages": {
            "success": installed["success"],
            "package_count": len(package_lines) if installed["success"] else None,
            "package_sample": package_sample,
            "output": installed["stdout"][:5000],
            "error": installed["stderr"],
            "return_code": installed["return_code"],
        },
        "orphan_check": orphan_check,
        "database_check": database_check,
        "package_cache": _inspect_pacman_cache(),
    }


if __name__ == "__main__":
    print("\n===== SYSTEM INFORMATION =====")
    print(get_system_info())
    print("\n===== PACMAN LOGS =====")
    print(inspect_pacman_logs())
    print("\n===== PACKAGE DATABASE AND CACHE =====")
    print(inspect_package_database())

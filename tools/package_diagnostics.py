"""Read-only pacman configuration and mirror diagnostics.

These checks inspect local text files only. They do not invoke pacman,
contact mirrors, or claim that repositories are operational.
"""

from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

PACMAN_CONFIG_PATH = Path("/etc/pacman.conf")
MIRRORLIST_PATH = Path("/etc/pacman.d/mirrorlist")

BARE_CONFIG_OPTIONS = {
    "CheckSpace",
    "Color",
    "DisableDownloadTimeout",
    "ILoveCandy",
    "NoProgressBar",
    "UseSyslog",
    "VerbosePkgLists",
}

SAFE_CONFIG_OPTIONS = {
    "Architecture",
    "CheckSpace",
    "Color",
    "DisableDownloadTimeout",
    "ParallelDownloads",
    "SigLevel",
}


def inspect_pacman_config(config_path: Path = PACMAN_CONFIG_PATH) -> dict:
    """Read selected pacman settings and perform conservative text checks.

    This is not a full libalpm/pacman configuration validation. In particular,
    Include files and repository availability are not resolved or tested.
    """
    try:
        content = config_path.read_text(errors="replace")
    except FileNotFoundError:
        return {
            "success": False,
            "config_exists": False,
            "repositories": [],
            "options": {},
            "basic_parse_status": "not_performed",
            "basic_parse_issues": [],
            "full_pacman_validation_performed": False,
            "repository_availability_tested": False,
            "error": "Pacman configuration file not found",
        }
    except OSError as exc:
        return {
            "success": False,
            "config_exists": True,
            "repositories": [],
            "options": {},
            "basic_parse_status": "not_performed",
            "basic_parse_issues": [],
            "full_pacman_validation_performed": False,
            "repository_availability_tested": False,
            "error": str(exc),
        }

    repositories = []
    options = {}
    issues = []
    current_section = None

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("["):
            if not line.endswith("]") or line.count("[") != 1 or line.count("]") != 1:
                issues.append(f"Line {line_number}: malformed section header")
                current_section = None
                continue

            section = line[1:-1].strip()
            if not section:
                issues.append(f"Line {line_number}: empty section name")
                current_section = None
                continue

            current_section = section
            if section.lower() != "options":
                repositories.append(section)
            continue

        if "=" not in line:
            # pacman.conf permits several boolean options as bare directives.
            if (
                current_section
                and current_section.lower() == "options"
                and line in BARE_CONFIG_OPTIONS
            ):
                options[line] = "enabled"
                continue
            issues.append(f"Line {line_number}: unrecognized or malformed directive")
            continue

        key, value = (part.strip() for part in line.split("=", 1))
        if not key:
            issues.append(f"Line {line_number}: directive has an empty key")
            continue
        if current_section is None:
            issues.append(f"Line {line_number}: directive appears outside a section")
            continue

        if current_section.lower() == "options" and key in SAFE_CONFIG_OPTIONS:
            options[key] = value

    return {
        "success": True,
        "config_exists": True,
        "repositories": repositories,
        "options": options,
        "basic_parse_status": "issues_detected" if issues else "basic_parse_passed",
        "basic_parse_issues": issues,
        "full_pacman_validation_performed": False,
        "repository_availability_tested": False,
        "error": "",
    }


def _parse_server_url(raw_url: str):
    """Return a conservative normalized URL and hostname, or (None, None)."""
    try:
        parsed = urlsplit(raw_url)
        # Accessing .port also validates malformed port values.
        _ = parsed.port
        if parsed.scheme.lower() not in {"http", "https", "ftp"}:
            return None, None
        if not parsed.hostname:
            return None, None
        if any(character.isspace() for character in raw_url):
            return None, None

        host = parsed.hostname.lower()
        normalized = (
            f"{parsed.scheme.lower()}://{host}"
            + (f":{parsed.port}" if parsed.port is not None else "")
            + parsed.path
            + (f"?{parsed.query}" if parsed.query else "")
        )
        return normalized, host
    except ValueError:
        return None, None


def inspect_mirror_status(mirrorlist_path: Path = MIRRORLIST_PATH) -> dict:
    """Summarize active Server directives without contacting mirror servers.

    Exact duplicate URL entries and repeated hostnames are reported separately.
    A repeated hostname is not automatically treated as a duplicate URL.
    """
    try:
        content = mirrorlist_path.read_text(errors="replace")
    except FileNotFoundError:
        return {
            "success": False,
            "mirrorlist_exists": False,
            "active_mirror_count": 0,
            "unique_mirror_hosts_count": 0,
            "duplicate_entries_count": 0,
            "repeated_host_occurrences_count": 0,
            "invalid_server_entries_count": 0,
            "invalid_server_lines": [],
            "network_reachability_tested": False,
            "error": "Pacman mirrorlist not found",
        }
    except OSError as exc:
        return {
            "success": False,
            "mirrorlist_exists": True,
            "active_mirror_count": 0,
            "unique_mirror_hosts_count": 0,
            "duplicate_entries_count": 0,
            "repeated_host_occurrences_count": 0,
            "invalid_server_entries_count": 0,
            "invalid_server_lines": [],
            "network_reachability_tested": False,
            "error": str(exc),
        }

    normalized_urls = []
    hosts = []
    invalid_lines = []

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = (part.strip() for part in line.split("=", 1))
        if key != "Server":
            continue

        normalized_url, host = _parse_server_url(value)
        if normalized_url is None:
            invalid_lines.append(line_number)
            continue

        normalized_urls.append(normalized_url)
        hosts.append(host)

    url_counts = Counter(normalized_urls)
    host_counts = Counter(hosts)

    return {
        "success": True,
        "mirrorlist_exists": True,
        "active_mirror_count": len(normalized_urls) + len(invalid_lines),
        "valid_server_entry_count": len(normalized_urls),
        "unique_mirror_hosts_count": len(host_counts),
        # Number of entries beyond the first occurrence of an exact URL.
        "duplicate_entries_count": sum(count - 1 for count in url_counts.values()),
        # Number of entries beyond the first occurrence of each hostname.
        "repeated_host_occurrences_count": sum(
            count - 1 for count in host_counts.values()
        ),
        "invalid_server_entries_count": len(invalid_lines),
        "invalid_server_lines": invalid_lines,
        "network_reachability_tested": False,
        "error": "",
    }

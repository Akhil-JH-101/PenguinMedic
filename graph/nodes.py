
import json
import re
from pathlib import Path

from pydantic import BaseModel

from agents.diagnostic import DiagnosticAgent
from agents.investigation import InvestigationAgent
from agents.solution import SolutionAgent, resolve_solution_mode

from tools.diagnostics import (
    get_system_info,
    inspect_pacman_logs,
    inspect_package_database,
)

from tools.system_diagnostics import (
    inspect_system_journal,
    inspect_failed_services,
    inspect_disk_usage,
    inspect_systemd_unit,
)

from tools.package_diagnostics import (
    inspect_pacman_config,
    inspect_mirror_status,
)

from tools.command_validator import validate_recovery_plan
from tools.recovery_verification import verify_recovery
from tools.privacy_filter import (
    sanitize_diagnostic_report,
    sanitize_additional_results,
    sanitize_value,
)
from tools.diagnostic_requests import validate_diagnostic_requests

from graph.state import PenguinMedicState


# ==========================================
# FINAL DIAGNOSTIC REPORT
# ==========================================

class FinalDiagnosticReport(BaseModel):
    issue_category: str
    problem_summary: str
    confirmed_observations: list[str]
    possible_explanations: list[str]
    missing_information: list[str]
    handoff_summary: str


# ==========================================
# AGENT INITIALIZATION
# ==========================================

agent = DiagnosticAgent()
investigation_agent = InvestigationAgent()
solution_agent = SolutionAgent()


# ==========================================
# DIAGNOSTIC TOOL REGISTRY
# ==========================================

AVAILABLE_TOOLS = {
    "get_system_info": get_system_info,
    "inspect_pacman_logs": inspect_pacman_logs,
    "inspect_package_database": inspect_package_database,
    "inspect_system_journal": inspect_system_journal,
    "inspect_failed_services": inspect_failed_services,
    "inspect_disk_usage": inspect_disk_usage,
    "inspect_systemd_unit": inspect_systemd_unit,
    "inspect_pacman_config": inspect_pacman_config,
    "inspect_mirror_status": inspect_mirror_status,
}


# ==========================================
# CONTROLLED SANDBOX TEST EVIDENCE
# ==========================================

def collect_sandbox_test_evidence(scenario: str) -> dict:
    """
    Inspect the fixed fixture for the selected sandbox demonstration.

    This is controlled sandbox demonstration logic, not a general-purpose diagnostic tool.
    """

    project_root = Path(__file__).resolve().parent.parent
    sandbox_dir = project_root / "sandbox" / "fixtures"

    if sandbox_dir.is_symlink() or not sandbox_dir.is_dir():
        return {
            "status": "unavailable",
            "reason": "Sandbox directory is missing or invalid."
        }

    if scenario == "cannot_proceed_demo":
        return {
            "status": "verified",
            "scenario": scenario,
            "evidence_consistency": "conflicting",
            "conflicting_observations": [
                "Synthetic diagnostic source A reports the sandbox target as missing.",
                "Synthetic diagnostic source B reports the same sandbox target as present.",
            ],
            "note": "These observations are deliberately contradictory test data, not real filesystem findings.",
        }

    if scenario in {"missing_file", "retry_demo"}:
        expected_file = sandbox_dir / "expected_content.txt"
        target_file = sandbox_dir / "important_file.txt"

        if expected_file.is_symlink() or not expected_file.is_file():
            return {
                "status": "unavailable",
                "reason": "Expected content file is missing or invalid."
            }

        if target_file.is_symlink():
            return {
                "status": "unavailable",
                "reason": "Target file is a symbolic link."
            }

        return {
            "status": "verified",
            "scenario": scenario,
            "target": str(target_file.relative_to(project_root)),
            "target_exists": target_file.is_file(),
            "target_path_exists": target_file.exists(),
            "expected_content_exists": expected_file.is_file(),
        }

    if scenario == "broken_config":
        config_dir = sandbox_dir / "config_test"
        expected_file = config_dir / "expected_app_config.json"
        target_file = config_dir / "app_config.json"

        if config_dir.is_symlink() or not config_dir.is_dir():
            return {
                "status": "unavailable",
                "reason": "Configuration sandbox directory is missing or invalid."
            }

        if expected_file.is_symlink() or not expected_file.is_file():
            return {
                "status": "unavailable",
                "reason": "Expected configuration file is missing or invalid."
            }

        if target_file.is_symlink() or not target_file.is_file():
            return {
                "status": "unavailable",
                "reason": "Target configuration file is missing or invalid."
            }

        try:
            expected_data = json.loads(expected_file.read_bytes())
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            return {
                "status": "unavailable",
                "reason": f"Expected configuration could not be validated: {error}"
            }

        try:
            json.loads(target_file.read_bytes())
            target_valid_json = True
            target_parse_error = ""
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            if isinstance(error, OSError):
                return {
                    "status": "unavailable",
                    "reason": f"Target configuration could not be read: {error}"
                }
            target_valid_json = False
            target_parse_error = str(error)

        return {
            "status": "verified",
            "scenario": scenario,
            "target": str(target_file.relative_to(project_root)),
            "target_valid_json": target_valid_json,
            "target_parse_error": target_parse_error,
            "expected_config_valid_json": isinstance(expected_data, (dict, list)),
        }

    return {
        "status": "unavailable",
        "reason": f"Unknown sandbox scenario: {scenario}"
    }


# ==========================================
# AGENT 1: INITIAL DIAGNOSTIC SELECTION
# ==========================================

def diagnostic_node(state: PenguinMedicState):
    """Ask Qwen which diagnostic tools are required."""

    print("\n[Agent 1] Selecting diagnostic tools...")

    user_problem = state["user_problem"]

    if state.get("live_recovery_mode") and state.get("pending_live_verification"):
        user_problem += """

POST-RECOVERY LIVE VERIFICATION:
A recovery command has just been attempted. Collect fresh, relevant diagnostics
for the ORIGINAL reported problem. Do not assume the command succeeded. Re-run
the most relevant checks so Agent 2 can assess whether the original symptom
persists. Do not propose or execute repairs from this diagnostic stage.
"""

    if state.get("sandbox_test_mode", False):
        scenario = state.get("sandbox_scenario", "missing_file")

        if scenario in {"missing_file", "retry_demo"}:
            scenario_instruction = (
                "The test harness will independently inspect the fixed "
                "missing-file fixture at sandbox/fixtures/important_file.txt. "
                "For retry_demo, the first approved execution is deliberately "
                "simulated to fail once, then a second approved attempt can run."
            )
        elif scenario == "cannot_proceed_demo":
            scenario_instruction = (
                "This is a decision-branch demonstration using deliberately "
                "conflicting synthetic sandbox evidence. Do not recommend repair."
            )
        elif scenario == "broken_config":
            scenario_instruction = (
                "The test harness will independently inspect the fixed "
                "JSON configuration fixture at "
                "sandbox/fixtures/config_test/app_config.json."
            )
        else:
            scenario_instruction = "The test scenario is unknown."

        user_problem += f"""

CONTROLLED PENGUINMEDIC SANDBOX TEST:

This is an isolated recovery integration test.
Do not request unrelated pacman or system diagnostics.
{scenario_instruction}

Do not invent tool names or commands.
"""

    request = agent.investigate(user_problem)

    print("[Agent 1] Diagnostic selection completed.")

    return {
        "diagnostic_request": request.model_dump()
    }


# ==========================================
# SYSTEMD UNIT NAME EXTRACTION
# ==========================================

def _requested_systemd_unit(problem_text: str) -> str | None:
    """Extract a literal .service name supplied in the user's problem text."""
    matches = re.findall(r"(?<![A-Za-z0-9:_.@-])([A-Za-z0-9:_.@-]+\.service)(?![A-Za-z0-9:_.@-])", problem_text or "")
    return matches[0] if matches else None


def _inspect_explicit_file_path(problem_text: str, missing_text: str) -> dict | None:
    """
    Inspect metadata for an absolute file path explicitly named in the problem
    or Agent 3's missing-evidence list. This never reads or modifies file content.
    """
    combined = f"{problem_text or ''}\\n{missing_text or ''}"
    candidates = re.findall(r"(?<![A-Za-z0-9_])(/[A-Za-z0-9._/-]+)", combined)
    if not candidates:
        return None

    candidates = [candidate.rstrip(".,:;)]}") for candidate in candidates]
    path_text = next(
        (candidate for candidate in candidates if candidate.startswith("/tmp/")),
        candidates[0],
    )

    try:
        target = Path(path_text)
        is_symlink = target.is_symlink()
        exists = target.exists()
        is_file = target.is_file() if exists and not is_symlink else False
        readable = bool(
            exists and is_file and not is_symlink and os.access(path_text, os.R_OK)
        )
        return {
            "success": True,
            "path": path_text,
            "exists": exists,
            "is_file": is_file,
            "is_symlink": is_symlink,
            "readable_by_current_process": readable,
            "inspection": "Metadata-only check; file contents were not read.",
        }
    except OSError as error:
        return {"success": False, "path": path_text, "error": str(error)}


def _run_selected_diagnostic(tool_name: str, tool, problem_text: str):
    if tool_name == "inspect_systemd_unit":
        unit_name = _requested_systemd_unit(problem_text)
        if not unit_name:
            return {
                "success": False,
                "error": "No explicit .service unit name was found in the user's problem description.",
            }
        return tool(unit_name)
    return tool()


# ==========================================
# PYTHON DIAGNOSTIC TOOL EXECUTION
# ==========================================

def tool_execution_node(state: PenguinMedicState):
    """Execute diagnostic tools selected by Agent 1."""

    print("\n[Tools] Collecting Linux diagnostic information...")

    requested_tools = (
        state["diagnostic_request"]["required_diagnostics"]
    )

    results = {}
    errors = []
    executed_tools = []

    for tool_name in requested_tools:

        tool = AVAILABLE_TOOLS.get(tool_name)

        if tool is None:
            errors.append(
                f"Unsupported diagnostic tool: {tool_name}"
            )
            continue

        try:
            print(f"[Tools] Running {tool_name}...")

            executed_tools.append(tool_name)
            results[tool_name] = _run_selected_diagnostic(
                tool_name, tool, state.get("user_problem", "")
            )

        except Exception as error:
            errors.append(
                f"{tool_name}: {str(error)}"
            )

    print("[Tools] Diagnostic collection completed.")

    return {
        "diagnostic_results": results,
        "errors": errors,
        "executed_diagnostics": executed_tools,
    }


# ==========================================
# AGENT 1: DIAGNOSTIC REPORT GENERATION
# ==========================================

def report_node(state: PenguinMedicState):
    """Ask Qwen to interpret the actual diagnostic evidence."""

    print("\n[Agent 1] Analyzing collected evidence...")

    diagnostic_request = state["diagnostic_request"]
    diagnostic_results = state["diagnostic_results"]
    errors = state.get("errors", [])

    compact_results = {}

    # Compact diagnostic evidence before sending it to Qwen.
    for tool_name, result in diagnostic_results.items():

        if tool_name in (
            "inspect_pacman_logs",
            "inspect_system_journal"
        ):
            compact_results[tool_name] = {
                "success": result.get("success"),
                "entries_reviewed": result.get("entries_reviewed"),
                "relevant_entries": [
                    line[:250] for line in result.get("relevant_entries", [])[-15:]
                ],
                "warning_count": result.get("warning_count"),
                "error_count": result.get("error_count"),
                "package_event_count": result.get("package_event_count"),
                "transaction_started_count": result.get("transaction_started_count"),
                "transaction_completed_count": result.get("transaction_completed_count"),
                "transaction_interrupted_marker_count": result.get("transaction_interrupted_marker_count"),
                "transaction_health_interpretation": result.get("transaction_health_interpretation"),
                "recent_journal_success": result.get("recent_journal_success"),
                "current_boot_success": result.get("current_boot_success"),
                "recent_warning_count": result.get("recent_warning_count"),
                "recent_error_count": result.get("recent_error_count"),
                "current_boot_entries_reviewed": result.get("current_boot_entries_reviewed"),
                "current_boot_relevant_entries": [
                    line[:250]
                    for line in result.get("current_boot_relevant_entries", [])[-15:]
                ],
                "current_boot_warning_count": result.get("current_boot_warning_count"),
                "current_boot_error_count": result.get("current_boot_error_count"),
                "error": result.get("error", ""),
            }

        elif tool_name == "inspect_package_database":
            compact_results[tool_name] = {
                "installed_packages": {
                    "success": result.get("installed_packages", {}).get("success"),
                    "package_count": result.get("installed_packages", {}).get("package_count"),
                    "package_sample": result.get("installed_packages", {}).get("package_sample", [])[:20],
                    "error": result.get("installed_packages", {}).get("error"),
                },
                "orphan_check": {
                    "success": result.get("orphan_check", {}).get("success"),
                    "status": result.get("orphan_check", {}).get("status"),
                    "orphan_count": result.get("orphan_check", {}).get("orphan_count"),
                    "error": result.get("orphan_check", {}).get("error"),
                },
                "database_check": {
                    "success": result.get("database_check", {}).get("success"),
                    "status": result.get("database_check", {}).get("status"),
                    "reported_problem_lines": result.get("database_check", {}).get("reported_problem_lines", [])[:20],
                    "output": result.get("database_check", {}).get("output", "")[:1000],
                    "error": result.get("database_check", {}).get("error"),
                },
                "package_cache": {
                    "success": result.get("package_cache", {}).get("success"),
                    "cache_exists": result.get("package_cache", {}).get("cache_exists"),
                    "archive_count": result.get("package_cache", {}).get("archive_count"),
                    "total_size_gib": result.get("package_cache", {}).get("total_size_gib"),
                    "error": result.get("package_cache", {}).get("error"),
                },
            }

        else:
            compact_results[tool_name] = result

    # Collect controlled sandbox evidence only in test mode.
    sandbox_evidence = None

    if state.get("sandbox_test_mode", False):
        scenario = state.get("sandbox_scenario", "missing_file")
        sandbox_evidence = collect_sandbox_test_evidence(scenario)

        compact_results["sandbox_test_evidence"] = sandbox_evidence

    response = agent.client.chat.completions.create(
        model=agent.model,
        messages=[
            {
                "role": "system",
                "content": """
You are Agent 1 of PenguinMedic.

Your task is to prepare an evidence-based diagnostic report
for the cloud investigation agent.

Rules:
- Use the actual diagnostic results provided.
- Distinguish verified observations from possible explanations.
- Never invent logs, package names or system conditions.
- Do not claim that a possible explanation is confirmed.
- Do not determine the final root cause.
- Do not suggest repair commands.
- Clearly identify missing or unavailable information.
- If a tool failed, mention that limitation.

When sandbox_test_evidence is supplied:
- Treat its status and scenario-specific fields as deterministic
  observations from the controlled test harness.
- For missing_file and retry_demo, report whether the fixed target is missing
  and whether its expected reference content exists.
- For cannot_proceed_demo, report the two supplied synthetic observations
  as conflicting and explicitly identify them as test data, not real findings.
- For broken_config, report whether the fixed target is valid JSON
  and whether the expected reference configuration is valid JSON.
- Do not invent additional filesystem findings.
- Do not propose a repair.
"""
            },
            {
                "role": "user",
                "content": json.dumps({
                    "initial_request": diagnostic_request,
                    "diagnostic_results": compact_results,
                    "tool_errors": errors,
                }, indent=2),
            },
        ],
        temperature=0.1,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "final_diagnostic_report",
                "strict": True,
                "schema": FinalDiagnosticReport.model_json_schema(),
            },
        },
    )

    choice = response.choices[0]
    result = choice.message.content

    if not result:
        raise RuntimeError(
            "Agent 1 returned empty output. "
            f"Finish reason: {choice.finish_reason}"
        )

    report = FinalDiagnosticReport.model_validate_json(result)

    # Preserve deterministic sandbox evidence in the final report.
    # The LLM cannot omit or contradict these observations.

    if sandbox_evidence is not None:
        scenario = state.get("sandbox_scenario", "missing_file")

        if sandbox_evidence.get("status") == "verified":

            if scenario in {"missing_file", "retry_demo"}:
                target_exists = sandbox_evidence["target_exists"]
                expected_exists = sandbox_evidence["expected_content_exists"]

                if not target_exists and expected_exists:
                    report.issue_category = (
                        "Controlled PenguinMedic Missing-File Recovery Test"
                    )
                    report.problem_summary = (
                        "The PenguinMedic sandbox recovery test file is missing."
                    )
                    report.confirmed_observations.append(
                        "Controlled sandbox verification confirms that "
                        "sandbox/fixtures/important_file.txt is missing "
                        "while expected_content.txt exists."
                    )
                    report.handoff_summary = (
                        "The controlled test harness confirms that the "
                        "designated sandbox target is missing and its "
                        "expected reference content exists."
                    )

                elif target_exists:
                    report.confirmed_observations.append(
                        "The controlled sandbox target file currently exists. "
                        "No missing-file recovery is justified."
                    )
                else:
                    report.missing_information.append(
                        "The sandbox reference content could not be verified."
                    )

            elif scenario == "cannot_proceed_demo":
                report.issue_category = "Controlled PenguinMedic Conflicting-Evidence Decision Test"
                report.problem_summary = (
                    "The sandbox decision test contains deliberately conflicting "
                    "observations about the same target file."
                )
                report.confirmed_observations.extend(
                    sandbox_evidence["conflicting_observations"]
                )
                report.missing_information.append(
                    "A trustworthy, consistent observation of the target file state is unavailable in this synthetic test."
                )
                report.handoff_summary = (
                    "The controlled test harness supplied contradictory synthetic "
                    "observations. Recovery must not be proposed from this evidence."
                )

            elif scenario == "broken_config":
                target_valid = sandbox_evidence["target_valid_json"]
                expected_valid = sandbox_evidence["expected_config_valid_json"]

                if not target_valid and expected_valid:
                    report.issue_category = (
                        "Controlled PenguinMedic Broken-Configuration Recovery Test"
                    )
                    report.problem_summary = (
                        "The PenguinMedic sandbox application configuration "
                        "contains invalid JSON."
                    )
                    report.confirmed_observations.append(
                        "Controlled sandbox verification confirms that "
                        "sandbox/fixtures/config_test/app_config.json "
                        "is invalid JSON."
                    )
                    report.confirmed_observations.append(
                        "The fixed expected_app_config.json reference file "
                        "contains valid JSON."
                    )
                    report.possible_explanations.append(
                        "The sandbox configuration is syntactically malformed."
                    )
                    report.handoff_summary = (
                        "The controlled test harness confirms that the "
                        "sandbox configuration is invalid JSON and a valid "
                        "reference configuration is available."
                    )

                elif target_valid:
                    report.confirmed_observations.append(
                        "The sandbox configuration is already valid JSON. "
                        "No configuration repair is justified."
                    )
                else:
                    report.missing_information.append(
                        "The expected sandbox configuration could not be validated."
                    )

        else:
            report.missing_information.append(
                "Sandbox evidence unavailable: "
                + sandbox_evidence.get("reason", "Unknown reason.")
            )

    print("[Agent 1] Final diagnostic report generated.")

    return {
        "diagnostic_report": report.model_dump()
    }


# ==========================================
# AGENT 2: CLOUD INVESTIGATION
# ==========================================

def investigation_node(state: PenguinMedicState):
    """Sanitize Agent 1's report before sending it to Agent 2."""

    print("\n[Privacy Filter] Sanitizing diagnostic report...")

    sanitized_report = sanitize_diagnostic_report(
        state["diagnostic_report"]
    )

    print("[Privacy Filter] Sanitization completed.")

    print("\n[Agent 2 - Groq] Investigating sanitized evidence...")

    investigation_input = dict(sanitized_report)

    additional_results = state.get(
        "sanitized_additional_results", {}
    )

    if additional_results:
        investigation_input["additional_diagnostic_results"] = (
            additional_results
        )

    report = investigation_agent.investigate(
        investigation_input
    )

    print("[Agent 2] Investigation completed.")

    return {
        "sanitized_report": sanitized_report,
        "investigation_report": report.model_dump(),
        "requested_diagnostics": [],
    }


# ==========================================
# AGENT 1: ADDITIONAL DIAGNOSTICS
# ==========================================

def additional_diagnostics_node(state: PenguinMedicState):
    """Agent 1 selects and executes additional diagnostics."""

    print("\n[Agent 1 - Qwen] Evaluating missing diagnostic evidence...")

    current_round = state.get("investigation_round", 0)

    if current_round >= 2:
        print("[Tools] Maximum investigation rounds reached.")

        return {
            "requested_diagnostics": [],
            "additional_diagnostic_errors": [
                "Maximum additional investigation rounds reached."
            ],
            "investigation_round": current_round,
        }

    recovery_plan = state.get("recovery_plan", {})

    followup_context = {
        "original_problem": state.get("user_problem", ""),
        "missing_information": recovery_plan.get(
            "missing_information", []
        ),
        "questions_for_user": recovery_plan.get(
            "questions_for_user", []
        ),
        "initial_diagnostic_report": state.get(
            "sanitized_report", {}
        ),
        "previous_additional_results": state.get(
            "sanitized_additional_results", {}
        ),
        "previously_executed_tools": state.get(
            "executed_diagnostics", []
        ),
        "systemd_unit_note": (
            "The named service was created with systemd-run. Such transient "
            "units are represented by runtime systemd properties and may not "
            "have a persistent .service unit file on disk. Do not request a "
            "persistent unit file if inspect_systemd_unit already returned "
            "runtime properties."
            if "systemd-run" in state.get("user_problem", "")
            else ""
        ),
    }

    request = agent.investigate(
        json.dumps(followup_context, indent=2)
    )

    requested = list(request.required_diagnostics)

    print("[Agent 1] Additional diagnostic selection completed.")

    # Deterministic fallback for the exact gap exposed by transient systemd
    # units: they have runtime properties, not necessarily a persistent file.
    missing_text = " ".join(recovery_plan.get("missing_information", [])).lower()
    unit_name = _requested_systemd_unit(state.get("user_problem", ""))
    systemd_gap = any(token in missing_text for token in (
        "unit file", "dependencies", "ordering", "execution context",
        "failure timestamp", "journal entries", "service-specific journal",
    ))
    previously_run = set(state.get("executed_diagnostics", []))
    if (
        unit_name
        and systemd_gap
        and "inspect_systemd_unit" not in previously_run
        and "inspect_systemd_unit" not in requested
    ):
        requested.append("inspect_systemd_unit")
        print(
            "[Agent 1] Adding targeted systemd unit inspection for "
            f"{unit_name}."
        )

    # The systemd unit was already inspected during the initial diagnostic
    # pass. For the controlled systemd-run test, close the remaining concrete
    # evidence gap by checking the explicitly named marker file's metadata.
    # This is read-only and does not depend on the LLM selecting a tool.
    file_inspection = None
    missing_text = " ".join(recovery_plan.get("missing_information", []))
    if any(token in missing_text.lower() for token in (
        "existence", "readability", "marker file", "missing file"
    )):
        file_inspection = _inspect_explicit_file_path(
            state.get("user_problem", ""),
            missing_text,
        )
        if file_inspection is not None:
            print("[Tools] Running targeted read-only file metadata inspection...")

    request.required_diagnostics = requested
    validation = validate_diagnostic_requests(requested)

    accepted = validation["accepted"]
    rejected = validation["rejected"]

    errors = [
        f"Rejected unsupported diagnostic tool: {name}"
        for name in rejected
    ]

    results = {}
    successfully_executed = []

    for tool_name in accepted:

        tool = AVAILABLE_TOOLS.get(tool_name)

        if tool is None:
            errors.append(f"Tool unavailable: {tool_name}")
            continue

        try:
            print(f"[Tools] Running {tool_name}...")

            results[tool_name] = _run_selected_diagnostic(
                tool_name, tool, state.get("user_problem", "")
            )
            successfully_executed.append(tool_name)

        except Exception as error:
            errors.append(f"{tool_name}: {str(error)}")

    all_raw_results = dict(
        state.get("additional_diagnostic_results", {})
    )

    all_raw_results.update(results)
    if file_inspection is not None:
        all_raw_results["requested_file_inspection"] = file_inspection

    sanitized_results = sanitize_additional_results(
        all_raw_results
    )

    executed = state.get("executed_diagnostics", [])

    all_executed = list(dict.fromkeys(
        executed + successfully_executed
    ))

    print("[Agent 1] Additional diagnostic collection completed.")

    return {
        "diagnostic_request": request.model_dump(),
        "additional_diagnostic_results": all_raw_results,
        "sanitized_additional_results": sanitized_results,
        "executed_diagnostics": all_executed,
        "investigation_round": current_round + 1,
        "requested_diagnostics": [],
        "additional_diagnostic_errors": errors,
    }


# ==========================================
# AGENT 3: SOLUTION GENERATION
# ==========================================

def solution_node(state: PenguinMedicState):
    """Agent 3 generates a recovery plan."""

    print("\n[Agent 3] Evaluating recovery decision...")

    if (
        state.get("sandbox_test_mode") is True
        and state.get("sandbox_scenario") == "cannot_proceed_demo"
    ):
        from agents.solution import RecoveryPlan
        print("[Agent 3 - Sandbox Decision] Conflicting evidence detected; refusing recovery.")
        plan = RecoveryPlan(
            decision="CANNOT_SAFELY_PROCEED",
            decision_reason=(
                "The controlled test contains contradictory observations for the "
                "same target. Its actual state cannot be established, so a repair "
                "would be speculative."
            ),
            problem_summary="The sandbox decision test supplied conflicting synthetic evidence.",
            evidence_basis=[
                "Synthetic source A reports the target as missing.",
                "Synthetic source B reports the same target as present.",
            ],
            missing_information=["A consistent, independently verified target state."],
            questions_for_user=[],
            proposed_solution=(
                "Do not modify anything. Obtain a reliable diagnostic observation "
                "before considering recovery."
            ),
            prerequisites=[],
            recovery_steps=[],
            overall_risk="high",
            warnings=[
                "This is deliberately conflicting synthetic sandbox evidence, not a real system diagnosis.",
                "No recovery operation will be validated, approved, or executed.",
            ],
            approval_required=True,
            plan_summary="Safe termination: insufficient trustworthy evidence; no recovery action proposed.",
        )
        return {"recovery_plan": plan.model_dump()}

    solution_input = {
        **state["sanitized_report"],
        "additional_diagnostic_results": state.get(
            "sanitized_additional_results", {}
        ),
        "sandbox_scenario": state.get("sandbox_scenario", ""),
        "previous_recovery_attempts": [
            {
                "attempt_number": item.get("attempt_number"),
                "status": item.get("status"),
                "action": item.get("action", ""),
                "verification": item.get("verification") or item.get("reason", ""),
                "evidence": item.get("evidence", []),
            }
            for item in state.get("recovery_verification_history", [])
        ],
    }

    operating_mode = resolve_solution_mode(
        sandbox_test_mode=state.get("sandbox_test_mode") is True,
        live_diagnostic_mode=state.get("live_diagnostic_mode") is True,
        live_recovery_mode=state.get("live_recovery_mode") is True,
    )

    print(f"[Agent 3] Operating mode: {operating_mode}")

    plan = solution_agent.generate_solution(
        solution_input,
        state["investigation_report"],
        operating_mode=operating_mode,
    )

    print("[Agent 3] Recovery plan generated.")

    return {
        "recovery_plan": plan.model_dump()
    }


# ==========================================
# AGENT 4: SAFETY VALIDATION
# ==========================================

def validation_node(state: PenguinMedicState):
    """Validate Agent 3's recovery plan."""

    print("\n[Agent 4 - Safety Gate] Validating recovery plan...")

    result = validate_recovery_plan(
        state["recovery_plan"],
        live_mode=state.get("live_recovery_mode", False),
    )

    print(
        f"[Safety Gate] Approved operations: "
        f"{len(result['approved_steps'])}"
    )

    print(
        f"[Safety Gate] Rejected operations: "
        f"{len(result['rejected_steps'])}"
    )

    return {
        "validation_result": result
    }



# ==========================================
# AGENT 4: INDEPENDENT RECOVERY VERIFICATION
# ==========================================

def recovery_verification_node(state: PenguinMedicState):
    """Independently verify that the original sandbox issue is resolved."""

    print("\n[Agent 4 - Verification] Independently checking recovery...")

    if not state.get("sandbox_test_mode", False):
        result = {
            "status": "blocked",
            "issue_resolved": False,
            "reason": "Independent recovery verification is restricted to sandbox mode.",
        }
    else:
        result = verify_recovery(
            authorized_steps=state.get("authorized_steps", []),
            execution_results=state.get("execution_results", []),
        )

    if result.get("status") == "success":
        print("[Agent 4 - Verification] Original sandbox issue is verified as resolved.")
    else:
        print("[Agent 4 - Verification] Recovery could not be independently verified.")

    attempt_number = state.get("recovery_attempt", 0)
    result = {**result, "attempt_number": attempt_number}
    history = list(state.get("recovery_verification_history", []))
    history.append(result)
    return {
        "recovery_verification_result": result,
        "recovery_verification_history": history,
    }

# ==========================================
# AGENT 2: LIVE POST-RECOVERY VERIFICATION
# ==========================================

def live_recovery_verification_node(state: PenguinMedicState):
    """Assess fresh live diagnostics after an approved shell command."""

    print("\n[Agent 2 - Verification] Assessing fresh post-recovery diagnostics...")

    execution_results = state.get("execution_results", [])
    execution_result = (
        execution_results[0]
        if isinstance(execution_results, list) and execution_results
        and isinstance(execution_results[0], dict)
        else {}
    )

    try:
        assessment = investigation_agent.verify_recovery_outcome(
            original_problem=state.get("user_problem", ""),
            fresh_diagnostic_report=state.get("sanitized_report", {}),
            fresh_investigation_report=state.get("investigation_report", {}),
            execution_result=execution_result,
        )
        result = {
            "status": assessment.status.lower(),
            "issue_resolved": assessment.status == "RESOLVED",
            "evidence": assessment.evidence,
            "verification": assessment.explanation,
        }
    except Exception as error:
        result = {
            "status": "inconclusive",
            "issue_resolved": False,
            "reason": f"Live verification could not be completed: {error}",
            "evidence": [],
        }

    attempt_number = state.get("recovery_attempt", 0)
    result["attempt_number"] = attempt_number
    result["execution_status"] = execution_result.get("status", "unknown")

    plan_steps = state.get("recovery_plan", {}).get("recovery_steps", [])
    if plan_steps and isinstance(plan_steps[0], dict):
        result["action"] = sanitize_value(plan_steps[0].get("action", ""))

    history = list(state.get("recovery_verification_history", []))
    history.append(result)

    if result.get("issue_resolved") is True:
        print("[Agent 2 - Verification] Fresh evidence supports that the original issue is resolved.")
    else:
        print("[Agent 2 - Verification] The issue is unresolved or could not be confirmed resolved.")

    return {
        "recovery_verification_result": result,
        "recovery_verification_history": history,
        "pending_live_verification": False,
    }


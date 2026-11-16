
import os
import json

from dotenv import load_dotenv
from openai import OpenAI, APIError
from pydantic import BaseModel, Field, ConfigDict, ValidationError
from typing import Literal

from skills.loader import load_skill


load_dotenv()


# ==========================================
# RECOVERY STEP SCHEMA
# ==========================================

class RecoveryStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_number: int
    action: str

    command: str = Field(
        description=(
            "The exact shell command to be reviewed and approved by the user "
            "in live mode, or a registered sandbox operation identifier in "
            "sandbox mode. Never claim it has already executed."
        )
    )

    explanation: str
    risk_level: Literal["low", "medium", "high"]
    requires_sudo: bool
    expected_result: str
    rollback_notes: str


# ==========================================
# RECOVERY PLAN SCHEMA
# ==========================================

class RecoveryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal[
        "MORE_INFORMATION_REQUIRED",
        "RECOVERY_PLAN_READY",
        "CANNOT_SAFELY_PROCEED"
    ]

    decision_reason: str

    problem_summary: str

    evidence_basis: list[str]

    missing_information: list[str]

    questions_for_user: list[str]

    proposed_solution: str

    prerequisites: list[str]

    recovery_steps: list[RecoveryStep]

    overall_risk: Literal["low", "medium", "high"]

    warnings: list[str]

    approval_required: bool

    plan_summary: str


# ==========================================
# APPLICATION-LEVEL PLAN VALIDATION
# ==========================================

def validate_plan_logic(plan: RecoveryPlan) -> RecoveryPlan:
    """Enforce application-level recovery plan rules."""

    if plan.decision in {
        "MORE_INFORMATION_REQUIRED",
        "CANNOT_SAFELY_PROCEED"
    }:

        if plan.recovery_steps:
            raise ValueError(
                "Agent 3 generated recovery steps despite "
                "not being authorized by its decision."
            )

    if plan.decision == "MORE_INFORMATION_REQUIRED":

        if not (
            plan.missing_information
            or plan.questions_for_user
        ):
            raise ValueError(
                "Agent 3 requested more information but "
                "did not specify what information is needed."
            )

    if plan.decision == "RECOVERY_PLAN_READY":

        if not plan.recovery_steps:
            raise ValueError(
                "Agent 3 declared recovery ready "
                "without generating recovery steps."
            )

        if not plan.evidence_basis:
            raise ValueError(
                "Recovery plan has no supporting evidence."
            )

        if not plan.proposed_solution.strip():
            raise ValueError(
                "Recovery plan has no proposed solution."
            )

    # Application always enforces human approval.
    plan.approval_required = True

    return plan


# ==========================================
# EXPLICIT OPERATING-MODE RESOLUTION
# ==========================================

def resolve_solution_mode(
    *,
    sandbox_test_mode: bool,
    live_diagnostic_mode: bool,
    live_recovery_mode: bool,
) -> Literal["sandbox", "live_diagnostic", "live_recovery"]:
    """Resolve exactly one operating mode; never infer sandbox from False."""

    active_modes = [
        mode
        for enabled, mode in (
            (sandbox_test_mode, "sandbox"),
            (live_diagnostic_mode, "live_diagnostic"),
            (live_recovery_mode, "live_recovery"),
        )
        if enabled is True
    ]

    if len(active_modes) != 1:
        raise ValueError(
            "Exactly one PenguinMedic operating mode must be active; "
            f"received {active_modes or 'no active mode'}."
        )

    return active_modes[0]


def mode_instructions(
    operating_mode: Literal["sandbox", "live_diagnostic", "live_recovery"]
) -> str:
    """Return instructions that match the explicitly selected mode."""

    if operating_mode == "sandbox":
        return """
SANDBOX DEMONSTRATION MODE:
- Use only the exact sandbox operations described in the loaded recovery skill.
- Do not generate arbitrary shell commands or request sudo.
- Never propose a live-system repair command in this mode.
"""

    if operating_mode == "live_diagnostic":
        return """
LIVE DIAGNOSTICS-ONLY MODE:
- You are investigating the user's actual Linux installation, not a sandbox.
- The sandbox fixture operations described elsewhere in the recovery skill
  are completely inapplicable. Never propose either sandbox operation.
- You may describe a plausible real Linux recovery approach and its exact
  candidate command for informational reporting, when evidence supports it.
- These are recommendations only. This mode is strictly read-only: no command
  will be approved or executed, and you must not imply otherwise.
- Prefer MORE_INFORMATION_REQUIRED when evidence is insufficient.
- Never invent paths, package names, versions, services, or system state.
"""

    if operating_mode == "live_recovery":
        return """
LIVE SYSTEM RECOVERY MODE:
- You are working with the user's actual Linux installation, not a sandbox.
- The sandbox fixture operations described elsewhere in the recovery skill
  are completely inapplicable. Never propose either sandbox operation.
- You may propose normal Linux shell commands, including commands not present
  in any application registry.
- The application displays the exact command string and requires an explicit
  YES from the human before execution. NO means nothing is executed.
- Generate one recovery step per plan. The command may use normal shell syntax
  when genuinely needed.
- Set requires_sudo=true when the command explicitly uses sudo or otherwise
  requires elevated privileges. Do not hide privilege requirements.
- Explain effects, expected result, risk, prerequisites, and realistic rollback.
- Prefer the smallest targeted repair supported by evidence. Avoid unrelated
  cleanup, upgrades, or maintenance.
- Never claim the command has executed or that approval has been granted.
- If evidence does not justify a command, request more information or decline.
"""

    raise ValueError(f"Unsupported operating mode: {operating_mode!r}")


# ==========================================
# AGENT 3: SOLUTION GENERATION AGENT
# ==========================================

class SolutionAgent:

    def __init__(self):

        api_key = os.getenv("GROQ_API_KEY")

        if not api_key:
            raise ValueError("GROQ_API_KEY not found in .env")

        self.client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=api_key
        )

        self.model = "openai/gpt-oss-20b"

        self.system_prompt = """
You are Agent 3: Solution Generation Agent of PenguinMedic.

You receive a diagnostic report from Agent 1 and an investigation
report from Agent 2. Decide whether the available evidence justifies
a supported recovery operation and produce the structured RecoveryPlan
required by the application.

The RecoveryPlan fields are:
- decision
- decision_reason
- problem_summary
- evidence_basis
- missing_information
- questions_for_user
- proposed_solution
- prerequisites
- recovery_steps
- overall_risk
- warnings
- approval_required
- plan_summary

Each recovery step must satisfy the RecoveryStep schema:
- step_number
- action
- command
- explanation
- risk_level
- requires_sudo
- expected_result
- rollback_notes

Follow the externally loaded recovery skill for evidence-based
recovery decisions, risk analysis, approval, and agent responsibilities.
You propose commands but never execute them.
"""
        self.system_prompt += "\n\n--- LOADED SAFE RECOVERY SKILL ---\n" + load_skill("recovery.md")
    # ==========================================
    # GENERATE RECOVERY PLAN
    # ==========================================

    def generate_solution(
        self,
        diagnostic_report: dict,
        investigation_report: dict,
        operating_mode: Literal["sandbox", "live_diagnostic", "live_recovery"] | None = None,
        live_mode: bool | None = None,
    ) -> RecoveryPlan:
        # Backward compatibility for earlier direct callers. New workflow code
        # always supplies the explicit three-state operating_mode.
        if operating_mode is None:
            operating_mode = "live_recovery" if live_mode is True else "sandbox"
        elif live_mode is not None:
            raise ValueError(
                "Pass operating_mode or legacy live_mode, not both."
            )

        if operating_mode not in {"sandbox", "live_diagnostic", "live_recovery"}:
            raise ValueError(f"Unsupported operating mode: {operating_mode!r}")

        def compact_evidence(value, *, depth=0):
            """Bound report size while retaining structured, recent evidence."""
            if depth >= 6:
                return str(value)[:500]
            if isinstance(value, str):
                return value if len(value) <= 900 else value[:900] + " ...[truncated]"
            if isinstance(value, list):
                return [
                    compact_evidence(item, depth=depth + 1)
                    for item in value[-8:]
                ]
            if isinstance(value, dict):
                compacted = {}
                for index, (key, item) in enumerate(value.items()):
                    if index >= 35:
                        compacted["_omitted_fields"] = len(value) - 35
                        break
                    compacted[str(key)] = compact_evidence(
                        item, depth=depth + 1
                    )
                return compacted
            if value is None or isinstance(value, (bool, int, float)):
                return value
            return str(value)[:500]

        input_data = {
            "diagnostic_report": compact_evidence(diagnostic_report),
            "investigation_report": compact_evidence(investigation_report),
        }
        serialized_input = json.dumps(input_data, separators=(",", ":"))

        # Keep the evidence as valid JSON. Never slice the serialized JSON
        # string, because doing so can silently remove the exact diagnostic
        # fields Agent 3 needs (or leave a malformed payload).
        max_input_chars = 12000
        if len(serialized_input) > max_input_chars:
            priority_keys = {
                "additional_diagnostic_results", "inspect_systemd_unit",
                "requested_file_inspection", "properties",
                "command_file_checks", "ExecMainStatus", "ExecMainCode",
                "ExecStart", "Result", "Transient", "FragmentPath",
                "journal_entries", "path", "exists",
                "is_file", "is_symlink", "readable_by_current_process",
                "likely_root_causes", "supporting_evidence",
                "contradicting_evidence", "confidence",
                "investigation_summary",
            }

            def budget_compact(value, *, depth=0):
                if depth >= 6:
                    return str(value)[:250]
                if isinstance(value, str):
                    return value if len(value) <= 350 else value[:350] + " ...[trimmed]"
                if isinstance(value, list):
                    return [
                        budget_compact(item, depth=depth + 1)
                        for item in value[-4:]
                    ]
                if isinstance(value, dict):
                    items = sorted(
                        value.items(),
                        key=lambda pair: (
                            0 if str(pair[0]) in priority_keys else 1
                        ),
                    )
                    compacted = {}
                    for key, item in items[:30]:
                        compacted[str(key)] = budget_compact(
                            item, depth=depth + 1
                        )
                    omitted = len(items) - len(compacted)
                    if omitted:
                        compacted["_omitted_fields"] = omitted
                    return compacted
                if value is None or isinstance(value, (bool, int, float)):
                    return value
                return str(value)[:250]

            input_data = budget_compact(input_data)
            serialized_input = json.dumps(input_data, separators=(",", ":"))

        if len(serialized_input) > max_input_chars:
            # Fail closed rather than send a cut-off evidence document that
            # could cause an unsupported recovery decision.
            raise ValueError(
                "Agent 3 evidence exceeds the safe prompt budget after "
                "structured compaction. No recovery plan was generated."
            )

        # Keep the complete application schema locally authoritative. Groq's
        # strict json_schema mode has returned HTTP 400 when the model emitted
        # a partial object, before our local correction loop could run. JSON
        # object mode lets us receive the response and validate/correct it
        # locally with the Pydantic RecoveryPlan model.
        output_schema = {
            "type": "object",
            "properties": {
                "decision": {
                    "type": "string",
                    "enum": [
                        "MORE_INFORMATION_REQUIRED",
                        "RECOVERY_PLAN_READY",
                        "CANNOT_SAFELY_PROCEED"
                    ]
                },
                "decision_reason": {"type": "string"},
                "problem_summary": {"type": "string"},
                "evidence_basis": {"type": "array", "items": {"type": "string"}},
                "missing_information": {"type": "array", "items": {"type": "string"}},
                "questions_for_user": {"type": "array", "items": {"type": "string"}},
                "proposed_solution": {"type": "string"},
                "prerequisites": {"type": "array", "items": {"type": "string"}},
                "recovery_steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step_number": {"type": "integer"},
                            "action": {"type": "string"},
                            "command": {"type": "string"},
                            "explanation": {"type": "string"},
                            "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
                            "requires_sudo": {"type": "boolean"},
                            "expected_result": {"type": "string"},
                            "rollback_notes": {"type": "string"}
                        },
                        "required": [
                            "step_number", "action", "command", "explanation",
                            "risk_level", "requires_sudo", "expected_result", "rollback_notes"
                        ],
                        "additionalProperties": False
                    }
                },
                "overall_risk": {"type": "string", "enum": ["low", "medium", "high"]},
                "warnings": {"type": "array", "items": {"type": "string"}},
                "approval_required": {"type": "boolean"},
                "plan_summary": {"type": "string"}
            },
            "required": [
                "decision", "decision_reason", "problem_summary", "evidence_basis",
                "missing_information", "questions_for_user", "proposed_solution",
                "prerequisites", "recovery_steps", "overall_risk", "warnings",
                "approval_required", "plan_summary"
            ],
            "additionalProperties": False
        }

        user_prompt = (
            "Return a RecoveryPlan as JSON. Use only the supplied diagnostic "
            "and investigation evidence. Do not invent observations, commands, "
            "prerequisites, or evidence. Consider previous_recovery_attempts "
            "when supplied; do not repeat a failed command without a clear "
            "evidence-based reason. Follow the active operating-mode "
            "instructions in the system message when proposing commands. For unknown or inapplicable list values, "
            "use empty arrays. If evidence is insufficient, choose "
            "MORE_INFORMATION_REQUIRED or CANNOT_SAFELY_PROCEED and return "
            "an empty recovery_steps array. Human approval is always required.\n"
            "You MUST return every top-level property in the schema below, "
            "even when its value is empty. Do not stop after evidence_basis. "
            "Each recovery_steps item must include all eight step properties. "
            "Return one complete JSON object, with no Markdown fences.\n\n"
            "Return every required RecoveryPlan field and all eight fields "
            "for each recovery step. Use the JSON response format.\\n\\n"
            "Reports:\\n" + serialized_input
        )

        mode_prompt = mode_instructions(operating_mode)

        messages = [
            {"role": "system", "content": self.system_prompt + "\n\n" + mode_prompt},
            {"role": "user", "content": user_prompt}
        ]

        last_error = None

        # One correction attempt is allowed. A second invalid result fails
        # closed and is never converted into an executable recovery plan.
        for attempt in range(2):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_completion_tokens=2500,
                    reasoning_effort="low",
                    messages=messages,
                    temperature=0.1,
                    response_format={"type": "json_object"}
                )
            except APIError as exc:
                # Preserve the provider's actual diagnostic details. A provider
                # generation error occurs before local Pydantic validation.
                details = getattr(exc, "body", None)
                if details is None:
                    details = str(exc)
                elif not isinstance(details, str):
                    details = json.dumps(details, default=str)
                raise RuntimeError(
                    "Groq failed while generating Agent 3's structured "
                    f"RecoveryPlan (HTTP {getattr(exc, 'status_code', 'unknown')}): "
                    f"{details}"
                ) from exc

            result = response.choices[0].message.content

            if not result or not result.strip():
                last_error = "The model returned an empty response."
            else:
                try:
                    plan = RecoveryPlan.model_validate_json(result)
                    plan = validate_plan_logic(plan)
                    return plan
                except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                    last_error = (
                        f"{type(exc).__name__}: {exc}; "
                        f"finish_reason={response.choices[0].finish_reason}"
                    )

            if attempt == 0:
                messages.extend([
                    {"role": "assistant", "content": result or ""},
                    {
                        "role": "user",
                        "content": (
                            "Your previous response did not pass PenguinMedic's "
                            "local RecoveryPlan validation. Correct the JSON and "
                            "return the complete object again. Do not remove "
                            "required fields, weaken safety rules, or invent "
                            "evidence. Preserve the original decision unless "
                            "the supplied evidence requires a different safe "
                            "decision.\n\n"
                            "Validation failure:\n"
                            + str(last_error)
                            + "\n\nReturn only the corrected JSON object."
                        )
                    }
                ])

        raise ValueError(
            "Agent 3 could not produce a valid RecoveryPlan after one "
            "correction attempt. No recovery plan was accepted. "
            f"Final validation error: {last_error}"
        )


# ==========================================
# STANDALONE TEST
# ==========================================

if __name__ == "__main__":

    agent = SolutionAgent()

    sample_diagnostic = {
        "issue_category": "Package Management Failure",
        "problem_summary": "Arch Linux update failure with missing packages.",
        "confirmed_observations": [
            "Pacman database integrity check passed.",
            "Recent transactions completed successfully.",
            "Root filesystem has sufficient free space."
        ],
        "possible_explanations": [
            "The failure may have occurred outside the reviewed log window."
        ],
        "missing_information": [
            "Exact names of missing packages.",
            "Original update error message."
        ],
        "handoff_summary": "More information is needed to confirm the failure."
    }

    sample_investigation = {
        "likely_root_causes": [
            "The failure may not be reflected in recent transaction logs."
        ],
        "supporting_evidence": [
            "Recent transactions completed successfully."
        ],
        "contradicting_evidence": [
            "No explicit package transaction failure was found."
        ],
        "additional_checks": [
            "Identify the exact package names reported as missing.",
            "Obtain the original package update error message."
        ],
        "confidence": "Low",
        "investigation_summary": (
            "There is insufficient evidence to establish a root cause."
        )
    }

    print("\n[Agent 3] Generating recovery plan...\n")

    plan = agent.generate_solution(
        sample_diagnostic,
        sample_investigation
    )

    print(plan.model_dump_json(indent=4))


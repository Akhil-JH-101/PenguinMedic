
import os
import json

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ConfigDict, ValidationError, model_validator
from typing import Literal
from openai import OpenAI

from skills.loader import load_skill
from tools.privacy_filter import sanitize_value



load_dotenv()


class InvestigationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    likely_root_causes: list[str]
    supporting_evidence: list[str]
    contradicting_evidence: list[str]
    additional_checks: list[str]
    confidence: str
    investigation_summary: str



class RecoveryVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["RESOLVED", "UNRESOLVED", "INCONCLUSIVE"]
    evidence: list[str]
    explanation: str

    @model_validator(mode="after")
    def require_evidence_for_conclusive_results(self):
        if self.status in {"RESOLVED", "UNRESOLVED"} and not self.evidence:
            raise ValueError("Conclusive verification requires supporting evidence.")
        if not self.explanation.strip():
            raise ValueError("Verification explanation must not be empty.")
        return self


class InvestigationAgent:

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
You are Agent 2: Cloud Investigation Agent of PenguinMedic.

Investigate the Linux problem using the diagnostic evidence supplied
by the application. The report may include original evidence and
additional results collected during later diagnostic rounds.

Return every field required by the InvestigationReport schema:
- likely_root_causes
- supporting_evidence
- contradicting_evidence
- additional_checks
- confidence
- investigation_summary

Follow the externally loaded diagnostics skill for evidence handling,
investigation policy, uncertainty, and safety boundaries.
"""
        self.system_prompt += "\n\n--- LOADED DIAGNOSTICS SKILL ---\n" + load_skill("diagnostics.md")
    def investigate(self, diagnostic_report: dict):
        """Generate and locally validate a complete investigation report.

        JSON-object mode avoids provider-side strict-schema rejection before
        the application can inspect the model response. Pydantic remains the
        authoritative schema, and one correction attempt is allowed.
        """

        # Pydantic remains authoritative; do not duplicate its generated
        # schema in the prompt because the field list is sufficient guidance.
        user_prompt = (
            "Investigate the diagnostic report and return exactly one JSON "
            "object with ALL SIX keys: "
            "likely_root_causes (array of strings), "
            "supporting_evidence (array of strings), "
            "contradicting_evidence (array of strings), "
            "additional_checks (array of strings), "
            "confidence (string), and investigation_summary (string).\\n"
            "Every key is mandatory. Use [] when an array has no supported "
            "items. Use 'Low' confidence when evidence is insufficient. "
            "Use only supplied evidence. Do not invent observations or "
            "recommend repairs. Return JSON only.\\n\\n"
            "Diagnostic report:\\n"
            + json.dumps(diagnostic_report, separators=(",", ":"), default=str)
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        last_error = None

        for attempt in range(2):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_completion_tokens=2000,
                reasoning_effort="low",
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            result = response.choices[0].message.content
            finish_reason = response.choices[0].finish_reason

            payload = None
            if not result or not result.strip():
                last_error = (
                    "The model returned an empty response. "
                    f"finish_reason={finish_reason}"
                )
            else:
                try:
                    payload = json.loads(result)
                    if not isinstance(payload, dict):
                        raise ValueError("The response must be a JSON object.")
                    return InvestigationReport.model_validate(payload)
                except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                    last_error = (
                        f"{type(exc).__name__}: {exc}; "
                        f"finish_reason={finish_reason}"
                    )

            if attempt == 0:
                missing = []
                if isinstance(payload, dict):
                    missing = [
                        name for name in InvestigationReport.model_fields
                        if name not in payload
                    ]
                messages.extend([
                    {"role": "assistant", "content": result or "{}"},
                    {
                        "role": "user",
                        "content": (
                            "Correct the JSON. Return all six keys, even if "
                            "some values are empty. Missing keys: "
                            + (", ".join(missing) if missing else "see validation error")
                            + ". Arrays must be arrays of strings. confidence "
                            "and investigation_summary must be strings. Use "
                            "only supplied evidence; do not invent findings. "
                            "Return JSON only."
                        ),
                    },
                ])
            elif isinstance(payload, dict):
                # Fail-soft only for valid JSON objects with omitted fields.
                # Unknown evidence stays unknown; nothing is fabricated.
                required = set(InvestigationReport.model_fields)
                extras = set(payload) - required
                if not extras:
                    missing = required - set(payload)
                    for field in (
                        "likely_root_causes",
                        "supporting_evidence",
                        "contradicting_evidence",
                        "additional_checks",
                    ):
                        if field not in payload:
                            payload[field] = []
                    if "confidence" not in payload:
                        payload["confidence"] = "Low"
                    if "investigation_summary" not in payload:
                        payload["investigation_summary"] = (
                            "Agent 2 returned an incomplete investigation "
                            "report. Missing fields were left unknown; no "
                            "supporting or contradicting evidence was inferred. "
                            "Further investigation is required."
                        )
                    try:
                        report = InvestigationReport.model_validate(payload)
                        report.confidence = "Low"
                        report.investigation_summary += (
                            " [Caution: the model response omitted required "
                            "fields: " + ", ".join(sorted(missing)) + ".]"
                        )
                        return report
                    except ValidationError as exc:
                        last_error = (
                            f"Fallback report still failed validation: {exc}"
                        )


        raise ValueError(
            "Agent 2 could not produce a valid InvestigationReport after "
            "one correction attempt. No investigation report was accepted. "
            f"Final validation error: {last_error}"
        )


    def verify_recovery_outcome(
        self,
        original_problem: str,
        fresh_diagnostic_report: dict,
        fresh_investigation_report: dict,
        execution_result: dict,
    ) -> RecoveryVerification:
        """Assess the original issue using fresh post-command evidence.

        The command text and raw stdout/stderr are deliberately not sent to
        Groq. Verification must be based on the new diagnostic evidence, not
        on the command's claimed purpose or exit code alone.
        """
        safe_input = {
            "original_problem": sanitize_value(original_problem),
            "fresh_diagnostic_report": sanitize_value(fresh_diagnostic_report),
            "fresh_investigation_report": sanitize_value(fresh_investigation_report),
            "execution_metadata": {
                "status": execution_result.get("status"),
                "exit_code": execution_result.get("exit_code"),
                "timed_out": execution_result.get("status") == "timeout",
            },
        }
        schema = RecoveryVerification.model_json_schema()
        system = """
You are Agent 2 performing PenguinMedic's post-recovery verification.
You must determine whether the user's ORIGINAL reported issue is now
resolved using only the FRESH post-execution diagnostic report and fresh
investigation report supplied to you.

Rules:
- Do not infer success from exit_code=0 or from the fact a command ran.
- Do not use old diagnostic evidence. The supplied reports are the fresh check.
- RESOLVED only when fresh evidence directly supports that the original
  symptom/condition is gone.
- UNRESOLVED when fresh evidence shows the original issue persists.
- INCONCLUSIVE when the relevant condition was not checked, evidence is
  insufficient, or findings conflict.
- Never invent observations. Cite the actual supplied evidence in `evidence`.
- Return one JSON object with exactly: status, evidence, explanation.
"""
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    "Assess the recovery using this fresh evidence. Return a "
                    "complete JSON object matching the schema.\n\nSchema:\n"
                    + json.dumps(schema, indent=2)
                    + "\n\nEvidence:\n"
                    + json.dumps(safe_input, indent=2)
                ),
            },
        ]
        last_error = None
        for attempt in range(2):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_completion_tokens=3000,
                reasoning_effort="low",
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if content and content.strip():
                try:
                    return RecoveryVerification.model_validate_json(content)
                except (ValidationError, ValueError) as exc:
                    last_error = str(exc)
            else:
                last_error = "The model returned an empty verification response."
            if attempt == 0:
                messages.extend([
                    {"role": "assistant", "content": content or ""},
                    {
                        "role": "user",
                        "content": (
                            "The previous response failed schema validation: "
                            + str(last_error)
                            + ". Return the complete JSON object with status "
                            "RESOLVED, UNRESOLVED, or INCONCLUSIVE, plus evidence "
                            "and explanation. Return JSON only."
                        ),
                    },
                ])
        raise ValueError(
            "Post-recovery verification could not produce a valid result: "
            + str(last_error)
        )




if __name__ == "__main__":

    agent = InvestigationAgent()

    sample_report = {
        "issue_category": "Package Management Failure",
        "problem_summary": "Arch Linux update failure with missing packages.",
        "confirmed_observations": [
            "Recent Pacman transactions completed successfully.",
            "Root disk has sufficient free space.",
            "No explicit package transaction failure was found."
        ],
        "possible_explanations": [
            "The reported missing packages may not match recent transactions."
        ],
        "missing_information": [
            "Exact names of missing packages.",
            "Full package update error output."
        ],
        "handoff_summary": "Further investigation of package state is required."
    }

    print("\n[Agent 2 - Groq] Investigating diagnostic evidence...\n")

    report = agent.investigate(sample_report)

    print(report.model_dump_json(indent=4))


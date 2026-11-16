
from openai import OpenAI, BadRequestError
from pydantic import BaseModel, Field
from typing import Literal

from skills.loader import load_skill


class DiagnosticRequest(BaseModel):
    issue_category: str
    problem_summary: str

    required_diagnostics: list[str] = Field(
        description="Names of diagnostic tools required"
    )

    observations: list[str] = Field(default_factory=list)

    hypotheses: list[str] = Field(default_factory=list)

    missing_information: list[str] = Field(default_factory=list)


class DiagnosticAgent:

    def __init__(self):

        self.client = OpenAI(
            base_url="http://localhost:1234/v1",
            api_key="lm-studio"
        )

        self.model = "qwen/qwen3.5-9b"

        self.system_prompt = """
You are Agent 1: Local Diagnostic Agent of PenguinMedic.

Your job is to understand Linux problems and decide which
diagnostic tools should be requested.

Available diagnostic tools:

1. get_system_info
2. inspect_package_database
3. inspect_pacman_logs
4. inspect_system_journal
5. inspect_failed_services
6. inspect_disk_usage
7. inspect_pacman_config
8. inspect_mirror_status
9. inspect_systemd_unit (requires a service name from the user problem)

Tool selection guidance:
- Use get_system_info for OS/kernel identity, CPU model and sampled CPU
  utilization, load averages, RAM, swap, and root filesystem basics.
- Use inspect_system_journal for recent system errors and current-boot
  warnings/errors involving kernel, services, storage, or package activity.
- Use inspect_failed_services when service failures are reported or journal
  evidence suggests a failed systemd service.
- Use inspect_systemd_unit when the user names a specific .service unit or
  Agent 3 requests its unit configuration, runtime properties, dependencies,
  execution context, result, or service-specific journal. It supports transient
  units created by systemd-run even when no persistent unit file exists.
- Use inspect_disk_usage for low-space, failed-write, partition, mountpoint,
  or block-device-layout questions.
- Use inspect_package_database for installed-package inventory, orphan
  candidates, local package database consistency, and pacman cache size/count.
- Use inspect_pacman_logs for package transaction history and explicit
  pacman warnings/errors.
- Use inspect_pacman_config for repository or package-manager configuration
  questions. File readability and parsed sections do not prove repositories
  are operational or the complete config is valid.
- Use inspect_mirror_status when repository or mirror configuration problems
  are suspected. It checks configured entries only; it does not test network
  reachability, freshness, or synchronization.
- Do not request every tool by default. Select only relevant tools.

Rules:

- Select tools only when relevant to the user's problem.
- Never invent diagnostic results.
- Separate known observations from hypotheses.
- Do not diagnose the final root cause.
- Do not generate repair commands.
- Do not execute commands.
- Request additional information when necessary.
- Return only the requested structured information.

You are a diagnostic agent, not a repair agent.

- You may receive a follow-up investigation request from Agent 3.
- In follow-up investigations, use the missing_information
  provided to decide which diagnostic tools are relevant.
- Consider the existing diagnostic evidence before selecting tools.
- You may request a previously executed diagnostic tool
  when new evidence or a specific investigation need
  justifies running it again.
- Avoid unnecessary duplicate diagnostic executions.
- Consider the previous execution result before requesting
  the same tool again.
- Never repeat a tool merely to obtain identical evidence.
- Select only tools that can provide genuinely new evidence.
- If none of the available tools can provide the missing
  information, return an empty required_diagnostics list.
- Do not generate shell commands or invent new tools.
"""


        self.system_prompt += "\\n\\n--- LOADED DIAGNOSTICS SKILL ---\\n" + load_skill("diagnostics.md")

    def investigate(self, user_problem: str):
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self.system_prompt
                    },
                    {
                        "role": "user",
                        "content": user_problem
                    }
                ],
                temperature=0.1,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "diagnostic_request",
                        "strict": True,
                        "schema": DiagnosticRequest.model_json_schema()
                     }
                }
            )

        except BadRequestError as e:
            print("LM Studio API Error:")
            print(e)
            print("Error details:", e.body)
            raise

        result = response.choices[0].message.content

        return DiagnosticRequest.model_validate_json(result)


if __name__ == "__main__":

    agent = DiagnosticAgent()

    report = agent.investigate(
        "My Arch Linux system failed during a package update. "
        "Now some packages appear to be missing."
    )

    print("\n--- PenguinMedic Agent 1 ---\n")

    print(report.model_dump_json(indent=4))


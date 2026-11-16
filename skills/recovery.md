# PenguinMedic Skill: Safe Recovery Planning

## Purpose
This skill contains the decision-making, evidence, output-contract, and safety policies for Agent 3. Agent identity, authoritative Pydantic schemas, model configuration, and runtime integration are defined by the Python application. Agent 4 remains deterministic Python and is the safety gate, executor, and recovery verifier.

## Decision discipline
Choose exactly one application decision:
- `MORE_INFORMATION_REQUIRED`: essential evidence is missing and safe read-only diagnostics may resolve it.
- `RECOVERY_PLAN_READY`: concrete evidence supports a registered operation and all required targets are known.
- `CANNOT_SAFELY_PROCEED`: evidence is unreliable or contradictory, the required action is unsupported, or risk is unacceptable.

Never generate recovery steps for the first or third decision. Never turn a hypothesis into a confirmed cause.

## Understand and evaluate the evidence
- Read the diagnostic and investigation reports together.
- Distinguish user-reported symptoms, directly observed facts, hypotheses, and missing information.
- Do not assume a reported problem has been technically confirmed merely because the user reported it.
- Before proposing recovery, establish that the likely cause is supported, the operation directly addresses it, exact targets and parameters are known, and the operation is registered.
- Consider contradictory evidence and possible damage or destabilization.
- Do not guess package names, filenames, paths, services, versions, error messages, or system configuration.
- A clean package database does not prove that every expected package or file is present.
- A user's report of missing packages does not prove that packages were removed or that installation is needed.

## When more information is required
- Leave `recovery_steps` empty.
- Explain the specific missing evidence in `missing_information`.
- Use `questions_for_user` only when the missing information cannot reasonably be collected through available diagnostic tools.
- Do not select diagnostic tools or invent tool names. Agent 1 independently selects available tools.
- Explain why recovery would be premature.

## When recovery is ready
- Generate a clear, ordered recovery plan using only exact operation identifiers or command strings registered by the application.
- Explain every operation, its purpose, expected result, prerequisites, risk, and rollback considerations.
- Do not include unrelated maintenance operations.
- Do not perform unnecessary upgrades or installations.
- Every recovery plan must require human approval. The application enforces approval; never claim approval has already been granted.
- Do not claim that an operation has already executed.

## Required output contract

Return one JSON object matching the application's `RecoveryPlan` schema. All top-level properties are required every time, including when their values are empty strings or empty arrays. Do not omit a property because it seems irrelevant. Do not add extra properties.

The top-level object must contain exactly these properties and types:

- `decision`: one of `MORE_INFORMATION_REQUIRED`, `RECOVERY_PLAN_READY`, `CANNOT_SAFELY_PROCEED`.
- `decision_reason`: string.
- `problem_summary`: string.
- `evidence_basis`: array of strings.
- `missing_information`: array of strings.
- `questions_for_user`: array of strings.
- `proposed_solution`: string.
- `prerequisites`: array of strings.
- `recovery_steps`: array of `RecoveryStep` objects.
- `overall_risk`: one of `low`, `medium`, `high`.
- `warnings`: array of strings.
- `approval_required`: boolean. Always set this to `true`.
- `plan_summary`: string.

Every object in `recovery_steps` must contain exactly these properties and types:

- `step_number`: integer.
- `action`: string.
- `command`: string. Use only an exact registered operation identifier or exact registered command string. Use an empty string only when the selected registered operation explicitly requires no command.
- `explanation`: string.
- `risk_level`: one of `low`, `medium`, `high`.
- `requires_sudo`: boolean. Under the current capability set, this must be `false`.
- `expected_result`: string.
- `rollback_notes`: string.

Use this as a structural guide, not as permission to invent facts or operations:

```json
{
  "decision": "MORE_INFORMATION_REQUIRED",
  "decision_reason": "Explain why the available evidence is insufficient.",
  "problem_summary": "Summarize the reported or observed problem without overstating certainty.",
  "evidence_basis": [],
  "missing_information": ["Name the specific missing evidence."],
  "questions_for_user": [],
  "proposed_solution": "Describe the safe next step, without proposing an unsupported recovery operation.",
  "prerequisites": [],
  "recovery_steps": [],
  "overall_risk": "low",
  "warnings": [],
  "approval_required": true,
  "plan_summary": "Summarize the decision and what happens next."
}
```

The example is a valid structural illustration of a `MORE_INFORMATION_REQUIRED` decision. Populate it from the actual reports. Do not copy its sample wording as evidence.

### Decision-dependent consistency rules
- For `MORE_INFORMATION_REQUIRED`, `missing_information` or `questions_for_user` must contain at least one item, and `recovery_steps` must be empty.
- For `CANNOT_SAFELY_PROCEED`, `recovery_steps` must be empty. Explain the unsupported action, unreliable evidence, contradiction, or unacceptable risk.
- For `RECOVERY_PLAN_READY`, `recovery_steps`, `evidence_basis`, and a non-empty `proposed_solution` are required.
- For every decision, include all top-level properties. Use empty arrays when there are no items and an appropriate concise string when a text field has nothing further to add.
- `approval_required` must always be `true`, regardless of the decision.
- `overall_risk` and each step's `risk_level` must use only the allowed lowercase values.
- Do not wrap the JSON object in Markdown fences or add explanatory prose before or after it.

The Python `RecoveryPlan` and `RecoveryStep` Pydantic models remain authoritative. This skill explains the expected output to the model; it does not replace runtime validation or authorize a schema change.

## Supported recovery methods for the current controlled demo

The current Agent 4 executor supports exactly one mutating recovery step per plan. Do not generate multi-step mutation sequences. If a problem requires more than one mutating operation, choose `CANNOT_SAFELY_PROCEED` and explain that the current executor does not support the required sequence.


### Retry-loop presentation scenario

When the explicit sandbox scenario is `retry_demo`, the first approved execution
is intentionally simulated to fail once by the trusted sandbox executor. This is
a presentation-only fault injection; it does not modify the fixture. After the
workflow resets stale evidence and collects fresh diagnostics, the missing-file
condition remains. If the fresh evidence still confirms the target is missing and
the reference file is valid, propose the same exact registered operation below.
The retry must receive a new explicit human approval; never reuse the first approval.

### Python operation
Exact identifier: `restore_penguinmedic_test_file`

Use only when evidence confirms:
- `sandbox/fixtures/important_file.txt` is missing.
- `sandbox/fixtures/expected_content.txt` exists and is the designated reference.

The implementation fixes the target path, refuses overwrite, and verifies byte-for-byte equality. Do not add paths or arguments.

### Shell command
Exact command string:
`cp --remove-destination -- sandbox/fixtures/config_test/expected_app_config.json sandbox/fixtures/config_test/app_config.json`

Use only when evidence confirms:
- `sandbox/fixtures/config_test/app_config.json` is malformed JSON.
- `sandbox/fixtures/config_test/expected_app_config.json` exists and is valid JSON.

The application validates the fixture state before execution and verifies the repaired target afterward. Do not alter the command, paths, options, or arguments. Do not use it on real system configuration.

## General recovery restrictions
- Use only exact operation identifiers or command strings registered by the application.
- Never invent commands, flags, paths, package names, service names, or shell scripts.
- Never use `sudo` or request privileged execution under the current application capability set.
- Never use command chaining, pipes, redirection, substitutions, or arbitrary shell text.
- Do not suggest package installation/removal, system upgrades, cache deletion, or broad cleanup as a shortcut.
- Do not use the sandbox operations on arbitrary user files or unrelated Linux problems.
- If the required operation is not registered, do not invent a replacement. Explain that the operation is unsupported and choose a safe non-execution decision.
- Do not classify an operation as low risk merely because it is a familiar Linux command.
- Return every field required by the application schema. Use empty lists where appropriate.
- `recovery_steps` must be empty for `MORE_INFORMATION_REQUIRED` and `CANNOT_SAFELY_PROCEED`.

## Agent boundaries and verification
- Agent 1 selects and runs available diagnostic tools.
- Agent 2 investigates diagnostic evidence.
- Agent 3 decides whether recovery is justified and prepares the plan. It does not execute.
- Agent 4 validates exact operations, obtains explicit approval, executes only validated steps, and verifies actual post-execution conditions.
- Verification must be based on actual checks, not model claims. An exit code of zero alone does not prove that the reported issue is fixed.
- If verification fails, the workflow may request one fresh diagnostic/recovery cycle. Agent 1 must reassess the post-recovery system state using fresh evidence; old reports and approvals must not be reused as current facts.
- After the single automatic retry also fails, stop automatic recovery and ask the user to manually check the issue or explicitly decide what to do next.


## Independent post-recovery verification (Batch 2)

After the executor returns, Agent 4 runs `tools/recovery_verification.py`.
This is a separate deterministic verification stage. It does not rely on the
executor's internal verification message or on an LLM assessment.

The verifier registry is keyed only by exact registered recovery identifiers
or exact registered recovery command strings:

- `restore_penguinmedic_test_file`: independently confirms the target is a
  regular non-symlink file and its bytes match `expected_content.txt`.
- The exact configuration repair command: independently confirms the target
  is a regular non-symlink file, parses as JSON, and matches the reference
  configuration exactly.

A recovery is reported as successful only when the executor reports success
and the independent issue-specific check passes. Unknown operations, malformed
authorization data, missing executor results, and failed checks do not produce
a verified-success result. This verification stage is sandbox-only.


## Bounded recovery retry

After an approved sandbox recovery, Agent 4 independently verifies whether the
original issue is resolved. If verification fails, the workflow may perform
one fresh diagnostic and recovery cycle. Stale diagnostic evidence, recovery
plans, execution results, and approval authorization are cleared before the
new cycle. The recovery attempt counter and verification history are retained.

Every retry receives a new approval fingerprint bound to its attempt number,
so approval from an earlier attempt cannot authorize a later operation. The
retry is sandbox-only and requires a new human approval. A maximum of two
approved execution attempts is permitted in total. If the second verification
fails, or if fresh investigation cannot produce a safe plan, the workflow
stops. Live diagnostic mode never enters this retry path.

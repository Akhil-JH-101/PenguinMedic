import uuid

from graph.workflow import build_graph
from langgraph.types import Command

from tools.sandbox_recovery import prepare_sandbox_scenario


SCENARIOS = {
    "1": {
        "key": "missing_file",
        "title": "Missing File Recovery",
        "problem": (
            "The PenguinMedic sandbox recovery test file is missing. "
            "Please investigate the problem."
        ),
    },
    "2": {
        "key": "broken_config",
        "title": "Broken Configuration Recovery",
        "problem": (
            "The PenguinMedic sandbox application configuration contains "
            "invalid JSON. Please investigate the problem."
        ),
    },
    "3": {
        "key": "retry_demo",
        "title": "Recovery Retry Loop (one simulated failure)",
        "problem": (
            "The PenguinMedic sandbox recovery test file is missing. "
            "Investigate and recover the missing test file."
        ),
    },
    "4": {
        "key": "cannot_proceed_demo",
        "title": "Cannot Safely Proceed (conflicting evidence)",
        "problem": (
            "Evaluate the controlled sandbox evidence and decide whether "
            "recovery can be justified safely."
        ),
    },
}


def print_header(title):
    print(f"\n{'=' * 55}")
    print(f"  {title}")
    print(f"{'=' * 55}")


def read_input(prompt):
    """Read one line, returning None cleanly when stdin reaches EOF."""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return None


def read_multiline_input(prompt):
    """Read a one-line or multiline description, terminated by a line containing END."""
    print(prompt)
    print("Enter your description below. Type END on its own line when finished.")

    lines = []
    while True:
        try:
            line = input("> " if not lines else "... ")
        except (EOFError, KeyboardInterrupt):
            return None

        if line.strip().upper() == "END":
            break

        lines.append(line)

    return "\n".join(lines).strip()


def print_list(items, empty_message="None"):
    if not items:
        print(f"  {empty_message}")
        return

    for item in items:
        print(f"  - {item}")


def select_scenario():
    """Display the test menu and return the selected scenario."""

    while True:
        print_header("PENGUINMEDIC")
        print("Select a sandbox test scenario:\n")
        print("  1. Missing File Recovery")
        print("  2. Broken Configuration Recovery")
        print("  3. Recovery Retry Loop (one simulated failure)")
        print("  4. Cannot Safely Proceed (conflicting evidence)")
        print("  5. Exit")
        print("\nRecovery scenarios use fixed sandbox fixtures; the decision-only")
        print("scenario uses synthetic conflicting evidence and changes no files.")

        choice = read_input("\nChoose an option (1-5): ")
        if choice is None:
            return None

        if choice == "5":
            return None

        if choice in SCENARIOS:
            return SCENARIOS[choice]

        print("\n[PenguinMedic] Invalid selection. Please choose 1, 2, 3, 4, or 5.")


def handle_approval(app, result, config):
    """Handle every approval interrupt, including a separately approved retry."""

    while "__interrupt__" in result:
        interrupt_data = result["__interrupt__"][0].value
        approved_steps = interrupt_data.get("approved_steps") or []
        rejected_steps = interrupt_data.get("rejected_steps") or []
        plan = interrupt_data.get("recovery_plan") or {}

        print_header("HUMAN APPROVAL REQUIRED")
        print("Recovery attempt: {} of 2".format(
            interrupt_data.get("attempt_number", "unknown")
        ))

        # Defensive guard: never ask the user to approve an empty or multi-step plan.
        if len(approved_steps) != 1:
            print("\n[PenguinMedic] Approval blocked: exactly one validated operation is required.")
            print("[PenguinMedic] Nothing will be executed.")
            approval_response = {
                "approved": False,
                "approval_id": interrupt_data.get("approval_id", ""),
            }
        else:
            print("\nProblem:")
            print(f"  {plan.get('problem_summary') or 'Not provided.'}")

            print("\nProposed solution:")
            print(f"  {plan.get('proposed_solution') or 'Not provided.'}")

            print("\nPlan summary:")
            print(f"  {plan.get('plan_summary') or 'Not provided.'}")

            print(f"\nOverall risk: {plan.get('overall_risk', 'Unknown')}")

            print("\nPrerequisites:")
            print_list(plan.get("prerequisites", []))

            print("\nWarnings:")
            print_list(plan.get("warnings", []))

            print("\nExact operation to be executed:")
            step = approved_steps[0]
            print(f"  Step: {step.get('step_number', 1)}")
            print(f"  Action: {step.get('action', 'Not provided')}")
            print(f"  Operation / command: {step.get('command', 'Not provided')}")
            print(f"  Risk: {step.get('risk_level', 'Unknown')}")
            print(f"  Requires sudo: {step.get('requires_sudo', 'Unknown')}")
            print(f"  Explanation: {step.get('explanation', 'Not provided')}")
            print(f"  Expected result: {step.get('expected_result', 'Not provided')}")
            print(f"  Rollback considerations: {step.get('rollback_notes', 'Not provided')}")

            if rejected_steps:
                print("\nRejected operations (these will NOT be executed):")
                for index, rejected in enumerate(rejected_steps, start=1):
                    print(f"  {index}. {rejected.get('action') or 'Unnamed operation'}")
                    print(f"     Reason: {rejected.get('reason') or 'Not provided'}")

            print("\nSAFETY BOUNDARY:")
            print(
                interrupt_data.get(
                    "warning",
                    "Only the single validated sandbox operation shown above can execute.",
                )
            )

            choice = read_input("\nApprove this exact operation? (yes/no): ")
            approved = choice == "yes" if choice is not None else False
            approval_response = {
                "approved": approved,
                "approval_id": interrupt_data.get("approval_id", ""),
            }

        result = app.invoke(
            Command(resume=approval_response),
            config=config,
        )

        if approval_response["approved"]:
            print("\n[PenguinMedic] Approval accepted.")
        else:
            print("\n[PenguinMedic] Approval rejected. No operation from this attempt will execute.")

    return result


def display_execution_results(results):
    """Display Agent 4 execution results."""

    print_header("AGENT 4: EXECUTION RESULTS")

    if not results:
        print("No execution results available.")
        return

    for result in results:
        status = result.get("status", "unknown").upper()

        print(f"\nStep {result.get('step_number', '?')}: {status}")

        if result.get("command"):
            print(f"Command: {result['command']}")

        if result.get("operation"):
            print(f"Operation: {result['operation']}")

        if result.get("target"):
            print(f"Target: {result['target']}")

        if result.get("verification"):
            print(f"Verification: {result['verification']}")

        if "exit_code" in result:
            print(f"Exit code: {result['exit_code']}")

        if result.get("stdout"):
            print("\nOutput:")
            print(result["stdout"].strip())

        if result.get("stderr"):
            print("\nErrors:")
            print(result["stderr"].strip())

        if result.get("reason"):
            print(f"Reason: {result['reason']}")


def display_final_result(result):
    """Display a concise workflow summary."""

    recovery_plan = result.get("recovery_plan", {})
    decision = recovery_plan.get("decision", "UNKNOWN")

    print_header("PENGUINMEDIC SUMMARY")

    print(f"\nDecision: {decision}")

    if decision == "RECOVERY_PLAN_READY":
        print("\nRecovery plan:")
        print(recovery_plan.get("proposed_solution", "No description available."))

        print("\nPlan summary:")
        print(recovery_plan.get("plan_summary", "No summary available."))

        print("\nWarnings:")
        print_list(recovery_plan.get("warnings", []))

    elif decision == "MORE_INFORMATION_REQUIRED":
        print("\nMore information is required.")
        print(recovery_plan.get("decision_reason", ""))

        print("\nMissing information:")
        print_list(recovery_plan.get("missing_information", []))

        print("\nQuestions for you:")
        print_list(recovery_plan.get("questions_for_user", []))

    elif decision == "CANNOT_SAFELY_PROCEED":
        print("\nRecovery cannot safely proceed.")
        print(recovery_plan.get("decision_reason", ""))

        print("\nWarnings:")
        print_list(recovery_plan.get("warnings", []))

    else:
        print("\nNo final recovery decision was produced.")

    if result.get("execution_results"):
        display_execution_results(result["execution_results"])

    verification = result.get("recovery_verification_result")
    if verification:
        print_header("AGENT 4: INDEPENDENT RECOVERY VERIFICATION")
        print(f"Status: {verification.get('status', 'unknown').upper()}")
        print(f"Issue resolved: {'YES' if verification.get('issue_resolved') is True else 'NO'}")
        if verification.get("target"):
            print(f"Verified target: {verification['target']}")
        if verification.get("verification"):
            print(f"Verification: {verification['verification']}")
        if verification.get("message"):
            print(verification["message"])
        if verification.get("reason"):
            print(f"Reason: {verification['reason']}")

    history = result.get("recovery_verification_history", [])
    if len(history) > 1:
        print_header("RECOVERY ATTEMPT HISTORY")
        for item in history:
            status = item.get("status", "unknown").upper()
            attempt = item.get("attempt_number", "?")
            print(f"Attempt {attempt}: {status}")
            if item.get("reason"):
                print(f"  Reason: {item['reason']}")

    if not verification and decision == "RECOVERY_PLAN_READY":
        if result.get("human_approved") is False:
            print("\nExecution skipped: approval was not granted.")
        else:
            print("\nNo execution results were recorded.")

    errors = result.get("errors", [])
    diagnostic_errors = result.get("additional_diagnostic_errors", [])

    if errors or diagnostic_errors:
        print_header("WORKFLOW WARNINGS")
        print_list(errors)
        print_list(diagnostic_errors)



def select_mode():
    """Select sandbox demonstrations or strictly read-only live diagnostics."""
    while True:
        print_header("PENGUINMEDIC")
        print("Choose an operating mode:\n")
        print("  1. Sandbox demonstrations")
        print("  2. Live system diagnostics (READ ONLY)")
        print("  3. Exit")
        choice = read_input("\nChoose an option (1-3): ")
        if choice is None:
            return None
        if choice == "1":
            return "sandbox"
        if choice == "2":
            return "live_diagnostic"
        if choice == "3":
            return None
        print("\n[PenguinMedic] Invalid selection. Please choose 1, 2, or 3.")


def display_live_diagnostic_result(result):
    """Display live findings without implying that any repair was performed."""
    print_header("LIVE SYSTEM DIAGNOSTIC REPORT")
    report = result.get("diagnostic_report", {})
    if report:
        print(f"\nIssue category: {report.get('issue_category', 'Unknown')}")
        print(f"\nProblem summary: {report.get('problem_summary', 'Unavailable')}")
        print("\nConfirmed observations:")
        print_list(report.get("confirmed_observations", []))
        print("\nPossible explanations:")
        print_list(report.get("possible_explanations", []))
        print("\nMissing information:")
        print_list(report.get("missing_information", []))
        print("\nHandoff summary:")
        print(report.get("handoff_summary", "Unavailable"))
    else:
        print("\nNo diagnostic report was produced.")

    investigation = result.get("investigation_report", {})
    if investigation:
        print_header("CLOUD INVESTIGATION")
        print("\nLikely root causes:")
        print_list(investigation.get("likely_root_causes", []))
        print("\nSupporting evidence:")
        print_list(investigation.get("supporting_evidence", []))
        print("\nContradicting evidence:")
        print_list(investigation.get("contradicting_evidence", []))
        print(f"\nConfidence: {investigation.get('confidence', 'Unknown')}")
        print("\nInvestigation summary:")
        print(investigation.get("investigation_summary", "Unavailable"))

    plan = result.get("recovery_plan", {})
    if plan:
        print_header("AGENT 3: RECOVERY ASSESSMENT")
        print(f"\nDecision: {plan.get('decision', 'Unknown')}")
        print(f"Reason: {plan.get('decision_reason', 'Unavailable')}")
        if plan.get("decision") == "RECOVERY_PLAN_READY":
            print("\nProposed solution (not executed):")
            print(plan.get("proposed_solution", "Unavailable"))
            print("\nPlan summary:")
            print(plan.get("plan_summary", "Unavailable"))
        elif plan.get("decision") == "MORE_INFORMATION_REQUIRED":
            print("\nMissing information:")
            print_list(plan.get("missing_information", []))
            print("\nQuestions for you:")
            print_list(plan.get("questions_for_user", []))
        else:
            print("\nWarnings:")
            print_list(plan.get("warnings", []))

    print_header("READ-ONLY MODE SAFETY")
    print("No recovery plan was validated for execution.")
    print("No approval was requested.")
    print("No repair commands or system modifications were performed.")
    errors = result.get("errors", [])
    diagnostic_errors = result.get("additional_diagnostic_errors", [])
    if errors or diagnostic_errors:
        print_header("DIAGNOSTIC WARNINGS")
        print_list(errors)
        print_list(diagnostic_errors)


def main():
    app = build_graph()
    while True:
        mode = select_mode()
        if mode is None:
            print("\n[PenguinMedic] Exiting.")
            return

        try:
            if mode == "sandbox":
                scenario = select_scenario()
                if scenario is None:
                    continue

                print_header(f"SCENARIO: {scenario['title']}")
                print("[PenguinMedic] Preparing the isolated sandbox fixture...")
                try:
                    preparation = prepare_sandbox_scenario(scenario["key"])
                except OSError as error:
                    print(f"[PenguinMedic] Could not prepare the test scenario: {error}")
                    continue

                if preparation.get("status") != "success":
                    print(
                        "[PenguinMedic] Could not prepare the test scenario: "
                        + preparation.get("reason", "Unknown error.")
                    )
                    continue

                print(f"[PenguinMedic] {preparation['message']}")
                print("[PenguinMedic] No real system configuration will be modified.")
                initial_state = {
                    "user_problem": scenario["problem"],
                    "sandbox_test_mode": True,
                    "sandbox_scenario": scenario["key"],
                    "live_diagnostic_mode": False,
                }
                config = {
                    "configurable": {
                        "thread_id": (
                            f"penguinmedic-sandbox-{scenario['key']}-"
                            f"{uuid.uuid4().hex}"
                        )
                    }
                }
                print("\n[PenguinMedic] Starting sandbox workflow...")
                result = app.invoke(initial_state, config=config)
                result = handle_approval(app, result, config)
                display_final_result(result)

            elif mode == "live_diagnostic":
                print_header("LIVE SYSTEM DIAGNOSTICS")
                print("This mode is READ ONLY.")
                print(
                    "PenguinMedic will inspect your actual Linux system "
                    "using its registered diagnostic tools."
                )
                print("It will not request approval or execute recovery operations.")
                user_problem = read_multiline_input(
                    "\nDescribe the Linux problem you want investigated:"
                )
                if user_problem is None:
                    print("\n[PenguinMedic] Input ended or was interrupted. Exiting safely.")
                    return
                if not user_problem:
                    print("[PenguinMedic] No problem description supplied. Returning to menu.")
                    continue

                initial_state = {
                    "user_problem": user_problem,
                    "sandbox_test_mode": False,
                    "live_diagnostic_mode": True,
                }
                config = {
                    "configurable": {
                        "thread_id": f"penguinmedic-live-{uuid.uuid4().hex}"
                    }
                }
                print("\n[PenguinMedic] Starting read-only live diagnostic workflow...")
                result = app.invoke(initial_state, config=config)

                # Defensive guard: never resume an unexpected approval interrupt.
                if "__interrupt__" in result:
                    print(
                        "[PenguinMedic] SAFETY STOP: the read-only workflow "
                        "unexpectedly reached an approval interrupt. "
                        "No approval was submitted."
                    )
                    continue
                display_live_diagnostic_result(result)

        except KeyboardInterrupt:
            print("\n\n[PenguinMedic] Workflow interrupted by user.")
        except Exception as error:
            print(f"\n[PenguinMedic] Workflow failed: {error}")


if __name__ == "__main__":
    main()

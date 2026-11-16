
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from graph.state import PenguinMedicState
from graph.nodes import (
    diagnostic_node,
    tool_execution_node,
    report_node,
    investigation_node,
    additional_diagnostics_node,
    solution_node,
    validation_node,
    recovery_verification_node,
)
from graph.approval import approval_node
from tools.command_executor import execute_authorized_steps
from tools.recovery_retry import (
    route_after_verification as _route_after_verification,
    build_retry_reset_update,
)

def executor_node(state: PenguinMedicState):
    results = execute_authorized_steps(
        authorized_steps=state.get("authorized_steps", []),
        human_approved=state.get("human_approved", False),
        approval_id=state.get("approval_id", ""),
        attempt_number=state.get("recovery_attempt", 0) + 1,
        sandbox_scenario=state.get("sandbox_scenario", ""),
    )

    attempt_number = state.get("recovery_attempt", 0) + 1
    attempt_was_authorized = (
        state.get("human_approved") is True
        and bool(state.get("authorized_steps"))
    )

    return {
        "execution_results": results,
        "recovery_attempt": (
            attempt_number if attempt_was_authorized
            else state.get("recovery_attempt", 0)
        ),
    }

def route_after_solution(state: PenguinMedicState):
    """Agent 3 decides the next stage of the workflow."""

    plan = state.get("recovery_plan", {})
    decision = plan.get("decision")
    current_round = state.get("investigation_round", 0)

    if decision == "RECOVERY_PLAN_READY":
        if (
            type(state.get("recovery_attempt", 0)) is not int
            or state.get("recovery_attempt", 0) >= 2
        ):
            print("[Workflow] No further recovery attempts are permitted.")
            return "stop"

        if not state.get("sandbox_test_mode", False):
            # Fail closed: only the explicitly selected sandbox mode may
            # enter the current recovery validator and executor.
            print(
                "[Workflow] Recovery execution is disabled outside the "
                "explicit sandbox mode."
            )
            return "stop"

        return "validation"

    if decision == "MORE_INFORMATION_REQUIRED":
        if current_round < 2:
            return "additional_diagnostics"

        print("[Workflow] Maximum diagnostic rounds reached.")
        return "stop"

    if decision == "CANNOT_SAFELY_PROCEED":
        return "stop"

    print("[Workflow] Unknown decision. Stopping safely.")
    return "stop"


def route_after_additional_diagnostics(state: PenguinMedicState):
    """Check whether Agent 1 selected usable diagnostic tools."""

    request = state.get("diagnostic_request", {})
    requested = request.get("required_diagnostics", [])

    allowed_tools = {
        "get_system_info",
        "inspect_pacman_logs",
        "inspect_package_database",
        "inspect_system_journal",
        "inspect_failed_services",
        "inspect_disk_usage",
        "inspect_pacman_config",
        "inspect_mirror_status",
    }

    valid_requests = [
        tool for tool in requested if tool in allowed_tools
    ]

    if valid_requests:
        return "investigation"

    print("[Workflow] No usable additional diagnostics selected.")
    return "stop"


def route_after_approval(state: PenguinMedicState):
    """Execute only when human approval and authorized steps exist."""

    if (
        state.get("human_approved") is True
        and state.get("authorized_steps")
    ):
        return "executor"

    return "stop"


def route_after_verification(state: PenguinMedicState):
    """Stop on success; otherwise permit one fresh approved sandbox retry."""
    route = _route_after_verification(state)
    if route == "retry":
        print(
            "[Workflow] Verification failed. A single fresh diagnostic and "
            "recovery attempt is permitted."
        )
    elif (
        type(state.get("recovery_attempt", 0)) is int
        and state.get("recovery_attempt", 0) >= 2
    ):
        print("[Workflow] Recovery attempt limit reached. Stopping safely.")
    return route


def retry_reset_node(state: PenguinMedicState):
    """Clear stale evidence and authorization before a fresh investigation."""
    return build_retry_reset_update()


def build_graph():
    workflow = StateGraph(PenguinMedicState)

    # Register workflow nodes.
    workflow.add_node("diagnostic", diagnostic_node)
    workflow.add_node("execute_tools", tool_execution_node)
    workflow.add_node("generate_report", report_node)
    workflow.add_node("investigation", investigation_node)
    workflow.add_node("additional_diagnostics", additional_diagnostics_node)
    workflow.add_node("solution", solution_node)
    workflow.add_node("validation", validation_node)
    workflow.add_node("approval", approval_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("recovery_verification", recovery_verification_node)
    workflow.add_node("retry_reset", retry_reset_node)

    # Initial diagnostic workflow.
    workflow.add_edge(START, "diagnostic")
    workflow.add_edge("diagnostic", "execute_tools")
    workflow.add_edge("execute_tools", "generate_report")
    workflow.add_edge("generate_report", "investigation")

    # Agent 2 investigates, then Agent 3 decides.
    workflow.add_edge("investigation", "solution")

    # Route according to Agent 3's decision.
    workflow.add_conditional_edges(
        "solution",
        route_after_solution,
        {
            "validation": "validation",
            "additional_diagnostics": "additional_diagnostics",
            "stop": END,
        },
    )

    # Additional diagnostic rounds.
    workflow.add_conditional_edges(
        "additional_diagnostics",
        route_after_additional_diagnostics,
        {
            "investigation": "investigation",
            "stop": END,
        },
    )

    # Agent 4: validation -> human approval -> execution.
    workflow.add_edge("validation", "approval")

    workflow.add_conditional_edges(
        "approval",
        route_after_approval,
        {
            "executor": "executor",
            "stop": END,
        },
    )

    workflow.add_edge("executor", "recovery_verification")
    workflow.add_conditional_edges(
        "recovery_verification",
        route_after_verification,
        {
            "retry": "retry_reset",
            "stop": END,
        },
    )

    # Retry starts from fresh diagnostics, not the previous evidence or approval.
    workflow.add_edge("retry_reset", "diagnostic")

    # In-memory checkpointing for approval interrupts.
    checkpointer = MemorySaver()

    return workflow.compile(checkpointer=checkpointer)


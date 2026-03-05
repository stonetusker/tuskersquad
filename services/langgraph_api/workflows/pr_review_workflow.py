from datetime import datetime

from langgraph.graph import StateGraph, END

from services.langgraph_api.state.workflow_state import (
    WorkflowState,
    WorkflowStatus,
)

from services.langgraph_api.core.workflow_registry import workflow_registry

from agents.planner.planner_agent import run_planner


async def persist_state(state: WorkflowState):
    """
    Persist workflow state to the in-memory registry so that
    dashboard polling can observe progress.
    """

    await workflow_registry.update_workflow(
        state["workflow_id"],
        state
    )

    return state


def add_finding(
    state: WorkflowState,
    agent: str,
    severity: str,
    confidence: float,
    test_name: str,
    finding: str,
    endpoint: str,
    recommendation: str
):
    """
    Helper for adding structured engineering findings.
    """

    state["findings"].append(
        {
            "agent": agent,
            "severity": severity,
            "confidence": confidence,
            "test_name": test_name,
            "finding": finding,
            "affected_endpoint": endpoint,
            "recommendation": recommendation,
        }
    )



async def planner_node(state: WorkflowState) -> WorkflowState:

    state["current_agent"] = "planner"

    plan = await run_planner(
        repo=state["repo"],
        pr_number=state["pr_number"]
    )

    # Defensive extraction of agent list
    agents = plan.get("agents")

    if not agents or not isinstance(agents, list):
        agents = ["security", "backend"]

    state["execution_plan"] = agents

    state["logs"].append(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "planner",
            "message": f"Execution plan created: {agents}"
        }
    )

    return await persist_state(state)



# ----------------------------
# Security Agent
# ----------------------------

async def security_node(state: WorkflowState) -> WorkflowState:

    state["current_agent"] = "security"

    state["logs"].append(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "security",
            "message": "Security agent executed"
        }
    )

    add_finding(
        state=state,
        agent="security",
        severity="MEDIUM",
        confidence=0.74,
        test_name="dependency_scan",
        finding="Outdated dependency detected",
        endpoint="/auth/login",
        recommendation="REVIEW"
    )

    return await persist_state(state)


# ----------------------------
# Backend Agent
# ----------------------------

async def backend_node(state: WorkflowState) -> WorkflowState:

    state["current_agent"] = "backend"

    state["logs"].append(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "backend",
            "message": "Backend agent executed"
        }
    )

    add_finding(
        state=state,
        agent="backend",
        severity="HIGH",
        confidence=0.82,
        test_name="checkout_latency",
        finding="Checkout latency increased by 35%",
        endpoint="/api/checkout",
        recommendation="BLOCK"
    )

    return await persist_state(state)


# ----------------------------
# Frontend Agent
# ----------------------------

async def frontend_node(state: WorkflowState) -> WorkflowState:

    state["current_agent"] = "frontend"

    state["logs"].append(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "frontend",
            "message": "Frontend agent executed"
        }
    )

    return await persist_state(state)


# ----------------------------
# SRE Agent
# ----------------------------

async def sre_node(state: WorkflowState) -> WorkflowState:

    state["current_agent"] = "sre"

    state["logs"].append(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "sre",
            "message": "SRE agent executed"
        }
    )

    return await persist_state(state)


# ----------------------------
# Judge Agent
# ----------------------------

async def judge_node(state: WorkflowState) -> WorkflowState:

    state["current_agent"] = "judge"

    state["logs"].append(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "judge",
            "message": "Judge agent evaluating findings"
        }
    )

    findings = state["findings"]

    decision = "ALLOW"

    for f in findings:
        if f["severity"] == "HIGH" and f["recommendation"] == "BLOCK":
            decision = "BLOCK"

    state["logs"].append(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "judge",
            "message": f"Decision: {decision}"
        }
    )

    if decision == "BLOCK":
        state["status"] = WorkflowStatus.WAITING_HUMAN_APPROVAL

    return await persist_state(state)


# ----------------------------
# Build Workflow Graph
# ----------------------------

def build_workflow():

    graph = StateGraph(WorkflowState)

    graph.add_node("planner", planner_node)
    graph.add_node("security", security_node)
    graph.add_node("backend", backend_node)
    graph.add_node("frontend", frontend_node)
    graph.add_node("sre", sre_node)
    graph.add_node("judge", judge_node)

    graph.set_entry_point("planner")

    graph.add_edge("planner", "security")
    graph.add_edge("security", "backend")
    graph.add_edge("backend", "frontend")
    graph.add_edge("frontend", "sre")
    graph.add_edge("sre", "judge")
    graph.add_edge("judge", END)

    return graph.compile()

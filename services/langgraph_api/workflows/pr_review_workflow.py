from datetime import datetime

from langgraph.graph import END, StateGraph

from agents.planner.planner_agent import run_planner

from services.langgraph_api.core.workflow_registry import workflow_registry
from services.langgraph_api.repositories.workflow_repository import WorkflowRepository
from services.langgraph_api.state.workflow_state import WorkflowState, WorkflowStatus


repo = WorkflowRepository()


async def persist_state(state: WorkflowState):
    await workflow_registry.update_workflow(
        state["workflow_id"],
        state,
    )
    return state


def persist_finding(state: WorkflowState, finding: dict):

    repo.store_engineering_finding(
        workflow_id=state["workflow_id"],
        agent_name=finding["agent"],
        finding_type=finding["test_name"],
        description=finding["finding"],
        confidence=finding["confidence"],
        recommendation=finding["recommendation"],
    )


def add_finding(
    state: WorkflowState,
    agent: str,
    severity: str,
    confidence: float,
    test_name: str,
    finding: str,
    endpoint: str,
    recommendation: str,
):

    new_finding = {
        "agent": agent,
        "severity": severity,
        "confidence": confidence,
        "test_name": test_name,
        "finding": finding,
        "affected_endpoint": endpoint,
        "recommendation": recommendation,
    }

    state["findings"].append(new_finding)

    persist_finding(state, new_finding)


# --------------------------------------------------
# Planner Node
# --------------------------------------------------

async def planner_node(state: WorkflowState) -> WorkflowState:

    state["current_agent"] = "planner"

    start_time = datetime.utcnow()

    plan = await run_planner(
        repo=state["repo"],
        pr_number=state["pr_number"],
    )

    end_time = datetime.utcnow()

    repo.log_agent_execution(
        workflow_id=state["workflow_id"],
        agent_name="planner",
        model_used="qwen2.5:14b",
        status="SUCCESS",
        started_at=start_time,
        completed_at=end_time,
    )

    agents = plan.get("agents")

    if not agents or not isinstance(agents, list):
        agents = ["security", "backend"]

    state["execution_plan"] = agents

    state["logs"].append(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "planner",
            "message": f"Execution plan created: {agents}",
        }
    )

    return await persist_state(state)


# --------------------------------------------------
# Security
# --------------------------------------------------

async def security_node(state: WorkflowState) -> WorkflowState:

    state["current_agent"] = "security"

    add_finding(
        state,
        "security",
        "MEDIUM",
        0.74,
        "dependency_scan",
        "Outdated dependency detected",
        "/auth/login",
        "REVIEW",
    )

    return await persist_state(state)


# --------------------------------------------------
# Backend
# --------------------------------------------------

async def backend_node(state: WorkflowState) -> WorkflowState:

    state["current_agent"] = "backend"

    add_finding(
        state,
        "backend",
        "HIGH",
        0.82,
        "checkout_latency",
        "Checkout latency increased by 35%",
        "/api/checkout",
        "BLOCK",
    )

    return await persist_state(state)


# --------------------------------------------------
# Frontend
# --------------------------------------------------

async def frontend_node(state: WorkflowState) -> WorkflowState:

    state["current_agent"] = "frontend"

    return await persist_state(state)


# --------------------------------------------------
# SRE
# --------------------------------------------------

async def sre_node(state: WorkflowState) -> WorkflowState:

    state["current_agent"] = "sre"

    return await persist_state(state)


# --------------------------------------------------
# Week-6 Challenger
# --------------------------------------------------

async def challenger_node(state: WorkflowState) -> WorkflowState:

    state["current_agent"] = "challenger"

    for finding in state["findings"]:

        if finding["test_name"] == "checkout_latency":

            finding["confidence"] = 0.62

            state["logs"].append(
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "agent": "challenger",
                    "message": "Benchmark environment variance detected. Confidence reduced.",
                }
            )

    return await persist_state(state)


# --------------------------------------------------
# Judge
# --------------------------------------------------

async def judge_node(state: WorkflowState) -> WorkflowState:

    state["current_agent"] = "judge"

    decision = "ALLOW"

    for finding in state["findings"]:

        if finding["severity"] == "HIGH" and finding["recommendation"] == "BLOCK":
            decision = "BLOCK"

    repo.store_governance_action(
        workflow_id=state["workflow_id"],
        decision=decision,
        judge_confidence=0.85,
    )

    if decision == "BLOCK":

        state["status"] = WorkflowStatus.WAITING_HUMAN_APPROVAL

        repo.update_workflow_status(
            workflow_id=state["workflow_id"],
            status="WAITING_HUMAN_APPROVAL",
        )

    return await persist_state(state)


# --------------------------------------------------
# Workflow Graph
# --------------------------------------------------

def build_workflow():

    graph = StateGraph(WorkflowState)

    graph.add_node("planner", planner_node)
    graph.add_node("security", security_node)
    graph.add_node("backend", backend_node)
    graph.add_node("frontend", frontend_node)
    graph.add_node("sre", sre_node)

    graph.add_node("challenger", challenger_node)
    graph.add_node("judge", judge_node)

    graph.set_entry_point("planner")

    graph.add_edge("planner", "security")
    graph.add_edge("security", "backend")
    graph.add_edge("backend", "frontend")
    graph.add_edge("frontend", "sre")

    # Week-6 debate stage
    graph.add_edge("sre", "challenger")

    graph.add_edge("challenger", "judge")

    graph.add_edge("judge", END)

    return graph.compile()
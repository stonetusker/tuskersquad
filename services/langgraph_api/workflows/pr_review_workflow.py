from datetime import datetime

from langgraph.graph import END, StateGraph

from agents.planner.planner_agent import run_planner
from services.langgraph_api.core.workflow_registry import workflow_registry
from services.langgraph_api.repositories.workflow_repository import WorkflowRepository
from services.langgraph_api.state.workflow_state import WorkflowState, WorkflowStatus


repo = WorkflowRepository()


async def persist_state(state: WorkflowState):
    """
    Persist workflow state to the in-memory registry so that
    dashboard polling can observe progress.
    """
    await workflow_registry.update_workflow(
        state["workflow_id"],
        state,
    )
    return state


def persist_finding(state: WorkflowState, finding: dict):
    """
    Persist engineering finding into Postgres.
    """
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
    """
    Helper for adding structured engineering findings.
    """

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

    # Persist finding immediately
    persist_finding(state, new_finding)


# --------------------------------------------------
# Planner Agent
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
# Security Agent
# --------------------------------------------------
async def security_node(state: WorkflowState) -> WorkflowState:

    state["current_agent"] = "security"

    start_time = datetime.utcnow()

    state["logs"].append(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "security",
            "message": "Security agent executed",
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
        recommendation="REVIEW",
    )

    end_time = datetime.utcnow()

    repo.log_agent_execution(
        workflow_id=state["workflow_id"],
        agent_name="security",
        model_used="deepseek-coder:6.7b",
        status="SUCCESS",
        started_at=start_time,
        completed_at=end_time,
    )

    return await persist_state(state)


# --------------------------------------------------
# Backend Agent
# --------------------------------------------------
async def backend_node(state: WorkflowState) -> WorkflowState:

    state["current_agent"] = "backend"

    start_time = datetime.utcnow()

    state["logs"].append(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "backend",
            "message": "Backend agent executed",
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
        recommendation="BLOCK",
    )

    end_time = datetime.utcnow()

    repo.log_agent_execution(
        workflow_id=state["workflow_id"],
        agent_name="backend",
        model_used="deepseek-coder:6.7b",
        status="SUCCESS",
        started_at=start_time,
        completed_at=end_time,
    )

    return await persist_state(state)


# --------------------------------------------------
# Frontend Agent
# --------------------------------------------------
async def frontend_node(state: WorkflowState) -> WorkflowState:

    state["current_agent"] = "frontend"

    start_time = datetime.utcnow()

    state["logs"].append(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "frontend",
            "message": "Frontend agent executed",
        }
    )

    end_time = datetime.utcnow()

    repo.log_agent_execution(
        workflow_id=state["workflow_id"],
        agent_name="frontend",
        model_used="deepseek-coder:6.7b",
        status="SUCCESS",
        started_at=start_time,
        completed_at=end_time,
    )

    return await persist_state(state)


# --------------------------------------------------
# SRE Agent
# --------------------------------------------------
async def sre_node(state: WorkflowState) -> WorkflowState:

    state["current_agent"] = "sre"

    start_time = datetime.utcnow()

    state["logs"].append(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "sre",
            "message": "SRE agent executed",
        }
    )

    end_time = datetime.utcnow()

    repo.log_agent_execution(
        workflow_id=state["workflow_id"],
        agent_name="sre",
        model_used="deepseek-coder:6.7b",
        status="SUCCESS",
        started_at=start_time,
        completed_at=end_time,
    )

    return await persist_state(state)


# --------------------------------------------------
# Judge Agent
# --------------------------------------------------
async def judge_node(state: WorkflowState) -> WorkflowState:

    state["current_agent"] = "judge"

    start_time = datetime.utcnow()

    state["logs"].append(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "judge",
            "message": "Judge agent evaluating findings",
        }
    )

    findings = state["findings"]
    decision = "ALLOW"

    for finding in findings:
        if finding["severity"] == "HIGH" and finding["recommendation"] == "BLOCK":
            decision = "BLOCK"

    state["logs"].append(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "judge",
            "message": f"Decision: {decision}",
        }
    )

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

    end_time = datetime.utcnow()

    repo.log_agent_execution(
        workflow_id=state["workflow_id"],
        agent_name="judge",
        model_used="qwen2.5:14b",
        status="SUCCESS",
        started_at=start_time,
        completed_at=end_time,
    )

    return await persist_state(state)


# --------------------------------------------------
# Build Workflow Graph
# --------------------------------------------------
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


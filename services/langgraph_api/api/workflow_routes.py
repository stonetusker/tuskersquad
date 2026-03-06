import asyncio
import traceback
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from services.langgraph_api.db.database import get_db
from services.langgraph_api.db.models import WorkflowRun

from pydantic import BaseModel

from services.langgraph_api.state.workflow_state import WorkflowStatus
from services.langgraph_api.core.workflow_registry import workflow_registry
from services.langgraph_api.workflows.pr_review_workflow import build_workflow
from services.langgraph_api.repositories.workflow_repository import WorkflowRepository

# DB access
from services.langgraph_api.db.database import SessionLocal
from services.langgraph_api.db.models import (
    WorkflowRun,
    AgentExecutionLog,
    EngineeringFinding,
    GovernanceAction,
)


router = APIRouter()

# Repository used for persistence in Postgres
repo = WorkflowRepository()


class WorkflowStartRequest(BaseModel):
    repo: str
    pr_number: int


class WorkflowStartResponse(BaseModel):
    workflow_id: str
    status: str


# ---------------------------------------------------------
# Safe Workflow Runner
# ---------------------------------------------------------
async def run_workflow(workflow_id: str):
    """
    Executes the LangGraph workflow asynchronously.
    """

    try:
        workflow = build_workflow()

        state = await workflow_registry.get_workflow(workflow_id)

        if not state:
            return

        result = await workflow.ainvoke(state)

        await workflow_registry.update_workflow(
            workflow_id,
            result,
        )

    except Exception as e:
        print("WORKFLOW EXECUTION FAILED")
        traceback.print_exc()

        state = await workflow_registry.get_workflow(workflow_id)

        if state:
            state["status"] = WorkflowStatus.FAILED

            state["logs"].append(
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "agent": "system",
                    "message": f"Workflow failed: {str(e)}",
                }
            )

            await workflow_registry.update_workflow(workflow_id, state)


# ---------------------------------------------------------
# Start Workflow
# ---------------------------------------------------------
@router.post("/workflow/start", response_model=WorkflowStartResponse)
async def start_workflow(request: WorkflowStartRequest):
    """
    Starts a new workflow run.

    1. Creates workflow record in Postgres
    2. Registers workflow in in-memory registry
    3. Launches async LangGraph execution
    """

    # Create workflow record in Postgres (required for FK constraints)
    workflow_id = repo.create_workflow_run(
        repository=request.repo,
        pr_number=request.pr_number,
    )

    state = {
        "workflow_id": workflow_id,
        "repo": request.repo,
        "pr_number": request.pr_number,
        "status": WorkflowStatus.RUNNING,
        "current_agent": None,
        "findings": [],
        "logs": [],
    }

    # Register workflow in memory so dashboard polling can see it
    await workflow_registry.register_workflow(state)

    # Run workflow asynchronously
    loop = asyncio.get_running_loop()
    loop.create_task(run_workflow(workflow_id))

    return WorkflowStartResponse(
        workflow_id=workflow_id,
        status="RUNNING",
    )


# ---------------------------------------------------------
# List Workflows (Registry)
# ---------------------------------------------------------
@router.get("/workflows")
async def list_workflows():
    """
    Returns active workflows from the in-memory registry.
    """

    workflows = await workflow_registry.list_workflows()
    return {"workflows": workflows}


# ---------------------------------------------------------
# Get Workflow State (Registry)
# ---------------------------------------------------------
@router.get("/workflow/{workflow_id}")
async def get_workflow(workflow_id: str):
    """
    Returns the full workflow state from the registry.
    """

    workflow = await workflow_registry.get_workflow(workflow_id)

    if not workflow:
        return {"error": "workflow not found"}

    return workflow


# ---------------------------------------------------------
# Resume Workflow (Human Approval)
# ---------------------------------------------------------
@router.post("/workflow/{workflow_id}/resume")
async def resume_workflow(workflow_id: str):
    """
    Resumes workflow after human approval.
    """

    workflow = await workflow_registry.get_workflow(workflow_id)

    if not workflow:
        return {"error": "workflow not found"}

    if workflow["status"] != WorkflowStatus.WAITING_HUMAN_APPROVAL:
        return {"error": "workflow not waiting for approval"}

    workflow["status"] = WorkflowStatus.COMPLETED

    workflow["logs"].append(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "human",
            "message": "Workflow resumed by human approval",
        }
    )

    await workflow_registry.update_workflow(workflow_id, workflow)

    # Persist workflow completion in Postgres
    repo.update_workflow_status(
        workflow_id=workflow_id,
        status="COMPLETED",
    )

    return {
        "workflow_id": workflow_id,
        "status": "COMPLETED",
    }


# ---------------------------------------------------------
# Dashboard Query APIs (Database)
# ---------------------------------------------------------

@router.get("/api/workflows")
def db_list_workflows(db: Session = Depends(get_db)):

    runs = db.query(WorkflowRun).order_by(
        WorkflowRun.created_at.desc()
    ).all()

    return {
        "workflows": [
            {
                "workflow_id": r.workflow_id,
                "repo": r.repo,
                "status": r.status
            }
            for r in runs
        ]
    }

@router.get("/api/workflows/{workflow_id}")
def db_get_workflow(workflow_id: str):
    """
    Returns a workflow run from Postgres.
    """
    db = SessionLocal()
    try:
        run = db.query(WorkflowRun).filter(WorkflowRun.workflow_id == workflow_id).first()
        if not run:
            return {"error": "workflow not found"}
        return run.__dict__
    finally:
        db.close()


@router.get("/api/workflows/{workflow_id}/agents")
def db_get_agents(workflow_id: str):
    """
    Returns agent execution timeline.
    """
    db = SessionLocal()
    try:
        agents = (
            db.query(AgentExecutionLog)
            .filter(AgentExecutionLog.workflow_id == workflow_id)
            .order_by(AgentExecutionLog.started_at)
            .all()
        )
        return {"agents": [a.__dict__ for a in agents]}
    finally:
        db.close()


@router.get("/api/workflows/{workflow_id}/findings")
def db_get_findings(workflow_id: str):
    """
    Returns engineering findings for a workflow.
    """
    db = SessionLocal()
    try:
        findings = (
            db.query(EngineeringFinding)
            .filter(EngineeringFinding.workflow_id == workflow_id)
            .all()
        )
        return {"findings": [f.__dict__ for f in findings]}
    finally:
        db.close()


@router.get("/api/workflows/{workflow_id}/governance")
def db_get_governance(workflow_id: str):
    """
    Returns governance decision for workflow.
    """
    db = SessionLocal()
    try:
        decision = (
            db.query(GovernanceAction)
            .filter(GovernanceAction.workflow_id == workflow_id)
            .first()
        )
        if not decision:
            return {"decision": None}
        return decision.__dict__
    finally:
        db.close()

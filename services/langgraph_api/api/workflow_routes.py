"""
Workflow API Routes
===================
All REST endpoints for TuskerSquad.

Human governance endpoints (approve/reject/retest/release) now call
``resume_workflow_with_decision()`` which feeds the decision back into
the paused LangGraph interrupt, OR falls back to direct DB writes for
the SimpleGraph path.
"""

import asyncio
import logging
import os
import threading
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.workflow_registry import workflow_registry
from ..db.database import get_db
from ..db.models import WorkflowRun
from ..repositories.agent_log_repository import AgentLogRepository
from ..repositories.finding_challenges_repository import FindingChallengesRepository
from ..repositories.findings_repository import FindingsRepository
from ..repositories.governance_repository import GovernanceRepository
from ..repositories.workflow_repository import WorkflowRepository
from ..repositories.qa_summary_repository import QASummaryRepository
from ..workflows.pr_review_workflow import execute_workflow, resume_workflow_with_decision

logger = logging.getLogger("langgraph.api.workflow_routes")

router = APIRouter(prefix="", tags=["workflow"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class StartWorkflow(BaseModel):
    repo: str = Field(..., description="Repository full name, e.g. owner/repo")
    pr_number: int = Field(..., description="Pull request number")


class ReleaseOverride(BaseModel):
    reason: str = Field(default="Release Manager override", description="Business justification")
    decision: str = Field(default="APPROVE", description="APPROVE or REJECT")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wf_to_dict(r: WorkflowRun) -> dict:
    return {
        "workflow_id": str(r.id),
        "repository": r.repository,
        "pr_number": r.pr_number,
        "status": r.status,
        "current_agent": r.current_agent,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Start workflow
# ---------------------------------------------------------------------------

@router.post("/workflow/start")
async def start_workflow(
    payload: StartWorkflow,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    repo = WorkflowRepository(db)
    try:
        workflow = repo.create_workflow_run(
            repository=payload.repo, pr_number=payload.pr_number
        )

        state = {
            "workflow_id": str(workflow.id),
            "repository": payload.repo,
            "pr_number": payload.pr_number,
            "status": workflow.status,
            "findings": [],
            "challenges": [],
            "current_agent": None,
        }
        await workflow_registry.register_workflow(state)

        thread = threading.Thread(target=execute_workflow, args=(str(workflow.id),))
        thread.daemon = True
        thread.start()

        logger.info(
            "workflow_started workflow=%s repo=%s pr=%s",
            workflow.id, payload.repo, payload.pr_number,
        )
        return {"workflow_id": str(workflow.id), "status": workflow.status}

    except Exception as exc:
        logger.exception("failed_to_start_workflow")
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# List / Get
# ---------------------------------------------------------------------------

@router.get("/workflows")
async def list_workflows():
    return await workflow_registry.list_workflows()


@router.get("/api/workflows")
def api_list_workflows(db: Session = Depends(get_db)):
    rows = db.query(WorkflowRun).order_by(WorkflowRun.created_at.desc()).all()
    return [_wf_to_dict(r) for r in rows]


@router.get("/api/workflow/{workflow_id}")
def api_get_workflow(workflow_id: str, db: Session = Depends(get_db)):
    row = db.query(WorkflowRun).filter(WorkflowRun.id == workflow_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="workflow not found")
    return _wf_to_dict(row)


@router.get("/workflow/{workflow_id}")
async def get_workflow(workflow_id: str):
    w = await workflow_registry.get_workflow(workflow_id)
    if not w:
        raise HTTPException(status_code=404, detail="workflow not found")
    return w


# ---------------------------------------------------------------------------
# Human governance actions
# ---------------------------------------------------------------------------

@router.post("/workflow/{workflow_id}/approve")
async def approve_workflow(workflow_id: str, db: Session = Depends(get_db)):
    """
    Human QA Lead approves the deployment.
    In LangGraph mode: feeds APPROVE into the paused interrupt.
    In SimpleGraph mode: updates DB directly.
    """
    gov_repo = GovernanceRepository(db)
    workflow_repo = WorkflowRepository(db)
    findings_repo = FindingsRepository(db)

    # Resume the graph (no-op for SimpleGraph)
    thread = threading.Thread(
        target=resume_workflow_with_decision,
        args=(workflow_id, "APPROVE", "Human QA Lead approval"),
    )
    thread.daemon = True
    thread.start()

    # Also update DB directly for SimpleGraph compatibility
    action = gov_repo.create_decision(workflow_id, "APPROVE")
    action.approved = True
    db.commit()
    workflow_repo.update_workflow_status(workflow_id, "COMPLETED")

    # Best-effort Gitea PR comment
    GITEA_URL = os.getenv("GITEA_URL")
    GITEA_TOKEN = os.getenv("GITEA_TOKEN")
    try:
        if GITEA_URL and GITEA_TOKEN:
            wfrow = db.query(WorkflowRun).filter(WorkflowRun.id == workflow_id).first()
            if wfrow:
                findings = findings_repo.list_by_workflow(workflow_id)
                body = "TuskerSquad governance decision: **APPROVE** (Human QA Lead)\n\nFindings:\n"
                for f in findings:
                    body += f"- [{f.agent}] {f.title} ({f.severity})\n"
                url = f"{GITEA_URL}/api/v1/repos/{wfrow.repository}/issues/{wfrow.pr_number}/comments"
                async with httpx.AsyncClient() as client:
                    await client.post(
                        url, json={"body": body},
                        headers={"Authorization": f"token {GITEA_TOKEN}"}, timeout=10.0,
                    )
    except Exception:
        logger.exception("failed_post_pr_comment_on_approve")

    try:
        await workflow_registry.update_workflow(
            workflow_id, {"workflow_id": workflow_id, "status": "COMPLETED"}
        )
    except Exception:
        pass

    return {"workflow_id": workflow_id, "status": "COMPLETED"}


@router.post("/workflow/{workflow_id}/reject")
async def reject_workflow(workflow_id: str, db: Session = Depends(get_db)):
    """Human QA Lead rejects the deployment."""
    gov_repo = GovernanceRepository(db)
    workflow_repo = WorkflowRepository(db)

    thread = threading.Thread(
        target=resume_workflow_with_decision,
        args=(workflow_id, "REJECT", "Human QA Lead rejection"),
    )
    thread.daemon = True
    thread.start()

    action = gov_repo.create_decision(workflow_id, "REJECT")
    action.approved = False
    db.commit()
    workflow_repo.update_workflow_status(workflow_id, "COMPLETED")

    GITEA_URL = os.getenv("GITEA_URL")
    GITEA_TOKEN = os.getenv("GITEA_TOKEN")
    try:
        if GITEA_URL and GITEA_TOKEN:
            wfrow = db.query(WorkflowRun).filter(WorkflowRun.id == workflow_id).first()
            if wfrow:
                body = "TuskerSquad governance decision: **REJECT** (Human QA Lead)\n\nDeployment blocked."
                url = f"{GITEA_URL}/api/v1/repos/{wfrow.repository}/issues/{wfrow.pr_number}/comments"
                async with httpx.AsyncClient() as client:
                    await client.post(
                        url, json={"body": body},
                        headers={"Authorization": f"token {GITEA_TOKEN}"}, timeout=10.0,
                    )
    except Exception:
        logger.exception("failed_post_pr_comment_on_reject")

    try:
        await workflow_registry.update_workflow(
            workflow_id, {"workflow_id": workflow_id, "status": "COMPLETED"}
        )
    except Exception:
        pass

    return {"workflow_id": workflow_id, "status": "COMPLETED"}


@router.post("/workflow/{workflow_id}/retest")
async def retest_workflow(workflow_id: str, db: Session = Depends(get_db)):
    """
    Human QA Lead requests a full re-run of the agent pipeline.
    In LangGraph mode: feeds RETEST into the interrupt → graph loops back to planner.
    In SimpleGraph mode: resets status and re-executes from scratch.
    """
    gov_repo = GovernanceRepository(db)
    workflow_repo = WorkflowRepository(db)

    gov_repo.create_decision(workflow_id, "RETEST_REQUESTED")
    db.commit()
    workflow_repo.update_workflow_status(workflow_id, "RUNNING")

    try:
        await workflow_registry.update_workflow(
            workflow_id, {"workflow_id": workflow_id, "status": "RUNNING"}
        )
    except Exception:
        pass

    # In LangGraph mode: resume with RETEST → graph re-runs from planner
    # In SimpleGraph mode: resume is a no-op, then re-execute below
    thread = threading.Thread(
        target=_retest_background,
        args=(workflow_id,),
    )
    thread.daemon = True
    thread.start()

    logger.info("retest_requested workflow=%s", workflow_id)
    return {"workflow_id": workflow_id, "status": "RUNNING", "action": "RETEST_REQUESTED"}


def _retest_background(workflow_id: str) -> None:
    """Background task: try LangGraph resume first, fall back to full re-execute."""
    try:
        resume_workflow_with_decision(workflow_id, "RETEST", "Human QA Lead retest request")
    except Exception:
        logger.exception("resume_retest_failed — falling back to full re-execute")
    # Always run full re-execute for SimpleGraph compatibility
    try:
        execute_workflow(workflow_id)
    except Exception:
        logger.exception("retest_execute_workflow_failed workflow=%s", workflow_id)


@router.post("/workflow/{workflow_id}/release")
async def release_manager_override(
    workflow_id: str,
    payload: ReleaseOverride,
    db: Session = Depends(get_db),
):
    """Release Manager business override — bypasses QA Lead decision."""
    gov_repo = GovernanceRepository(db)
    workflow_repo = WorkflowRepository(db)
    findings_repo = FindingsRepository(db)

    decision = payload.decision.upper()
    if decision not in ("APPROVE", "REJECT"):
        raise HTTPException(status_code=400, detail="decision must be APPROVE or REJECT")

    action = gov_repo.create_decision(workflow_id, f"RELEASE_MANAGER_{decision}")
    action.approved = decision == "APPROVE"
    db.commit()
    workflow_repo.update_workflow_status(workflow_id, "COMPLETED")

    GITEA_URL = os.getenv("GITEA_URL")
    GITEA_TOKEN = os.getenv("GITEA_TOKEN")
    try:
        if GITEA_URL and GITEA_TOKEN:
            wfrow = db.query(WorkflowRun).filter(WorkflowRun.id == workflow_id).first()
            if wfrow:
                body = (
                    f"TuskerSquad governance decision: **{decision}** "
                    f"(Release Manager Override)\n\n**Reason:** {payload.reason}\n\n"
                    "_This decision overrides the QA Lead recommendation._"
                )
                url = f"{GITEA_URL}/api/v1/repos/{wfrow.repository}/issues/{wfrow.pr_number}/comments"
                async with httpx.AsyncClient() as client:
                    await client.post(
                        url, json={"body": body},
                        headers={"Authorization": f"token {GITEA_TOKEN}"}, timeout=10.0,
                    )
    except Exception:
        logger.exception("failed_post_pr_comment_on_release_override")

    try:
        await workflow_registry.update_workflow(
            workflow_id,
            {
                "workflow_id": workflow_id,
                "status": "COMPLETED",
                "release_manager_decision": decision,
                "release_manager_reason": payload.reason,
            },
        )
    except Exception:
        pass

    logger.info("release_manager_override workflow=%s decision=%s", workflow_id, decision)
    return {
        "workflow_id": workflow_id,
        "status": "COMPLETED",
        "decision": decision,
        "reason": payload.reason,
    }


@router.post("/workflow/{workflow_id}/resume")
async def resume_workflow(workflow_id: str, db: Session = Depends(get_db)):
    """Generic resume endpoint (used by integration tests and external tools)."""
    workflow_repo = WorkflowRepository(db)
    workflow_repo.update_workflow_status(workflow_id, "RUNNING")
    thread = threading.Thread(target=execute_workflow, args=(workflow_id,))
    thread.daemon = True
    thread.start()
    return {"workflow_id": workflow_id, "status": "RUNNING"}


# ---------------------------------------------------------------------------
# Sub-resource endpoints
# ---------------------------------------------------------------------------

@router.get("/workflows/{workflow_id}/findings")
def get_findings(workflow_id: str, db: Session = Depends(get_db)):
    rows = FindingsRepository(db).list_by_workflow(workflow_id)
    return [
        {
            "id": str(r.id),
            "agent": r.agent,
            "severity": r.severity,
            "title": r.title,
            "description": r.description,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/workflows/{workflow_id}/governance")
async def get_governance(workflow_id: str, db: Session = Depends(get_db)):
    rows = GovernanceRepository(db).list_by_workflow(workflow_id)
    actions = [
        {
            "id": str(r.id),
            "decision": r.decision,
            "approved": bool(r.approved) if r.approved is not None else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]

    rationale = None
    try:
        reg = await workflow_registry.get_workflow(workflow_id)
        if reg and isinstance(reg, dict):
            rationale = reg.get("rationale")
    except Exception:
        logger.exception("failed_to_fetch_registry_for_rationale")

    return {"actions": actions, "rationale": rationale}


@router.get("/workflows/{workflow_id}/agents")
def get_agents(workflow_id: str, db: Session = Depends(get_db)):
    rows = AgentLogRepository(db).list_by_workflow(workflow_id)
    return [
        {
            "id": str(r.id),
            "agent": r.agent,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in rows
    ]


@router.get("/workflows/{workflow_id}/qa")
async def get_qa_summary(workflow_id: str, db: Session = Depends(get_db)):
    """Return the QA Lead's standup summary and risk level."""
    row = QASummaryRepository(db).get_by_workflow(workflow_id)
    if row:
        return {
            "workflow_id": workflow_id,
            "risk_level": row.risk_level,
            "summary": row.summary,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    try:
        reg = await workflow_registry.get_workflow(workflow_id)
        if reg and isinstance(reg, dict) and reg.get("qa_summary"):
            return {
                "workflow_id": workflow_id,
                "risk_level": reg.get("risk_level", "UNKNOWN"),
                "summary": reg.get("qa_summary", ""),
                "created_at": None,
            }
    except Exception:
        logger.exception("failed_to_fetch_registry_for_qa")

    raise HTTPException(status_code=404, detail="QA summary not available yet")

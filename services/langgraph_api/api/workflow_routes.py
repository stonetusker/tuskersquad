"""
Workflow API Routes
===================
All REST endpoints for TuskerSquad.
"""

import logging
import os
import threading
import uuid
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
from ..workflows.pr_review_workflow import (
    execute_workflow,
    resume_workflow_with_decision,
    get_graph,
)

logger = logging.getLogger("langgraph.api.workflow_routes")

router = APIRouter(prefix="", tags=["workflow"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class StartWorkflow(BaseModel):
    repo: str = Field(..., description="Repository full name e.g. owner/repo")
    pr_number: int = Field(..., description="Pull request number")


class ReleaseOverride(BaseModel):
    reason: str = Field(default="Release Manager override")
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


def _parse_uuid(workflow_id: str) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(workflow_id)
    except (ValueError, AttributeError):
        return None


def _get_wf_row(db: Session, workflow_id: str) -> Optional[WorkflowRun]:
    uid = _parse_uuid(workflow_id)
    if uid is None:
        return None
    return db.query(WorkflowRun).filter(WorkflowRun.id == uid).first()


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

        t = threading.Thread(target=execute_workflow, args=(str(workflow.id),), daemon=True)
        t.start()

        logger.info("workflow_started id=%s repo=%s pr=%s", workflow.id, payload.repo, payload.pr_number)
        return {"workflow_id": str(workflow.id), "status": workflow.status}
    except Exception as exc:
        logger.exception("start_workflow_failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# List / Get
# ---------------------------------------------------------------------------

@router.get("/workflows/live")
async def list_workflows_live():
    """In-memory registry list (fast, includes running workflows)."""
    return await workflow_registry.list_workflows()


@router.get("/workflows")
def api_list_workflows(db: Session = Depends(get_db)):
    """Persistent DB list (survives restarts)."""
    rows = db.query(WorkflowRun).order_by(WorkflowRun.created_at.desc()).all()
    return [_wf_to_dict(r) for r in rows]


@router.get("/workflow/{workflow_id}")
async def get_workflow(workflow_id: str, db: Session = Depends(get_db)):
    """Try in-memory registry first (has live status), fall back to DB."""
    reg = await workflow_registry.get_workflow(workflow_id)
    if reg:
        return reg
    # Fall back to DB for workflows not in registry (after restart)
    row = _get_wf_row(db, workflow_id)
    if row:
        return _wf_to_dict(row)
    raise HTTPException(status_code=404, detail="workflow not found")


# ---------------------------------------------------------------------------
# Human governance actions
# ---------------------------------------------------------------------------

@router.post("/workflow/{workflow_id}/approve")
async def approve_workflow(workflow_id: str, db: Session = Depends(get_db)):
    gov_repo = GovernanceRepository(db)
    workflow_repo = WorkflowRepository(db)

    # For SimpleGraph: update DB directly
    action = gov_repo.create_decision(workflow_id, "APPROVE")
    action.approved = True
    db.commit()
    workflow_repo.update_workflow_status(workflow_id, "COMPLETED")
    await workflow_registry.update_workflow(workflow_id, {"workflow_id": workflow_id, "status": "COMPLETED"})

    # For LangGraph: resume paused interrupt in background
    t = threading.Thread(
        target=resume_workflow_with_decision,
        args=(workflow_id, "APPROVE", "Human QA Lead approval"),
        daemon=True,
    )
    t.start()

    _post_gitea_comment(workflow_id, "APPROVE", None, db)
    return {"workflow_id": workflow_id, "status": "COMPLETED"}


@router.post("/workflow/{workflow_id}/reject")
async def reject_workflow(workflow_id: str, db: Session = Depends(get_db)):
    gov_repo = GovernanceRepository(db)
    workflow_repo = WorkflowRepository(db)

    action = gov_repo.create_decision(workflow_id, "REJECT")
    action.approved = False
    db.commit()
    workflow_repo.update_workflow_status(workflow_id, "COMPLETED")
    await workflow_registry.update_workflow(workflow_id, {"workflow_id": workflow_id, "status": "COMPLETED"})

    t = threading.Thread(
        target=resume_workflow_with_decision,
        args=(workflow_id, "REJECT", "Human QA Lead rejection"),
        daemon=True,
    )
    t.start()

    _post_gitea_comment(workflow_id, "REJECT", None, db)
    return {"workflow_id": workflow_id, "status": "COMPLETED"}


@router.post("/workflow/{workflow_id}/retest")
async def retest_workflow(workflow_id: str, db: Session = Depends(get_db)):
    gov_repo = GovernanceRepository(db)
    workflow_repo = WorkflowRepository(db)

    gov_repo.create_decision(workflow_id, "RETEST_REQUESTED")
    db.commit()
    workflow_repo.update_workflow_status(workflow_id, "RUNNING")
    await workflow_registry.update_workflow(workflow_id, {"workflow_id": workflow_id, "status": "RUNNING"})

    t = threading.Thread(target=_retest_background, args=(workflow_id,), daemon=True)
    t.start()

    return {"workflow_id": workflow_id, "status": "RUNNING", "action": "RETEST_REQUESTED"}


def _retest_background(workflow_id: str) -> None:
    """
    For LangGraph: resume with RETEST so graph loops back to planner.
    For SimpleGraph: just re-execute (resume is a no-op).
    Avoids running the pipeline twice by checking graph type.
    """
    from ..workflows.graph_builder import LangGraphWrapper
    graph = get_graph()

    if isinstance(graph, LangGraphWrapper):
        try:
            resume_workflow_with_decision(workflow_id, "RETEST", "Human retest request")
            return  # LangGraph handled it
        except Exception:
            logger.exception("langgraph_retest_failed — falling back to full re-execute")

    # SimpleGraph fallback: full re-execute
    try:
        execute_workflow(workflow_id)
    except Exception:
        logger.exception("retest_execute_failed workflow=%s", workflow_id)


@router.post("/workflow/{workflow_id}/release")
async def release_manager_override(
    workflow_id: str,
    payload: ReleaseOverride,
    db: Session = Depends(get_db),
):
    gov_repo = GovernanceRepository(db)
    workflow_repo = WorkflowRepository(db)

    decision = payload.decision.upper()
    if decision not in ("APPROVE", "REJECT"):
        raise HTTPException(status_code=400, detail="decision must be APPROVE or REJECT")

    action = gov_repo.create_decision(workflow_id, f"RELEASE_MANAGER_{decision}")
    action.approved = (decision == "APPROVE")
    db.commit()
    workflow_repo.update_workflow_status(workflow_id, "COMPLETED")
    await workflow_registry.update_workflow(workflow_id, {
        "workflow_id": workflow_id,
        "status": "COMPLETED",
        "release_decision": decision,
        "release_reason": payload.reason,
    })

    _post_gitea_comment(workflow_id, decision, payload.reason, db, is_release=True)

    logger.info("release_manager_override workflow=%s decision=%s", workflow_id, decision)
    return {"workflow_id": workflow_id, "status": "COMPLETED", "decision": decision, "reason": payload.reason}


@router.post("/workflow/{workflow_id}/resume")
async def resume_workflow(workflow_id: str, db: Session = Depends(get_db)):
    WorkflowRepository(db).update_workflow_status(workflow_id, "RUNNING")
    t = threading.Thread(target=execute_workflow, args=(workflow_id,), daemon=True)
    t.start()
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
        if reg:
            rationale = reg.get("rationale")
    except Exception:
        pass
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
            "output": getattr(r, "output", None) or "",
        }
        for r in rows
    ]


@router.get("/workflows/{workflow_id}/qa")
async def get_qa_summary(workflow_id: str, db: Session = Depends(get_db)):
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
        if reg and reg.get("qa_summary"):
            return {
                "workflow_id": workflow_id,
                "risk_level": reg.get("risk_level", "UNKNOWN"),
                "summary": reg.get("qa_summary", ""),
                "created_at": None,
            }
    except Exception:
        pass
    raise HTTPException(status_code=404, detail="QA summary not available yet")


# ---------------------------------------------------------------------------
# Gitea comment helper
# ---------------------------------------------------------------------------

def _post_gitea_comment(workflow_id: str, decision: str, reason: Optional[str], db: Session,
                        is_release: bool = False) -> None:
    GITEA_URL = os.getenv("GITEA_URL")
    GITEA_TOKEN = os.getenv("GITEA_TOKEN")
    if not GITEA_URL or not GITEA_TOKEN:
        return
    try:
        import httpx as _httpx
        wf = _get_wf_row(db, workflow_id)
        if not wf:
            return
        label = "Release Manager Override" if is_release else "Human QA Lead"
        body = f"TuskerSquad decision: **{decision}** ({label})"
        if reason:
            body += f"\n\n**Reason:** {reason}"
        url = f"{GITEA_URL}/api/v1/repos/{wf.repository}/issues/{wf.pr_number}/comments"
        with _httpx.Client(timeout=8) as client:
            client.post(url, json={"body": body},
                        headers={"Authorization": f"token {GITEA_TOKEN}"})
    except Exception:
        logger.debug("gitea_comment_failed workflow=%s", workflow_id)

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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.workflow_registry import workflow_registry
from ..core.gitea_client import (
    build_comment_body,
    merge_pr_sync,
    trigger_deploy_pipeline,
    set_pr_label,
    post_pr_comment_sync,
)

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


class StartWorkflow(BaseModel):
    repo: str = Field(..., description="Repository full name")
    pr_number: int = Field(..., description="Pull request number")


class ReleaseOverride(BaseModel):
    reason: str = Field(default="Release Manager override")
    decision: str = Field(default="APPROVE")


def _wf_to_dict(r: WorkflowRun) -> dict:
    return {
        "workflow_id": str(r.id),
        "repository": r.repository,
        "pr_number": r.pr_number,
        "status": r.status,
        "current_agent": r.current_agent,
        "merge_status": r.merge_status,
        "deploy_status": r.deploy_status,
        "deploy_url": r.deploy_url,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _parse_uuid(workflow_id: str) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(workflow_id)
    except Exception:
        return None


def _get_wf_row(db: Session, workflow_id: str) -> Optional[WorkflowRun]:
    uid = _parse_uuid(workflow_id)
    if not uid:
        return None
    return db.query(WorkflowRun).filter(WorkflowRun.id == uid).first()


def _flag(env_var: str) -> bool:
    return os.getenv(env_var, "false").lower() in ("true", "1", "yes")


# -------------------------------------------------------------------------
# MERGE + DEPLOY BACKGROUND WORKER
# -------------------------------------------------------------------------

def _run_merge_and_deploy(
    workflow_id: str,
    repository: str,
    pr_number: int,
    findings: list,
    qa_summary: str,
    risk_level: str,
    rationale: str,
    is_release: bool = False,
    release_reason: str = "",
):

    from ..db.database import SessionLocal

    db = SessionLocal()
    wf_repo = WorkflowRepository(db)

    merged = False
    deployed = False
    deploy_url = ""
    merge_sha = None

    try:

        # ---------------- MERGE ----------------
        if _flag("AUTO_MERGE_ON_APPROVE"):

            wf_repo.update_merge_status(workflow_id, "pending")
            db.commit()

            result = merge_pr_sync(repository, pr_number)

            if result and result.get("success"):

                merged = True
                merge_sha = result.get("sha")

                wf_repo.update_merge_status(
                    workflow_id,
                    "success",
                    merge_sha,
                )
                db.commit()

                workflow_registry.update_workflow_sync(
                    workflow_id,
                    {"workflow_id": workflow_id, "merge_status": "success"},
                )

                set_pr_label(repository, pr_number, "tuskersquad:approved")

                logger.info(
                    "merge_success repo=%s pr=%s sha=%s",
                    repository,
                    pr_number,
                    merge_sha,
                )

            else:

                wf_repo.update_merge_status(workflow_id, "failed")
                db.commit()

                logger.warning(
                    "merge_failed repo=%s pr=%s err=%s",
                    repository,
                    pr_number,
                    result.get("error") if result else "unknown",
                )

        else:

            wf_repo.update_merge_status(workflow_id, "skipped")
            db.commit()
            set_pr_label(repository, pr_number, "tuskersquad:approved")

        # ---------------- DEPLOY ----------------
        if merged and _flag("DEPLOY_ON_MERGE"):

            wf_repo.update_deploy_status(workflow_id, "pending")
            db.commit()

            deploy = trigger_deploy_pipeline(repository, pr_number, workflow_id)

            deploy_url = deploy.get("url", "")

            if deploy and deploy.get("success"):

                deployed = True

                wf_repo.update_deploy_status(
                    workflow_id,
                    "triggered",
                    deploy_url,
                )
                db.commit()

                workflow_registry.update_workflow_sync(
                    workflow_id,
                    {
                        "workflow_id": workflow_id,
                        "deploy_status": "triggered",
                        "deploy_url": deploy_url,
                    },
                )

                set_pr_label(repository, pr_number, "tuskersquad:deployed")

                logger.info(
                    "deploy_triggered repo=%s pr=%s url=%s",
                    repository,
                    pr_number,
                    deploy_url,
                )

            else:

                wf_repo.update_deploy_status(
                    workflow_id,
                    "failed",
                    deploy_url,
                )
                db.commit()

                logger.warning(
                    "deploy_failed repo=%s pr=%s err=%s",
                    repository,
                    pr_number,
                    deploy.get("error") if deploy else "unknown",
                )

        elif not _flag("DEPLOY_ON_MERGE"):

            wf_repo.update_deploy_status(workflow_id, "skipped")
            db.commit()

        # ---------------- COMMENT ----------------
        body = build_comment_body(
            workflow_id=workflow_id,
            decision="APPROVE",
            findings=findings,
            qa_summary=qa_summary,
            risk_level=risk_level,
            rationale=rationale,
            is_release=is_release,
            release_reason=release_reason,
            merged=merged,
            deployed=deployed,
            deploy_url=deploy_url,
        )

        post_pr_comment_sync(repository, pr_number, body)

    except Exception:

        logger.exception("merge_deploy_thread_failed workflow=%s", workflow_id)

    finally:

        db.close()


# -------------------------------------------------------------------------
# START WORKFLOW
# -------------------------------------------------------------------------

@router.post("/workflow/start")
async def start_workflow(
    payload: StartWorkflow,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):

    repo = WorkflowRepository(db)

    workflow = repo.create_workflow_run(
        repository=payload.repo,
        pr_number=payload.pr_number,
    )

    state = {
        "workflow_id": str(workflow.id),
        "repository": payload.repo,
        "pr_number": payload.pr_number,
        "status": workflow.status,
        "findings": [],
        "challenges": [],
        "current_agent": None,
        "merge_status": None,
        "deploy_status": None,
    }

    await workflow_registry.register_workflow(state)

    threading.Thread(
        target=execute_workflow,
        args=(str(workflow.id),),
        daemon=True,
    ).start()

    return {
        "workflow_id": str(workflow.id),
        "status": workflow.status,
    }


# -------------------------------------------------------------------------
# WORKFLOW LIST / GET
# -------------------------------------------------------------------------

@router.get("/workflows")
def api_list_workflows(db: Session = Depends(get_db)):
    rows = db.query(WorkflowRun).order_by(WorkflowRun.created_at.desc()).all()
    return [_wf_to_dict(r) for r in rows]



@router.get("/workflows/live")
async def list_workflows_live():
    """
    Returns workflows currently in memory (running workflows).
    Used by dashboard for real-time updates.
    """
    try:
        return await workflow_registry.list_workflows()
    except Exception:
        logger.exception("live_workflow_fetch_failed")
        return []

@router.get("/workflow/{workflow_id}")
async def get_workflow(workflow_id: str, db: Session = Depends(get_db)):

    reg = await workflow_registry.get_workflow(workflow_id)

    if reg:

        row = _get_wf_row(db, workflow_id)

        if row:
            reg.setdefault("merge_status", row.merge_status)
            reg.setdefault("deploy_status", row.deploy_status)
            reg.setdefault("deploy_url", row.deploy_url)

        return reg

    row = _get_wf_row(db, workflow_id)

    if row:
        return _wf_to_dict(row)

    raise HTTPException(status_code=404, detail="workflow not found")


# -------------------------------------------------------------------------
# MERGE STATUS POLL
# -------------------------------------------------------------------------

@router.get("/workflow/{workflow_id}/merge-status")
async def get_merge_status(workflow_id: str, db: Session = Depends(get_db)):

    row = _get_wf_row(db, workflow_id)

    if not row:
        raise HTTPException(status_code=404, detail="workflow not found")

    return {
        "workflow_id": workflow_id,
        "merge_status": row.merge_status,
        "deploy_status": row.deploy_status,
        "deploy_url": row.deploy_url,
    }

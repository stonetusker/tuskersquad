"""
Workflow API Routes
===================
All REST endpoints for TuskerSquad.

New in this release
-------------------
- approve_workflow  now calls _run_merge_and_deploy() in a background thread
  when AUTO_MERGE_ON_APPROVE=true.
- release_manager_override also triggers merge+deploy when decision=APPROVE
  and AUTO_MERGE_ON_APPROVE=true.
- GET /workflow/{id}  now returns merge_status, deploy_status, deploy_url.
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


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response models
# ─────────────────────────────────────────────────────────────────────────────

class StartWorkflow(BaseModel):
    repo:      str = Field(..., description="Repository full name e.g. owner/repo")
    pr_number: int = Field(..., description="Pull request number")


class ReleaseOverride(BaseModel):
    reason:   str = Field(default="Release Manager override")
    decision: str = Field(default="APPROVE", description="APPROVE or REJECT")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _wf_to_dict(r: WorkflowRun) -> dict:
    return {
        "workflow_id":   str(r.id),
        "repository":    r.repository,
        "pr_number":     r.pr_number,
        "status":        r.status,
        "current_agent": r.current_agent,
        "merge_status":  r.merge_status,
        "deploy_status": r.deploy_status,
        "deploy_url":    r.deploy_url,
        "created_at":    r.created_at.isoformat() if r.created_at else None,
        "updated_at":    r.updated_at.isoformat() if r.updated_at else None,
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


def _flag(env_var: str) -> bool:
    return os.getenv(env_var, "false").lower() in ("true", "1", "yes")


# ─────────────────────────────────────────────────────────────────────────────
# Merge + Deploy  (runs in background thread after approve)
# ─────────────────────────────────────────────────────────────────────────────

def _run_merge_and_deploy(
    workflow_id: str,
    repository:  str,
    pr_number:   int,
    findings:    list,
    qa_summary:  str,
    risk_level:  str,
    rationale:   str,
    is_release:  bool = False,
    release_reason: str = "",
) -> None:
    """
    Background thread that:
      1. Merges the PR via Gitea API           (if AUTO_MERGE_ON_APPROVE=true)
      2. Triggers deploy pipeline              (if DEPLOY_ON_MERGE=true)
      3. Updates DB merge_status / deploy_status
      4. Posts a rich markdown comment to the PR
      5. Sets a tuskersquad:approved label
    """
    from ..db.database import SessionLocal  # avoid circular at module load
    db = SessionLocal()
    wf_repo = WorkflowRepository(db)

    merged     = False
    deployed   = False
    deploy_url = ""

    try:
        # ── 1. Auto-Merge ───────────────────────────────────────────────────
        if _flag("AUTO_MERGE_ON_APPROVE"):
            logger.info("auto_merge_start repo=%s pr=%s wf=%s",
                        repository, pr_number, workflow_id)
            wf_repo.update_merge_status(workflow_id, "pending")

            merge_result = merge_pr_sync(repository, pr_number)

            if merge_result["success"]:
                wf_repo.update_merge_status(workflow_id, "success")
                workflow_registry.update_workflow_sync(workflow_id, {
                    "workflow_id":  workflow_id,
                    "merge_status": "success",
                })
                merged = True
                # Label the PR as approved
                set_pr_label(repository, pr_number, "tuskersquad:approved")
                logger.info("auto_merge_success repo=%s pr=%s", repository, pr_number)
            else:
                wf_repo.update_merge_status(workflow_id, "failed")
                workflow_registry.update_workflow_sync(workflow_id, {
                    "workflow_id":  workflow_id,
                    "merge_status": "failed",
                })
                logger.warning("auto_merge_failed repo=%s pr=%s err=%s",
                               repository, pr_number, merge_result.get("error"))
        else:
            wf_repo.update_merge_status(workflow_id, "skipped")
            # Still label the PR
            set_pr_label(repository, pr_number, "tuskersquad:approved")

        # ── 2. Deploy on Merge ───────────────────────────────────────────────
        if merged and _flag("DEPLOY_ON_MERGE"):
            logger.info("deploy_start repo=%s pr=%s wf=%s",
                        repository, pr_number, workflow_id)
            wf_repo.update_deploy_status(workflow_id, "pending")

            deploy_result = trigger_deploy_pipeline(repository, pr_number, workflow_id)
            deploy_url    = deploy_result.get("url", "")

            if deploy_result["success"]:
                wf_repo.update_deploy_status(workflow_id, "triggered", deploy_url)
                workflow_registry.update_workflow_sync(workflow_id, {
                    "workflow_id":   workflow_id,
                    "deploy_status": "triggered",
                    "deploy_url":    deploy_url,
                })
                deployed = True
                set_pr_label(repository, pr_number, "tuskersquad:deployed")
                logger.info("deploy_triggered repo=%s pr=%s url=%s",
                            repository, pr_number, deploy_url)
            else:
                wf_repo.update_deploy_status(workflow_id, "failed", deploy_url)
                workflow_registry.update_workflow_sync(workflow_id, {
                    "workflow_id":   workflow_id,
                    "deploy_status": "failed",
                    "deploy_url":    deploy_url,
                })
                logger.warning("deploy_failed repo=%s pr=%s err=%s",
                               repository, pr_number, deploy_result.get("error"))
        elif not _flag("DEPLOY_ON_MERGE"):
            wf_repo.update_deploy_status(workflow_id, "skipped")

        # ── 3. Rich PR comment ───────────────────────────────────────────────
        comment_body = build_comment_body(
            workflow_id    = workflow_id,
            decision       = "APPROVE",
            findings       = findings,
            qa_summary     = qa_summary,
            risk_level     = risk_level,
            rationale      = rationale,
            is_release     = is_release,
            release_reason = release_reason,
            merged         = merged,
            deployed       = deployed,
            deploy_url     = deploy_url,
        )
        post_pr_comment_sync(repository, pr_number, comment_body)

    except Exception:
        logger.exception("merge_deploy_thread_failed workflow=%s", workflow_id)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Start workflow
# ─────────────────────────────────────────────────────────────────────────────

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
            "workflow_id":   str(workflow.id),
            "repository":    payload.repo,
            "pr_number":     payload.pr_number,
            "status":        workflow.status,
            "findings":      [],
            "challenges":    [],
            "current_agent": None,
            "merge_status":  None,
            "deploy_status": None,
        }
        await workflow_registry.register_workflow(state)

        t = threading.Thread(
            target=execute_workflow, args=(str(workflow.id),), daemon=True
        )
        t.start()

        logger.info("workflow_started id=%s repo=%s pr=%s",
                    workflow.id, payload.repo, payload.pr_number)
        return {"workflow_id": str(workflow.id), "status": workflow.status}
    except Exception as exc:
        logger.exception("start_workflow_failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# List / Get
# ─────────────────────────────────────────────────────────────────────────────

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
    """Try in-memory registry first, fall back to DB."""
    reg = await workflow_registry.get_workflow(workflow_id)
    if reg:
        # Merge DB fields not in registry
        row = _get_wf_row(db, workflow_id)
        if row:
            reg.setdefault("merge_status",  row.merge_status)
            reg.setdefault("deploy_status", row.deploy_status)
            reg.setdefault("deploy_url",    row.deploy_url)
        return reg
    row = _get_wf_row(db, workflow_id)
    if row:
        return _wf_to_dict(row)
    raise HTTPException(status_code=404, detail="workflow not found")


# ─────────────────────────────────────────────────────────────────────────────
# Human governance actions
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/workflow/{workflow_id}/approve")
async def approve_workflow(workflow_id: str, db: Session = Depends(get_db)):
    gov_repo      = GovernanceRepository(db)
    workflow_repo = WorkflowRepository(db)
    findings_repo = FindingsRepository(db)
    qa_repo       = QASummaryRepository(db)

    # Update governance + status
    action          = gov_repo.create_decision(workflow_id, "APPROVE")
    action.approved = True
    db.commit()
    workflow_repo.update_workflow_status(workflow_id, "COMPLETED")
    await workflow_registry.update_workflow(workflow_id, {
        "workflow_id": workflow_id,
        "status":      "COMPLETED",
    })

    # Resume LangGraph interrupt (no-op for SimpleGraph)
    threading.Thread(
        target=resume_workflow_with_decision,
        args=(workflow_id, "APPROVE", "Human QA Lead approval"),
        daemon=True,
    ).start()

    # Gather context for the merge/deploy thread
    wf         = _get_wf_row(db, workflow_id)
    repository = wf.repository if wf else ""
    pr_number  = wf.pr_number  if wf else 0

    findings = [
        {"agent": f.agent, "title": f.title, "severity": f.severity}
        for f in findings_repo.list_by_workflow(workflow_id)
    ]
    qa         = qa_repo.get_by_workflow(workflow_id)
    qa_summary = qa.summary    if qa else ""
    risk_level = qa.risk_level if qa else ""

    reg        = await workflow_registry.get_workflow(workflow_id)
    rationale  = (reg or {}).get("rationale", "")

    # Merge + Deploy in background (non-blocking)
    if repository and pr_number:
        threading.Thread(
            target=_run_merge_and_deploy,
            args=(workflow_id, repository, pr_number,
                  findings, qa_summary, risk_level, rationale),
            daemon=True,
        ).start()
    else:
        # No Gitea info — just post a basic comment
        _post_gitea_comment(workflow_id, "APPROVE", None, db)

    return {
        "workflow_id":       workflow_id,
        "status":            "COMPLETED",
        "auto_merge_queued": _flag("AUTO_MERGE_ON_APPROVE") and bool(repository),
        "deploy_queued":     _flag("DEPLOY_ON_MERGE") and bool(repository),
    }


@router.post("/workflow/{workflow_id}/reject")
async def reject_workflow(workflow_id: str, db: Session = Depends(get_db)):
    gov_repo      = GovernanceRepository(db)
    workflow_repo = WorkflowRepository(db)

    action          = gov_repo.create_decision(workflow_id, "REJECT")
    action.approved = False
    db.commit()
    workflow_repo.update_workflow_status(workflow_id, "COMPLETED")
    await workflow_registry.update_workflow(workflow_id, {
        "workflow_id": workflow_id,
        "status":      "COMPLETED",
    })

    threading.Thread(
        target=resume_workflow_with_decision,
        args=(workflow_id, "REJECT", "Human QA Lead rejection"),
        daemon=True,
    ).start()

    # Label PR as rejected
    wf = _get_wf_row(db, workflow_id)
    if wf and wf.repository:
        set_pr_label(wf.repository, wf.pr_number, "tuskersquad:rejected")

    _post_gitea_comment(workflow_id, "REJECT", None, db)
    return {"workflow_id": workflow_id, "status": "COMPLETED"}


@router.post("/workflow/{workflow_id}/retest")
async def retest_workflow(workflow_id: str, db: Session = Depends(get_db)):
    gov_repo      = GovernanceRepository(db)
    workflow_repo = WorkflowRepository(db)

    gov_repo.create_decision(workflow_id, "RETEST_REQUESTED")
    db.commit()
    workflow_repo.update_workflow_status(workflow_id, "RUNNING")
    await workflow_registry.update_workflow(workflow_id, {
        "workflow_id": workflow_id,
        "status":      "RUNNING",
    })

    threading.Thread(target=_retest_background, args=(workflow_id,), daemon=True).start()
    return {"workflow_id": workflow_id, "status": "RUNNING", "action": "RETEST_REQUESTED"}


def _retest_background(workflow_id: str) -> None:
    from ..workflows.graph_builder import LangGraphWrapper
    graph = get_graph()
    if isinstance(graph, LangGraphWrapper):
        try:
            resume_workflow_with_decision(workflow_id, "RETEST", "Human retest request")
            return
        except Exception:
            logger.exception("langgraph_retest_failed — falling back to full re-execute")
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
    gov_repo      = GovernanceRepository(db)
    workflow_repo = WorkflowRepository(db)
    findings_repo = FindingsRepository(db)
    qa_repo       = QASummaryRepository(db)

    decision = payload.decision.upper()
    if decision not in ("APPROVE", "REJECT"):
        raise HTTPException(status_code=400, detail="decision must be APPROVE or REJECT")

    action          = gov_repo.create_decision(workflow_id, f"RELEASE_MANAGER_{decision}")
    action.approved = (decision == "APPROVE")
    db.commit()
    workflow_repo.update_workflow_status(workflow_id, "COMPLETED")
    await workflow_registry.update_workflow(workflow_id, {
        "workflow_id":      workflow_id,
        "status":           "COMPLETED",
        "release_decision": decision,
        "release_reason":   payload.reason,
    })

    wf         = _get_wf_row(db, workflow_id)
    repository = wf.repository if wf else ""
    pr_number  = wf.pr_number  if wf else 0

    if decision == "APPROVE" and repository and pr_number:
        findings = [
            {"agent": f.agent, "title": f.title, "severity": f.severity}
            for f in findings_repo.list_by_workflow(workflow_id)
        ]
        qa         = qa_repo.get_by_workflow(workflow_id)
        qa_summary = qa.summary    if qa else ""
        risk_level = qa.risk_level if qa else ""
        reg        = await workflow_registry.get_workflow(workflow_id)
        rationale  = (reg or {}).get("rationale", "")

        threading.Thread(
            target=_run_merge_and_deploy,
            args=(workflow_id, repository, pr_number,
                  findings, qa_summary, risk_level, rationale,
                  True, payload.reason),
            daemon=True,
        ).start()
    else:
        _post_gitea_comment(workflow_id, decision, payload.reason, db, is_release=True)

    logger.info("release_manager_override workflow=%s decision=%s", workflow_id, decision)
    return {
        "workflow_id":       workflow_id,
        "status":            "COMPLETED",
        "decision":          decision,
        "reason":            payload.reason,
        "auto_merge_queued": decision == "APPROVE" and _flag("AUTO_MERGE_ON_APPROVE"),
    }


@router.post("/workflow/{workflow_id}/resume")
async def resume_workflow(workflow_id: str, db: Session = Depends(get_db)):
    WorkflowRepository(db).update_workflow_status(workflow_id, "RUNNING")
    threading.Thread(target=execute_workflow, args=(workflow_id,), daemon=True).start()
    return {"workflow_id": workflow_id, "status": "RUNNING"}


# ─────────────────────────────────────────────────────────────────────────────
# Sub-resource endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/workflows/{workflow_id}/findings")
def get_findings(workflow_id: str, db: Session = Depends(get_db)):
    rows = FindingsRepository(db).list_by_workflow(workflow_id)
    return [
        {
            "id":          str(r.id),
            "agent":       r.agent,
            "severity":    r.severity,
            "title":       r.title,
            "description": r.description,
            "created_at":  r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/workflows/{workflow_id}/governance")
async def get_governance(workflow_id: str, db: Session = Depends(get_db)):
    rows = GovernanceRepository(db).list_by_workflow(workflow_id)
    actions = [
        {
            "id":         str(r.id),
            "decision":   r.decision,
            "approved":   bool(r.approved) if r.approved is not None else None,
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
            "id":           str(r.id),
            "agent":        r.agent,
            "status":       r.status,
            "started_at":   r.started_at.isoformat()   if r.started_at   else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "output":       getattr(r, "output", None) or "",
        }
        for r in rows
    ]


@router.get("/workflows/{workflow_id}/qa")
async def get_qa_summary(workflow_id: str, db: Session = Depends(get_db)):
    row = QASummaryRepository(db).get_by_workflow(workflow_id)
    if row:
        return {
            "workflow_id": workflow_id,
            "risk_level":  row.risk_level,
            "summary":     row.summary,
            "created_at":  row.created_at.isoformat() if row.created_at else None,
        }
    try:
        reg = await workflow_registry.get_workflow(workflow_id)
        if reg and reg.get("qa_summary"):
            return {
                "workflow_id": workflow_id,
                "risk_level":  reg.get("risk_level", "UNKNOWN"),
                "summary":     reg.get("qa_summary", ""),
                "created_at":  None,
            }
    except Exception:
        pass
    raise HTTPException(status_code=404, detail="QA summary not available yet")


# ─────────────────────────────────────────────────────────────────────────────
# Merge / Deploy status endpoint  (for UI polling)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/workflow/{workflow_id}/merge-status")
async def get_merge_status(workflow_id: str, db: Session = Depends(get_db)):
    """
    Lightweight endpoint for the UI to poll merge/deploy progress.
    Returns merge_status, deploy_status, deploy_url.
    """
    row = _get_wf_row(db, workflow_id)
    if not row:
        raise HTTPException(status_code=404, detail="workflow not found")
    return {
        "workflow_id":   workflow_id,
        "merge_status":  row.merge_status,
        "deploy_status": row.deploy_status,
        "deploy_url":    row.deploy_url,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Legacy Gitea comment helper  (used for REJECT / simple paths)
# ─────────────────────────────────────────────────────────────────────────────

def _post_gitea_comment(
    workflow_id: str,
    decision: str,
    reason: Optional[str],
    db: Session,
    is_release: bool = False,
) -> None:
    try:
        wf = _get_wf_row(db, workflow_id)
        if not wf or not wf.repository:
            return
        body = build_comment_body(
            workflow_id    = workflow_id,
            decision       = decision,
            findings       = [],
            is_release     = is_release,
            release_reason = reason or "",
        )
        post_pr_comment_sync(wf.repository, wf.pr_number, body)
    except Exception:
        logger.debug("gitea_comment_failed workflow=%s", workflow_id)

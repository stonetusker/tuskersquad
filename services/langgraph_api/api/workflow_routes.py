"""
Workflow API Routes
===================
Includes new transparency endpoints:
  /workflows/{id}/llm-logs      — LLM conversation log (agent ↔ Ollama)
  /workflows/{id}/agent-decisions — Per-agent decision summaries
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
    build_governance_comment,
    build_initial_review_comment,
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
from ..repositories.llm_log_repository import LLMLogRepository
from ..repositories.agent_decision_repository import AgentDecisionRepository
from ..workflows.pr_review_workflow import (
    execute_workflow,
    resume_workflow_with_decision,
    get_graph,
)

logger = logging.getLogger("langgraph.api.workflow_routes")

router = APIRouter(prefix="", tags=["workflow"])


# ─── Request models ───────────────────────────────────────────────────────────

class StartWorkflow(BaseModel):
    repo:      str = Field(..., description="owner/repo")
    pr_number: int = Field(..., description="Pull request number")


class ReleaseOverride(BaseModel):
    reason:   str = Field(default="Release Manager override")
    decision: str = Field(default="APPROVE")


# ─── Helpers ──────────────────────────────────────────────────────────────────

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
    except Exception:
        return None


def _get_wf_row(db: Session, workflow_id: str) -> Optional[WorkflowRun]:
    uid = _parse_uuid(workflow_id)
    if not uid:
        return None
    return db.query(WorkflowRun).filter(WorkflowRun.id == uid).first()


def _flag(env_var: str) -> bool:
    return os.getenv(env_var, "false").lower() in ("true", "1", "yes")


# ─── Merge + Deploy background worker ────────────────────────────────────────

def _run_merge_and_deploy(
    workflow_id, repository, pr_number,
    findings, qa_summary, risk_level, rationale,
    agent_decisions=None,
    is_release=False, release_reason="",
):
    from ..db.database import SessionLocal
    db      = SessionLocal()
    wf_repo = WorkflowRepository(db)
    merged  = deployed = False
    deploy_url = ""

    try:
        if _flag("AUTO_MERGE_ON_APPROVE"):
            wf_repo.update_merge_status(workflow_id, "pending")
            result = merge_pr_sync(repository, pr_number)
            if result and result.get("success"):
                merged = True
                wf_repo.update_merge_status(workflow_id, "success", result.get("sha"))
                workflow_registry.update_workflow_sync(workflow_id, {
                    "workflow_id": workflow_id, "merge_status": "success"
                })
                set_pr_label(repository, pr_number, "tuskersquad:approved")
            else:
                wf_repo.update_merge_status(workflow_id, "failed")
        else:
            wf_repo.update_merge_status(workflow_id, "skipped")
            set_pr_label(repository, pr_number, "tuskersquad:approved")

        if merged and _flag("DEPLOY_ON_MERGE"):
            wf_repo.update_deploy_status(workflow_id, "pending")
            deploy = trigger_deploy_pipeline(repository, pr_number, workflow_id)
            deploy_url = deploy.get("url", "")
            if deploy and deploy.get("success"):
                deployed = True
                wf_repo.update_deploy_status(workflow_id, "triggered", deploy_url)
                workflow_registry.update_workflow_sync(workflow_id, {
                    "workflow_id": workflow_id,
                    "deploy_status": "triggered",
                    "deploy_url": deploy_url,
                })
                set_pr_label(repository, pr_number, "tuskersquad:deployed")
            else:
                wf_repo.update_deploy_status(workflow_id, "failed", deploy_url)
        elif not _flag("DEPLOY_ON_MERGE"):
            wf_repo.update_deploy_status(workflow_id, "skipped")

        # Governance comment (approve decision + merge/deploy status)
        body = build_governance_comment(
            workflow_id=workflow_id,
            decision="APPROVE",
            actor="Release Manager Override" if is_release else "Human Reviewer",
            reason=release_reason if is_release else "",
            is_release=is_release,
            merged=merged,
            deployed=deployed,
            deploy_url=deploy_url,
        )
        post_pr_comment_sync(repository, pr_number, body)

    except Exception:
        logger.exception("merge_deploy_thread_failed workflow=%s", workflow_id)
    finally:
        db.close()


# ─── Start ────────────────────────────────────────────────────────────────────

@router.post("/workflow/start")
async def start_workflow(
    payload: StartWorkflow,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    repo     = WorkflowRepository(db)
    workflow = repo.create_workflow_run(repository=payload.repo, pr_number=payload.pr_number)
    state = {
        "workflow_id":    str(workflow.id),
        "repository":     payload.repo,
        "pr_number":      payload.pr_number,
        "status":         workflow.status,
        "findings":       [],
        "challenges":     [],
        "current_agent":  None,
        "merge_status":   None,
        "deploy_status":  None,
        "agent_timeline": [],
    }
    await workflow_registry.register_workflow(state)
    threading.Thread(target=execute_workflow, args=(str(workflow.id),), daemon=True).start()
    logger.info("workflow_started id=%s repo=%s pr=%s", workflow.id, payload.repo, payload.pr_number)
    return {"workflow_id": str(workflow.id), "status": workflow.status}


# ─── List / Get ───────────────────────────────────────────────────────────────

@router.get("/workflows")
def api_list_workflows(db: Session = Depends(get_db)):
    rows = db.query(WorkflowRun).order_by(WorkflowRun.created_at.desc()).all()
    return [_wf_to_dict(r) for r in rows]


@router.get("/workflows/live")
async def list_workflows_live():
    try:
        return await workflow_registry.list_workflows()
    except Exception:
        return []


@router.get("/workflows/heatmap")
async def get_risk_heatmap(db: Session = Depends(get_db)):
    from ..db.models import EngineeringFinding
    from sqlalchemy import func

    rows = (
        db.query(
            EngineeringFinding.agent,
            EngineeringFinding.severity,
            func.count(EngineeringFinding.id).label("count"),
        )
        .group_by(EngineeringFinding.agent, EngineeringFinding.severity)
        .all()
    )

    agents     = ["planner", "backend", "frontend", "security", "sre", "challenger", "qa_lead", "judge"]
    severities = ["HIGH", "MEDIUM", "LOW"]
    lookup     = {(r.agent, r.severity): r.count for r in rows}

    matrix = [
        {"agent": a, "severity": s, "count": lookup.get((a, s), 0)}
        for a in agents for s in severities
    ]
    recent = db.query(WorkflowRun).order_by(WorkflowRun.created_at.desc()).limit(20).all()
    trend  = [{"workflow_id": str(w.id)[:8], "repository": w.repository,
               "status": w.status, "created_at": w.created_at.isoformat() if w.created_at else None}
              for w in recent]
    return {"matrix": matrix, "agents": agents, "severities": severities, "trend": trend}


@router.get("/workflow/{workflow_id}")
async def get_workflow(workflow_id: str, db: Session = Depends(get_db)):
    reg = await workflow_registry.get_workflow(workflow_id)
    if reg:
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


@router.get("/workflow/{workflow_id}/merge-status")
async def get_merge_status(workflow_id: str, db: Session = Depends(get_db)):
    row = _get_wf_row(db, workflow_id)
    if not row:
        raise HTTPException(status_code=404, detail="workflow not found")
    return {
        "workflow_id":   workflow_id,
        "merge_status":  row.merge_status,
        "deploy_status": row.deploy_status,
        "deploy_url":    row.deploy_url,
    }


# ─── Sub-resources ────────────────────────────────────────────────────────────

@router.get("/workflows/{workflow_id}/findings")
def get_findings(workflow_id: str, db: Session = Depends(get_db)):
    rows = FindingsRepository(db).list_by_workflow(workflow_id)
    return [
        {"id": str(r.id), "agent": r.agent, "severity": r.severity,
         "title": r.title, "description": r.description,
         "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]


@router.get("/workflows/{workflow_id}/governance")
async def get_governance(workflow_id: str, db: Session = Depends(get_db)):
    rows    = GovernanceRepository(db).list_by_workflow(workflow_id)
    actions = [
        {"id": str(r.id), "decision": r.decision,
         "approved": bool(r.approved) if r.approved is not None else None,
         "created_at": r.created_at.isoformat() if r.created_at else None}
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
        {"id": str(r.id), "agent": r.agent, "status": r.status,
         "started_at":   r.started_at.isoformat()   if r.started_at   else None,
         "completed_at": r.completed_at.isoformat() if r.completed_at else None,
         "output":       getattr(r, "output", None) or ""}
        for r in rows
    ]


@router.get("/workflows/{workflow_id}/qa")
async def get_qa_summary(workflow_id: str, db: Session = Depends(get_db)):
    row = QASummaryRepository(db).get_by_workflow(workflow_id)
    if row:
        return {"workflow_id": workflow_id, "risk_level": row.risk_level,
                "summary": row.summary, "created_at": row.created_at.isoformat() if row.created_at else None}
    try:
        reg = await workflow_registry.get_workflow(workflow_id)
        if reg and reg.get("qa_summary"):
            return {"workflow_id": workflow_id, "risk_level": reg.get("risk_level", "UNKNOWN"),
                    "summary": reg.get("qa_summary", ""), "created_at": None}
    except Exception:
        pass
    raise HTTPException(status_code=404, detail="QA summary not available yet")


@router.get("/workflows/{workflow_id}/reasoning")
async def get_reasoning(workflow_id: str, db: Session = Depends(get_db)):
    """LLM reasoning log: per-agent output for the reasoning viewer."""
    rows      = AgentLogRepository(db).list_by_workflow(workflow_id)
    reasoning = []
    for r in rows:
        out = getattr(r, "output", None) or ""
        if out:
            reasoning.append({"agent": r.agent, "output": out,
                               "started_at": r.started_at.isoformat() if r.started_at else None,
                               "completed_at": r.completed_at.isoformat() if r.completed_at else None})
    try:
        reg = await workflow_registry.get_workflow(workflow_id)
        if reg and reg.get("agent_reasoning"):
            for item in reg["agent_reasoning"]:
                if not any(r["agent"] == item["agent"] for r in reasoning):
                    reasoning.append(item)
    except Exception:
        pass
    return reasoning


@router.get("/workflows/{workflow_id}/llm-logs")
def get_llm_logs(workflow_id: str, db: Session = Depends(get_db)):
    """Return all LLM conversation records for a workflow."""
    rows = LLMLogRepository(db).list_by_workflow(workflow_id)
    return [
        {"id": str(r.id), "agent": r.agent, "model": r.model,
         "prompt": r.prompt, "response": r.response,
         "duration_ms": r.duration_ms, "success": r.success, "error": r.error,
         "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]


@router.get("/workflows/{workflow_id}/agent-decisions")
def get_agent_decisions(workflow_id: str, db: Session = Depends(get_db)):
    """Per-agent decision summaries for the transparency panel."""
    rows = AgentDecisionRepository(db).list_by_workflow(workflow_id)
    if rows:
        return [
            {"agent": r.agent, "decision": r.decision, "summary": r.summary,
             "risk_level": r.risk_level, "test_count": r.test_count,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows
        ]
    # Fallback: derive from registry
    try:
        from ..core.workflow_registry import workflow_registry as reg_
        state = reg_.get_workflow_sync(workflow_id)
        if state and state.get("agent_decisions"):
            return [
                {"agent": a, **d} for a, d in state["agent_decisions"].items()
            ]
    except Exception:
        pass
    return []


# ─── APPROVE ─────────────────────────────────────────────────────────────────

@router.post("/workflow/{workflow_id}/approve")
async def approve_workflow(workflow_id: str, db: Session = Depends(get_db)):
    gov_repo  = GovernanceRepository(db)
    wf_repo   = WorkflowRepository(db)
    f_repo    = FindingsRepository(db)
    qa_repo   = QASummaryRepository(db)

    action = gov_repo.create_decision(workflow_id, "APPROVE")
    action.approved = True
    db.commit()
    wf_repo.update_workflow_status(workflow_id, "COMPLETED")
    await workflow_registry.update_workflow(workflow_id, {"workflow_id": workflow_id, "status": "COMPLETED"})

    threading.Thread(
        target=resume_workflow_with_decision, args=(workflow_id, "APPROVE", "Human approval"), daemon=True
    ).start()

    wf         = _get_wf_row(db, workflow_id)
    repository = wf.repository if wf else ""
    pr_number  = wf.pr_number  if wf else 0
    findings   = [{"agent": f.agent, "title": f.title, "severity": f.severity,
                   "description": f.description} for f in f_repo.list_by_workflow(workflow_id)]
    qa         = qa_repo.get_by_workflow(workflow_id)
    qa_summary = qa.summary    if qa else ""
    risk_level = qa.risk_level if qa else ""
    reg        = await workflow_registry.get_workflow(workflow_id)
    rationale  = (reg or {}).get("rationale", "")
    ad         = (reg or {}).get("agent_decisions", {})

    if repository and pr_number:
        threading.Thread(
            target=_run_merge_and_deploy,
            args=(workflow_id, repository, pr_number, findings, qa_summary, risk_level, rationale, ad),
            daemon=True,
        ).start()
    else:
        _post_governance_comment(workflow_id, "APPROVE", None, db)

    return {"workflow_id": workflow_id, "status": "COMPLETED",
            "auto_merge_queued": _flag("AUTO_MERGE_ON_APPROVE") and bool(repository),
            "deploy_queued": _flag("DEPLOY_ON_MERGE") and bool(repository)}


# ─── REJECT ──────────────────────────────────────────────────────────────────

@router.post("/workflow/{workflow_id}/reject")
async def reject_workflow(workflow_id: str, db: Session = Depends(get_db)):
    gov_repo = GovernanceRepository(db)
    wf_repo  = WorkflowRepository(db)

    action = gov_repo.create_decision(workflow_id, "REJECT")
    action.approved = False
    db.commit()
    wf_repo.update_workflow_status(workflow_id, "COMPLETED")
    await workflow_registry.update_workflow(workflow_id, {"workflow_id": workflow_id, "status": "COMPLETED"})

    threading.Thread(
        target=resume_workflow_with_decision, args=(workflow_id, "REJECT", "Human rejection"), daemon=True
    ).start()

    wf = _get_wf_row(db, workflow_id)
    if wf and wf.repository:
        set_pr_label(wf.repository, wf.pr_number, "tuskersquad:rejected")

    _post_governance_comment(workflow_id, "REJECT", None, db)
    return {"workflow_id": workflow_id, "status": "COMPLETED"}


# ─── RETEST ───────────────────────────────────────────────────────────────────

@router.post("/workflow/{workflow_id}/retest")
async def retest_workflow(workflow_id: str, db: Session = Depends(get_db)):
    gov_repo = GovernanceRepository(db)
    wf_repo  = WorkflowRepository(db)

    gov_repo.create_decision(workflow_id, "RETEST_REQUESTED")
    db.commit()
    wf_repo.update_workflow_status(workflow_id, "RUNNING")
    await workflow_registry.update_workflow(workflow_id, {"workflow_id": workflow_id, "status": "RUNNING"})
    threading.Thread(target=_retest_background, args=(workflow_id,), daemon=True).start()
    return {"workflow_id": workflow_id, "status": "RUNNING", "action": "RETEST_REQUESTED"}


def _retest_background(workflow_id: str):
    graph = get_graph()
    if isinstance(graph, LangGraphWrapper):
        try:
            resume_workflow_with_decision(workflow_id, "RETEST", "Human retest request")
            return
        except Exception:
            logger.exception("langgraph_retest_failed")
    try:
        execute_workflow(workflow_id)
    except Exception:
        logger.exception("retest_execute_failed workflow=%s", workflow_id)


# ─── RELEASE MANAGER OVERRIDE ────────────────────────────────────────────────

@router.post("/workflow/{workflow_id}/release")
async def release_manager_override(
    workflow_id: str,
    payload: ReleaseOverride,
    db: Session = Depends(get_db),
):
    gov_repo = GovernanceRepository(db)
    wf_repo  = WorkflowRepository(db)
    f_repo   = FindingsRepository(db)
    qa_repo  = QASummaryRepository(db)

    decision = payload.decision.upper()
    if decision not in ("APPROVE", "REJECT"):
        raise HTTPException(status_code=400, detail="decision must be APPROVE or REJECT")

    action = gov_repo.create_decision(workflow_id, f"RELEASE_MANAGER_{decision}")
    action.approved = (decision == "APPROVE")
    db.commit()
    wf_repo.update_workflow_status(workflow_id, "COMPLETED")
    await workflow_registry.update_workflow(workflow_id, {
        "workflow_id": workflow_id, "status": "COMPLETED",
        "release_decision": decision, "release_reason": payload.reason,
    })

    wf         = _get_wf_row(db, workflow_id)
    repository = wf.repository if wf else ""
    pr_number  = wf.pr_number  if wf else 0

    if decision == "APPROVE" and repository and pr_number:
        findings  = [{"agent": f.agent, "title": f.title, "severity": f.severity,
                      "description": f.description} for f in f_repo.list_by_workflow(workflow_id)]
        qa        = qa_repo.get_by_workflow(workflow_id)
        reg       = await workflow_registry.get_workflow(workflow_id)
        threading.Thread(
            target=_run_merge_and_deploy,
            args=(workflow_id, repository, pr_number, findings,
                  qa.summary    if qa else "",
                  qa.risk_level if qa else "",
                  (reg or {}).get("rationale", ""),
                  (reg or {}).get("agent_decisions", {}),
                  True, payload.reason),
            daemon=True,
        ).start()
    else:
        _post_governance_comment(workflow_id, decision, payload.reason, db, is_release=True)

    return {"workflow_id": workflow_id, "status": "COMPLETED", "decision": decision,
            "reason": payload.reason,
            "auto_merge_queued": decision == "APPROVE" and _flag("AUTO_MERGE_ON_APPROVE")}


@router.post("/workflow/{workflow_id}/resume")
async def resume_workflow(workflow_id: str, db: Session = Depends(get_db)):
    WorkflowRepository(db).update_workflow_status(workflow_id, "RUNNING")
    threading.Thread(target=execute_workflow, args=(workflow_id,), daemon=True).start()
    return {"workflow_id": workflow_id, "status": "RUNNING"}


# ─── Governance comment helper ────────────────────────────────────────────────

def _post_governance_comment(
    workflow_id, decision, reason, db, is_release=False,
) -> None:
    try:
        wf = _get_wf_row(db, workflow_id)
        if not wf or not wf.repository:
            return
        body = build_governance_comment(
            workflow_id=workflow_id,
            decision=decision,
            actor="Release Manager" if is_release else "Human Reviewer",
            reason=reason or "",
            is_release=is_release,
        )
        post_pr_comment_sync(wf.repository, wf.pr_number, body)
    except Exception:
        logger.debug("governance_comment_failed workflow=%s", workflow_id)


# ─── Gitea runtime info ───────────────────────────────────────────────────────

@router.get("/gitea/info")
async def gitea_info():
    """
    Return the authenticated Gitea user and their repositories.
    Used by the frontend to populate the repo picker — avoids hardcoding owner names.
    Returns { user: "...", repos: ["owner/repo", ...], error: null }
    """
    import os
    gitea_url = os.getenv("GITEA_URL", "").rstrip("/")
    token     = os.getenv("GITEA_TOKEN", "")

    result = {"user": None, "repos": [], "error": None,
              "gitea_url": gitea_url or None}

    if not gitea_url or not token:
        result["error"] = "GITEA_URL or GITEA_TOKEN not configured"
        return result

    headers = {"Authorization": f"token {token}", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            # Get authenticated user
            ur = await client.get(f"{gitea_url}/api/v1/user", headers=headers)
            if ur.status_code != 200:
                result["error"] = f"Gitea /user returned {ur.status_code}: {ur.text[:200]}"
                return result
            user_data = ur.json()
            username  = user_data.get("login", "")
            result["user"] = username

            # Get repos accessible by this token (limit 50)
            rr = await client.get(
                f"{gitea_url}/api/v1/repos/search",
                headers=headers,
                params={"limit": 50, "sort": "newest"},
            )
            if rr.status_code == 200:
                repos = rr.json().get("data", [])
                result["repos"] = [r["full_name"] for r in repos]
            else:
                # Fallback: just list repos owned by the user
                or_ = await client.get(
                    f"{gitea_url}/api/v1/user/repos",
                    headers=headers,
                    params={"limit": 50},
                )
                if or_.status_code == 200:
                    result["repos"] = [r["full_name"] for r in or_.json()]

    except httpx.ConnectError:
        result["error"] = f"Cannot connect to Gitea at {gitea_url}"
    except Exception as exc:
        result["error"] = str(exc)

    return result

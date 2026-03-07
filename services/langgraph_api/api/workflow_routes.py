from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
import threading
import logging

from pydantic import BaseModel, Field

from ..db.database import get_db
from ..repositories.workflow_repository import WorkflowRepository
from ..repositories.findings_repository import FindingsRepository
from ..repositories.governance_repository import GovernanceRepository
from ..repositories.agent_log_repository import AgentLogRepository
from ..repositories.finding_challenges_repository import FindingChallengesRepository
from ..workflows.pr_review_workflow import execute_workflow
from ..core.workflow_registry import workflow_registry
import os
import httpx
import asyncio
import logging

logger = logging.getLogger("langgraph.api.workflow_routes")


# Request model for starting a workflow
class StartWorkflow(BaseModel):
    repo: str = Field(..., description="Repository full name, e.g. owner/repo")
    pr_number: int = Field(..., description="Pull request number")


router = APIRouter(prefix="", tags=["workflow"])


@router.post("/workflow/start")
async def start_workflow(payload: StartWorkflow, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):

    repo = WorkflowRepository(db)

    try:
        repository_name = payload.repo
        pr_number = payload.pr_number

        workflow = repo.create_workflow_run(
            repository=repository_name,
            pr_number=pr_number
        )

        # register in-memory state for quick inspection
        state = {
            "workflow_id": str(workflow.id),
            "repository": repository_name,
            "pr_number": pr_number,
            "status": workflow.status,
            "findings": [],
            "challenges": [],
            "current_agent": None,
        }

        await workflow_registry.register_workflow(state)

        # run orchestration asynchronously in a background thread
        thread = threading.Thread(target=execute_workflow, args=(str(workflow.id),))
        thread.daemon = True
        thread.start()

        logger.info("workflow_started", extra={"workflow_id": str(workflow.id), "repository": repository_name, "pr_number": pr_number})

        return {"workflow_id": str(workflow.id), "status": workflow.status}

    except Exception as exc:
        logger.exception("failed_to_start_workflow", exc_info=exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/workflows")
async def list_workflows():
    return await workflow_registry.list_workflows()



@router.get("/api/workflows")
def api_list_workflows(db: Session = Depends(get_db)):
    """Return workflows from the persistent database (for dashboard/inspection)."""
    repo = WorkflowRepository(db)

    rows = db.query(repo.db.get_bind().dialect.type_descriptor) if False else None
    # simple direct query using the ORM model
    from ..db.models import WorkflowRun

    q = db.query(WorkflowRun).all()

    return [
        {
            "workflow_id": str(r.id),
            "repository": r.repository,
            "pr_number": r.pr_number,
            "status": r.status,
            "current_agent": r.current_agent,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in q
    ]



@router.get("/api/workflow/{workflow_id}")
def api_get_workflow(workflow_id: str, db: Session = Depends(get_db)):
    from ..db.models import WorkflowRun

    row = db.query(WorkflowRun).filter(WorkflowRun.id == workflow_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="workflow not found")

    return {
        "workflow_id": str(row.id),
        "repository": row.repository,
        "pr_number": row.pr_number,
        "status": row.status,
        "current_agent": row.current_agent,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/workflow/{workflow_id}")
async def get_workflow(workflow_id: str):
    w = await workflow_registry.get_workflow(workflow_id)
    if not w:
        raise HTTPException(status_code=404, detail="workflow not found")
    return w


@router.post("/workflow/{workflow_id}/resume")
async def resume_workflow(workflow_id: str, db: Session = Depends(get_db)):
    # simple resume: set status back to RUNNING and restart execution
    repo = WorkflowRepository(db)
    repo.update_workflow_status(workflow_id, "RUNNING")

    thread = threading.Thread(target=execute_workflow, args=(workflow_id,))
    thread.daemon = True
    thread.start()

    logger.info("workflow_resumed", extra={"workflow_id": workflow_id})

    return {"workflow_id": workflow_id, "status": "RUNNING"}



@router.post("/workflow/{workflow_id}/approve")
async def approve_workflow(workflow_id: str, db: Session = Depends(get_db)):
    """Human approves the workflow: mark governance approved and complete the workflow.

    Also post a summary comment to the PR via Gitea (if env vars set).
    """
    repo = WorkflowRepository(db)
    gov_repo = GovernanceRepository(db)
    findings_repo = FindingsRepository(db)

    # mark governance approved
    action = gov_repo.create_decision(workflow_id, "APPROVE")
    action.approved = True
    db.commit()

    # finalize workflow
    repo.update_workflow_status(workflow_id, "COMPLETED")

    # best-effort: post a PR comment via Gitea
    GITEA_URL = os.getenv("GITEA_URL")
    GITEA_TOKEN = os.getenv("GITEA_TOKEN")

    try:
        if GITEA_URL and GITEA_TOKEN:
            # fetch workflow to include repo/pr_number
            wf = repo.db.query(repo.db.get_bind().dialect.type_descriptor)
            # simple approach: fetch workflow run directly
            from ..db.models import WorkflowRun
            wfrow = db.query(WorkflowRun).filter(WorkflowRun.id == workflow_id).first()

            if wfrow:
                # build summary
                findings = findings_repo.list_by_workflow(workflow_id)
                body = f"TuskerSquad governance decision: APPROVE\n\nFindings:\n"
                for f in findings:
                    body += f"- [{f.agent}] {f.title} ({f.severity})\n"

                owner_repo = wfrow.repository
                pr_number = wfrow.pr_number

                url = f"{GITEA_URL}/api/v1/repos/{owner_repo}/issues/{pr_number}/comments"
                headers = {"Authorization": f"token {GITEA_TOKEN}"}
                async with httpx.AsyncClient() as client:
                    await client.post(url, json={"body": body}, headers=headers, timeout=10.0)
    except Exception:
        logging.exception("failed_post_pr_comment_on_approve")

    # update registry
    try:
        await workflow_registry.update_workflow(workflow_id, {"workflow_id": workflow_id, "status": "COMPLETED"})
    except Exception:
        pass

    return {"workflow_id": workflow_id, "status": "COMPLETED"}


@router.post("/workflow/{workflow_id}/reject")
async def reject_workflow(workflow_id: str, db: Session = Depends(get_db)):
    repo = WorkflowRepository(db)
    gov_repo = GovernanceRepository(db)

    action = gov_repo.create_decision(workflow_id, "REJECT")
    action.approved = False
    db.commit()

    repo.update_workflow_status(workflow_id, "COMPLETED")

    try:
        await workflow_registry.update_workflow(workflow_id, {"workflow_id": workflow_id, "status": "COMPLETED"})
    except Exception:
        pass

    return {"workflow_id": workflow_id, "status": "COMPLETED"}


@router.get("/workflows/{workflow_id}/findings")
def get_findings(workflow_id: str, db: Session = Depends(get_db)):
    repo = FindingsRepository(db)
    rows = repo.list_by_workflow(workflow_id)

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
def get_governance(workflow_id: str, db: Session = Depends(get_db)):
    repo = GovernanceRepository(db)
    rows = repo.list_by_workflow(workflow_id)

    actions = [
        {
            "id": str(r.id),
            "decision": r.decision,
            "approved": bool(r.approved) if r.approved is not None else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]

    # attempt to include any in-memory LLM rationale stored in the workflow registry
    try:
        reg = asyncio.run(workflow_registry.get_workflow(workflow_id))
        rationale = None
        if reg and isinstance(reg, dict):
            rationale = reg.get('rationale')
        if rationale:
            return {"actions": actions, "rationale": rationale}
    except Exception:
        logger.exception("failed_to_fetch_registry_for_rationale")

    return actions


@router.get("/workflows/{workflow_id}/agents")
def get_agents(workflow_id: str, db: Session = Depends(get_db)):
    repo = AgentLogRepository(db)
    rows = repo.list_by_workflow(workflow_id)

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

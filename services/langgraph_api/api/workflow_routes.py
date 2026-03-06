from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import threading

from ..db.database import get_db
from ..repositories.workflow_repository import WorkflowRepository
from ..repositories.findings_repository import FindingsRepository
from ..repositories.governance_repository import GovernanceRepository
from ..repositories.agent_log_repository import AgentLogRepository
from ..repositories.finding_challenges_repository import FindingChallengesRepository
from ..workflows.pr_review_workflow import execute_workflow
from ..core.workflow_registry import workflow_registry

# No prefix here; main.py mounts this router at '/api'
router = APIRouter(prefix="", tags=["workflow"])


@router.post("/workflow/start")
async def start_workflow(payload: dict, db: Session = Depends(get_db)):

    repo = WorkflowRepository(db)

    try:
        repository_name = payload.get("repo") or payload.get("repository")
        pr_number = payload.get("pr_number")

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

        # run orchestration asynchronously
        thread = threading.Thread(target=execute_workflow, args=(workflow.id,))
        thread.daemon = True
        thread.start()

        return {"workflow_id": str(workflow.id), "status": workflow.status}

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/workflows")
async def list_workflows():
    return await workflow_registry.list_workflows()


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

    return {"workflow_id": workflow_id, "status": "RUNNING"}


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

    return [
        {
            "id": str(r.id),
            "decision": r.decision,
            "approved": r.approved,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


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

import uuid
import asyncio
import traceback
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from services.langgraph_api.state.workflow_state import WorkflowStatus
from services.langgraph_api.core.workflow_registry import workflow_registry
from services.langgraph_api.workflows.pr_review_workflow import build_workflow


router = APIRouter()


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

    try:

        workflow = build_workflow()

        state = await workflow_registry.get_workflow(workflow_id)

        if not state:
            return

        result = await workflow.ainvoke(state)

        await workflow_registry.update_workflow(
            workflow_id,
            result
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
                    "message": f"Workflow failed: {str(e)}"
                }
            )

            await workflow_registry.update_workflow(workflow_id, state)


# ---------------------------------------------------------
# Start Workflow
# ---------------------------------------------------------

@router.post("/workflow/start", response_model=WorkflowStartResponse)
async def start_workflow(request: WorkflowStartRequest):

    workflow_id = f"wf_{uuid.uuid4().hex[:8]}"

    state = {
        "workflow_id": workflow_id,
        "repo": request.repo,
        "pr_number": request.pr_number,
        "status": WorkflowStatus.RUNNING,
        "current_agent": None,
        "findings": [],
        "logs": [],
    }

    await workflow_registry.register_workflow(state)

    loop = asyncio.get_running_loop()
    loop.create_task(run_workflow(workflow_id))

    return WorkflowStartResponse(
        workflow_id=workflow_id,
        status="RUNNING"
    )


@router.get("/workflows")
async def list_workflows():

    workflows = await workflow_registry.list_workflows()

    return {"workflows": workflows}


# ---------------------------------------------------------
# Get Workflow State
# ---------------------------------------------------------

@router.get("/workflow/{workflow_id}")
async def get_workflow(workflow_id: str):

    workflow = await workflow_registry.get_workflow(workflow_id)

    if not workflow:
        return {"error": "workflow not found"}

    return workflow


# ---------------------------------------------------------
# Resume Workflow
# ---------------------------------------------------------

@router.post("/workflow/{workflow_id}/resume")
async def resume_workflow(workflow_id: str):

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
            "message": "Workflow resumed by human approval"
        }
    )

    await workflow_registry.update_workflow(workflow_id, workflow)

    return {
        "workflow_id": workflow_id,
        "status": "COMPLETED"
    }

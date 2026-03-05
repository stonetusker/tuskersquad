from fastapi import FastAPI
import uuid

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/workflow/start")
def start_workflow(payload: dict):

    workflow_id = str(uuid.uuid4())

    return {
        "workflow_id": workflow_id,
        "status": "started"
    }

@app.post("/workflow/{workflow_id}/resume")
def resume_workflow(workflow_id: str):

    return {
        "workflow_id": workflow_id,
        "status": "resumed"
    }

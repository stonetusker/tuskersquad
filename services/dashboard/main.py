from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
import httpx
import asyncio

app = FastAPI(title="TuskerSquad Dashboard API")


@app.get("/health")
def health():
    return {"status": "ok"}

# Allow dev frontend to call dashboard APIs
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LANGGRAPH_URL = os.getenv("LANGGRAPH_URL", "http://langgraph-api:8000")

logger = logging.getLogger("dashboard")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@app.get("/api/ui/workflows")
async def list_workflows():
    """Return a merged list of workflows.

    We prefer the persistent DB listing (`/api/workflows`) but also
    include in-memory running workflows from `/api/workflows` so the UI can
    show workflows that are active but not yet fully persisted/updated.
    """
    results = {}

    async def fetch_json_with_retries(client, url, attempts=3, delay=1.0):
        last_exc = None
        for attempt in range(1, attempts + 1):
            try:
                r = await client.get(url, timeout=10.0)
                r.raise_for_status()
                return r.json() or []
            except Exception as exc:
                last_exc = exc
                logger.warning("fetch_attempt_failed", extra={"url": url, "attempt": attempt, "error": str(exc)})
                if attempt < attempts:
                    await asyncio.sleep(delay)
        logger.exception("failed_fetch_after_retries", extra={"url": url, "error": str(last_exc)})
        return []

    async with httpx.AsyncClient() as client:
        db_list = await fetch_json_with_retries(client, f"{LANGGRAPH_URL}/api/workflows")

        for w in db_list:
            results[str(w.get("workflow_id"))] = w

        mem_list = await fetch_json_with_retries(client, f"{LANGGRAPH_URL}/api/workflows/live")

        for m in mem_list:
            wid = str(m.get("workflow_id"))
            # prefer registry status/current_agent for in-progress workflows
            if wid in results:
                results[wid]["status"] = m.get("status", results[wid].get("status"))
                results[wid]["current_agent"] = m.get("current_agent", results[wid].get("current_agent"))
            else:
                results[wid] = {
                    "workflow_id": wid,
                    "repository": m.get("repository"),
                    "pr_number": m.get("pr_number"),
                    "status": m.get("status"),
                    "current_agent": m.get("current_agent"),
                    "created_at": m.get("created_at"),
                    "updated_at": m.get("updated_at"),
                }

    # return merged list
    return list(results.values())


@app.get("/api/ui/workflow/{workflow_id}")
async def get_workflow(workflow_id: str):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{LANGGRAPH_URL}/api/workflow/{workflow_id}", timeout=10.0)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.exception("failed_get_workflow")
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/ui/workflow/{workflow_id}/agents")
async def get_agents(workflow_id: str):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{LANGGRAPH_URL}/api/workflows/{workflow_id}/agents", timeout=10.0)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.exception("failed_get_agents")
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/ui/workflow/{workflow_id}/findings")
async def get_findings(workflow_id: str):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{LANGGRAPH_URL}/api/workflows/{workflow_id}/findings", timeout=10.0)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.exception("failed_get_findings")
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/ui/workflow/{workflow_id}/governance")
async def get_governance(workflow_id: str):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{LANGGRAPH_URL}/api/workflows/{workflow_id}/governance", timeout=10.0)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.exception("failed_get_governance")
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/ui/workflow/{workflow_id}/approve")
async def approve_workflow(workflow_id: str):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{LANGGRAPH_URL}/api/workflow/{workflow_id}/approve", timeout=10.0)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.exception("failed_approve_workflow")
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/ui/workflow/{workflow_id}/reject")
async def reject_workflow(workflow_id: str):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{LANGGRAPH_URL}/api/workflow/{workflow_id}/reject", timeout=10.0)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.exception("failed_reject_workflow")
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/ui/workflow/{workflow_id}/qa")
async def get_qa_summary(workflow_id: str):
    """Proxy the QA Lead summary for a workflow."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{LANGGRAPH_URL}/api/workflows/{workflow_id}/qa", timeout=10.0)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.exception("failed_get_qa_summary")
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/ui/workflow/{workflow_id}/retest")
async def retest_workflow(workflow_id: str):
    """Proxy the retest (re-run) request to LangGraph."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{LANGGRAPH_URL}/api/workflow/{workflow_id}/retest", timeout=10.0
            )
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.exception("failed_retest_workflow")
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/ui/workflow/{workflow_id}/release")
async def release_manager_override(workflow_id: str, request: Request):
    """Proxy a Release Manager override decision."""
    try:
        payload = await request.json()
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{LANGGRAPH_URL}/api/workflow/{workflow_id}/release",
                json=payload,
                timeout=10.0,
            )
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.exception("failed_release_override")
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/ui/workflow/{workflow_id}/merge-status")
async def get_merge_status(workflow_id: str):
    """Proxy the merge/deploy status for live UI polling."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{LANGGRAPH_URL}/api/workflow/{workflow_id}/merge-status",
                timeout=10.0,
            )
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.exception("failed_get_merge_status")
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/ui/workflow/{workflow_id}/merge-status")
async def get_merge_status(workflow_id: str):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{LANGGRAPH_URL}/api/workflow/{workflow_id}/merge-status", timeout=10.0)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/ui/workflows/heatmap")
async def get_heatmap():
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{LANGGRAPH_URL}/api/workflows/heatmap", timeout=10.0)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/ui/workflows/{workflow_id}/reasoning")
async def get_reasoning(workflow_id: str):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{LANGGRAPH_URL}/api/workflows/{workflow_id}/reasoning", timeout=10.0)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

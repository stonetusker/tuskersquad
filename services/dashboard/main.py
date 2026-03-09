"""TuskerSquad Dashboard BFF — proxies all LangGraph API calls for the React frontend."""
import asyncio
import logging
import os

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="TuskerSquad Dashboard API")

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


@app.get("/health")
def health():
    return {"status": "ok", "service": "dashboard-bff"}


async def _fetch(client, url, attempts=3, delay=1.0):
    for attempt in range(1, attempts + 1):
        try:
            r = await client.get(url, timeout=12.0)
            r.raise_for_status()
            return r.json() or []
        except Exception as exc:
            if attempt == attempts:
                logger.warning("fetch_failed url=%s err=%s", url, exc)
                return []
            await asyncio.sleep(delay)


async def _post(client, url, body=None, attempts=3):
    for attempt in range(1, attempts + 1):
        try:
            r = await client.post(url, json=body or {}, timeout=12.0)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            if attempt == attempts:
                raise HTTPException(status_code=502, detail=str(exc))
            await asyncio.sleep(1.0)


# ─── Workflows ────────────────────────────────────────────────────────────────

@app.get("/api/ui/workflows")
async def list_workflows():
    results = {}
    async with httpx.AsyncClient() as client:
        db_list  = await _fetch(client, f"{LANGGRAPH_URL}/api/workflows")
        for w in db_list:
            results[str(w.get("workflow_id"))] = w

        mem_list = await _fetch(client, f"{LANGGRAPH_URL}/api/workflows/live")
        for m in mem_list:
            wid = str(m.get("workflow_id"))
            if wid in results:
                results[wid]["status"]        = m.get("status", results[wid].get("status"))
                results[wid]["current_agent"] = m.get("current_agent", results[wid].get("current_agent"))
            else:
                results[wid] = m
    return list(results.values())


@app.get("/api/ui/workflow/{workflow_id}")
async def get_workflow(workflow_id: str):
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{LANGGRAPH_URL}/api/workflow/{workflow_id}", timeout=12.0)
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail="not found")
        r.raise_for_status()
        return r.json()


# ─── Sub-resource proxies (all GET) ──────────────────────────────────────────

def _sub_route(path_suffix: str):
    """Generate a proxy GET endpoint for /api/ui/workflow/{id}/<suffix>."""
    async def _handler(workflow_id: str):
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{LANGGRAPH_URL}/api/workflows/{workflow_id}/{path_suffix}", timeout=12.0
            )
            if r.status_code == 404:
                raise HTTPException(status_code=404, detail=f"{path_suffix} not found")
            r.raise_for_status()
            return r.json()
    return _handler

app.get("/api/ui/workflow/{workflow_id}/agents")       (_sub_route("agents"))
app.get("/api/ui/workflow/{workflow_id}/findings")     (_sub_route("findings"))
app.get("/api/ui/workflow/{workflow_id}/governance")   (_sub_route("governance"))
app.get("/api/ui/workflow/{workflow_id}/qa")           (_sub_route("qa"))
app.get("/api/ui/workflow/{workflow_id}/reasoning")    (_sub_route("reasoning"))
app.get("/api/ui/workflow/{workflow_id}/llm-logs")     (_sub_route("llm-logs"))
app.get("/api/ui/workflow/{workflow_id}/agent-decisions") (_sub_route("agent-decisions"))


@app.get("/api/ui/workflow/{workflow_id}/merge-status")
async def get_merge_status(workflow_id: str):
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{LANGGRAPH_URL}/api/workflow/{workflow_id}/merge-status", timeout=8.0)
        r.raise_for_status()
        return r.json()


# ─── Governance actions (POST) ────────────────────────────────────────────────

@app.post("/api/ui/workflow/{workflow_id}/approve")
async def approve(workflow_id: str):
    async with httpx.AsyncClient() as c:
        return await _post(c, f"{LANGGRAPH_URL}/api/workflow/{workflow_id}/approve")


@app.post("/api/ui/workflow/{workflow_id}/reject")
async def reject(workflow_id: str):
    async with httpx.AsyncClient() as c:
        return await _post(c, f"{LANGGRAPH_URL}/api/workflow/{workflow_id}/reject")


@app.post("/api/ui/workflow/{workflow_id}/retest")
async def retest(workflow_id: str):
    async with httpx.AsyncClient() as c:
        return await _post(c, f"{LANGGRAPH_URL}/api/workflow/{workflow_id}/retest")


@app.post("/api/ui/workflow/{workflow_id}/release")
async def release(workflow_id: str, request: Request):
    body = await request.json()
    async with httpx.AsyncClient() as c:
        return await _post(c, f"{LANGGRAPH_URL}/api/workflow/{workflow_id}/release", body)


# ─── Heatmap ─────────────────────────────────────────────────────────────────

@app.get("/api/ui/heatmap")
async def heatmap():
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{LANGGRAPH_URL}/api/workflows/heatmap", timeout=12.0)
        r.raise_for_status()
        return r.json()

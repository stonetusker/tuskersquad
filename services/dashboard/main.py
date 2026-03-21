"""
TuskerSquad Dashboard BFF
=========================
Proxies all LangGraph API calls for the React frontend.
Each route is an explicitly named function to avoid FastAPI duplicate-name warnings.
"""
import asyncio
import logging
import os

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="TuskerSquad Dashboard BFF", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LANGGRAPH_URL = os.getenv("LANGGRAPH_URL", "http://tuskersquad-langgraph:8000")

logger = logging.getLogger("dashboard")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get(url: str, retries: int = 3) -> list | dict:
    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                r = await client.get(url)
                r.raise_for_status()
                return r.json()
        except Exception as exc:
            if attempt == retries:
                logger.warning("_get_failed url=%s err=%s", url, exc)
                return []
            await asyncio.sleep(0.5)
    return []


async def _post_proxy(url: str, body: dict | None = None) -> dict:
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(url, json=body or {})
                r.raise_for_status()
                return r.json()
        except Exception as exc:
            if attempt == 3:
                raise HTTPException(status_code=502, detail=str(exc))
            await asyncio.sleep(1.0)
    return {}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "dashboard-bff"}


@app.get("/api/ui/ollama-status")
async def ollama_status():
    """
    Probe Ollama and return availability + loaded models.
    The frontend polls this every 15 s to show/hide the LLM warning banner.
    Response: { available, models, url, error }
    """
    ollama_url = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(f"{ollama_url}/api/tags")
            r.raise_for_status()
            data = r.json()
            model_names = [m.get("name", "") for m in data.get("models", [])]
            return {
                "available": True,
                "models": model_names,
                "url": ollama_url,
                "error": None,
            }
    except Exception as exc:
        return {
            "available": False,
            "models": [],
            "url": ollama_url,
            "error": str(exc)[:200],
        }


# ── Workflow list ─────────────────────────────────────────────────────────────

@app.get("/api/ui/workflows")
async def list_workflows():
    results = {}
    db_list  = await _get(f"{LANGGRAPH_URL}/api/workflows")
    mem_list = await _get(f"{LANGGRAPH_URL}/api/workflows/live")

    for w in (db_list if isinstance(db_list, list) else []):
        results[str(w.get("workflow_id"))] = w

    for m in (mem_list if isinstance(mem_list, list) else []):
        wid = str(m.get("workflow_id"))
        if wid in results:
            results[wid]["status"]        = m.get("status", results[wid].get("status"))
            results[wid]["current_agent"] = m.get("current_agent", results[wid].get("current_agent"))
        else:
            results[wid] = m

    return list(results.values())


# ── Workflow detail ───────────────────────────────────────────────────────────

@app.get("/api/ui/workflow/{workflow_id}")
async def get_workflow(workflow_id: str):
    async with httpx.AsyncClient(timeout=12.0) as client:
        r = await client.get(f"{LANGGRAPH_URL}/api/workflow/{workflow_id}")
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail="workflow not found")
        r.raise_for_status()
        return r.json()


# ── Sub-resource GET proxies (each has a unique function name) ────────────────

@app.get("/api/ui/workflow/{workflow_id}/agents")
async def get_agents(workflow_id: str):
    return await _get(f"{LANGGRAPH_URL}/api/workflows/{workflow_id}/agents")

@app.get("/api/ui/workflow/{workflow_id}/findings")
async def get_findings(workflow_id: str):
    return await _get(f"{LANGGRAPH_URL}/api/workflows/{workflow_id}/findings")

@app.get("/api/ui/workflow/{workflow_id}/governance")
async def get_governance(workflow_id: str):
    return await _get(f"{LANGGRAPH_URL}/api/workflows/{workflow_id}/governance")

@app.get("/api/ui/workflow/{workflow_id}/qa")
async def get_qa(workflow_id: str):
    async with httpx.AsyncClient(timeout=12.0) as client:
        r = await client.get(f"{LANGGRAPH_URL}/api/workflows/{workflow_id}/qa")
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail="qa not found")
        r.raise_for_status()
        return r.json()

@app.get("/api/ui/workflow/{workflow_id}/reasoning")
async def get_reasoning(workflow_id: str):
    return await _get(f"{LANGGRAPH_URL}/api/workflows/{workflow_id}/reasoning")

@app.get("/api/ui/workflow/{workflow_id}/llm-logs")
async def get_llm_logs(workflow_id: str):
    return await _get(f"{LANGGRAPH_URL}/api/workflows/{workflow_id}/llm-logs")

@app.get("/api/ui/workflow/{workflow_id}/diff")
async def get_diff(workflow_id: str):
    """Proxy: diff context and git provider info fetched by the planner agent."""
    return await _get(f"{LANGGRAPH_URL}/api/workflows/{workflow_id}/diff")


@app.get("/api/ui/workflow/{workflow_id}/agent-decisions")
async def get_agent_decisions(workflow_id: str):
    return await _get(f"{LANGGRAPH_URL}/api/workflows/{workflow_id}/agent-decisions")

@app.get("/api/ui/workflow/{workflow_id}/merge-status")
async def get_merge_status(workflow_id: str):
    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(f"{LANGGRAPH_URL}/api/workflow/{workflow_id}/merge-status")
        r.raise_for_status()
        return r.json()


# ── Governance POST actions ───────────────────────────────────────────────────


@app.get("/api/ui/gitea/info")
async def gitea_info():
    """Proxy to langgraph /api/gitea/info — returns Gitea user + repo list."""
    return await _get(f"{LANGGRAPH_URL}/api/gitea/info")

@app.post("/api/ui/workflow/{workflow_id}/approve")
async def approve_workflow(workflow_id: str):
    return await _post_proxy(f"{LANGGRAPH_URL}/api/workflow/{workflow_id}/approve")

@app.post("/api/ui/workflow/{workflow_id}/reject")
async def reject_workflow(workflow_id: str):
    return await _post_proxy(f"{LANGGRAPH_URL}/api/workflow/{workflow_id}/reject")

@app.post("/api/ui/workflow/{workflow_id}/retest")
async def retest_workflow(workflow_id: str):
    return await _post_proxy(f"{LANGGRAPH_URL}/api/workflow/{workflow_id}/retest")

@app.post("/api/ui/workflow/{workflow_id}/release")
async def release_override(workflow_id: str, request: Request):
    body = await request.json()
    return await _post_proxy(f"{LANGGRAPH_URL}/api/workflow/{workflow_id}/release", body)


# ── Heatmap ───────────────────────────────────────────────────────────────────

@app.get("/api/ui/heatmap")
async def get_heatmap():
    return await _get(f"{LANGGRAPH_URL}/api/workflows/heatmap")

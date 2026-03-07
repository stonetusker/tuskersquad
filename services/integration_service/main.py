from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
import asyncio
from typing import Optional

import httpx

app = FastAPI()

# Allow dev frontend to call the integration service
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LANGGRAPH_URL = os.getenv("LANGGRAPH_URL", "http://langgraph-api:8000")
GITEA_URL = os.getenv("GITEA_URL", "http://tuskersquad-gitea:3000")
GITEA_TOKEN = os.getenv("GITEA_TOKEN")

logger = logging.getLogger("integration_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {
        "service": "integration_service",
        "status": "ok",
        "endpoints": ["/health", "/gitea/webhook", "/webhook/simulate"],
        "info": "POST /webhook/simulate to trigger a workflow; POST /gitea/webhook for real Gitea webhooks",
    }


async def post_with_retries(url: str, json: dict, retries: int = 3, delay: float = 1.0):
    async with httpx.AsyncClient() as client:
        for attempt in range(1, retries + 1):
            try:
                resp = await client.post(url, json=json, timeout=10.0)
                resp.raise_for_status()
                return resp
            except Exception as exc:
                logger.warning("POST failed", extra={"url": url, "attempt": attempt, "error": str(exc)})
                if attempt == retries:
                    raise
                await asyncio.sleep(delay)


async def post_pr_comment(repo: str, pr_number: int, body: str) -> Optional[dict]:
    """Post a comment to a Gitea PR. Requires GITEA_TOKEN and GITEA_URL env vars.

    Returns parsed JSON response on success, otherwise None.
    """
    if not GITEA_TOKEN:
        logger.info("GITEA_TOKEN not set; skipping PR comment")
        return None

    # Gitea API: POST /api/v1/repos/{owner}/{repo}/issues/{index}/comments
    try:
        owner_repo = repo
        # if payload uses full repo path like "owner/repo" keep it
        if "/" in repo:
            owner_repo = repo
        url = f"{GITEA_URL}/api/v1/repos/{owner_repo}/issues/{pr_number}/comments"

        headers = {"Authorization": f"token {GITEA_TOKEN}"}

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={"body": body}, headers=headers, timeout=10.0)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.exception("Failed to post PR comment", exc_info=exc)
        return None


@app.post("/gitea/webhook")
async def gitea_webhook(request: Request):
    payload = await request.json()

    logger.info("Webhook received from Gitea", extra={"payload": payload})

    repository = payload.get("repository", {}).get("full_name") or payload.get("repository", {}).get("name")
    pr_number = payload.get("pull_request", {}).get("number") or payload.get("pr_number") or 1

    if not repository:
        raise HTTPException(status_code=400, detail="missing repository in payload")

    try:
        # trigger workflow in LangGraph service
        body = {"repo": repository, "pr_number": pr_number}
        await post_with_retries(f"{LANGGRAPH_URL}/api/workflow/start", json=body)
    except Exception as exc:
        logger.exception("Failed to trigger LangGraph workflow", exc_info=exc)
        raise HTTPException(status_code=502, detail=str(exc))

    # optional: post a comment that workflow was started (best-effort)
    try:
        comment = f"TuskerSquad: workflow triggered for {repository} PR #{pr_number}"
        await post_pr_comment(repository, pr_number, comment)
    except Exception:
        # do not fail the webhook if posting comment fails
        logger.exception("Failed to post PR comment (non-fatal)")

    return {"status": "workflow triggered"}


@app.post("/webhook/simulate")
async def simulate_webhook(request: Request):
    payload = await request.json()
    repository = payload.get("repo") or payload.get("repository")
    pr_number = payload.get("pr_number") or payload.get("pr") or 1
    if not repository:
        raise HTTPException(status_code=400, detail="missing repo field")

    try:
        body = {"repo": repository, "pr_number": pr_number}
        await post_with_retries(f"{LANGGRAPH_URL}/api/workflow/start", json=body)
    except Exception as exc:
        logger.exception("Failed to trigger LangGraph workflow (simulate)", exc_info=exc)
        raise HTTPException(status_code=502, detail=str(exc))

    return {"workflow_id": f"sim-{int(asyncio.get_event_loop().time()*1000)}", "status": "RUNNING"}

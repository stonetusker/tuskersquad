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


# ---------------------------------------------------------------------------
# Git status update
# ---------------------------------------------------------------------------

@app.post("/git/status")
async def update_git_status(request: Request):
    """
    Update the commit status on a Gitea PR.
    Payload: { "repo": "owner/repo", "pr_number": N, "state": "pending|success|failure", "description": "..." }
    """
    payload = await request.json()
    repo = payload.get("repo")
    state = payload.get("state", "pending")
    description = payload.get("description", "TuskerSquad review in progress")

    if not repo:
        raise HTTPException(status_code=400, detail="missing repo field")

    result = {
        "status": "recorded",
        "repo": repo,
        "state": state,
        "description": description,
    }

    if GITEA_TOKEN:
        try:
            # Gitea commit status API
            sha = payload.get("sha")
            if sha:
                url = f"{GITEA_URL}/api/v1/repos/{repo}/statuses/{sha}"
                headers = {"Authorization": f"token {GITEA_TOKEN}"}
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        url,
                        json={"state": state, "description": description, "context": "tuskersquad"},
                        headers=headers,
                        timeout=10.0,
                    )
                    result["gitea_response"] = resp.status_code
        except Exception as exc:
            logger.exception("git_status_post_failed")
            result["error"] = str(exc)

    logger.info("git_status_updated", extra=result)
    return result


# ---------------------------------------------------------------------------
# Jira integration (stub — logs action, returns simulated response)
# ---------------------------------------------------------------------------

JIRA_URL = os.getenv("JIRA_URL", "")
JIRA_TOKEN = os.getenv("JIRA_TOKEN", "")
JIRA_PROJECT = os.getenv("JIRA_PROJECT", "TUSKER")


@app.post("/jira/create")
async def create_jira_issue(request: Request):
    """
    Create a Jira issue for a finding.
    Payload: { "summary": "...", "description": "...", "priority": "Medium", "workflow_id": "..." }

    When JIRA_URL and JIRA_TOKEN are set, posts to the real Jira REST API.
    Otherwise returns a simulated response for demo purposes.
    """
    payload = await request.json()
    summary = payload.get("summary", "TuskerSquad finding")
    description = payload.get("description", "")
    priority = payload.get("priority", "Medium")
    workflow_id = payload.get("workflow_id", "unknown")

    logger.info(
        "jira_create_issue",
        extra={"summary": summary, "priority": priority, "workflow_id": workflow_id},
    )

    if JIRA_URL and JIRA_TOKEN:
        try:
            issue_payload = {
                "fields": {
                    "project": {"key": JIRA_PROJECT},
                    "summary": summary,
                    "description": description,
                    "issuetype": {"name": "Bug"},
                    "priority": {"name": priority},
                }
            }
            headers = {
                "Authorization": f"Bearer {JIRA_TOKEN}",
                "Content-Type": "application/json",
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{JIRA_URL}/rest/api/3/issue",
                    json=issue_payload,
                    headers=headers,
                    timeout=10.0,
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "status": "created",
                    "issue_key": data.get("key"),
                    "issue_url": f"{JIRA_URL}/browse/{data.get('key')}",
                    "workflow_id": workflow_id,
                }
        except Exception as exc:
            logger.exception("jira_api_failed")
            # Fall through to simulated response

    # Simulated response when Jira is not configured
    simulated_key = f"{JIRA_PROJECT}-{abs(hash(summary)) % 9000 + 1000}"
    return {
        "status": "simulated",
        "issue_key": simulated_key,
        "issue_url": f"https://jira.example.com/browse/{simulated_key}",
        "workflow_id": workflow_id,
        "note": "Set JIRA_URL and JIRA_TOKEN environment variables to connect to a real Jira instance.",
    }


# ---------------------------------------------------------------------------
# Slack notification (stub — logs action, returns simulated response)
# ---------------------------------------------------------------------------

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")


@app.post("/slack/notify")
async def slack_notify(request: Request):
    """
    Send a Slack notification about a workflow event.
    Payload: { "message": "...", "workflow_id": "...", "level": "info|warning|critical" }

    When SLACK_WEBHOOK_URL is set, posts to the real Slack incoming webhook.
    Otherwise returns a simulated response for demo purposes.
    """
    payload = await request.json()
    message = payload.get("message", "TuskerSquad notification")
    workflow_id = payload.get("workflow_id", "unknown")
    level = payload.get("level", "info")

    level_emoji = {"info": ":information_source:", "warning": ":warning:", "critical": ":red_circle:"}.get(level, ":white_circle:")

    logger.info(
        "slack_notify",
        extra={"message": message, "level": level, "workflow_id": workflow_id},
    )

    if SLACK_WEBHOOK_URL:
        try:
            slack_payload = {
                "text": f"{level_emoji} *TuskerSquad* | Workflow `{workflow_id}`\n{message}"
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    SLACK_WEBHOOK_URL, json=slack_payload, timeout=10.0
                )
                resp.raise_for_status()
                return {"status": "sent", "workflow_id": workflow_id}
        except Exception as exc:
            logger.exception("slack_webhook_failed")

    # Simulated response
    return {
        "status": "simulated",
        "message": message,
        "workflow_id": workflow_id,
        "note": "Set SLACK_WEBHOOK_URL environment variable to send real Slack notifications.",
    }

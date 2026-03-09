"""
TuskerSquad Integration Service
================================
Receives Gitea PR webhooks and triggers the LangGraph review pipeline.

Gitea webhook setup (shopflow repo → Settings → Webhooks → Add Webhook):
  Type        : Gitea
  Target URL  : http://tuskersquad-integration:8001/gitea/webhook
                ↑ Use the container name — NOT localhost. Gitea runs inside
                  Docker so localhost resolves to the Gitea container itself.
  Content-Type: application/json
  Events      : check "Pull Requests" only
  Secret      : (optional) if set in Gitea, also set GITEA_WEBHOOK_SECRET
                in infra/.env to the same value
"""

import asyncio
import hashlib
import hmac
import logging
import os
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("integration_service")

app = FastAPI(title="TuskerSquad Integration Service", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LANGGRAPH_URL        = os.getenv("LANGGRAPH_URL",        "http://tuskersquad-langgraph:8000")
GITEA_URL            = os.getenv("GITEA_URL",            "http://tuskersquad-gitea:3000")
GITEA_TOKEN          = os.getenv("GITEA_TOKEN",          "")
GITEA_WEBHOOK_SECRET = os.getenv("GITEA_WEBHOOK_SECRET", "")

# Only these Gitea PR actions start a new review
TRIGGER_ACTIONS = {"opened", "synchronize", "reopened"}


# ── HMAC signature validation ─────────────────────────────────────────────────

def _verify_signature(raw_body: bytes, sig_header: str) -> bool:
    """
    Verify Gitea's HMAC-SHA256 signature (X-Gitea-Signature header).
    Only enforced when GITEA_WEBHOOK_SECRET is set in the environment.
    If no secret is configured, all requests are accepted.
    """
    if not GITEA_WEBHOOK_SECRET:
        return True  # secret not configured → allow all
    if not sig_header:
        logger.warning("webhook_sig_missing: secret is configured but header absent")
        return False
    expected = hmac.new(
        GITEA_WEBHOOK_SECRET.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, sig_header.strip().lower())


# ── HTTP helpers ──────────────────────────────────────────────────────────────

async def _post_with_retries(url: str, body: dict, retries: int = 3) -> dict:
    last_exc: Optional[Exception] = None
    async with httpx.AsyncClient(timeout=12.0) as client:
        for attempt in range(1, retries + 1):
            try:
                r = await client.post(url, json=body)
                r.raise_for_status()
                return r.json()
            except Exception as exc:
                last_exc = exc
                logger.warning("http_retry url=%s attempt=%d err=%s", url, attempt, exc)
                if attempt < retries:
                    await asyncio.sleep(1.5)
    raise last_exc  # type: ignore[misc]


async def _post_pr_comment(repo: str, pr_number: int, body: str) -> bool:
    """Post a comment to a Gitea PR. Silent on failure — best-effort only."""
    if not GITEA_TOKEN:
        logger.info("pr_comment_skip: GITEA_TOKEN not set in infra/.env")
        return False
    url = f"{GITEA_URL}/api/v1/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"token {GITEA_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json={"body": body}, headers=headers)
        if r.status_code in (200, 201):
            logger.info("pr_comment_posted repo=%s pr=%s", repo, pr_number)
            return True
        logger.warning(
            "pr_comment_failed repo=%s pr=%s http=%s resp=%s",
            repo, pr_number, r.status_code, r.text[:200],
        )
        return False
    except Exception:
        logger.exception("pr_comment_exception repo=%s pr=%s", repo, pr_number)
        return False


def _parse_gitea_pr_payload(payload: dict) -> tuple:
    """
    Pull (repository, pr_number, action) from a Gitea pull_request webhook.

    Gitea payload shape:
    {
      "action":  "opened" | "synchronize" | "closed" | "reopened" | ...,
      "number":  42,                      ← top-level PR number
      "pull_request": { "number": 42 },   ← also here
      "repository": {
        "full_name": "owner/repo",         ← preferred
        "name": "repo"                     ← fallback
      }
    }
    """
    action   = payload.get("action", "")
    repo_obj = payload.get("repository") or {}
    repo     = repo_obj.get("full_name") or repo_obj.get("name")
    pr_obj   = payload.get("pull_request") or {}
    pr_num   = payload.get("number") or pr_obj.get("number") or payload.get("pr_number")
    try:
        pr_num = int(pr_num) if pr_num is not None else None
    except (TypeError, ValueError):
        pr_num = None
    return repo, pr_num, action


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "integration-service"}


@app.get("/")
def root():
    return {
        "service": "tuskersquad-integration",
        "webhook_url": "http://tuskersquad-integration:8001/gitea/webhook",
        "note": (
            "Use the container name (tuskersquad-integration) in Gitea's webhook URL, "
            "NOT localhost. Gitea runs inside Docker so localhost resolves to itself."
        ),
    }


@app.post("/gitea/webhook")
async def gitea_webhook(request: Request):
    """
    Receive a Gitea pull_request webhook and start a TuskerSquad review.

    Gitea sends X-Gitea-Event: pull_request for PR events.
    Only action=opened|synchronize|reopened triggers a new review.
    """
    # 1. Read raw body for HMAC (must happen before .json())
    raw_body = await request.body()

    # 2. Validate signature if secret is configured
    sig = request.headers.get("X-Gitea-Signature", "")
    if not _verify_signature(raw_body, sig):
        logger.warning("webhook_rejected: invalid HMAC signature")
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    # 3. Decode JSON
    try:
        import json as _json
        payload = _json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    # 4. Event type guard — only pull_request events contain PR data
    event = request.headers.get("X-Gitea-Event", "")
    logger.info("webhook_received event='%s'", event)

    if event and event != "pull_request":
        logger.info("webhook_skip: event='%s' is not pull_request", event)
        return {"status": "ignored", "reason": f"event '{event}' does not trigger review"}

    # 5. Parse PR fields
    repository, pr_number, action = _parse_gitea_pr_payload(payload)

    logger.info(
        "webhook_pr_parsed: action='%s' repo='%s' pr=%s",
        action, repository, pr_number,
    )

    # 6. Action guard — only start reviews on open/push
    if action and action not in TRIGGER_ACTIONS:
        logger.info("webhook_skip: action='%s' not in %s", action, TRIGGER_ACTIONS)
        return {"status": "ignored", "reason": f"action '{action}' does not trigger review"}

    # 7. Validate required fields
    if not repository:
        logger.error("webhook_error: missing repository. payload=%s", str(payload)[:400])
        raise HTTPException(status_code=400, detail="missing repository in payload")
    if pr_number is None:
        logger.error("webhook_error: missing pr_number. payload=%s", str(payload)[:400])
        raise HTTPException(status_code=400, detail="missing pr_number in payload")

    # 8. Post immediate "in-review" comment (fire-and-forget, don't block response)
    asyncio.create_task(_post_pr_comment(
        repository, pr_number,
        "## 🔍 TuskerSquad Review Started\n\n"
        f"> **{repository}** · PR #{pr_number} · `{action}`\n\n"
        "The 8-agent AI pipeline is now running. "
        "Each agent will post its findings as a comment when it completes.\n\n"
        "| Agent | Role |\n|-------|------|\n"
        "| 🧭 Planner | Scope & strategy |\n"
        "| ⚙️ Backend | API & pytest |\n"
        "| 🎨 Frontend | UI / Playwright |\n"
        "| 🔐 Security | OWASP probes |\n"
        "| 📡 SRE | Latency & load |\n"
        "| ⚔️ Challenger | False-positive audit |\n"
        "| 📋 QA Lead | Risk synthesis |\n"
        "| ⚖️ Judge | Final decision |\n\n"
        "*Powered by TuskerSquad · Stonetusker Systems*"
    ))

    # 9. Trigger the review workflow
    try:
        result = await _post_with_retries(
            f"{LANGGRAPH_URL}/api/workflow/start",
            body={"repo": repository, "pr_number": pr_number},
        )
        workflow_id = result.get("workflow_id", "unknown")
        logger.info(
            "workflow_started repo='%s' pr=%s workflow_id=%s",
            repository, pr_number, workflow_id,
        )
        return {
            "status": "workflow_started",
            "workflow_id": workflow_id,
            "repository": repository,
            "pr_number": pr_number,
            "action": action,
        }
    except Exception as exc:
        logger.exception("workflow_start_failed repo='%s' pr=%s", repository, pr_number)
        # Return 200 so Gitea doesn't retry in a loop
        return JSONResponse(
            status_code=200,
            content={"status": "error", "detail": str(exc)},
        )


@app.post("/webhook/simulate")
async def simulate_webhook(request: Request):
    """Manual trigger for testing. Body: { "repo": "owner/repo", "pr_number": 1 }"""
    try:
        import json as _json
        payload = _json.loads(await request.body())
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")

    repository = payload.get("repo") or payload.get("repository")
    pr_number  = int(payload.get("pr_number") or payload.get("pr") or 1)

    if not repository:
        raise HTTPException(status_code=400, detail="missing 'repo' field")

    logger.info("simulate_webhook repo='%s' pr=%s", repository, pr_number)

    try:
        result = await _post_with_retries(
            f"{LANGGRAPH_URL}/api/workflow/start",
            body={"repo": repository, "pr_number": pr_number},
        )
        return {
            "status": "workflow_started",
            "workflow_id": result.get("workflow_id"),
            "repository": repository,
            "pr_number": pr_number,
        }
    except Exception as exc:
        logger.exception("simulate_start_failed")
        raise HTTPException(status_code=502, detail=str(exc))

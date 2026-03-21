"""
TuskerSquad Integration Service
================================
Receives webhooks from Gitea, GitHub, and GitLab.
Triggers the LangGraph review pipeline on PR/MR events.

Webhook endpoints:
  POST /gitea/webhook    - Gitea pull_request events
  POST /github/webhook   - GitHub pull_request events
  POST /gitlab/webhook   - GitLab merge_request events
  POST /webhook/simulate - Manual trigger for any provider (testing)
"""

import asyncio
import hashlib
import hmac
import json
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

app = FastAPI(title="TuskerSquad Integration Service", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LANGGRAPH_URL         = os.getenv("LANGGRAPH_URL",         "http://tuskersquad-langgraph:8000")
GITEA_URL             = os.getenv("GITEA_URL",             "http://tuskersquad-gitea:3000")
GITEA_TOKEN           = os.getenv("GITEA_TOKEN",           "")
GITEA_WEBHOOK_SECRET  = os.getenv("GITEA_WEBHOOK_SECRET",  "")
GITHUB_TOKEN          = os.getenv("GITHUB_TOKEN",          "")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
GITLAB_TOKEN          = os.getenv("GITLAB_TOKEN",          "")
GITLAB_WEBHOOK_SECRET = os.getenv("GITLAB_WEBHOOK_SECRET", "")

_GITEA_TRIGGER  = {"opened", "synchronized", "reopened", "created", "reopen"}
_GITHUB_TRIGGER = {"opened", "synchronize", "reopened", "ready_for_review"}
_GITLAB_TRIGGER = {"open", "reopen", "update"}

_BACKEND_TOOL  = os.getenv("BACKEND_TEST_TOOL",  "pytest")
_FRONTEND_TOOL = os.getenv("FRONTEND_TEST_TOOL", "playwright")
_SECURITY_TOOL = os.getenv("SECURITY_PROBE_TOOL","httpx")
_SRE_TOOL      = os.getenv("SRE_LOAD_TOOL",      "httpx")


@app.on_event("startup")
async def _startup_log():
    logger.info("TuskerSquad Integration Service v2 starting")
    logger.info("  Gitea  : token=%s secret=%s -> POST /gitea/webhook",
                bool(GITEA_TOKEN), bool(GITEA_WEBHOOK_SECRET))
    logger.info("  GitHub : token=%s secret=%s -> POST /github/webhook",
                bool(GITHUB_TOKEN), bool(GITHUB_WEBHOOK_SECRET))
    logger.info("  GitLab : token=%s secret=%s -> POST /gitlab/webhook",
                bool(GITLAB_TOKEN), bool(GITLAB_WEBHOOK_SECRET))
    logger.info("  LangGraph : %s", LANGGRAPH_URL)


# HTTP helpers

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
    raise last_exc


async def _start_workflow(repository: str, pr_number: int, provider: str = "gitea") -> dict:
    return await _post_with_retries(
        f"{LANGGRAPH_URL}/api/workflow/start",
        body={"repo": repository, "pr_number": pr_number, "provider": provider},
    )


# "Review started" comment body

def _review_started_body(provider: str, repository: str,
                          pr_number: int, action: str) -> str:
    return (
        f"## TuskerSquad Review Started\n\n"
        f"> **{repository}** · PR #{pr_number} · `{action}` · provider: `{provider}`\n\n"
        "Full-stack agent pipeline is running. Results posted when complete.\n\n"
        "| Agent | Role | Tool |\n|-------|------|------|\n"
        "| Repo Validator | Verify PR and repository access | git + HTTP |\n"
        f"| Planner | Scope the review, analyse PR diff | {provider} diff |\n"
        f"| Backend Engineer | Run API test suite against PR code | {_BACKEND_TOOL} |\n"
        f"| Frontend Engineer | UI behaviour, accessibility checks | {_FRONTEND_TOOL} |\n"
        f"| Security Engineer | OWASP probes: auth bypass, SQLi, JWT, CORS | {_SECURITY_TOOL} |\n"
        f"| SRE Engineer | p95 latency measurement, SLA analysis | {_SRE_TOOL} |\n"
        "| Builder | Clone PR branch, build Docker image | docker build |\n"
        "| Deployer | Deploy ephemeral container, expose preview URL | docker run |\n"
        "| Tester | Run automated tests against live PR container | pytest |\n"
        "| API Validator | Schema and contract validation | httpx |\n"
        "| Security Runtime | Live attack probes against running container | httpx |\n"
        "| Runtime Analyser | CPU / memory profiling, log analysis | docker stats |\n"
        "| Log Inspector | Read structured logs from each microservice | /logs/events |\n"
        "| Correlator | Join client findings + server logs into root causes | rule-based + LLM |\n"
        "| Challenger | Dispute findings affected by environment variance | rule-based |\n"
        "| QA Lead | Synthesise overall risk level | phi3:mini |\n"
        "| Judge | Final APPROVE / REJECT / REVIEW_REQUIRED decision | qwen2.5:14b |\n"
        "| Cleanup | Stop container, remove image, wipe workspace | docker rm |\n\n"
        "*TuskerSquad*"
    )


# Provider comment helpers

async def _post_gitea_comment(repo: str, pr_number: int, body: str) -> bool:
    if not GITEA_TOKEN:
        return False
    url = f"{GITEA_URL}/api/v1/repos/{repo}/issues/{pr_number}/comments"
    headers = {"Authorization": f"token {GITEA_TOKEN}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(url, json={"body": body}, headers=headers)
        ok = r.status_code in (200, 201)
        if not ok:
            logger.warning("gitea_comment_failed repo=%s pr=%s http=%s",
                           repo, pr_number, r.status_code)
        return ok
    except Exception:
        logger.exception("gitea_comment_exception repo=%s pr=%s", repo, pr_number)
        return False


async def _post_github_comment(repo: str, pr_number: int, body: str) -> bool:
    if not GITHUB_TOKEN:
        logger.info("github_comment_skip: GITHUB_TOKEN not set")
        return False
    api_base = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    url = f"{api_base}/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(url, json={"body": body}, headers=headers)
        if r.status_code in (200, 201):
            logger.info("github_comment_posted repo=%s pr=%s", repo, pr_number)
            return True
        logger.warning("github_comment_failed repo=%s pr=%s http=%s body=%s",
                       repo, pr_number, r.status_code, r.text[:300])
        if r.status_code == 401:
            logger.error("github_401: GITHUB_TOKEN invalid or expired")
        elif r.status_code == 404:
            logger.error("github_404: %s PR#%s not found", repo, pr_number)
        return False
    except Exception:
        logger.exception("github_comment_exception repo=%s pr=%s", repo, pr_number)
        return False


async def _post_gitlab_comment(repo: str, mr_number: int, body: str) -> bool:
    if not GITLAB_TOKEN:
        logger.info("gitlab_comment_skip: GITLAB_TOKEN not set")
        return False
    from urllib.parse import quote
    gitlab_base = os.getenv("GITLAB_URL", "https://gitlab.com").rstrip("/")
    pid = quote(repo, safe="")
    url = f"{gitlab_base}/api/v4/projects/{pid}/merge_requests/{mr_number}/notes"
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(url, json={"body": body}, headers=headers)
        if r.status_code in (200, 201):
            logger.info("gitlab_comment_posted repo=%s mr=%s", repo, mr_number)
            return True
        logger.warning("gitlab_comment_failed repo=%s mr=%s http=%s body=%s",
                       repo, mr_number, r.status_code, r.text[:300])
        return False
    except Exception:
        logger.exception("gitlab_comment_exception repo=%s mr=%s", repo, mr_number)
        return False


# Signature verification

def _verify_gitea_sig(raw_body: bytes, headers: dict) -> bool:
    if not GITEA_WEBHOOK_SECRET:
        return True
    sig = headers.get("x-gitea-signature", "")
    if not sig:
        return False
    expected = hmac.new(GITEA_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig.strip().lower())


def _verify_github_sig(raw_body: bytes, headers: dict) -> bool:
    if not GITHUB_WEBHOOK_SECRET:
        return True
    sig = headers.get("x-hub-signature-256", "")
    if not sig:
        logger.warning("github_webhook: X-Hub-Signature-256 missing but secret configured")
        return False
    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig)


def _verify_gitlab_sig(raw_body: bytes, headers: dict) -> bool:
    if not GITLAB_WEBHOOK_SECRET:
        return True
    return headers.get("x-gitlab-token", "") == GITLAB_WEBHOOK_SECRET


# Payload parsers

def _parse_gitea(payload: dict) -> tuple:
    repo_obj = payload.get("repository") or {}
    repo     = repo_obj.get("full_name") or repo_obj.get("name", "")
    pr_obj   = payload.get("pull_request") or {}
    pr_num   = payload.get("number") or pr_obj.get("number")
    action   = payload.get("action", "")
    sha      = pr_obj.get("head", {}).get("sha", "")
    try:
        pr_num = int(pr_num) if pr_num is not None else None
    except (TypeError, ValueError):
        pr_num = None
    
    # Log if action is missing (indicates webhook payload issue)
    if not action and pr_num and repo:
        logger.warning("gitea_webhook_missing_action repo='%s' pr=%s", repo, pr_num)
    
    return repo, pr_num, action, sha


def _parse_github(payload: dict) -> tuple:
    action   = payload.get("action", "")
    pr_obj   = payload.get("pull_request") or {}
    repo_obj = payload.get("repository") or {}
    repo     = repo_obj.get("full_name", "")
    pr_num   = pr_obj.get("number")
    sha      = pr_obj.get("head", {}).get("sha", "")
    normalised = {
        "opened": "opened", "synchronize": "synchronize",
        "reopened": "reopened", "ready_for_review": "opened",
    }.get(action, action)
    try:
        pr_num = int(pr_num) if pr_num is not None else None
    except (TypeError, ValueError):
        pr_num = None
    return repo, pr_num, normalised, sha


def _parse_gitlab(payload: dict) -> tuple:
    kind = payload.get("object_kind", "")
    if kind != "merge_request":
        return None, None, kind, ""
    attrs  = payload.get("object_attributes") or {}
    action = attrs.get("action", "")
    mr_iid = attrs.get("iid")
    sha    = attrs.get("last_commit", {}).get("id", "")
    project= payload.get("project") or {}
    repo   = project.get("path_with_namespace", "")
    normalised = {"open": "opened", "reopen": "reopened", "update": "synchronize"}.get(action, action)
    try:
        mr_iid = int(mr_iid) if mr_iid is not None else None
    except (TypeError, ValueError):
        mr_iid = None
    return repo, mr_iid, normalised, sha


# Shared handler core

async def _handle_pr_event(
    provider: str,
    repository: Optional[str],
    pr_number: Optional[int],
    action: str,
    trigger_actions: set,
    comment_fn,
) -> JSONResponse:
    logger.info("webhook_parsed provider=%s action='%s' repo='%s' pr=%s",
                provider, action, repository, pr_number)

    if action and action not in trigger_actions:
        return JSONResponse({"status": "ignored",
                             "reason": f"action '{action}' does not trigger review"})
    if not repository:
        raise HTTPException(status_code=400, detail="missing repository in payload")
    if pr_number is None:
        raise HTTPException(status_code=400, detail="missing pr_number in payload")

    asyncio.create_task(
        comment_fn(repository, pr_number,
                   _review_started_body(provider, repository, pr_number, action))
    )

    try:
        result = await _start_workflow(repository, pr_number, provider)
        workflow_id = result.get("workflow_id", "unknown")
        logger.info("workflow_started provider=%s repo='%s' pr=%s wf=%s",
                    provider, repository, pr_number, workflow_id)
        return JSONResponse({
            "status":      "workflow_started",
            "provider":    provider,
            "workflow_id": workflow_id,
            "repository":  repository,
            "pr_number":   pr_number,
            "action":      action,
        })
    except Exception as exc:
        logger.exception("workflow_start_failed provider=%s repo='%s' pr=%s",
                         provider, repository, pr_number)
        return JSONResponse(status_code=200, content={"status": "error", "detail": str(exc)})


# Routes

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "integration-service",
        "providers": {
            "gitea":  {"configured": bool(GITEA_TOKEN),  "webhook": "/gitea/webhook"},
            "github": {"configured": bool(GITHUB_TOKEN), "webhook": "/github/webhook"},
            "gitlab": {"configured": bool(GITLAB_TOKEN), "webhook": "/gitlab/webhook"},
        },
    }


@app.get("/")
def root():
    return {
        "service":   "tuskersquad-integration",
        "endpoints": {
            "gitea":  "POST /gitea/webhook",
            "github": "POST /github/webhook",
            "gitlab": "POST /gitlab/webhook",
            "manual": "POST /webhook/simulate  body: {repo, pr_number, provider?}",
        },
    }


@app.post("/gitea/webhook")
async def gitea_webhook(request: Request):
    """Receive Gitea pull_request webhook and start a TuskerSquad review."""
    raw_body = await request.body()
    if not _verify_gitea_sig(raw_body, dict(request.headers)):
        logger.warning("gitea_webhook_rejected: invalid HMAC signature")
        raise HTTPException(status_code=401, detail="invalid webhook signature")
    try:
        payload = json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    event = request.headers.get("x-gitea-event", "")
    logger.info("gitea_webhook_received event='%s'", event)
    if event and event != "pull_request":
        return {"status": "ignored", "reason": f"event '{event}' is not pull_request"}

    repo, pr_num, action, sha = _parse_gitea(payload)
    return await _handle_pr_event(
        provider="gitea", repository=repo, pr_number=pr_num, action=action,
        trigger_actions=_GITEA_TRIGGER, comment_fn=_post_gitea_comment,
    )


@app.post("/github/webhook")
async def github_webhook(request: Request):
    """
    Receive GitHub pull_request webhook and start a TuskerSquad review.

    GitHub Setup:
      Repo → Settings → Webhooks → Add webhook
        Payload URL : http://<your-host>:8001/github/webhook
        Content type: application/json
        Secret      : set GITHUB_WEBHOOK_SECRET in infra/.env
        Events      : Pull requests
    """
    raw_body = await request.body()
    if not _verify_github_sig(raw_body, dict(request.headers)):
        logger.warning("github_webhook_rejected: invalid X-Hub-Signature-256")
        raise HTTPException(status_code=401, detail="invalid webhook signature")
    try:
        payload = json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    event = request.headers.get("x-github-event", "")
    logger.info("github_webhook_received event='%s'", event)
    if event and event != "pull_request":
        return {"status": "ignored", "reason": f"event '{event}' is not pull_request"}

    repo, pr_num, action, sha = _parse_github(payload)
    return await _handle_pr_event(
        provider="github", repository=repo, pr_number=pr_num, action=action,
        trigger_actions=_GITHUB_TRIGGER, comment_fn=_post_github_comment,
    )


@app.post("/gitlab/webhook")
async def gitlab_webhook(request: Request):
    """
    Receive GitLab merge_request webhook and start a TuskerSquad review.

    GitLab Setup:
      Project → Settings → Webhooks → Add new webhook
        URL         : http://<your-host>:8001/gitlab/webhook
        Secret token: set GITLAB_WEBHOOK_SECRET in infra/.env
        Trigger     : Merge request events
    """
    raw_body = await request.body()
    if not _verify_gitlab_sig(raw_body, dict(request.headers)):
        logger.warning("gitlab_webhook_rejected: invalid X-Gitlab-Token")
        raise HTTPException(status_code=401, detail="invalid webhook token")
    try:
        payload = json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    kind = payload.get("object_kind", "")
    logger.info("gitlab_webhook_received object_kind='%s'", kind)
    if kind and kind != "merge_request":
        return {"status": "ignored", "reason": f"object_kind '{kind}' is not merge_request"}

    repo, mr_num, action, sha = _parse_gitlab(payload)
    return await _handle_pr_event(
        provider="gitlab", repository=repo, pr_number=mr_num, action=action,
        trigger_actions=_GITLAB_TRIGGER, comment_fn=_post_gitlab_comment,
    )


@app.post("/webhook/simulate")
async def simulate_webhook(request: Request):
    """
    Manually trigger a review for any provider.
    Body: { "repo": "owner/repo", "pr_number": 1, "provider": "github" }
    """
    try:
        payload = json.loads(await request.body())
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")

    repository = payload.get("repo") or payload.get("repository")
    pr_number  = int(payload.get("pr_number") or payload.get("pr") or 1)
    provider   = (payload.get("provider") or os.getenv("GIT_PROVIDER", "gitea")).lower()

    if not repository:
        raise HTTPException(status_code=400, detail="missing 'repo' field")

    logger.info("simulate_webhook provider=%s repo='%s' pr=%s", provider, repository, pr_number)

    try:
        result = await _start_workflow(repository, pr_number, provider)
        return {
            "status":      "workflow_started",
            "provider":    provider,
            "workflow_id": result.get("workflow_id"),
            "repository":  repository,
            "pr_number":   pr_number,
        }
    except Exception as exc:
        logger.exception("simulate_start_failed")
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/webhook/debug")
async def webhook_debug():
    return {
        "langgraph_url":    LANGGRAPH_URL,
        "default_provider": os.getenv("GIT_PROVIDER", "gitea"),
        "providers": {
            "gitea": {
                "url": GITEA_URL, "token_set": bool(GITEA_TOKEN),
                "secret_set": bool(GITEA_WEBHOOK_SECRET),
                "webhook": "POST /gitea/webhook",
            },
            "github": {
                "api_url": os.getenv("GITHUB_API_URL", "https://api.github.com"),
                "token_set": bool(GITHUB_TOKEN), "secret_set": bool(GITHUB_WEBHOOK_SECRET),
                "webhook": "POST /github/webhook",
                "setup": "GitHub repo -> Settings -> Webhooks -> Add webhook",
            },
            "gitlab": {
                "url": os.getenv("GITLAB_URL", "https://gitlab.com"),
                "token_set": bool(GITLAB_TOKEN), "secret_set": bool(GITLAB_WEBHOOK_SECRET),
                "webhook": "POST /gitlab/webhook",
                "setup": "GitLab project -> Settings -> Webhooks",
            },
        },
        "manual_trigger": "POST /webhook/simulate  body: {repo, pr_number, provider}",
    }


@app.post("/webhook/test-parse")
async def test_parse(request: Request):
    """Parse any payload without triggering a workflow. Pass X-Provider header."""
    try:
        payload = json.loads(await request.body())
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")

    provider = request.headers.get("x-provider", "gitea").lower()

    if provider == "github":
        repo, pr_num, action, sha = _parse_github(payload)
        trigger_set = _GITHUB_TRIGGER
    elif provider == "gitlab":
        repo, pr_num, action, sha = _parse_gitlab(payload)
        trigger_set = _GITLAB_TRIGGER
    else:
        repo, pr_num, action, sha = _parse_gitea(payload)
        trigger_set = _GITEA_TRIGGER

    would_trigger = bool(repo and pr_num is not None and action in trigger_set)

    return {
        "provider":          provider,
        "parsed_repository": repo,
        "parsed_pr_number":  pr_num,
        "parsed_action":     action,
        "parsed_head_sha":   sha,
        "would_trigger":     would_trigger,
        "trigger_actions":   list(trigger_set),
        "skip_reason": (
            None if would_trigger else
            f"action '{action}' not in trigger set" if action not in trigger_set else
            "missing repository or pr_number"
        ),
    }

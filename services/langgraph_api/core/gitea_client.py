"""
Gitea API Client
================
All Gitea interactions for TuskerSquad.

Capabilities
------------
- Post PR comments  (rich markdown with findings table)
- Merge a PR after human APPROVE
- Create / set labels on a PR  (APPROVED / REJECTED / IN-REVIEW)
- Trigger a Gitea Actions deploy pipeline after merge
- Post commit status checks (pending → success / failure)

Environment variables
---------------------
GITEA_URL              http://tuskersquad-gitea:3000   (required)
GITEA_TOKEN            <personal-access-token>          (required)
AUTO_MERGE_ON_APPROVE  true | false  (default false)
MERGE_STYLE            merge | rebase | squash          (default merge)
DEPLOY_ON_MERGE        true | false  (default false)
DEPLOY_BRANCH          main                             (default main)
DEPLOY_PIPELINE        deploy  (Gitea Actions workflow filename without .yml)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("langgraph.gitea")


# ─────────────────────────────────────────────────────────────────────────────
# Config helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_config():
    url   = os.getenv("GITEA_URL", "").rstrip("/")
    token = os.getenv("GITEA_TOKEN", "")
    return url, token


def _headers(token: str) -> dict:
    return {"Authorization": f"token {token}", "Content-Type": "application/json"}


def _flag(env_var: str) -> bool:
    return os.getenv(env_var, "false").lower() in ("true", "1", "yes")


# ─────────────────────────────────────────────────────────────────────────────
# Rich comment builder
# ─────────────────────────────────────────────────────────────────────────────

_DECISION_ICON = {
    "APPROVE":          "✅",
    "REJECT":           "❌",
    "REVIEW_REQUIRED":  "⚠️",
    "RETEST_REQUESTED": "🔄",
}
_SEV_ICON = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}


def build_comment_body(
    workflow_id: str,
    decision: str,
    findings: list,
    qa_summary: str = "",
    risk_level: str = "",
    rationale: str = "",
    is_release: bool = False,
    release_reason: str = "",
    merged: bool = False,
    deployed: bool = False,
    deploy_url: str = "",
) -> str:
    icon  = _DECISION_ICON.get(decision, "🤖")
    label = "Release Manager Override" if is_release else "TuskerSquad AI Governance"
    ts    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"## {icon} TuskerSquad Decision: **{decision}**",
        f"> **{label}** · workflow `{workflow_id[:8]}` · {ts}",
        "",
    ]

    if risk_level:
        ri = _SEV_ICON.get(risk_level, "⚪")
        lines += [f"**Overall Risk:** {ri} `{risk_level}`", ""]

    if qa_summary:
        lines += [
            "<details>",
            "<summary><strong>📋 QA Lead Summary</strong> (click to expand)</summary>",
            "",
            qa_summary[:800],
            "",
            "</details>",
            "",
        ]

    if rationale:
        lines += [
            "<details>",
            "<summary><strong>⚖️ Judge Rationale</strong></summary>",
            "",
            rationale[:600],
            "",
            "</details>",
            "",
        ]

    if is_release and release_reason:
        lines += [f"**Business justification:** {release_reason}", ""]

    if findings:
        lines += ["### 🔍 Findings", ""]
        lines += ["| Agent | Severity | Finding |", "|-------|----------|---------|"]
        for f in findings[:20]:
            sev = f.get("severity", "LOW")
            si  = _SEV_ICON.get(sev, "⚪")
            lines.append(f"| `{f.get('agent','?')}` | {si} {sev} | {f.get('title','?')} |")
        if len(findings) > 20:
            lines.append(f"| … | | _{len(findings)-20} more findings_ |")
        lines.append("")

    if merged:
        lines += ["---", "🔀 **PR merged automatically by TuskerSquad after AI review**", ""]
    if deployed:
        dl = f" · [View pipeline]({deploy_url})" if deploy_url else ""
        lines += [f"🚀 **Deployment pipeline triggered**{dl}", ""]

    lines += [
        "---",
        "*Powered by [TuskerSquad](https://stonetusker.com) · Stonetusker Systems*",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Post comments
# ─────────────────────────────────────────────────────────────────────────────

def post_pr_comment_sync(owner_repo: str, pr_number: int, body: str) -> Optional[dict]:
    """POST a markdown comment to a Gitea PR (sync)."""
    url, token = _get_config()
    if not url or not token:
        logger.info("gitea_skip_comment: config incomplete")
        return None
    endpoint = f"{url}/api/v1/repos/{owner_repo}/issues/{pr_number}/comments"
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.post(endpoint, json={"body": body}, headers=_headers(token))
            r.raise_for_status()
            return r.json()
    except Exception:
        logger.exception("post_pr_comment_sync_failed repo=%s pr=%s", owner_repo, pr_number)
        return None


async def post_pr_comment_async(owner_repo: str, pr_number: int, body: str) -> Optional[dict]:
    url, token = _get_config()
    if not url or not token:
        return None
    endpoint = f"{url}/api/v1/repos/{owner_repo}/issues/{pr_number}/comments"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(endpoint, json={"body": body}, headers=_headers(token))
            r.raise_for_status()
            return r.json()
    except Exception:
        logger.exception("post_pr_comment_async_failed repo=%s pr=%s", owner_repo, pr_number)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# PR Labels
# ─────────────────────────────────────────────────────────────────────────────

_LABEL_COLOURS = {
    "tuskersquad:approved":  "27ae60",
    "tuskersquad:rejected":  "e74c3c",
    "tuskersquad:in-review": "f39c12",
    "tuskersquad:deployed":  "2980b9",
}


def _ensure_label(url: str, token: str, owner_repo: str, name: str) -> Optional[int]:
    list_url = f"{url}/api/v1/repos/{owner_repo}/labels"
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.get(list_url, headers=_headers(token))
            r.raise_for_status()
            for lbl in r.json():
                if lbl.get("name") == name:
                    return lbl["id"]
            colour = _LABEL_COLOURS.get(name, "95a5a6")
            r2 = client.post(list_url, json={"name": name, "color": f"#{colour}"},
                             headers=_headers(token))
            r2.raise_for_status()
            return r2.json().get("id")
    except Exception:
        logger.exception("ensure_label_failed repo=%s label=%s", owner_repo, name)
        return None


def set_pr_label(owner_repo: str, pr_number: int, label_name: str) -> bool:
    """Attach a label to a PR, creating it in the repo first if needed."""
    url, token = _get_config()
    if not url or not token:
        return False
    label_id = _ensure_label(url, token, owner_repo, label_name)
    if not label_id:
        return False
    endpoint = f"{url}/api/v1/repos/{owner_repo}/issues/{pr_number}/labels"
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.post(endpoint, json={"labels": [label_id]}, headers=_headers(token))
            return r.status_code in (200, 201)
    except Exception:
        logger.exception("set_pr_label_failed repo=%s pr=%s label=%s",
                         owner_repo, pr_number, label_name)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Commit Status
# ─────────────────────────────────────────────────────────────────────────────

def post_commit_status(owner_repo: str, sha: str, state: str, description: str) -> bool:
    """state: pending | success | failure | warning | error"""
    url, token = _get_config()
    if not url or not token or not sha:
        return False
    endpoint = f"{url}/api/v1/repos/{owner_repo}/statuses/{sha}"
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.post(endpoint, json={
                "state":       state,
                "description": description,
                "context":     "tuskersquad/review",
            }, headers=_headers(token))
            return r.status_code in (200, 201)
    except Exception:
        logger.exception("post_commit_status_failed repo=%s sha=%s", owner_repo, sha)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Auto-Merge
# ─────────────────────────────────────────────────────────────────────────────

def merge_pr_sync(
    owner_repo: str,
    pr_number: int,
    merge_style: Optional[str] = None,
    commit_message: str = "",
) -> dict:
    """
    Merge a Gitea PR via the REST API.

    Returns
    -------
    {"success": bool, "status_code": int, "error": str|None}
    """
    url, token = _get_config()
    if not url or not token:
        logger.warning("merge_pr_skipped: GITEA_URL or GITEA_TOKEN not set")
        return {"success": False, "status_code": 0, "error": "config_missing"}

    style = merge_style or os.getenv("MERGE_STYLE", "merge")
    if style not in ("merge", "rebase", "squash"):
        style = "merge"

    if not commit_message:
        commit_message = "chore: auto-merged by TuskerSquad after AI review ✅"

    endpoint = f"{url}/api/v1/repos/{owner_repo}/pulls/{pr_number}/merge"
    payload  = {
        "Do":                        style,
        "merge_message_field":       commit_message,
        "delete_branch_after_merge": False,
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(endpoint, json=payload, headers=_headers(token))

        if r.status_code == 204:
            logger.info("merge_pr_success repo=%s pr=%s style=%s",
                        owner_repo, pr_number, style)
            return {"success": True, "status_code": 204, "error": None}

        err = (r.text or "unknown")[:300]
        logger.warning("merge_pr_non204 repo=%s pr=%s status=%s body=%s",
                       owner_repo, pr_number, r.status_code, err)
        return {"success": False, "status_code": r.status_code, "error": err}

    except Exception as exc:
        logger.exception("merge_pr_exception repo=%s pr=%s", owner_repo, pr_number)
        return {"success": False, "status_code": 0, "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# Deploy on Merge  (Gitea Actions workflow_dispatch)
# ─────────────────────────────────────────────────────────────────────────────

def trigger_deploy_pipeline(
    owner_repo: str,
    pr_number: int,
    workflow_id: str,
    ref: Optional[str] = None,
) -> dict:
    """
    Dispatch a Gitea Actions workflow after merge.

    The repo must contain  .gitea/workflows/<DEPLOY_PIPELINE>.yml
    with  ``on: workflow_dispatch``.

    Returns
    -------
    {"success": bool, "status_code": int, "error": str|None, "url": str}
    """
    url, token = _get_config()
    if not url or not token:
        logger.warning("deploy_skipped: GITEA_URL or GITEA_TOKEN not set")
        return {"success": False, "status_code": 0, "error": "config_missing", "url": ""}

    pipeline = os.getenv("DEPLOY_PIPELINE", "deploy")
    branch   = ref or os.getenv("DEPLOY_BRANCH", "main")
    endpoint = f"{url}/api/v1/repos/{owner_repo}/actions/workflows/{pipeline}.yml/dispatches"
    run_url  = f"{url}/{owner_repo}/actions"

    payload = {
        "ref": branch,
        "inputs": {
            "pr_number":    str(pr_number),
            "workflow_id":  workflow_id,
            "triggered_by": "tuskersquad-auto-merge",
        },
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(endpoint, json=payload, headers=_headers(token))

        if r.status_code in (200, 201, 204):
            logger.info("deploy_triggered repo=%s pr=%s pipeline=%s branch=%s",
                        owner_repo, pr_number, pipeline, branch)
            return {"success": True, "status_code": r.status_code, "error": None, "url": run_url}

        err = (r.text or "unknown")[:300]
        logger.warning("deploy_trigger_non2xx repo=%s status=%s body=%s",
                       owner_repo, r.status_code, err)
        return {"success": False, "status_code": r.status_code, "error": err, "url": run_url}

    except Exception as exc:
        logger.exception("deploy_trigger_exception repo=%s pr=%s", owner_repo, pr_number)
        return {"success": False, "status_code": 0, "error": str(exc), "url": run_url}

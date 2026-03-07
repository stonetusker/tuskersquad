import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger("langgraph.gitea")


def _get_config():
    url = os.getenv("GITEA_URL")
    token = os.getenv("GITEA_TOKEN")
    return url, token


def build_comment_body(workflow_id: str, decision: str, findings: list) -> str:
    lines = [f"TuskerSquad governance decision: {decision}", ""]
    if findings:
        lines.append("Findings:")
        for f in findings:
            lines.append(f"- [{f.get('agent')}] {f.get('title')} ({f.get('severity')})")

    lines.append("")
    lines.append(f"Workflow: {workflow_id}")
    return "\n".join(lines)


def post_pr_comment_sync(owner_repo: str, pr_number: int, body: str) -> Optional[dict]:
    """Sync POST to Gitea to create a PR comment. Returns parsed JSON or None.

    Uses env vars `GITEA_URL` and `GITEA_TOKEN`. Does not log the token.
    """
    url, token = _get_config()
    if not url or not token:
        logger.info("Gitea config incomplete; skipping PR comment")
        return None

    endpoint = f"{url.rstrip('/')}/api/v1/repos/{owner_repo}/issues/{pr_number}/comments"

    headers = {"Authorization": f"token {token}"}

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(endpoint, json={"body": body}, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except Exception:
        logger.exception("failed_post_pr_comment_sync")
        return None


async def post_pr_comment_async(owner_repo: str, pr_number: int, body: str) -> Optional[dict]:
    url, token = _get_config()
    if not url or not token:
        logger.info("Gitea config incomplete; skipping PR comment")
        return None

    endpoint = f"{url.rstrip('/')}/api/v1/repos/{owner_repo}/issues/{pr_number}/comments"
    headers = {"Authorization": f"token {token}"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(endpoint, json={"body": body}, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except Exception:
        logger.exception("failed_post_pr_comment_async")
        return None

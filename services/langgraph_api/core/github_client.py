"""
GitHub Provider
===============
Implements GitProvider for GitHub.com and GitHub Enterprise Server (GHES).

Auth:
  GITHUB_TOKEN    — personal access token or fine-grained PAT
                    Scopes needed: repo (read + write PR comments, read contents)
  GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_PATH, GITHUB_APP_INSTALLATION_ID
                    — GitHub App auth (preferred for orgs)

GHES:
  GITHUB_API_URL  — e.g. https://github.example.com/api/v3  (default: https://api.github.com)

Webhook:
  GITHUB_WEBHOOK_SECRET — set this in GitHub repo Settings → Webhooks

GitHub sends X-Hub-Signature-256 for HMAC-SHA256 verification.
GitHub PR event action values:
  opened | synchronize | reopened | edited | closed | ready_for_review
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Dict, List, Optional

import httpx

from .git_provider import GitProvider, PRInfo, FileDiff, parse_unified_diff

logger = logging.getLogger("tuskersquad.github_provider")

_GITHUB_API_URL = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")

# GitHub actions that should trigger a review
GITHUB_TRIGGER_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}


class GitHubProvider(GitProvider):

    @property
    def name(self) -> str:
        return "github"

    def _token(self) -> str:
        return os.getenv("GITHUB_TOKEN", "")

    def _headers(self, accept: str = "application/vnd.github+json") -> dict:
        token = self._token()
        return {
            "Authorization": f"Bearer {token}" if token else "",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        }

    def _api(self, path: str) -> str:
        """Build full API URL from a /repos/... path."""
        return f"{_GITHUB_API_URL}{path}"

    # ── PR info ───────────────────────────────────────────────────────────────

    def get_pr_info(self, owner_repo: str, pr_number: int) -> Optional[PRInfo]:
        if not self._token():
            logger.warning("github_get_pr_info: GITHUB_TOKEN not set")
            return None
        try:
            with httpx.Client(timeout=10) as c:
                r = c.get(self._api(f"/repos/{owner_repo}/pulls/{pr_number}"),
                          headers=self._headers())
                r.raise_for_status()
                d = r.json()
                return PRInfo(
                    provider="github",
                    repo=owner_repo,
                    number=pr_number,
                    title=d.get("title", ""),
                    description=d.get("body", "") or "",
                    head_sha=d.get("head", {}).get("sha", ""),
                    base_branch=d.get("base", {}).get("ref", ""),
                    head_branch=d.get("head", {}).get("ref", ""),
                    author=d.get("user", {}).get("login", ""),
                    url=d.get("html_url", ""),
                    raw=d,
                )
        except Exception as exc:
            logger.debug("github_get_pr_info_failed: %s", exc)
            return None

    # ── Diff ──────────────────────────────────────────────────────────────────

    def get_pr_diff(self, owner_repo: str, pr_number: int) -> List[FileDiff]:
        if not self._token():
            return []
        try:
            with httpx.Client(timeout=30, follow_redirects=True) as c:
                r = c.get(
                    self._api(f"/repos/{owner_repo}/pulls/{pr_number}"),
                    headers=self._headers(accept="application/vnd.github.diff"),
                )
                r.raise_for_status()
                return parse_unified_diff(r.text)
        except Exception as exc:
            logger.debug("github_get_diff_failed: %s", exc)
            return []

    # ── Comments ──────────────────────────────────────────────────────────────

    def post_comment(self, owner_repo: str, pr_number: int, body: str) -> Optional[dict]:
        if not self._token():
            logger.warning("github_post_comment: GITHUB_TOKEN not set for %s", owner_repo)
            return None
        try:
            with httpx.Client(timeout=10) as c:
                r = c.post(
                    self._api(f"/repos/{owner_repo}/issues/{pr_number}/comments"),
                    headers=self._headers(),
                    json={"body": body},
                )
                if r.status_code in (200, 201):
                    logger.info("github_comment_posted repo=%s pr=%s", owner_repo, pr_number)
                    return r.json()
                logger.error("github_comment_failed repo=%s pr=%s http=%s body=%s",
                             owner_repo, pr_number, r.status_code, r.text[:400])
                if r.status_code == 401:
                    logger.error("github_401: GITHUB_TOKEN is invalid — check token and scopes")
                elif r.status_code == 403:
                    logger.error("github_403: token lacks 'repo' write scope for %s", owner_repo)
                elif r.status_code == 404:
                    logger.error("github_404: repo or PR not found — check %s PR#%s exists", owner_repo, pr_number)
                return None
        except httpx.ConnectError:
            logger.error("github_connect_error: cannot reach %s", _GITHUB_API_URL)
            return None
        except Exception:
            logger.exception("github_post_comment_exception repo=%s pr=%s", owner_repo, pr_number)
            return None

    def post_inline_comment(self, owner_repo: str, pr_number: int,
                            body: str, file_path: str, line: int,
                            commit_sha: str = "") -> Optional[dict]:
        """
        Post a pull request review comment on a specific line.
        Uses GitHub's /pulls/{pr_number}/comments endpoint.
        Requires commit_sha (the head SHA of the PR).
        Falls back to regular comment if sha is missing.
        """
        if not self._token():
            return None
        if not commit_sha:
            # Fall back to issue comment with file reference
            return self.post_comment(owner_repo, pr_number,
                                     f"**`{file_path}` line {line}:** {body}")
        try:
            with httpx.Client(timeout=10) as c:
                r = c.post(
                    self._api(f"/repos/{owner_repo}/pulls/{pr_number}/comments"),
                    headers=self._headers(),
                    json={
                        "body": body,
                        "commit_id": commit_sha,
                        "path": file_path,
                        "line": line,
                        "side": "RIGHT",
                    },
                )
                if r.status_code in (200, 201):
                    return r.json()
                logger.debug("github_inline_comment_failed http=%s: %s", r.status_code, r.text[:200])
                # Fallback to regular comment
                return self.post_comment(owner_repo, pr_number,
                                         f"**`{file_path}` line {line}:**\n\n{body}")
        except Exception:
            logger.exception("github_inline_comment_exception")
            return None

    # ── Labels ────────────────────────────────────────────────────────────────

    def _ensure_label(self, owner_repo: str, label: str) -> bool:
        """Create the label if it does not exist yet."""
        _LABEL_COLOURS = {
            "tuskersquad:approved":  "27ae60",
            "tuskersquad:rejected":  "e74c3c",
            "tuskersquad:in-review": "f39c12",
            "tuskersquad:deployed":  "2980b9",
        }
        try:
            with httpx.Client(timeout=8) as c:
                # Check if label exists
                r = c.get(self._api(f"/repos/{owner_repo}/labels"),
                          headers=self._headers())
                if r.status_code == 200:
                    for lbl in r.json():
                        if lbl.get("name") == label:
                            return True
                # Create label
                colour = _LABEL_COLOURS.get(label, "95a5a6")
                c.post(self._api(f"/repos/{owner_repo}/labels"),
                       headers=self._headers(),
                       json={"name": label, "color": colour})
            return True
        except Exception:
            return False

    def set_label(self, owner_repo: str, pr_number: int, label: str) -> bool:
        if not self._token():
            return False
        self._ensure_label(owner_repo, label)
        try:
            with httpx.Client(timeout=8) as c:
                r = c.post(
                    self._api(f"/repos/{owner_repo}/issues/{pr_number}/labels"),
                    headers=self._headers(),
                    json={"labels": [label]},
                )
                return r.status_code in (200, 201)
        except Exception:
            return False

    # ── Commit status ─────────────────────────────────────────────────────────

    def post_commit_status(self, owner_repo: str, sha: str,
                           state: str, description: str) -> bool:
        """
        Post a GitHub commit status (shown as the green/red check on a PR).
        state: 'pending' | 'success' | 'failure' | 'error'
        """
        if not self._token() or not sha:
            return False
        try:
            with httpx.Client(timeout=8) as c:
                r = c.post(
                    self._api(f"/repos/{owner_repo}/statuses/{sha}"),
                    headers=self._headers(),
                    json={
                        "state": state,
                        "description": description[:140],
                        "context": "tuskersquad/review",
                        "target_url": "",
                    },
                )
                return r.status_code in (200, 201)
        except Exception:
            return False

    # ── Merge ─────────────────────────────────────────────────────────────────

    def merge_pr(self, owner_repo: str, pr_number: int,
                 merge_style: str = "merge", message: str = "") -> dict:
        if not self._token():
            return {"success": False, "error": "GITHUB_TOKEN not set"}

        # GitHub merge method: merge | squash | rebase
        method_map = {"merge": "merge", "squash": "squash", "rebase": "rebase"}
        method = method_map.get(merge_style.lower(), "merge")

        try:
            with httpx.Client(timeout=15) as c:
                r = c.put(
                    self._api(f"/repos/{owner_repo}/pulls/{pr_number}/merge"),
                    headers=self._headers(),
                    json={
                        "commit_title": message or "chore: auto-merged by TuskerSquad after review",
                        "merge_method": method,
                    },
                )
                if r.status_code == 200:
                    return {"success": True, "status_code": 200, "error": None}
                return {"success": False, "status_code": r.status_code, "error": r.text[:300]}
        except Exception as exc:
            return {"success": False, "status_code": 0, "error": str(exc)}

    # ── Pipeline ──────────────────────────────────────────────────────────────

    def trigger_pipeline(self, owner_repo: str, pr_number: int,
                         workflow_id: str, ref: str = "") -> dict:
        """
        Trigger a GitHub Actions workflow via workflow_dispatch event.
        Requires GITHUB_ACTIONS_WORKFLOW env var (default: 'deploy.yml').
        """
        if not self._token():
            return {"success": False, "error": "GITHUB_TOKEN not set", "url": ""}

        workflow_file = os.getenv("GITHUB_ACTIONS_WORKFLOW",
                                  os.getenv("DEPLOY_PIPELINE", "deploy") + ".yml")
        branch = ref or os.getenv("DEPLOY_BRANCH", "main")
        run_url = f"https://github.com/{owner_repo}/actions"

        try:
            with httpx.Client(timeout=15) as c:
                r = c.post(
                    self._api(f"/repos/{owner_repo}/actions/workflows/{workflow_file}/dispatches"),
                    headers=self._headers(),
                    json={
                        "ref": branch,
                        "inputs": {
                            "pr_number": str(pr_number),
                            "workflow_id": workflow_id,
                            "triggered_by": "tuskersquad",
                        },
                    },
                )
                if r.status_code in (204, 200, 201):
                    return {"success": True, "status_code": r.status_code, "error": None, "url": run_url}
                return {"success": False, "status_code": r.status_code,
                        "error": r.text[:300], "url": run_url}
        except Exception as exc:
            return {"success": False, "status_code": 0, "error": str(exc), "url": run_url}

    # ── Webhook ───────────────────────────────────────────────────────────────

    def verify_webhook_signature(self, raw_body: bytes, headers: dict) -> bool:
        """GitHub uses X-Hub-Signature-256: sha256=<hex>"""
        secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
        if not secret:
            return True
        sig_header = headers.get("x-hub-signature-256", "")
        if not sig_header:
            logger.warning("github_webhook: signature header missing but secret is configured")
            return False
        expected = "sha256=" + hmac.new(
            secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, sig_header)

    def parse_webhook_payload(self, payload: dict, headers: dict) -> tuple:
        """
        GitHub pull_request event payload.
        https://docs.github.com/en/webhooks/webhook-events-and-payloads#pull_request
        """
        action   = payload.get("action", "")
        pr_obj   = payload.get("pull_request") or {}
        repo_obj = payload.get("repository") or {}

        owner_repo = repo_obj.get("full_name", "")
        pr_number  = pr_obj.get("number")
        sha        = pr_obj.get("head", {}).get("sha", "")

        # Normalise GitHub actions to our standard set
        normalised = {
            "opened":           "opened",
            "synchronize":      "synchronize",
            "reopened":         "reopened",
            "ready_for_review": "opened",   # treat as opened
        }.get(action, action)

        try:
            pr_number = int(pr_number) if pr_number is not None else None
        except (TypeError, ValueError):
            pr_number = None

        if action not in GITHUB_TRIGGER_ACTIONS:
            return owner_repo, pr_number, action, sha

        return owner_repo, pr_number, normalised, sha

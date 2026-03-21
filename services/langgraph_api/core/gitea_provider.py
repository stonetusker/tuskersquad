"""
Gitea Provider
==============
Wraps the existing gitea_client into the GitProvider interface.
This keeps all existing behaviour unchanged — Gitea is the default.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Dict, List, Optional

import httpx

from .git_provider import GitProvider, PRInfo, FileDiff, parse_unified_diff

logger = logging.getLogger("tuskersquad.gitea_provider")


class GiteaProvider(GitProvider):

    @property
    def name(self) -> str:
        return "gitea"

    def _url(self) -> str:
        return os.getenv("GITEA_URL", "").rstrip("/")

    def _token(self) -> str:
        return os.getenv("GITEA_TOKEN", "")

    def _headers(self) -> dict:
        return {"Authorization": f"token {self._token()}", "Content-Type": "application/json"}

    # ── PR info ───────────────────────────────────────────────────────────────

    def get_pr_info(self, owner_repo: str, pr_number: int) -> Optional[PRInfo]:
        url = self._url()
        if not url:
            return None
        endpoint = f"{url}/api/v1/repos/{owner_repo}/pulls/{pr_number}"
        try:
            with httpx.Client(timeout=10) as c:
                r = c.get(endpoint, headers=self._headers())
                r.raise_for_status()
                d = r.json()
                return PRInfo(
                    provider="gitea",
                    repo=owner_repo,
                    number=pr_number,
                    title=d.get("title", ""),
                    description=d.get("body", ""),
                    head_sha=d.get("head", {}).get("sha", ""),
                    base_branch=d.get("base", {}).get("ref", ""),
                    head_branch=d.get("head", {}).get("ref", ""),
                    author=d.get("user", {}).get("login", ""),
                    url=d.get("html_url", ""),
                    raw=d,
                )
        except Exception as exc:
            logger.debug("gitea_get_pr_info_failed: %s", exc)
            return None

    # ── Diff ──────────────────────────────────────────────────────────────────

    def get_pr_diff(self, owner_repo: str, pr_number: int) -> List[FileDiff]:
        url = self._url()
        if not url:
            return []
        # Gitea diff endpoint
        endpoint = f"{url}/api/v1/repos/{owner_repo}/pulls/{pr_number}.diff"
        try:
            with httpx.Client(timeout=20) as c:
                r = c.get(endpoint, headers=self._headers())
                r.raise_for_status()
                return parse_unified_diff(r.text)
        except Exception as exc:
            logger.debug("gitea_get_diff_failed: %s", exc)
            return []

    # ── Comments ──────────────────────────────────────────────────────────────

    def post_comment(self, owner_repo: str, pr_number: int, body: str) -> Optional[dict]:
        from .gitea_client import post_pr_comment_sync
        return post_pr_comment_sync(owner_repo, pr_number, body)

    def post_inline_comment(self, owner_repo: str, pr_number: int,
                            body: str, file_path: str, line: int,
                            commit_sha: str = "") -> Optional[dict]:
        """
        Gitea supports inline review comments via /pulls/{index}/reviews.
        Falls back to regular comment if anything fails.
        """
        url = self._url()
        token = self._token()
        if not url or not token:
            return None
        endpoint = f"{url}/api/v1/repos/{owner_repo}/pulls/{pr_number}/reviews"
        try:
            with httpx.Client(timeout=10) as c:
                r = c.post(endpoint, headers=self._headers(), json={
                    "body": body,
                    "comments": [{"path": file_path, "new_position": line, "body": body}],
                    "event": "COMMENT",
                })
                if r.status_code in (200, 201):
                    return r.json()
        except Exception:
            pass
        # Fallback: regular comment with file reference
        fallback = f"**Inline comment on `{file_path}` line {line}:**\n\n{body}"
        return self.post_comment(owner_repo, pr_number, fallback)

    # ── Labels ────────────────────────────────────────────────────────────────

    def set_label(self, owner_repo: str, pr_number: int, label: str) -> bool:
        from .gitea_client import set_pr_label
        return set_pr_label(owner_repo, pr_number, label)

    # ── Merge ─────────────────────────────────────────────────────────────────

    def merge_pr(self, owner_repo: str, pr_number: int,
                 merge_style: str = "merge", message: str = "") -> dict:
        from .gitea_client import merge_pr_sync
        return merge_pr_sync(owner_repo, pr_number, merge_style, message)

    # ── Pipeline ──────────────────────────────────────────────────────────────

    def trigger_pipeline(self, owner_repo: str, pr_number: int,
                         workflow_id: str, ref: str = "") -> dict:
        from .gitea_client import trigger_deploy_pipeline
        return trigger_deploy_pipeline(owner_repo, pr_number, workflow_id, ref)

    # ── Webhook ───────────────────────────────────────────────────────────────

    def verify_webhook_signature(self, raw_body: bytes, headers: dict) -> bool:
        secret = os.getenv("GITEA_WEBHOOK_SECRET", "")
        if not secret:
            return True
        sig = headers.get("x-gitea-signature", "")
        if not sig:
            return False
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig.strip().lower())

    def parse_webhook_payload(self, payload: dict, headers: dict) -> tuple:
        repo_obj = payload.get("repository") or {}
        repo = repo_obj.get("full_name") or repo_obj.get("name")
        pr_obj = payload.get("pull_request") or {}
        pr_num = payload.get("number") or pr_obj.get("number")
        action = payload.get("action", "")
        sha = pr_obj.get("head", {}).get("sha", "")
        try:
            pr_num = int(pr_num) if pr_num is not None else None
        except (TypeError, ValueError):
            pr_num = None
        return repo, pr_num, action, sha

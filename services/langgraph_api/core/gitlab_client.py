"""
GitLab Provider
===============
Implements GitProvider for GitLab.com and self-hosted GitLab instances.

Auth:
  GITLAB_TOKEN      — personal access token or project access token
                      Scopes needed: api (read_repository, write_repository)
  GITLAB_URL        — base URL (default: https://gitlab.com)

Webhook:
  GITLAB_WEBHOOK_SECRET — set in GitLab project Settings → Webhooks → Secret token
  GitLab sends X-Gitlab-Token: <secret> (plaintext comparison, not HMAC)

GitLab uses "merge requests" (MR) not "pull requests" (PR).
All external APIs use pr_number to mean MR IID (internal ID).
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional
from urllib.parse import quote

import httpx

from .git_provider import GitProvider, PRInfo, FileDiff, parse_unified_diff

logger = logging.getLogger("tuskersquad.gitlab_provider")

_GITLAB_URL = os.getenv("GITLAB_URL", "https://gitlab.com").rstrip("/")

# GitLab MR actions that should trigger a review
GITLAB_TRIGGER_ACTIONS = {"open", "reopen", "update"}


class GitLabProvider(GitProvider):

    @property
    def name(self) -> str:
        return "gitlab"

    def _token(self) -> str:
        return os.getenv("GITLAB_TOKEN", "")

    def _base(self) -> str:
        return os.getenv("GITLAB_URL", _GITLAB_URL).rstrip("/")

    def _headers(self) -> dict:
        return {
            "PRIVATE-TOKEN": self._token(),
            "Content-Type": "application/json",
        }

    def _project_id(self, owner_repo: str) -> str:
        """GitLab API uses URL-encoded namespace/project as project ID."""
        return quote(owner_repo, safe="")

    def _api(self, path: str) -> str:
        return f"{self._base()}/api/v4{path}"

    # ── PR info (MR in GitLab) ────────────────────────────────────────────────

    def get_pr_info(self, owner_repo: str, pr_number: int) -> Optional[PRInfo]:
        if not self._token():
            logger.warning("gitlab_get_pr_info: GITLAB_TOKEN not set")
            return None
        pid = self._project_id(owner_repo)
        try:
            with httpx.Client(timeout=10) as c:
                r = c.get(self._api(f"/projects/{pid}/merge_requests/{pr_number}"),
                          headers=self._headers())
                r.raise_for_status()
                d = r.json()
                return PRInfo(
                    provider="gitlab",
                    repo=owner_repo,
                    number=pr_number,
                    title=d.get("title", ""),
                    description=d.get("description", "") or "",
                    head_sha=d.get("sha", ""),
                    base_branch=d.get("target_branch", ""),
                    head_branch=d.get("source_branch", ""),
                    author=d.get("author", {}).get("username", ""),
                    url=d.get("web_url", ""),
                    raw=d,
                )
        except Exception as exc:
            logger.debug("gitlab_get_pr_info_failed: %s", exc)
            return None

    # ── Diff ──────────────────────────────────────────────────────────────────

    def get_pr_diff(self, owner_repo: str, pr_number: int) -> List[FileDiff]:
        if not self._token():
            return []
        pid = self._project_id(owner_repo)
        try:
            with httpx.Client(timeout=30) as c:
                # GitLab returns diffs as JSON array with diff strings
                r = c.get(
                    self._api(f"/projects/{pid}/merge_requests/{pr_number}/diffs"),
                    headers=self._headers(),
                    params={"per_page": 100},
                )
                r.raise_for_status()
                diffs = r.json()

            # Reconstruct unified diff from GitLab's JSON format
            unified_parts = []
            for d in diffs:
                old_path = d.get("old_path", "")
                new_path = d.get("new_path", "")
                diff_text = d.get("diff", "")
                if diff_text:
                    header = f"diff --git a/{old_path} b/{new_path}\n"
                    if d.get("new_file"):
                        header += "new file mode 100644\n"
                    elif d.get("deleted_file"):
                        header += "deleted file mode 100644\n"
                    elif d.get("renamed_file"):
                        header += f"rename from {old_path}\nrename to {new_path}\n"
                    header += f"--- a/{old_path}\n+++ b/{new_path}\n"
                    unified_parts.append(header + diff_text)

            return parse_unified_diff("\n".join(unified_parts))

        except Exception as exc:
            logger.debug("gitlab_get_diff_failed: %s", exc)
            return []

    # ── Comments ──────────────────────────────────────────────────────────────

    def post_comment(self, owner_repo: str, pr_number: int, body: str) -> Optional[dict]:
        if not self._token():
            logger.warning("gitlab_post_comment: GITLAB_TOKEN not set for %s", owner_repo)
            return None
        pid = self._project_id(owner_repo)
        try:
            with httpx.Client(timeout=10) as c:
                r = c.post(
                    self._api(f"/projects/{pid}/merge_requests/{pr_number}/notes"),
                    headers=self._headers(),
                    json={"body": body},
                )
                if r.status_code in (200, 201):
                    logger.info("gitlab_comment_posted repo=%s mr=%s", owner_repo, pr_number)
                    return r.json()
                logger.error("gitlab_comment_failed repo=%s mr=%s http=%s body=%s",
                             owner_repo, pr_number, r.status_code, r.text[:400])
                if r.status_code == 401:
                    logger.error("gitlab_401: GITLAB_TOKEN is invalid")
                elif r.status_code == 403:
                    logger.error("gitlab_403: token lacks 'api' scope for %s", owner_repo)
                elif r.status_code == 404:
                    logger.error("gitlab_404: project or MR not found — check %s MR!%s", owner_repo, pr_number)
                return None
        except httpx.ConnectError:
            logger.error("gitlab_connect_error: cannot reach %s", self._base())
            return None
        except Exception:
            logger.exception("gitlab_post_comment_exception repo=%s mr=%s", owner_repo, pr_number)
            return None

    def post_inline_comment(self, owner_repo: str, pr_number: int,
                            body: str, file_path: str, line: int,
                            commit_sha: str = "") -> Optional[dict]:
        """
        Post an inline comment on a specific MR diff line.
        Uses GitLab MR discussions API.
        """
        if not self._token():
            return None
        pid = self._project_id(owner_repo)

        if not commit_sha:
            return self.post_comment(owner_repo, pr_number,
                                     f"**`{file_path}` line {line}:**\n\n{body}")
        try:
            with httpx.Client(timeout=10) as c:
                r = c.post(
                    self._api(f"/projects/{pid}/merge_requests/{pr_number}/discussions"),
                    headers=self._headers(),
                    json={
                        "body": body,
                        "position": {
                            "position_type": "text",
                            "new_path": file_path,
                            "new_line": line,
                            "head_sha": commit_sha,
                            "base_sha": commit_sha,  # will be resolved by GitLab
                            "start_sha": commit_sha,
                        },
                    },
                )
                if r.status_code in (200, 201):
                    return r.json()
        except Exception:
            pass
        # Fallback
        return self.post_comment(owner_repo, pr_number,
                                 f"**`{file_path}` line {line}:**\n\n{body}")

    # ── Labels ────────────────────────────────────────────────────────────────

    def set_label(self, owner_repo: str, pr_number: int, label: str) -> bool:
        if not self._token():
            return False
        pid = self._project_id(owner_repo)
        try:
            with httpx.Client(timeout=8) as c:
                # Get current labels first
                r = c.get(self._api(f"/projects/{pid}/merge_requests/{pr_number}"),
                          headers=self._headers())
                if r.status_code != 200:
                    return False
                current = r.json().get("labels", [])
                if label not in current:
                    current.append(label)
                r2 = c.put(
                    self._api(f"/projects/{pid}/merge_requests/{pr_number}"),
                    headers=self._headers(),
                    json={"labels": ",".join(current)},
                )
                return r2.status_code in (200, 201)
        except Exception:
            return False

    # ── Merge ─────────────────────────────────────────────────────────────────

    def merge_pr(self, owner_repo: str, pr_number: int,
                 merge_style: str = "merge", message: str = "") -> dict:
        if not self._token():
            return {"success": False, "error": "GITLAB_TOKEN not set"}
        pid = self._project_id(owner_repo)

        # GitLab merge options
        should_squash = merge_style == "squash"

        try:
            with httpx.Client(timeout=15) as c:
                r = c.put(
                    self._api(f"/projects/{pid}/merge_requests/{pr_number}/merge"),
                    headers=self._headers(),
                    json={
                        "merge_commit_message": message or "chore: auto-merged by TuskerSquad after review",
                        "squash": should_squash,
                        "should_remove_source_branch": False,
                    },
                )
                if r.status_code in (200, 201):
                    return {"success": True, "status_code": r.status_code, "error": None}
                return {"success": False, "status_code": r.status_code, "error": r.text[:300]}
        except Exception as exc:
            return {"success": False, "status_code": 0, "error": str(exc)}

    # ── Pipeline ──────────────────────────────────────────────────────────────

    def trigger_pipeline(self, owner_repo: str, pr_number: int,
                         workflow_id: str, ref: str = "") -> dict:
        """
        Trigger a GitLab CI pipeline via pipeline triggers API.
        Requires GITLAB_TRIGGER_TOKEN env var.
        """
        trigger_token = os.getenv("GITLAB_TRIGGER_TOKEN", "")
        if not trigger_token:
            return {"success": False, "error": "GITLAB_TRIGGER_TOKEN not set", "url": ""}

        pid = self._project_id(owner_repo)
        branch = ref or os.getenv("DEPLOY_BRANCH", "main")
        run_url = f"{self._base()}/{owner_repo}/-/pipelines"

        try:
            with httpx.Client(timeout=15) as c:
                r = c.post(
                    self._api(f"/projects/{pid}/trigger/pipeline"),
                    data={
                        "token": trigger_token,
                        "ref": branch,
                        "variables[PR_NUMBER]": str(pr_number),
                        "variables[WORKFLOW_ID]": workflow_id,
                        "variables[TRIGGERED_BY]": "tuskersquad",
                    },
                )
                if r.status_code in (200, 201):
                    pipeline_id = r.json().get("id", "")
                    run_url = f"{self._base()}/{owner_repo}/-/pipelines/{pipeline_id}"
                    return {"success": True, "status_code": r.status_code, "error": None, "url": run_url}
                return {"success": False, "status_code": r.status_code,
                        "error": r.text[:300], "url": run_url}
        except Exception as exc:
            return {"success": False, "status_code": 0, "error": str(exc), "url": run_url}

    # ── Webhook ───────────────────────────────────────────────────────────────

    def verify_webhook_signature(self, raw_body: bytes, headers: dict) -> bool:
        """
        GitLab uses a plaintext secret token in X-Gitlab-Token header.
        Not HMAC — just a string comparison.
        """
        secret = os.getenv("GITLAB_WEBHOOK_SECRET", "")
        if not secret:
            return True  # no secret configured → accept all
        token_header = headers.get("x-gitlab-token", "")
        return token_header == secret

    def parse_webhook_payload(self, payload: dict, headers: dict) -> tuple:
        """
        GitLab merge_request webhook payload.
        https://docs.gitlab.com/ee/user/project/integrations/webhooks.html#merge-request-events

        GitLab payload shape:
        {
          "object_kind": "merge_request",
          "object_attributes": {
            "iid": 1,          <- internal MR ID (what we call pr_number)
            "action": "open" | "update" | "reopen" | "close" | "merge",
            "last_commit": {"id": "<sha>"}
          },
          "project": {"path_with_namespace": "owner/repo"}
        }
        """
        kind = payload.get("object_kind", "")
        if kind != "merge_request":
            return None, None, kind, ""

        attrs    = payload.get("object_attributes") or {}
        action   = attrs.get("action", "")
        mr_iid   = attrs.get("iid")
        sha      = attrs.get("last_commit", {}).get("id", "")

        project  = payload.get("project") or {}
        repo     = project.get("path_with_namespace", "")

        # Normalise GitLab actions
        normalised = {
            "open":   "opened",
            "reopen": "reopened",
            "update": "synchronize",
        }.get(action, action)

        try:
            mr_iid = int(mr_iid) if mr_iid is not None else None
        except (TypeError, ValueError):
            mr_iid = None

        return repo, mr_iid, normalised, sha

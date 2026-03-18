"""
TuskerSquad Git Provider Abstraction
=====================================
Defines the interface every git provider must implement.
Concrete implementations: GiteaProvider, GitHubProvider, GitLabProvider.

Provider selection (in priority order):
  1. GIT_PROVIDER env var: "gitea" | "github" | "gitlab"
  2. Auto-detect from repo URL format passed in webhook payload
  3. Default: gitea (backward-compatible)

All public functions on the provider have the same signature so
callers (pr_review_workflow, gitea_client wrappers) never need
to know which provider they are talking to.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger("tuskersquad.git_provider")


# ─── Data classes ─────────────────────────────────────────────────────────────

class PRInfo:
    """Normalised PR/MR metadata returned by every provider."""
    __slots__ = (
        "provider", "repo", "number", "title", "description",
        "head_sha", "base_branch", "head_branch", "author",
        "url", "diff_url", "raw",
    )

    def __init__(self, **kwargs):
        for k in self.__slots__:
            setattr(self, k, kwargs.get(k, ""))
        self.raw = kwargs.get("raw", {})

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__ if k != "raw"}


class DiffHunk:
    """One contiguous changed section within a file."""
    __slots__ = ("file_path", "old_start", "old_lines", "new_start", "new_lines",
                 "header", "added_lines", "removed_lines", "context_lines")

    def __init__(self, **kwargs):
        for k in self.__slots__:
            setattr(self, k, kwargs.get(k, "" if k in ("file_path", "header") else 0
                                         if k in ("old_start","old_lines","new_start","new_lines") else []))


class FileDiff:
    """Diff for a single file."""
    __slots__ = ("file_path", "old_path", "status", "hunks", "additions", "deletions")

    def __init__(self, **kwargs):
        for k in self.__slots__:
            setattr(self, k, kwargs.get(k,
                "" if k in ("file_path","old_path","status") else
                [] if k == "hunks" else 0))

    @property
    def changed_line_numbers(self) -> List[int]:
        """New-file line numbers that were added or modified."""
        lines = []
        for hunk in self.hunks:
            lines.extend(hunk.added_lines)
        return lines


# ─── Abstract base ─────────────────────────────────────────────────────────────

class GitProvider(ABC):
    """Abstract base class — all providers must implement these methods."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def get_pr_info(self, owner_repo: str, pr_number: int) -> Optional[PRInfo]: ...

    @abstractmethod
    def get_pr_diff(self, owner_repo: str, pr_number: int) -> List[FileDiff]: ...

    @abstractmethod
    def post_comment(self, owner_repo: str, pr_number: int, body: str) -> Optional[dict]: ...

    @abstractmethod
    def post_inline_comment(self, owner_repo: str, pr_number: int,
                            body: str, file_path: str, line: int,
                            commit_sha: str = "") -> Optional[dict]: ...

    @abstractmethod
    def set_label(self, owner_repo: str, pr_number: int, label: str) -> bool: ...

    @abstractmethod
    def remove_label(self, owner_repo: str, pr_number: int, label: str) -> bool: ...

    @abstractmethod
    def merge_pr(self, owner_repo: str, pr_number: int,
                 merge_style: str = "merge", message: str = "") -> dict: ...

    @abstractmethod
    def trigger_pipeline(self, owner_repo: str, pr_number: int,
                         workflow_id: str, ref: str = "") -> dict: ...

    @abstractmethod
    def verify_webhook_signature(self, raw_body: bytes, headers: dict) -> bool: ...

    @abstractmethod
    def parse_webhook_payload(self, payload: dict, headers: dict) -> tuple:
        """
        Returns (owner_repo: str, pr_number: int, action: str, head_sha: str).
        action is normalised: 'opened' | 'synchronize' | 'closed' | 'reopened'
        Returns (None, None, None, None) for non-PR events.
        """
        ...


# ─── Diff parser (shared utility, format is the same across all providers) ────

def parse_unified_diff(diff_text: str) -> List[FileDiff]:
    """
    Parse a unified diff string into FileDiff objects.
    Works with the output from Gitea, GitHub, and GitLab — they all use
    standard unified diff format.
    """
    files: List[FileDiff] = []
    current_file: Optional[FileDiff] = None
    current_hunk: Optional[DiffHunk] = None
    new_line_no = 0

    for raw_line in diff_text.splitlines():
        # New file section
        if raw_line.startswith("diff --git "):
            if current_hunk and current_file:
                current_file.hunks.append(current_hunk)
            if current_file:
                files.append(current_file)
            current_file = FileDiff()
            current_hunk = None

        elif raw_line.startswith("--- "):
            # old path: --- a/path/to/file  or  --- /dev/null
            path = raw_line[4:]
            if path.startswith("a/"):
                path = path[2:]
            elif path.startswith("/dev/null"):
                path = ""
            if current_file and path:
                current_file.old_path = path

        elif raw_line.startswith("+++ "):
            path = raw_line[4:]
            if path.startswith("b/"):
                path = path[2:]
            elif path.startswith("/dev/null"):
                path = ""
            if current_file:
                current_file.file_path = path

        elif raw_line.startswith("new file"):
            if current_file:
                current_file.status = "added"
        elif raw_line.startswith("deleted file"):
            if current_file:
                current_file.status = "deleted"
        elif raw_line.startswith("rename"):
            if current_file:
                current_file.status = "renamed"

        elif raw_line.startswith("@@"):
            # @@ -old_start,old_lines +new_start,new_lines @@
            if current_hunk and current_file:
                current_file.hunks.append(current_hunk)
            current_hunk = DiffHunk(file_path=current_file.file_path if current_file else "",
                                    header=raw_line)
            try:
                import re
                m = re.search(r"\+(\d+)(?:,(\d+))?", raw_line)
                if m:
                    new_line_no = int(m.group(1))
                    current_hunk.new_start = new_line_no
                    current_hunk.new_lines = int(m.group(2) or 1)
                m2 = re.search(r"-(\d+)(?:,(\d+))?", raw_line)
                if m2:
                    current_hunk.old_start = int(m2.group(1))
                    current_hunk.old_lines = int(m2.group(2) or 1)
            except Exception:
                pass

        elif current_hunk is not None:
            if raw_line.startswith("+"):
                current_hunk.added_lines.append(new_line_no)
                if current_file:
                    current_file.additions += 1
                new_line_no += 1
            elif raw_line.startswith("-"):
                current_hunk.removed_lines.append(new_line_no)
                if current_file:
                    current_file.deletions += 1
            else:
                # context line
                current_hunk.context_lines.append(new_line_no)
                new_line_no += 1

    # Flush last hunk and file
    if current_hunk and current_file:
        current_file.hunks.append(current_hunk)
    if current_file:
        if not current_file.status:
            current_file.status = "modified"
        files.append(current_file)

    return files


def summarise_diff(file_diffs: List[FileDiff]) -> dict:
    """
    Produce a structured summary of the diff for the planner agent.
    """
    changed_files = [f.file_path or f.old_path for f in file_diffs if (f.file_path or f.old_path)]
    by_ext: Dict[str, int] = {}
    for f in file_diffs:
        path = f.file_path or f.old_path
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else "other"
        by_ext[ext] = by_ext.get(ext, 0) + 1

    total_add = sum(f.additions for f in file_diffs)
    total_del = sum(f.deletions for f in file_diffs)

    # Identify high-risk file patterns
    risk_patterns = {
        "auth":     ["auth", "login", "token", "jwt", "password", "secret", "credential"],
        "payment":  ["checkout", "payment", "order", "price", "billing"],
        "infra":    ["dockerfile", "docker-compose", "requirements", ".env", "config"],
        "database": ["migration", "model", "schema", "db", "database"],
        "security": ["security", "cors", "csrf", "xss", "validation"],
    }
    risk_flags: List[str] = []
    for category, keywords in risk_patterns.items():
        for f in file_diffs:
            fp = (f.file_path or f.old_path).lower()
            if any(kw in fp for kw in keywords):
                if category not in risk_flags:
                    risk_flags.append(category)
                break

    return {
        "total_files_changed": len(file_diffs),
        "total_additions": total_add,
        "total_deletions": total_del,
        "changed_files": changed_files,
        "files_by_extension": by_ext,
        "risk_flags": risk_flags,                # categories of risky files touched
        "high_churn": total_add + total_del > 500,
        "file_details": [
            {
                "path":          f.file_path or f.old_path,
                "status":        f.status,
                "additions":     f.additions,
                "deletions":     f.deletions,
                "changed_lines": f.changed_line_numbers[:50],
            }
            for f in file_diffs[:30]  # cap at 30 files for state size
        ],
    }


# ─── Provider factory ──────────────────────────────────────────────────────────

def get_provider(provider_name: str = None) -> "GitProvider":
    """
    Return the configured git provider.

    Resolution order:
      1. provider_name argument (used when webhook handler knows the source)
      2. GIT_PROVIDER env var
      3. "gitea" (default — backward-compatible)
    """
    name = (provider_name or os.getenv("GIT_PROVIDER", "gitea")).lower().strip()

    if name == "github":
        from .github_client import GitHubProvider
        return GitHubProvider()
    elif name == "gitlab":
        from .gitlab_client import GitLabProvider
        return GitLabProvider()
    else:
        from .gitea_provider import GiteaProvider
        return GiteaProvider()


def detect_provider_from_repo(owner_repo: str) -> str:
    """
    Best-effort provider detection from a repo identifier.
    Webhook payloads from GitHub include 'clone_url' containing github.com etc.
    Falls back to GIT_PROVIDER env var or 'gitea'.
    """
    if not owner_repo:
        return os.getenv("GIT_PROVIDER", "gitea")
    repo_lower = owner_repo.lower()
    if "github.com" in repo_lower:
        return "github"
    if "gitlab.com" in repo_lower or "gitlab" in repo_lower:
        return "gitlab"
    return os.getenv("GIT_PROVIDER", "gitea")

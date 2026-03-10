"""
Diff Analyzer
=============
Fetches the PR/MR diff from the active git provider and produces:

  1. diff_context  — structured summary (files changed, risk flags, line numbers)
                     stored on workflow state for every agent to read

  2. annotate_findings_with_diff()
                   — enriches agent findings with diff context:
                     - was this finding in a changed file?
                     - was the exact line changed in this PR?
                     - this lets the judge de-prioritise findings in untouched code

Called by the planner_node so all downstream agents have diff context.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from .git_provider import FileDiff, PRInfo, get_provider, summarise_diff

logger = logging.getLogger("tuskersquad.diff_analyzer")


# ─── Main entry point ─────────────────────────────────────────────────────────

def fetch_and_analyse_diff(
    owner_repo: str,
    pr_number: int,
    provider_name: str = None,
) -> Dict[str, Any]:
    """
    Fetch the diff for a PR/MR from the active git provider and return
    a structured diff_context dict for the workflow state.

    Returns an empty context dict if the diff cannot be fetched
    (e.g. token not configured) — agents must handle this gracefully.
    """
    provider = get_provider(provider_name)

    pr_info: Optional[PRInfo] = None
    file_diffs: List[FileDiff] = []

    try:
        pr_info = provider.get_pr_info(owner_repo, pr_number)
    except Exception as exc:
        logger.debug("diff_analyzer_pr_info_failed provider=%s: %s", provider.name, exc)

    try:
        file_diffs = provider.get_pr_diff(owner_repo, pr_number)
        logger.info("diff_fetched provider=%s repo=%s pr=%s files=%d",
                    provider.name, owner_repo, pr_number, len(file_diffs))
    except Exception as exc:
        logger.warning("diff_analyzer_diff_failed provider=%s repo=%s pr=%s: %s",
                       provider.name, owner_repo, pr_number, exc)

    if not file_diffs:
        return _empty_context(owner_repo, pr_number, provider.name, pr_info)

    summary = summarise_diff(file_diffs)

    return {
        "provider":          provider.name,
        "owner_repo":        owner_repo,
        "pr_number":         pr_number,
        "head_sha":          pr_info.head_sha if pr_info else "",
        "base_branch":       pr_info.base_branch if pr_info else "",
        "head_branch":       pr_info.head_branch if pr_info else "",
        "pr_title":          pr_info.title if pr_info else "",
        "pr_description":    (pr_info.description[:500] if pr_info else ""),
        "pr_author":         pr_info.author if pr_info else "",
        # Diff summary
        "total_files_changed": summary["total_files_changed"],
        "total_additions":     summary["total_additions"],
        "total_deletions":     summary["total_deletions"],
        "changed_files":       summary["changed_files"],
        "files_by_extension":  summary["files_by_extension"],
        "risk_flags":          summary["risk_flags"],
        "high_churn":          summary["high_churn"],
        "file_details":        summary["file_details"],
        # Quick lookup for line-level annotation
        "_changed_lines_by_file": {
            f.file_path: set(f.changed_line_numbers)
            for f in file_diffs
        },
        "available": True,
    }


def _empty_context(owner_repo: str, pr_number: int,
                   provider: str, pr_info: Optional[PRInfo]) -> Dict[str, Any]:
    return {
        "provider":            provider,
        "owner_repo":          owner_repo,
        "pr_number":           pr_number,
        "head_sha":            pr_info.head_sha if pr_info else "",
        "base_branch":         pr_info.base_branch if pr_info else "",
        "head_branch":         pr_info.head_branch if pr_info else "",
        "pr_title":            pr_info.title if pr_info else "",
        "pr_description":      (pr_info.description[:500] if pr_info else ""),
        "pr_author":           pr_info.author if pr_info else "",
        "total_files_changed": 0,
        "total_additions":     0,
        "total_deletions":     0,
        "changed_files":       [],
        "files_by_extension":  {},
        "risk_flags":          [],
        "high_churn":          False,
        "file_details":        [],
        "_changed_lines_by_file": {},
        "available":           False,
    }


# ─── Finding annotation ───────────────────────────────────────────────────────

def annotate_findings_with_diff(
    findings: List[Dict[str, Any]],
    diff_context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Enrich each finding with diff-awareness metadata:

      in_changed_file : bool  — the affected file was changed in this PR
      on_changed_line : bool  — the specific line was changed in this PR
      diff_relevance  : "direct" | "related" | "unrelated"
                         direct   = finding is on a changed line
                         related  = finding is in a changed file
                         unrelated = finding is outside the PR diff entirely

    This allows the judge to weight findings:
      direct/related   → more likely introduced by this PR → higher priority
      unrelated        → pre-existing issue → lower priority, don't block merge

    Findings that have no file/line context (e.g. log_inspector, correlator)
    are marked as diff_relevance="systemic" — they apply to the whole service.
    """
    if not diff_context.get("available"):
        # No diff available — mark all as unknown
        for f in findings:
            f.setdefault("in_changed_file", None)
            f.setdefault("on_changed_line", None)
            f.setdefault("diff_relevance", "unknown")
        return findings

    changed_files = set(diff_context.get("changed_files", []))
    changed_lines_by_file = diff_context.get("_changed_lines_by_file", {})

    systemic_agents = {"log_inspector", "correlator", "qa_lead", "judge", "challenger", "planner"}

    for f in findings:
        agent = f.get("agent", "")

        if agent in systemic_agents:
            f["in_changed_file"]  = None
            f["on_changed_line"]  = None
            f["diff_relevance"]   = "systemic"
            continue

        # Try to extract file path from finding title or description
        file_path = f.get("file_path") or _extract_file_path(f, changed_files)
        line_num  = f.get("line_number")

        if file_path:
            in_file = file_path in changed_files
            on_line = False
            if in_file and line_num:
                on_line = int(line_num) in changed_lines_by_file.get(file_path, set())

            f["in_changed_file"] = in_file
            f["on_changed_line"] = on_line
            f["diff_relevance"]  = (
                "direct"   if on_line else
                "related"  if in_file else
                "unrelated"
            )
        else:
            # No file context — try to match by keyword
            matched = _file_keywords_match(f, changed_files)
            f["in_changed_file"] = matched
            f["on_changed_line"] = False
            f["diff_relevance"]  = "related" if matched else "unrelated"

    return findings


def _extract_file_path(finding: Dict, changed_files: set) -> Optional[str]:
    """
    Try to find a file path in the finding title or description
    that matches one of the changed files in the diff.
    """
    text = f"{finding.get('title','')} {finding.get('description','')}"
    for cf in changed_files:
        # Match by filename (without full path)
        filename = cf.split("/")[-1]
        if filename and filename in text:
            return cf
        # Match by full path
        if cf in text:
            return cf
    return None


def _file_keywords_match(finding: Dict, changed_files: set) -> bool:
    """Check if the finding's keywords suggest it relates to changed files."""
    text = (
        f"{finding.get('title','')} {finding.get('description','')} "
        f"{finding.get('test_name','')}"
    ).lower()
    for cf in changed_files:
        parts = cf.lower().replace("/", " ").replace("_", " ").replace(".", " ").split()
        if any(len(p) > 3 and p in text for p in parts):
            return True
    return False


# ─── Planner context builder ──────────────────────────────────────────────────

def build_planner_context(diff_context: Dict[str, Any]) -> str:
    """
    Build a human-readable planning context string from the diff.
    This is injected into the planner agent's output so all downstream
    agents know what changed in this PR.
    """
    if not diff_context.get("available"):
        return "Diff not available — running full test suite."

    lines = [
        "## PR Diff Analysis",
        "",
        f"**PR:** {diff_context.get('pr_title', '(no title)')}",
        f"**Author:** {diff_context.get('pr_author', 'unknown')}",
        f"**Branch:** `{diff_context.get('head_branch','?')}` → `{diff_context.get('base_branch','?')}`",
        f"**Provider:** {diff_context.get('provider','?')}",
        "",
        f"**Files changed:** {diff_context['total_files_changed']}  "
        f"(+{diff_context['total_additions']} / -{diff_context['total_deletions']} lines)",
        "",
    ]

    risk_flags = diff_context.get("risk_flags", [])
    if risk_flags:
        lines += [
            f"**Risk areas touched:** {', '.join(risk_flags)}",
            "",
        ]

    if diff_context.get("high_churn"):
        lines += ["**High-churn PR** (>500 line changes) — run full test suite.", ""]

    # List changed files (max 20)
    changed = diff_context.get("changed_files", [])
    if changed:
        lines.append("**Changed files:**")
        for f in changed[:20]:
            lines.append(f"  - `{f}`")
        if len(changed) > 20:
            lines.append(f"  - *(+{len(changed)-20} more files)*")
        lines.append("")

    # Agent focus recommendations based on risk flags
    recommendations = []
    flag_to_agents = {
        "auth":     ["security", "backend"],
        "payment":  ["backend", "sre"],
        "infra":    ["sre", "security"],
        "database": ["backend", "sre"],
        "security": ["security"],
    }
    mentioned = set()
    for flag in risk_flags:
        for agent in flag_to_agents.get(flag, []):
            if agent not in mentioned:
                recommendations.append(f"- **{agent}**: focus on `{flag}` changes")
                mentioned.add(agent)

    if recommendations:
        lines += ["**Recommended agent focus:**"] + recommendations + [""]

    return "\n".join(lines)

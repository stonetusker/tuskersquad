"""
Gitea API Client
================
All Gitea interactions for TuskerSquad.

PR Comment strategy (transparency-first):
  1. An INITIAL comment is posted when the pipeline completes, showing
     every agent's decision, tests run, findings and rationale.
  2. A GOVERNANCE comment is added when a human approves/rejects/overrides.
  3. Merge + deploy status updates are appended as follow-up comments.

Environment variables
---------------------
GITEA_URL              http://tuskersquad-gitea:3000
GITEA_TOKEN            <personal-access-token>
AUTO_MERGE_ON_APPROVE  true | false
MERGE_STYLE            merge | rebase | squash
DEPLOY_ON_MERGE        true | false
DEPLOY_BRANCH          main
DEPLOY_PIPELINE        deploy
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("langgraph.gitea")

# ─── Config ───────────────────────────────────────────────────────────────────

def _get_config():
    return os.getenv("GITEA_URL", "").rstrip("/"), os.getenv("GITEA_TOKEN", "")

def _headers(token: str) -> dict:
    return {"Authorization": f"token {token}", "Content-Type": "application/json"}

def _flag(env_var: str) -> bool:
    return os.getenv(env_var, "false").lower() in ("true", "1", "yes")

# ─── Icons ────────────────────────────────────────────────────────────────────

_DECISION_ICON = {
    "APPROVE":          "[APPROVED]",
    "REJECT":           "[REJECTED]",
    "REVIEW_REQUIRED":  "[REVIEW REQUIRED]",
    "RETEST_REQUESTED": "[RETEST]",
    "PASS":             "[PASS]",
    "FLAG":             "[FLAG]",
    "CHALLENGE":        "[CHALLENGE]",
}
_SEV_ICON     = {"HIGH": "[HIGH]", "MEDIUM": "[MEDIUM]", "LOW": "[LOW]", "NONE": ""}
_AGENT_ICON   = {
    "planner":       "",
    "backend":       "",
    "frontend":      "",
    "security":      "",
    "sre":           "",
    "log_inspector": "",
    "correlator":    "",
    "challenger":    "",
    "qa_lead":       "",
    "judge":         "",
}
_AGENT_LABEL  = {
    "planner":       "Planner Agent",
    "backend":       "Backend Engineer",
    "frontend":      "Frontend Engineer",
    "security":      "Security Engineer",
    "sre":           "SRE / Performance",
    "log_inspector": "Log Inspector (Server-Side)",
    "correlator":    "Correlator / Root Cause Analyst",
    "challenger":    "Challenger Agent",
    "qa_lead":       "QA Lead",
    "judge":         "Judge Agent",
}


# ─── Per-agent decision block builder ────────────────────────────────────────

def _agent_section(
    agent: str,
    findings: list,
    agent_decision: Optional[dict] = None,
) -> list:
    """
    Build markdown lines for a single agent's section in the PR comment.
    agent_decision: {decision, summary, risk_level, test_count}
    findings: list of {agent, severity, title, description}
    """
    label = _AGENT_LABEL.get(agent, agent.replace("_", " ").title())
    my_findings = [f for f in findings if f.get("agent") == agent]

    if agent_decision:
        d         = agent_decision.get("decision", "PASS")
        di        = _DECISION_ICON.get(d, "[UNKNOWN]")
        risk      = agent_decision.get("risk_level", "LOW")
        ri        = _SEV_ICON.get(risk, "")
        tests     = agent_decision.get("test_count", len(my_findings))
        summary   = (agent_decision.get("summary") or "").strip()
    else:
        d       = "FLAG" if my_findings else "PASS"
        di      = _DECISION_ICON.get(d, "[UNKNOWN]")
        risk    = "HIGH" if any(f.get("severity") == "HIGH" for f in my_findings) else \
                  "MEDIUM" if my_findings else "NONE"
        ri      = _SEV_ICON.get(risk, "")
        tests   = len(my_findings)
        summary = ""

    lines = [
        f"#### {label}  {di}  Risk: {ri if ri else risk}",
    ]
    if summary:
        lines.append(f"> {summary[:400]}")
        lines.append("")

    if my_findings:
        lines.append(f"**Tests run:** {tests} · **Findings:** {len(my_findings)}")
        lines.append("")
        for f in my_findings[:8]:
            sev = f.get("severity", "LOW")
            si = _SEV_ICON.get(sev, sev)
            desc = (f.get("description") or "")[:160]
            lines.append(f"- **{si}** {f.get('title', '?')} — {desc}")
        if len(my_findings) > 8:
            lines.append(f"- *(+{len(my_findings)-8} more findings)*")
    else:
        lines.append(f"**Tests run:** {tests} · **Findings:** 0 — No issues detected.")

    lines.append("")
    return lines


# ─── Full transparency comment builder ───────────────────────────────────────

def build_initial_review_comment(
    workflow_id: str,
    decision:    str,
    findings:    list,
    qa_summary:  str = "",
    risk_level:  str = "",
    rationale:   str = "",
    agent_decisions: Optional[dict] = None,   # {agent_name: {decision, summary, risk_level, test_count}}
    developer_brief: str = "",                # from correlator agent — cross-layer RCA
) -> str:
    """
    Build the rich initial PR comment posted when the pipeline completes.
    Includes cross-layer root cause analysis from the correlator agent.
    """
    icon  = _DECISION_ICON.get(decision, "[UNKNOWN]")
    ts   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    risk_icon = _SEV_ICON.get(risk_level, "")

    lines = [
        f"## TuskerSquad Review — {icon} **{decision}**",
        f"> Workflow `{workflow_id[:8]}` · {ts} · Overall Risk: {risk_icon} `{risk_level or 'UNKNOWN'}`",
        "",
    ]

    # QA Lead summary — shown first so it's never trimmed by Gitea's PR comment preview
    if qa_summary:
        lines += [
            "### QA Lead Summary",
            "",
            qa_summary[:800],
            "",
        ]

    # Root cause analysis brief from correlator
    if developer_brief:
        lines += [
            developer_brief[:2000],
            "",
        ]

    # Judge rationale
    if rationale:
        lines += [
            "<details>",
            "<summary><strong>Judge Rationale</strong> (click to expand)</summary>",
            "",
            rationale[:800],
            "",
            "</details>",
            "",
        ]

    # Per-agent breakdown
    PIPELINE_ORDER = ["planner", "backend", "frontend", "security", "sre",
                      "log_inspector", "correlator", "challenger", "qa_lead", "judge"]
    lines += [
        "---",
        "### Agent Findings",
        "",
        "<details>",
        "<summary><strong>Click to expand full agent report</strong></summary>",
        "",
    ]

    for agent in PIPELINE_ORDER:
        ad = (agent_decisions or {}).get(agent)
        lines += _agent_section(agent, findings, ad)

    lines += ["</details>", ""]

    # High-severity findings table at top level
    high_findings = [f for f in findings if (f.get("severity") or "").upper() == "HIGH"]
    if high_findings:
        lines += ["### High-Severity Findings", ""]
        lines += ["| Agent | Finding | Description |", "|-------|---------|-------------|"]
        for f in high_findings[:10]:
            desc = (f.get("description") or "")[:100].replace("|", "\\|")
            lines.append(f"| `{f.get('agent','?')}` | {f.get('title','?')} | {desc} |")
        lines.append("")

    lines += [
        "---",
        f"*TuskerSquad full-stack review — workflow `{workflow_id[:8]}` · {ts}*",
    ]
    return "\n".join(lines)


def build_governance_comment(
    workflow_id:    str,
    decision:       str,
    actor:          str = "Human Reviewer",
    reason:         str = "",
    is_release:     bool = False,
    merged:         bool = False,
    deployed:       bool = False,
    deploy_url:     str  = "",
) -> str:
    """Compact governance decision comment (approve/reject/override)."""
    icon  = _DECISION_ICON.get(decision, "[UNKNOWN]")
    ts   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    label = "Release Manager Override" if is_release else "Human Governance Decision"

    lines = [
        f"### {icon} {label}: **{decision}**",
        f"> **{actor}** · workflow `{workflow_id[:8]}` · {ts}",
        "",
    ]
    if reason:
        lines += [f"**Reason:** {reason}", ""]
    if merged:
        lines += ["**PR merged automatically by TuskerSquad.**", ""]
    if deployed:
        dl = f" · [View pipeline]({deploy_url})" if deploy_url else ""
        lines += [f"**Deployment pipeline triggered.**{dl}", ""]
    lines += ["---", "*TuskerSquad*"]
    return "\n".join(lines)


# Keep backward-compat alias
def build_comment_body(
    workflow_id: str,
    decision:    str,
    findings:    list,
    qa_summary:  str = "",
    risk_level:  str = "",
    rationale:   str = "",
    is_release:  bool = False,
    release_reason: str = "",
    merged:      bool = False,
    deployed:    bool = False,
    deploy_url:  str  = "",
    agent_decisions: Optional[dict] = None,
) -> str:
    return build_initial_review_comment(
        workflow_id=workflow_id,
        decision=decision,
        findings=findings,
        qa_summary=qa_summary,
        risk_level=risk_level,
        rationale=rationale,
        agent_decisions=agent_decisions,
    )


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def post_pr_comment_sync(owner_repo: str, pr_number: int, body: str) -> Optional[dict]:
    url, token = _get_config()
    if not url:
        logger.warning("gitea_skip_comment: GITEA_URL not set")
        return None
    if not token:
        logger.warning("gitea_skip_comment: GITEA_TOKEN not set — add it to infra/.env and restart")
        return None
    endpoint = f"{url}/api/v1/repos/{owner_repo}/issues/{pr_number}/comments"
    logger.info("gitea_comment_post endpoint=%s", endpoint)
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.post(endpoint, json={"body": body}, headers=_headers(token))
        if r.status_code in (200, 201):
            logger.info("gitea_comment_ok repo=%s pr=%s", owner_repo, pr_number)
            return r.json()
        # Log full details so the user can diagnose the failure
        logger.error(
            "gitea_comment_failed repo=%s pr=%s http=%s body=%s",
            owner_repo, pr_number, r.status_code, r.text[:500],
        )
        if r.status_code == 401:
            logger.error("gitea_401: token is invalid or expired — regenerate at http://localhost:3000/user/settings/applications")
        elif r.status_code == 403:
            logger.error("gitea_403: token lacks permission — needs 'issue' write scope for repo %s", owner_repo)
        elif r.status_code == 404:
            logger.error("gitea_404: repo or PR not found — check repo='%s' pr=%s exists in Gitea", owner_repo, pr_number)
        return None
    except httpx.ConnectError:
        logger.error("gitea_connect_error: cannot reach %s — is Gitea running?", url)
        return None
    except Exception:
        logger.exception("gitea_comment_exception repo=%s pr=%s", owner_repo, pr_number)
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


# ─── Labels ───────────────────────────────────────────────────────────────────

_LABEL_COLOURS = {
    "tuskersquad:approved":  "27ae60",
    "tuskersquad:rejected":  "e74c3c",
    "tuskersquad:in-review": "f39c12",
    "tuskersquad:deployed":  "2980b9",
}

def _ensure_label(url, token, owner_repo, name) -> Optional[int]:
    list_url = f"{url}/api/v1/repos/{owner_repo}/labels"
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.get(list_url, headers=_headers(token))
            r.raise_for_status()
            for lbl in r.json():
                if lbl.get("name") == name:
                    return lbl["id"]
            colour = _LABEL_COLOURS.get(name, "95a5a6")
            r2 = client.post(list_url, json={"name": name, "color": f"#{colour}"}, headers=_headers(token))
            r2.raise_for_status()
            return r2.json().get("id")
    except Exception:
        logger.exception("ensure_label_failed repo=%s label=%s", owner_repo, name)
        return None


def set_pr_label(owner_repo: str, pr_number: int, label_name: str) -> bool:
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
        logger.exception("set_pr_label_failed")
        return False


def remove_pr_label(owner_repo: str, pr_number: int, label_name: str) -> bool:
    url, token = _get_config()
    if not url or not token:
        return False
    # First get the label ID
    label_id = None
    list_url = f"{url}/api/v1/repos/{owner_repo}/labels"
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.get(list_url, headers=_headers(token))
            r.raise_for_status()
            for lbl in r.json():
                if lbl.get("name") == label_name:
                    label_id = lbl["id"]
                    break
    except Exception:
        logger.exception("find_label_failed repo=%s label=%s", owner_repo, label_name)
        return False
    
    if not label_id:
        # Label doesn't exist, consider it successfully removed
        return True
    
    # Remove the label from the PR
    endpoint = f"{url}/api/v1/repos/{owner_repo}/issues/{pr_number}/labels/{label_id}"
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.delete(endpoint, headers=_headers(token))
            return r.status_code in (200, 204)
    except Exception:
        logger.exception("remove_pr_label_failed")
        return False


# ─── Commit status ────────────────────────────────────────────────────────────

def post_commit_status(owner_repo, sha, state, description) -> bool:
    url, token = _get_config()
    if not url or not token or not sha:
        return False
    endpoint = f"{url}/api/v1/repos/{owner_repo}/statuses/{sha}"
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.post(endpoint, json={
                "state": state, "description": description,
                "context": "tuskersquad/review",
            }, headers=_headers(token))
            return r.status_code in (200, 201)
    except Exception:
        logger.exception("post_commit_status_failed")
        return False


# ─── Auto-Merge ───────────────────────────────────────────────────────────────

def merge_pr_sync(owner_repo, pr_number, merge_style=None, commit_message="") -> dict:
    url, token = _get_config()
    if not url or not token:
        return {"success": False, "status_code": 0, "error": "config_missing"}
    style = merge_style or os.getenv("MERGE_STYLE", "merge")
    if style not in ("merge", "rebase", "squash"):
        style = "merge"
    if not commit_message:
        commit_message = "chore: auto-merged by TuskerSquad after review"
    endpoint = f"{url}/api/v1/repos/{owner_repo}/pulls/{pr_number}/merge"
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(endpoint, json={
                "Do": style,
                "merge_message_field": commit_message,
                "delete_branch_after_merge": False,
            }, headers=_headers(token))
        if r.status_code == 204:
            return {"success": True, "status_code": 204, "error": None}
        return {"success": False, "status_code": r.status_code, "error": r.text[:300]}
    except Exception as exc:
        return {"success": False, "status_code": 0, "error": str(exc)}


# ─── Deploy pipeline ──────────────────────────────────────────────────────────

def trigger_deploy_pipeline(owner_repo, pr_number, workflow_id, ref=None) -> dict:
    url, token = _get_config()
    if not url or not token:
        return {"success": False, "status_code": 0, "error": "config_missing", "url": ""}
    pipeline = os.getenv("DEPLOY_PIPELINE", "deploy")
    branch   = ref or os.getenv("DEPLOY_BRANCH", "main")
    endpoint = f"{url}/api/v1/repos/{owner_repo}/actions/workflows/{pipeline}.yml/dispatches"
    run_url  = f"{url}/{owner_repo}/actions"
    payload  = {"ref": branch, "inputs": {
        "pr_number": str(pr_number),
        "workflow_id": workflow_id,
        "triggered_by": "tuskersquad-auto-merge",
    }}
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(endpoint, json=payload, headers=_headers(token))
        if r.status_code in (200, 201, 204):
            return {"success": True, "status_code": r.status_code, "error": None, "url": run_url}
        return {"success": False, "status_code": r.status_code, "error": r.text[:300], "url": run_url}
    except Exception as exc:
        return {"success": False, "status_code": 0, "error": str(exc), "url": run_url}

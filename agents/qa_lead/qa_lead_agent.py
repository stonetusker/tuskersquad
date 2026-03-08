"""
QA Lead Agent
=============
Synthesises findings from all engineering agents into:
  1. A standup-style summary (what each agent found)
  2. A risk overview (overall risk rating + recommendation)

Uses phi3:mini via Ollama when available; falls back to a deterministic
template-based summary when Ollama is not configured.
"""

import os

def _run_async(coro):
    """Run coroutine safely from background thread or async context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result(timeout=30)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return _run_async(coro)

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("agents.qa_lead")


def _severity_rank(s: str) -> int:
    return {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get((s or "").upper(), 0)


def _build_template_summary(findings: List[Dict]) -> str:
    """Deterministic template summary -- no LLM required."""
    if not findings:
        return "No findings reported by engineering agents. PR appears clean."

    by_agent: Dict[str, List[Dict]] = {}
    for f in findings:
        by_agent.setdefault(f.get("agent", "unknown"), []).append(f)

    lines = ["## QA Lead Standup Summary\n"]
    for agent, agent_findings in sorted(by_agent.items()):
        severities = [f.get("severity", "LOW") for f in agent_findings]
        worst = max(severities, key=_severity_rank)
        lines.append(
            f"**{agent.upper()}** ({len(agent_findings)} finding(s), worst: {worst})"
        )
        for f in agent_findings:
            lines.append(
                f"  - [{f.get('severity','?')}] {f.get('title','')}: "
                f"{f.get('description','')[:120]}"
            )

    high = [f for f in findings if _severity_rank(f.get("severity")) == 3]
    medium = [f for f in findings if _severity_rank(f.get("severity")) == 2]

    lines.append("\n## Risk Overview")
    if high:
        lines.append(
            f"**Overall Risk: HIGH** -- {len(high)} HIGH severity finding(s) "
            "require immediate attention before merge."
        )
    elif medium:
        lines.append(
            f"**Overall Risk: MEDIUM** -- {len(medium)} MEDIUM severity "
            "finding(s) should be reviewed."
        )
    else:
        lines.append(
            "**Overall Risk: LOW** -- No HIGH or MEDIUM findings. "
            "PR may proceed with standard review."
        )

    lines.append(
        f"\nTotal findings: {len(findings)} | High: {len(high)} | Medium: {len(medium)}"
    )
    return "\n".join(lines)


async def _llm_summary(findings: List[Dict]) -> Optional[str]:
    """Request a natural-language standup summary from phi3:mini via Ollama."""
    ollama_url = os.getenv("OLLAMA_URL")
    if not ollama_url:
        return None

    try:
        from core.llm_client import LLMClient
        llm = LLMClient()

        findings_text = "\n".join(
            f"- [{f.get('severity')}] {f.get('agent')}: {f.get('title')} -- "
            f"{f.get('description','')[:200]}"
            for f in findings
        )

        prompt = (
            "You are a QA Lead. Write a brief standup summary and risk overview "
            "for this PR review.\n"
            "Format:\n"
            "1. One sentence per agent summarising what they found.\n"
            "2. An overall risk rating (LOW / MEDIUM / HIGH) with one sentence "
            "justification.\n\n"
            f"Findings:\n{findings_text}\n\n"
            "Standup Summary:"
        )

        resp = await asyncio.wait_for(llm.generate("qa_lead", prompt), timeout=15)
        return resp

    except asyncio.TimeoutError:
        logger.warning("qa_lead_llm_timeout")
        return None
    except Exception:
        logger.exception("qa_lead_llm_failed")
        return None


def run_qa_lead_agent(
    workflow_id: str,
    repository: str,
    pr_number: int,
    findings: List[Dict],
) -> Dict[str, Any]:
    """
    Main entry point called by the graph runner.

    Returns dict with keys: summary (str), risk_level (str), agent_log (dict).
    """
    start = datetime.utcnow()
    logger.info("qa_lead_agent_started", extra={"workflow_id": workflow_id})

    # Try LLM summary; fall back to template
    llm_summary = None
    try:
        llm_summary = _run_async(_llm_summary(findings))
    except RuntimeError:
        pass

    summary = llm_summary if llm_summary else _build_template_summary(findings)

    high_count = sum(1 for f in findings if _severity_rank(f.get("severity")) == 3)
    med_count = sum(1 for f in findings if _severity_rank(f.get("severity")) == 2)

    if high_count > 0:
        risk_level = "HIGH"
    elif med_count > 1:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    agent_log = {
        "agent": "qa_lead",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
    }

    return {
        "summary": summary,
        "risk_level": risk_level,
        "agent_log": agent_log,
    }

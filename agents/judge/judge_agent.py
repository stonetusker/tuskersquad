"""
Judge Agent
===========
Makes the final deployment decision based on:
  - Engineering findings (severity / count)
  - Challenger disputes
  - QA Lead risk level
  - Optional LLM reasoning via qwen2.5:14b

Decision values: APPROVE | REJECT | REVIEW_REQUIRED
"""

import asyncio
import os


def _run_async(coro):
    """Run a coroutine safely from a background thread."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            return asyncio.run(coro)
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result(timeout=30)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("agents.judge")


def _severity_rank(s: str) -> int:
    return {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get((s or "").upper(), 0)


def _rule_based_decision(
    findings: List[Dict],
    challenges: List[Dict],
    risk_level: str,
) -> str:
    """
    Deterministic rule-based fallback.

    Rules (in priority order):
      1. Any HIGH severity finding → REVIEW_REQUIRED
      2. QA Lead risk_level == HIGH → REVIEW_REQUIRED
      3. Active challenger disputes > 0 → REVIEW_REQUIRED
      4. MEDIUM findings > 1 → REVIEW_REQUIRED
      5. Otherwise → APPROVE
    """
    high = [f for f in findings if _severity_rank(f.get("severity")) == 3]
    if high:
        return "REVIEW_REQUIRED"

    if (risk_level or "").upper() == "HIGH":
        return "REVIEW_REQUIRED"

    if len(challenges) > 0:
        return "REVIEW_REQUIRED"

    med = [f for f in findings if _severity_rank(f.get("severity")) == 2]
    if len(med) > 1:
        return "REVIEW_REQUIRED"

    return "APPROVE"


async def _llm_decision(
    findings: List[Dict],
    challenges: List[Dict],
    qa_summary: str,
) -> Optional[str]:
    """Ask the LLM judge for a decision. Returns raw response text or None."""
    ollama_url = os.getenv("OLLAMA_URL")
    if not ollama_url:
        return None

    try:
        from core.llm_client import get_llm_client
        llm = get_llm_client()

        findings_text = "\n".join(
            f"- [{f.get('severity')}] {f.get('agent')}: {f.get('title')}"
            for f in findings
        )
        challenge_text = (
            "\n".join(
                f"- {c.get('challenger_agent')} challenged finding {c.get('finding_id')}: "
                f"{c.get('challenge_reason')}"
                for c in challenges
            )
            or "None"
        )

        prompt = (
            "You are the Judge agent for a CI/CD governance system.\n"
            "Review the following and respond with exactly one word: "
            "APPROVE, REJECT, or REVIEW_REQUIRED.\n\n"
            f"QA Summary:\n{qa_summary[:600]}\n\n"
            f"Findings:\n{findings_text}\n\n"
            f"Challenger disputes:\n{challenge_text}\n\n"
            "Decision (APPROVE / REJECT / REVIEW_REQUIRED):"
        )

        resp = await asyncio.wait_for(llm.generate("judge", prompt), timeout=15)
        return resp

    except asyncio.TimeoutError:
        logger.warning("judge_llm_timeout")
        return None
    except Exception:
        logger.exception("judge_llm_failed")
        return None


def _parse_llm_decision(text: str) -> Optional[str]:
    upper = (text or "").upper()
    if "APPROVE" in upper:
        return "APPROVE"
    if "REJECT" in upper:
        return "REJECT"
    if "REVIEW_REQUIRED" in upper or "REVIEW" in upper:
        return "REVIEW_REQUIRED"
    return None


def run_judge_agent(
    workflow_id: str,
    repository: str,
    pr_number: int,
    findings: List[Dict],
    challenges: List[Dict],
    qa_summary: str,
    risk_level: str,
) -> Dict[str, Any]:
    """
    Main entry point called by the graph runner.

    Returns dict with keys: decision (str), rationale (str), agent_log (dict).
    """
    start = datetime.utcnow()
    logger.info("judge_agent_started", extra={"workflow_id": workflow_id})

    llm_response = None
    try:
        llm_response = _run_async(
            _llm_decision(findings, challenges, qa_summary)
        )
    except RuntimeError:
        pass

    decision = None
    rationale = ""

    if llm_response:
        decision = _parse_llm_decision(llm_response)
        rationale = llm_response

    if decision is None:
        decision = _rule_based_decision(findings, challenges, risk_level)
        rationale = (
            f"Rule-based decision: {decision}. "
            f"Findings: {len(findings)} total, "
            f"HIGH: {sum(1 for f in findings if _severity_rank(f.get('severity'))==3)}, "
            f"MEDIUM: {sum(1 for f in findings if _severity_rank(f.get('severity'))==2)}. "
            f"Challenges: {len(challenges)}. "
            f"QA risk level: {risk_level}."
        )

    logger.info(
        "judge_decision",
        extra={"workflow_id": workflow_id, "decision": decision},
    )

    agent_log = {
        "agent": "judge",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
    }

    return {
        "decision": decision,
        "rationale": rationale,
        "agent_log": agent_log,
    }

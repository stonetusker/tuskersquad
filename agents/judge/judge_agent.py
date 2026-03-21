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
    runtime_analysis: Dict = None,
    repository: str = None,
) -> str:
    """
    Deterministic rule-based fallback.

    Rules (in priority order):
      1. Any HIGH severity finding → REVIEW_REQUIRED
      2. QA Lead risk_level == HIGH → REVIEW_REQUIRED
      3. Active challenger disputes > 0 → REVIEW_REQUIRED
      4. Runtime health issues (high CPU/memory, unhealthy status) → REVIEW_REQUIRED
      5. MEDIUM findings > 1 → REVIEW_REQUIRED
      6. Otherwise → APPROVE
    """
    high = [f for f in findings if _severity_rank(f.get("severity")) == 3]
    if high:
        return "REVIEW_REQUIRED"

    if (risk_level or "").upper() == "HIGH":
        return "REVIEW_REQUIRED"

    if len(challenges) > 0:
        return "REVIEW_REQUIRED"

    # Check runtime analysis for health issues
    if runtime_analysis:
        runtime_health = runtime_analysis.get("runtime_health", {})
        if not runtime_health.get("healthy", True):
            return "REVIEW_REQUIRED"

        # Check container stats for resource issues
        container_stats = runtime_analysis.get("container_stats", {})
        cpu_percent = container_stats.get("cpu_percent", 0)
        mem_percent = container_stats.get("memory_percent", 0)

        cpu_threshold = float(os.getenv("CPU_THRESHOLD", "80"))
        mem_threshold = float(os.getenv("MEM_THRESHOLD", "80"))

        if cpu_percent > cpu_threshold or mem_percent > mem_threshold:
            return "REVIEW_REQUIRED"

    med = [f for f in findings if _severity_rank(f.get("severity")) == 2]
    if len(med) > 1:
        return "REVIEW_REQUIRED"

    return "APPROVE"


async def _llm_decision(
    findings: List[Dict],
    challenges: List[Dict],
    qa_summary: str,
    runtime_analysis: Dict = None,
    workflow_id: str = None,
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

        runtime_text = ""
        if runtime_analysis:
            runtime_health = runtime_analysis.get("runtime_health", {})
            container_stats = runtime_analysis.get("container_stats", {})
            runtime_text = f"\nRuntime Analysis:\n- Health Status: {'Healthy' if runtime_health.get('healthy', True) else 'Unhealthy'}\n- High Priority Issues: {runtime_health.get('high_priority_issues', 0)}\n- CPU Usage: {container_stats.get('cpu_percent', 'N/A')}%\n- Memory Usage: {container_stats.get('memory_percent', 'N/A')}%\n"

        prompt = (
            "You are the Judge agent for a CI/CD governance system.\n"
            "Review the following and respond with exactly one word: "
            "APPROVE, REJECT, or REVIEW_REQUIRED.\n\n"
            f"QA Summary:\n{qa_summary[:600]}\n\n"
            f"Findings:\n{findings_text}\n\n"
            f"Challenger disputes:\n{challenge_text}\n\n"
            f"{runtime_text}"
            "Decision (APPROVE / REJECT / REVIEW_REQUIRED):"
        )

        resp = await asyncio.wait_for(llm.generate("judge", prompt, workflow_id=workflow_id), timeout=90)
        return resp

    except asyncio.TimeoutError:
        logger.warning("judge_llm_timeout")
        return None
    except Exception:
        logger.exception("judge_llm_failed")
        return None


def _parse_llm_decision(text: str) -> Optional[str]:
    upper = (text or "").upper()
    # Look for exact matches first
    if "APPROVE" in upper:
        return "APPROVE"
    if "REJECT" in upper:
        return "REJECT"
    if "REVIEW_REQUIRED" in upper or "REVIEW" in upper:
        return "REVIEW_REQUIRED"
    # Look for the first word
    words = upper.split()
    for word in words:
        if word in ("APPROVE", "REJECT", "REVIEW_REQUIRED", "REVIEW"):
            if word == "REVIEW":
                return "REVIEW_REQUIRED"
            return word
    return None


def run_judge_agent(
    workflow_id: str,
    repository: str,
    pr_number: int,
    findings: List[Dict],
    challenges: List[Dict],
    qa_summary: str,
    risk_level: str,
    runtime_analysis: Dict = None,
) -> Dict[str, Any]:
    """
    Main entry point called by the graph runner.

    Returns dict with keys: decision (str), rationale (str), agent_log (dict).
    """
    start = datetime.utcnow()
    logger.info("judge_agent_started", extra={"workflow_id": workflow_id})

    auto_approve_demo = os.getenv("AUTO_APPROVE_DEMO", "false").lower() == "true"
    if auto_approve_demo:
        decision = "APPROVE"
        rationale = "Auto-approved for demo environment."
        agent_log = {
            "agent": "judge",
            "status": "COMPLETED",
            "started_at": start.isoformat(),
            "completed_at": datetime.utcnow().isoformat(),
        }
        logger.info(
            "judge_decision",
            extra={"workflow_id": workflow_id, "decision": decision},
        )
        return {
            "decision": decision,
            "rationale": rationale,
            "agent_log": agent_log,
        }

    llm_response = None
    # Always use rule-based decision for consistency
    try:
        llm_response = _run_async(
            _llm_decision(findings, challenges, qa_summary, runtime_analysis,
                         workflow_id=str(workflow_id) if workflow_id else None)
        )
    except RuntimeError:
        pass

    decision = None
    rationale = ""

    if llm_response:
        decision = _parse_llm_decision(llm_response)
        rationale = llm_response

    if decision is None:
        decision = _rule_based_decision(findings, challenges, risk_level, runtime_analysis, repository)
        rationale = (
            f"Rule-based decision: {decision}. "
            f"Findings: {len(findings)} total, "
            f"HIGH: {sum(1 for f in findings if _severity_rank(f.get('severity'))==3)}, "
            f"MEDIUM: {sum(1 for f in findings if _severity_rank(f.get('severity'))==2)}. "
            f"Challenges: {len(challenges)}. "
            f"QA risk level: {risk_level}."
        )

        # Add runtime analysis info to rationale if available
        if runtime_analysis:
            runtime_health = runtime_analysis.get("runtime_health", {})
            container_stats = runtime_analysis.get("container_stats", {})
            rationale += (
                f" Runtime health: {'healthy' if runtime_health.get('healthy', True) else 'unhealthy'}. "
                f"CPU: {container_stats.get('cpu_percent', 'N/A')}%, "
                f"Memory: {container_stats.get('memory_percent', 'N/A')}%."
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

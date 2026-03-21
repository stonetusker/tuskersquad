"""
Judge Agent
===========
Makes the final deployment decision based on:
  - Engineering findings (severity / count)
  - Challenger disputes
  - QA Lead risk level
  - Optional LLM reasoning via qwen2.5:14b

Decision values: APPROVE | REJECT | REVIEW_REQUIRED

AUTO_APPROVE_DEMO mode (set AUTO_APPROVE_DEMO=true in infra/.env):
  Skips the challenger dispute check so a PR with only LOW findings
  is APPROVED rather than held at REVIEW_REQUIRED due to environment-
  variance disputes on latency measurements. Any HIGH finding still
  always requires human review regardless of this setting.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("agents.judge")


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


def _severity_rank(s: str) -> int:
    return {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get((s or "").upper(), 0)


def _rule_based_decision(
    findings: List[Dict],
    challenges: List[Dict],
    risk_level: str,
    runtime_analysis: Dict = None,
) -> str:
    """
    Deterministic rule-based decision.

    Rules (in priority order):
      1. Any HIGH severity finding                         → REVIEW_REQUIRED
      2. QA Lead risk_level == HIGH                        → REVIEW_REQUIRED
      3. Active challenger disputes (unless AUTO_APPROVE_DEMO=true) → REVIEW_REQUIRED
      4. Runtime health issues (high CPU/mem, unhealthy)   → REVIEW_REQUIRED
      5. MEDIUM findings > 1                               → REVIEW_REQUIRED
      6. Otherwise                                         → APPROVE
    """
    # Rule 1: any HIGH finding always blocks — no exceptions
    high = [f for f in findings if _severity_rank(f.get("severity")) == 3]
    if high:
        return "REVIEW_REQUIRED"

    # Rule 2: QA Lead assessed overall risk as HIGH
    if (risk_level or "").upper() == "HIGH":
        return "REVIEW_REQUIRED"

    # Rule 3: challenger disputes
    # AUTO_APPROVE_DEMO skips this check so latency-variance disputes on a
    # clean demo run don't block approval. HIGH findings still block above.
    auto_approve_demo = os.getenv("AUTO_APPROVE_DEMO", "false").lower() == "true"
    if len(challenges) > 0 and not auto_approve_demo:
        return "REVIEW_REQUIRED"

    # Rule 4: runtime health issues
    if runtime_analysis:
        runtime_health = runtime_analysis.get("runtime_health", {})
        if not runtime_health.get("healthy", True):
            return "REVIEW_REQUIRED"
        container_stats = runtime_analysis.get("container_stats", {})
        cpu_percent = container_stats.get("cpu_percent", 0)
        mem_percent = container_stats.get("memory_percent", 0)
        cpu_threshold = float(os.getenv("CPU_THRESHOLD", "80"))
        mem_threshold = float(os.getenv("MEM_THRESHOLD", "80"))
        if cpu_percent > cpu_threshold or mem_percent > mem_threshold:
            return "REVIEW_REQUIRED"

    # Rule 5: more than one MEDIUM finding
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
            rh = runtime_analysis.get("runtime_health", {})
            cs = runtime_analysis.get("container_stats", {})
            runtime_text = (
                f"\nRuntime Analysis:\n"
                f"- Health: {'Healthy' if rh.get('healthy', True) else 'Unhealthy'}\n"
                f"- CPU: {cs.get('cpu_percent', 'N/A')}%  "
                f"Memory: {cs.get('memory_percent', 'N/A')}%\n"
            )

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

        resp = await asyncio.wait_for(
            llm.generate("judge", prompt, workflow_id=workflow_id), timeout=90
        )
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
    runtime_analysis: Dict = None,
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
            _llm_decision(
                findings, challenges, qa_summary, runtime_analysis,
                workflow_id=str(workflow_id) if workflow_id else None,
            )
        )
    except RuntimeError:
        pass

    decision = None
    rationale = ""

    if llm_response:
        decision = _parse_llm_decision(llm_response)
        rationale = llm_response

    if decision is None:
        decision = _rule_based_decision(
            findings, challenges, risk_level, runtime_analysis
        )
        high_count  = sum(1 for f in findings if _severity_rank(f.get("severity")) == 3)
        med_count   = sum(1 for f in findings if _severity_rank(f.get("severity")) == 2)
        rationale = (
            f"Rule-based decision: {decision}. "
            f"Findings: {len(findings)} total — HIGH: {high_count}, MEDIUM: {med_count}. "
            f"Challenger disputes: {len(challenges)}. "
            f"QA risk level: {risk_level}. "
            f"AUTO_APPROVE_DEMO: {os.getenv('AUTO_APPROVE_DEMO', 'false')}."
        )
        if runtime_analysis:
            rh = runtime_analysis.get("runtime_health", {})
            cs = runtime_analysis.get("container_stats", {})
            rationale += (
                f" Runtime: {'healthy' if rh.get('healthy', True) else 'unhealthy'}. "
                f"CPU {cs.get('cpu_percent', 'N/A')}%, "
                f"Memory {cs.get('memory_percent', 'N/A')}%."
            )

    logger.info(
        "judge_decision",
        extra={"workflow_id": workflow_id, "decision": decision},
    )

    return {
        "decision":  decision,
        "rationale": rationale,
        "agent_log": {
            "agent":        "judge",
            "status":       "COMPLETED",
            "started_at":   start.isoformat(),
            "completed_at": datetime.utcnow().isoformat(),
        },
    }

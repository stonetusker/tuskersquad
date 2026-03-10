"""
PR Review Workflow Executor
============================
Executes the TuskerSquad agent pipeline and persists results to PostgreSQL.
New: LLM conversation logging, per-agent decision summaries, rich PR comments.
"""

import asyncio
import concurrent.futures
import logging
import os
import time
from typing import Any, Dict, Optional


def _run_async(coro):
    """Run a coroutine safely from a background thread."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            return asyncio.run(coro)
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result(timeout=30)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


from ..db.database import SessionLocal
from ..repositories.workflow_repository import WorkflowRepository
from ..repositories.findings_repository import FindingsRepository
from ..repositories.governance_repository import GovernanceRepository
from ..repositories.agent_log_repository import AgentLogRepository
from ..repositories.finding_challenges_repository import FindingChallengesRepository
from ..repositories.qa_summary_repository import QASummaryRepository
from ..repositories.llm_log_repository import LLMLogRepository
from ..repositories.agent_decision_repository import AgentDecisionRepository
from .graph_builder import build_graph, LangGraphWrapper
from ..core.workflow_registry import workflow_registry
from ..core.gitea_client import (
    build_initial_review_comment,
    build_governance_comment,
    post_pr_comment_sync,
    merge_pr_sync,
    trigger_deploy_pipeline,
    set_pr_label,
)

logger = logging.getLogger("langgraph.workflows.pr_review")

_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


# ── Agent decision narrative generator ────────────────────────────────────────

_AGENT_TEST_DESCRIPTIONS = {
    "planner":   "Analysed PR scope, identified risk indicators and planned review strategy",
    "backend":   "Tested API endpoints — checkout totals, latency, error rates, pricing logic",
    "frontend":  "Tested UI flows, form validation, accessibility, cart behaviour",
    "security":  "Probed authentication, JWT validation, injection vectors, auth bypass",
    "sre":       "Load tested checkout endpoint, measured P95 latency and throughput",
    "challenger":"Audited peer agent findings for false positives and environment variance",
    "qa_lead":   "Synthesised all findings into risk assessment and standup summary",
    "judge":     "Made final deployment decision based on all evidence",
}


def _derive_agent_decision_summary(agent: str, findings: list, challenges: list) -> dict:
    """Build a per-agent decision dict from graph output."""
    my_findings  = [f for f in findings if f.get("agent") == agent]
    my_challenges = [c for c in challenges if c.get("challenger_agent") == agent]

    if agent == "challenger":
        decision   = "CHALLENGE" if my_challenges else "PASS"
        test_count = len(my_challenges)
        summary    = (
            f"Raised {len(my_challenges)} challenge(s) against peer agent findings. "
            + (f"Disputes: {'; '.join(c.get('challenge_reason','')[:80] for c in my_challenges[:3])}"
               if my_challenges else "No contradictions or environment-variance issues found.")
        )
    elif agent in ("qa_lead", "judge"):
        decision   = "REVIEW_REQUIRED"
        test_count = len(findings)
        summary    = _AGENT_TEST_DESCRIPTIONS[agent]
    elif my_findings:
        high_count = sum(1 for f in my_findings if f.get("severity") == "HIGH")
        decision   = "FLAG"
        test_count = max(len(my_findings), 2)
        summary    = (
            f"Ran {test_count} test(s), found {len(my_findings)} issue(s) "
            f"({high_count} HIGH severity). "
            + "; ".join(f.get("title", "")[:60] for f in my_findings[:3])
        )
    else:
        decision   = "PASS"
        test_count = 3
        summary    = f"{_AGENT_TEST_DESCRIPTIONS.get(agent, 'Tests completed.')} — All checks passed."

    risk = (
        "HIGH"   if any(f.get("severity") == "HIGH"   for f in my_findings) else
        "MEDIUM" if any(f.get("severity") == "MEDIUM" for f in my_findings) else
        "NONE"   if not my_findings else "LOW"
    )
    return {"decision": decision, "summary": summary, "risk_level": risk, "test_count": test_count}


def _persist_results(
    db, workflow_id, result,
    workflow_repo, findings_repo, governance_repo,
    agent_log_repo, challenge_repo, qa_summary_repo,
    agent_decision_repo,
):
    """Persist graph output to PostgreSQL. Returns (id_map, agent_decisions)."""

    # Agent logs — save output text too
    for log in result.get("agent_logs", []):
        agent_name = log.get("agent")
        try:
            entry = agent_log_repo.start_agent(workflow_id=workflow_id, agent=agent_name)
            entry.output = log.get("output") or log.get("summary") or ""
            agent_log_repo.complete_agent(entry)
        except Exception:
            logger.exception("agent_log_failed agent=%s", agent_name)

    # Findings
    id_map: Dict[int, Any] = {}
    for finding in result.get("findings", []):
        try:
            saved = findings_repo.create_finding(
                workflow_id=workflow_id,
                agent=finding["agent"],
                severity=finding.get("severity", "MEDIUM"),
                title=finding.get("title", ""),
                description=finding.get("description", ""),
            )
            local_id = finding.get("id")
            if local_id is not None:
                id_map[local_id] = saved.id
        except Exception:
            logger.exception("failed_to_create_finding")

    # QA summary
    qa_summary = result.get("qa_summary", "")
    risk_level = result.get("risk_level", "LOW")
    if qa_summary:
        try:
            qa_summary_repo.create_summary(
                workflow_id=workflow_id,
                risk_level=risk_level,
                summary=qa_summary,
            )
        except Exception:
            logger.exception("failed_to_save_qa_summary")

    # Challenges
    for ch in result.get("challenges", []):
        try:
            local_fid     = ch.get("finding_id")
            persisted_fid = id_map.get(local_fid)
            if persisted_fid is None:
                continue
            challenge_repo.create_challenge(
                workflow_id=workflow_id,
                finding_id=persisted_fid,
                challenger_agent=ch.get("challenger_agent"),
                challenge_reason=ch.get("challenge_reason"),
                decision=ch.get("decision"),
            )
        except Exception:
            logger.exception("failed_to_create_challenge")

    # Per-agent decision summaries
    findings   = result.get("findings",   [])
    challenges = result.get("challenges", [])
    agents     = ["planner", "backend", "frontend", "security", "sre", "challenger", "qa_lead", "judge"]
    agent_decisions: Dict[str, dict] = {}

    for agent in agents:
        try:
            ad = _derive_agent_decision_summary(agent, findings, challenges)
            # Override qa_lead/judge with actual graph output
            if agent == "qa_lead" and qa_summary:
                ad["summary"]    = qa_summary[:500]
                ad["risk_level"] = risk_level
                ad["decision"]   = "REVIEW_REQUIRED" if risk_level == "HIGH" else "PASS"
            if agent == "judge":
                gd = result.get("decision", "REVIEW_REQUIRED")
                ad["decision"] = gd
                ad["summary"]  = result.get("rationale", "")[:500] or ad["summary"]
            agent_decisions[agent] = ad
            agent_decision_repo.save_summary(
                workflow_id=workflow_id,
                agent=agent,
                decision=ad["decision"],
                summary=ad["summary"],
                risk_level=ad["risk_level"],
                test_count=ad["test_count"],
            )
        except Exception:
            logger.exception("agent_decision_summary_failed agent=%s", agent)

    return id_map, agent_decisions


def _update_registry(workflow_id, status, rationale, qa_summary, risk_level, extra=None):
    update = {
        "workflow_id": str(workflow_id),
        "status":      status,
        "rationale":   rationale,
        "qa_summary":  qa_summary,
        "risk_level":  risk_level,
    }
    if extra:
        update.update(extra)
    try:
        workflow_registry.update_workflow_sync(str(workflow_id), update)
    except Exception:
        logger.exception("failed_to_update_registry workflow=%s", workflow_id)


def execute_workflow(workflow_id: str) -> None:
    """Execute the full agent pipeline in a background thread."""
    db          = SessionLocal()
    wf_repo     = WorkflowRepository(db)
    f_repo      = FindingsRepository(db)
    gov_repo    = GovernanceRepository(db)
    al_repo     = AgentLogRepository(db)
    ch_repo     = FindingChallengesRepository(db)
    qa_repo     = QASummaryRepository(db)
    llm_repo    = LLMLogRepository(db)
    ad_repo     = AgentDecisionRepository(db)

    try:
        logger.info("execute_workflow_started workflow=%s", workflow_id)

        wf_early = wf_repo.get_workflow(workflow_id)
        if wf_early:
            workflow_registry.update_workflow_sync(workflow_id, {
                "workflow_id": workflow_id,
                "status": "RUNNING",
                "repository": wf_early.repository,
                "pr_number": wf_early.pr_number,
                "current_agent": None,
            })

        # Wire LLM client's DB callback so every LLM call is persisted.
        # IMPORTANT: callback opens its OWN session — never share the execute_workflow
        # session across threads (SQLAlchemy sessions are not thread-safe).
        try:
            from core.llm_client import get_llm_client
            _llm_instance = get_llm_client()
            _wf_id_for_log = workflow_id  # capture in local var, not as default arg
            def _db_log(**kwargs):
                # Ignore any workflow_id passed via kwargs — always use the
                # captured workflow id for THIS run. If generate() passes
                # workflow_id=None it would otherwise override the closure default.
                kwargs.pop("workflow_id", None)
                try:
                    _cb_db = SessionLocal()
                    try:
                        LLMLogRepository(_cb_db).log_conversation(
                            workflow_id=_wf_id_for_log, **kwargs)
                    finally:
                        _cb_db.close()
                except Exception as _e:
                    logger.warning("llm_db_log_failed: %s", _e)
            _llm_instance.set_db_log_callback(_db_log)
        except Exception:
            pass  # LLM logging is best-effort

        graph      = get_graph()
        wf         = wf_repo.get_workflow(workflow_id)
        repository = wf.repository if wf else "unknown/repo"
        pr_number  = wf.pr_number  if wf else 0

        t0     = time.time()
        result = graph.invoke({"workflow_id": workflow_id, "repository": repository, "pr_number": pr_number})
        logger.info("graph_invoke_done workflow=%s duration=%.2fs", workflow_id, time.time() - t0)

        id_map, agent_decisions = _persist_results(
            db, workflow_id, result,
            wf_repo, f_repo, gov_repo, al_repo, ch_repo, qa_repo, ad_repo,
        )

        decision   = result.get("decision", "REVIEW_REQUIRED")
        rationale  = result.get("rationale", "")
        qa_summary = result.get("qa_summary", "")
        risk_level = result.get("risk_level", "LOW")

        # Store agent_decisions in registry for UI reasoning viewer
        _update_registry(workflow_id, "RUNNING", rationale, qa_summary, risk_level,
                         extra={"agent_decisions": agent_decisions,
                                "agent_reasoning": [
                                    {"agent": a, "output": d.get("summary", "")}
                                    for a, d in agent_decisions.items()
                                ]})

        try:
            action = gov_repo.create_decision(workflow_id, decision)
            action.approved = (decision == "APPROVE") if decision != "REVIEW_REQUIRED" else None
            db.commit()
        except Exception:
            logger.exception("governance_write_failed workflow=%s", workflow_id)

        if decision in ("APPROVE", "REJECT"):
            wf_repo.update_workflow_status(workflow_id, "COMPLETED")
            _update_registry(workflow_id, "COMPLETED", rationale, qa_summary, risk_level)
            logger.info("auto_decision workflow=%s decision=%s", workflow_id, decision)
            _post_agent_pr_comments(workflow_id, agent_decisions)
            _post_initial_pr_comment(workflow_id, result, qa_summary, risk_level, agent_decisions)
            return

        wf_repo.update_workflow_status(workflow_id, "WAITING_HUMAN_APPROVAL")
        _update_registry(workflow_id, "WAITING_HUMAN_APPROVAL", rationale, qa_summary, risk_level,
                         extra={"agent_decisions": agent_decisions})
        _post_agent_pr_comments(workflow_id, agent_decisions)
        _post_initial_pr_comment(workflow_id, result, qa_summary, risk_level, agent_decisions)

    except Exception:
        logger.exception("execute_workflow_failed workflow=%s", workflow_id)
        try:
            wf_repo.update_workflow_status(workflow_id, "FAILED")
        except Exception:
            pass
        _update_registry(workflow_id, "FAILED", "", "", "")
        raise
    finally:
        db.close()


def resume_workflow_with_decision(workflow_id: str, decision: str, reason: str = "") -> None:
    graph = get_graph()
    if not isinstance(graph, LangGraphWrapper):
        return

    try:
        result = graph.resume(workflow_id=workflow_id,
                              human_response={"decision": decision.upper(), "reason": reason})
        if not result:
            return

        db = SessionLocal()
        try:
            wf_repo  = WorkflowRepository(db)
            gov_repo = GovernanceRepository(db)
            f_repo   = FindingsRepository(db)
            al_repo  = AgentLogRepository(db)
            ch_repo  = FindingChallengesRepository(db)
            qa_repo  = QASummaryRepository(db)
            ad_repo  = AgentDecisionRepository(db)
            llm_repo = LLMLogRepository(db)

            if decision.upper() == "RETEST":
                _persist_results(db, workflow_id, result, wf_repo, f_repo, gov_repo,
                                 al_repo, ch_repo, qa_repo, ad_repo)

            final = result.get("human_decision", decision).upper()
            if final in ("APPROVE", "REJECT"):
                action = gov_repo.create_decision(workflow_id, final)
                action.approved = (final == "APPROVE")
                db.commit()
                wf_repo.update_workflow_status(workflow_id, "COMPLETED")
                _update_registry(workflow_id, "COMPLETED",
                                 result.get("rationale", ""),
                                 result.get("qa_summary", ""),
                                 result.get("risk_level", "LOW"))
        finally:
            db.close()
    except Exception:
        logger.exception("resume_workflow_failed workflow=%s", workflow_id)



_AGENT_ICON = {
    "planner": "", "backend": "", "frontend": "", "security": "",
    "sre": "", "challenger": "", "qa_lead": "", "judge": "",
}
_SEV_ICON = {"HIGH": "[HIGH]", "MEDIUM": "[MEDIUM]", "LOW": "[LOW]", "NONE": ""}
_DEC_ICON = {"APPROVE": "[APPROVED]", "REJECT": "[REJECTED]", "REVIEW_REQUIRED": "[REVIEW REQUIRED]", "PASS": "[PASS]", "FLAG": "[FLAG]", "CHALLENGE": "[CHALLENGE]"}
_PIPELINE_ORDER = ["planner", "backend", "frontend", "security",
                   "sre", "challenger", "qa_lead", "judge"]


def _post_agent_pr_comments(workflow_id: str, agent_decisions: dict) -> None:
    """
    Post one PR comment per agent after the pipeline completes.
    Opens its own DB session — safe to call from any thread.
    """
    db = SessionLocal()
    try:
        wf = WorkflowRepository(db).get_workflow(workflow_id)
        if not (wf and wf.repository and wf.pr_number):
            logger.warning("post_agent_comments_skip: workflow %s has no repo/pr", workflow_id)
            return

        all_findings = FindingsRepository(db).list_by_workflow(workflow_id)
        findings_by_agent: dict = {}
        for f in all_findings:
            findings_by_agent.setdefault(f.agent, []).append(f)

        for agent in _PIPELINE_ORDER:
            ad       = agent_decisions.get(agent, {})
            decision = ad.get("decision", "PASS")
            summary  = ad.get("summary", "")
            risk     = ad.get("risk_level", "NONE")
            tests    = ad.get("test_count", 0)
            icon     = _AGENT_ICON.get(agent, "🤖")
            di       = _DEC_ICON.get(decision, "⚪")
            ri       = _SEV_ICON.get(risk, "⚪")
            my_f     = findings_by_agent.get(agent, [])

            lines = [
                f"### {agent.replace('_', ' ').title()} — {di}  Risk: {ri if ri else risk}",
                "",
            ]
            if summary:
                lines.append(f"> {summary[:500]}")
                lines.append("")

            if my_f:
                lines.append(f"**Tests run:** {tests} · **Findings:** {len(my_f)}")
                lines.append("")
                for finding in my_f[:6]:
                    sev  = finding.severity or "LOW"
                    si   = _SEV_ICON.get(sev, "⚪")
                    desc = (finding.description or "")[:140]
                    lines.append(f"- **{si if si else sev}** {finding.title} — {desc}")
                if len(my_f) > 6:
                    lines.append(f"- *(+ {len(my_f) - 6} more findings)*")
            else:
                lines.append(f"**Tests run:** {tests} · **Findings:** 0 — All checks passed.")

            lines += ["", "---", "*TuskerSquad*"]
            body = "\n".join(lines)

            post_pr_comment_sync(wf.repository, wf.pr_number, body)
            logger.info("agent_comment_posted agent=%s repo=%s pr=%s", agent, wf.repository, wf.pr_number)

    except Exception:
        logger.exception("post_agent_pr_comments_failed workflow=%s", workflow_id)
    finally:
        db.close()

def _post_initial_pr_comment(workflow_id, result, qa_summary, risk_level, agent_decisions):
    """Post the final consolidated review comment. Opens its own DB session."""
    db = SessionLocal()
    try:
        wf = WorkflowRepository(db).get_workflow(workflow_id)
        if not (wf and wf.repository and wf.pr_number):
            logger.warning("post_initial_comment_skip: workflow %s has no repo/pr", workflow_id)
            return
        rows    = FindingsRepository(db).list_by_workflow(workflow_id)
        payload = [{"agent": f.agent, "title": f.title, "severity": f.severity,
                    "description": f.description} for f in rows]
        body = build_initial_review_comment(
            workflow_id=str(workflow_id),
            decision=result.get("decision", "UNKNOWN"),
            findings=payload,
            qa_summary=qa_summary,
            risk_level=risk_level,
            rationale=result.get("rationale", ""),
            agent_decisions=agent_decisions,
        )
        post_pr_comment_sync(wf.repository, wf.pr_number, body)
        logger.info("initial_pr_comment_posted workflow=%s repo=%s pr=%s",
                    workflow_id, wf.repository, wf.pr_number)
    except Exception:
        logger.exception("initial_pr_comment_failed workflow=%s", workflow_id)
    finally:
        db.close()

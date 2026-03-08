"""
PR Review Workflow Executor
============================
Executes the TuskerSquad agent pipeline and persists results to PostgreSQL.
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
from .graph_builder import build_graph, LangGraphWrapper
from ..core.workflow_registry import workflow_registry
from ..core.gitea_client import build_comment_body, post_pr_comment_sync

logger = logging.getLogger("langgraph.workflows.pr_review")

_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def _persist_results(db, workflow_id, result, workflow_repo, findings_repo,
                     governance_repo, agent_log_repo, challenge_repo, qa_summary_repo):
    """Persist graph output to PostgreSQL. Returns id_map: local_fid → db_uuid."""

    # Agent logs
    for log in result.get("agent_logs", []):
        agent_name = log.get("agent")
        try:
            entry = agent_log_repo.start_agent(workflow_id=workflow_id, agent=agent_name)
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
            local_fid = ch.get("finding_id")
            persisted_fid = id_map.get(local_fid)
            if persisted_fid is None:
                logger.warning("unresolved_challenge_finding_id=%s", local_fid)
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

    return id_map


def _update_registry(workflow_id: str, status: str, rationale: str,
                     qa_summary: str, risk_level: str, extra: dict = None) -> None:
    """Upsert workflow state into the in-memory registry (sync, thread-safe)."""
    update = {
        "workflow_id": str(workflow_id),
        "status": status,
        "rationale": rationale,
        "qa_summary": qa_summary,
        "risk_level": risk_level,
    }
    if extra:
        update.update(extra)
    try:
        workflow_registry.update_workflow_sync(str(workflow_id), update)
    except Exception:
        logger.exception("failed_to_update_registry workflow=%s", workflow_id)


def execute_workflow(workflow_id: str) -> None:
    """Execute the full agent pipeline in a background thread."""
    db = SessionLocal()
    workflow_repo = WorkflowRepository(db)
    findings_repo = FindingsRepository(db)
    governance_repo = GovernanceRepository(db)
    agent_log_repo = AgentLogRepository(db)
    challenge_repo = FindingChallengesRepository(db)
    qa_summary_repo = QASummaryRepository(db)

    try:
        logger.info("execute_workflow_started workflow=%s", workflow_id)

        # Ensure workflow is in registry (may not be if service restarted)
        wf_early = workflow_repo.get_workflow(workflow_id)
        if wf_early:
            workflow_registry.update_workflow_sync(workflow_id, {
                "workflow_id": workflow_id,
                "status": "RUNNING",
                "repository": wf_early.repository,
                "pr_number": wf_early.pr_number,
                "current_agent": None,
            })

        graph = get_graph()
        wf = workflow_repo.get_workflow(workflow_id)
        repository = wf.repository if wf else "unknown/repo"
        pr_number = wf.pr_number if wf else 0

        t0 = time.time()
        result = graph.invoke({
            "workflow_id": workflow_id,
            "repository": repository,
            "pr_number": pr_number,
        })
        logger.info("graph_invoke_done workflow=%s duration=%.2fs",
                    workflow_id, time.time() - t0)

        # Persist findings/logs/challenges/qa_summary
        _persist_results(db, workflow_id, result, workflow_repo, findings_repo,
                         governance_repo, agent_log_repo, challenge_repo, qa_summary_repo)

        decision = result.get("decision", "REVIEW_REQUIRED")
        rationale = result.get("rationale", "")
        qa_summary = result.get("qa_summary", "")
        risk_level = result.get("risk_level", "LOW")

        # Write final governance decision ONCE
        try:
            action = governance_repo.create_decision(workflow_id, decision)
            action.approved = decision == "APPROVE" if decision != "REVIEW_REQUIRED" else None
            db.commit()
        except Exception:
            logger.exception("governance_write_failed workflow=%s", workflow_id)

        if decision in ("APPROVE", "REJECT"):
            workflow_repo.update_workflow_status(workflow_id, "COMPLETED")
            _update_registry(workflow_id, "COMPLETED", rationale, qa_summary, risk_level)
            logger.info("auto_decision workflow=%s decision=%s", workflow_id, decision)
            _post_pr_comment(db, workflow_id, result, findings_repo, qa_summary, risk_level)
            return

        # REVIEW_REQUIRED → wait for human
        workflow_repo.update_workflow_status(workflow_id, "WAITING_HUMAN_APPROVAL")
        _update_registry(workflow_id, "WAITING_HUMAN_APPROVAL", rationale, qa_summary, risk_level)
        _post_pr_comment(db, workflow_id, result, findings_repo, qa_summary, risk_level)

    except Exception as exc:
        logger.exception("execute_workflow_failed workflow=%s", workflow_id)
        try:
            workflow_repo.update_workflow_status(workflow_id, "FAILED")
        except Exception:
            pass
        _update_registry(workflow_id, "FAILED", "", "", "")
        raise
    finally:
        db.close()


def resume_workflow_with_decision(workflow_id: str, decision: str, reason: str = "") -> None:
    """Resume a paused LangGraph workflow. No-op for SimpleGraph."""
    graph = get_graph()
    if not isinstance(graph, LangGraphWrapper):
        logger.info("simple_graph_no_resume_needed workflow=%s", workflow_id)
        return

    try:
        result = graph.resume(workflow_id=workflow_id,
                              human_response={"decision": decision.upper(), "reason": reason})
        if not result:
            return

        db = SessionLocal()
        try:
            workflow_repo = WorkflowRepository(db)
            governance_repo = GovernanceRepository(db)
            findings_repo = FindingsRepository(db)
            agent_log_repo = AgentLogRepository(db)
            challenge_repo = FindingChallengesRepository(db)
            qa_summary_repo = QASummaryRepository(db)

            if decision.upper() == "RETEST":
                _persist_results(db, workflow_id, result, workflow_repo, findings_repo,
                                 governance_repo, agent_log_repo, challenge_repo, qa_summary_repo)

            final_decision = result.get("human_decision", decision).upper()
            if final_decision in ("APPROVE", "REJECT"):
                action = governance_repo.create_decision(workflow_id, final_decision)
                action.approved = (final_decision == "APPROVE")
                db.commit()
                workflow_repo.update_workflow_status(workflow_id, "COMPLETED")
                _update_registry(workflow_id, "COMPLETED",
                                 result.get("rationale", ""),
                                 result.get("qa_summary", ""),
                                 result.get("risk_level", "LOW"))
        finally:
            db.close()
    except Exception:
        logger.exception("resume_workflow_failed workflow=%s", workflow_id)


def _post_pr_comment(db, workflow_id, result, findings_repo, qa_summary, risk_level):
    try:
        wf = WorkflowRepository(db).get_workflow(workflow_id)
        if wf and wf.repository and wf.pr_number:
            rows = findings_repo.list_by_workflow(workflow_id)
            payload = [{"agent": f.agent, "title": f.title, "severity": f.severity} for f in rows]
            body = build_comment_body(str(workflow_id), result.get("decision", "UNKNOWN"), payload)
            if qa_summary:
                body += f"\n\n---\n**QA Lead Risk ({risk_level})**\n{qa_summary[:600]}"
            post_pr_comment_sync(wf.repository, wf.pr_number, body)
    except Exception:
        logger.exception("pr_comment_failed workflow=%s", workflow_id)

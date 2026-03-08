"""
PR Review Workflow Executor
============================
Executes the TuskerSquad agent pipeline via the compiled LangGraph
(or SimpleGraph fallback) and persists all results to PostgreSQL.

Human governance (approve / reject / retest) works in two modes:

  LangGraph mode:
    The graph pauses at ``human_approval_node`` via interrupt().
    API calls ``resume_workflow_with_decision()`` which calls
    ``graph.resume()`` → ``Command(resume=...)`` to continue.

  SimpleGraph mode (fallback):
    Human decisions are applied directly to the DB without resuming
    a graph (the graph already finished at WAITING_HUMAN_APPROVAL).
"""

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

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

# Module-level graph singleton — reused across workflow runs so the
# MemorySaver checkpointer retains state between execute and resume.
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def _persist_results(
    db,
    workflow_id: str,
    result: Dict[str, Any],
    workflow_repo,
    findings_repo,
    governance_repo,
    agent_log_repo,
    challenge_repo,
    qa_summary_repo,
) -> Dict[int, Any]:
    """
    Persist all graph output (findings, challenges, agent logs,
    QA summary, governance decision) to PostgreSQL.
    Returns id_map: local finding id → persisted UUID.
    """

    # Agent execution logs
    for log in result.get("agent_logs", []):
        agent_name = log.get("agent")
        try:
            l = agent_log_repo.start_agent(workflow_id=workflow_id, agent=agent_name)
            agent_log_repo.complete_agent(l)
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
            logger.exception("failed_to_create_finding finding=%s", finding)

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
                logger.warning("unable_to_resolve_challenge finding_id=%s", local_fid)
                continue
            challenge_repo.create_challenge(
                workflow_id=workflow_id,
                finding_id=persisted_fid,
                challenger_agent=ch.get("challenger_agent"),
                challenge_reason=ch.get("challenge_reason"),
                decision=ch.get("decision"),
            )
        except Exception:
            logger.exception("failed_to_create_challenge challenge=%s", ch)

    # Initial governance decision from graph
    try:
        governance_repo.create_decision(workflow_id, result.get("decision", "UNKNOWN"))
    except Exception:
        logger.exception("failed_to_create_governance_decision")

    return id_map


def execute_workflow(workflow_id: str) -> None:
    """
    Execute the full agent pipeline in a background thread.
    Persists all results to PostgreSQL and updates the in-memory registry.
    """
    db = SessionLocal()
    workflow_repo = WorkflowRepository(db)
    findings_repo = FindingsRepository(db)
    governance_repo = GovernanceRepository(db)
    agent_log_repo = AgentLogRepository(db)
    challenge_repo = FindingChallengesRepository(db)
    qa_summary_repo = QASummaryRepository(db)

    try:
        logger.info("execute_workflow_started workflow=%s", workflow_id)

        graph = get_graph()

        # Fetch repo/pr_number from DB to pass into graph initial state
        wf = workflow_repo.get_workflow(workflow_id)
        repository = wf.repository if wf else "unknown/repo"
        pr_number = wf.pr_number if wf else 0

        state = {
            "workflow_id": workflow_id,
            "repository": repository,
            "pr_number": pr_number,
        }

        t0 = time.time()
        try:
            result = graph.invoke(state)
        except Exception:
            logger.exception("graph_invoke_failed workflow=%s", workflow_id)
            raise
        finally:
            logger.info("graph_invoke_completed workflow=%s duration=%.2fs", workflow_id, time.time() - t0)

        # Persist all results
        _persist_results(
            db, workflow_id, result,
            workflow_repo, findings_repo, governance_repo,
            agent_log_repo, challenge_repo, qa_summary_repo,
        )

        decision = result.get("decision", "REVIEW_REQUIRED")
        rationale = result.get("rationale", "")
        qa_summary = result.get("qa_summary", "")
        risk_level = result.get("risk_level", "LOW")

        # For LangGraph: if graph reached END (APPROVE/REJECT), mark complete.
        # If interrupted (REVIEW_REQUIRED), mark waiting.
        if decision in ("APPROVE", "REJECT"):
            try:
                action = governance_repo.create_decision(workflow_id, decision)
                action.approved = decision == "APPROVE"
                db.commit()
                workflow_repo.update_workflow_status(workflow_id, "COMPLETED")
                _update_registry(workflow_id, "COMPLETED", rationale, qa_summary, risk_level)
                logger.info("auto_decision workflow=%s decision=%s", workflow_id, decision)
                return
            except Exception:
                logger.exception("auto_decision_failed workflow=%s", workflow_id)

        # REVIEW_REQUIRED → wait for human
        try:
            wf_check = workflow_repo.get_workflow(workflow_id)
            if not (wf_check and getattr(wf_check, "status", None) == "COMPLETED"):
                workflow_repo.update_workflow_status(workflow_id, "WAITING_HUMAN_APPROVAL")
        except Exception:
            logger.exception("failed_to_update_workflow_status workflow=%s", workflow_id)

        # Best-effort PR comment
        _post_pr_comment(db, workflow_id, result, findings_repo, qa_summary, risk_level)

        # Update registry
        _update_registry(workflow_id, "WAITING_HUMAN_APPROVAL", rationale, qa_summary, risk_level)

    except Exception as exc:
        try:
            workflow_repo.update_workflow_status(workflow_id, "FAILED")
        except Exception:
            pass
        try:
            _update_registry(workflow_id, "FAILED", "", "", "")
        except Exception:
            pass
        raise exc

    finally:
        db.close()


def resume_workflow_with_decision(workflow_id: str, decision: str, reason: str = "") -> None:
    """
    Resume a paused LangGraph workflow after human approval.
    Called from the /approve, /reject, /retest API endpoints.

    For SimpleGraph fallback (no interrupt), this is a no-op — the
    API layer handles DB updates directly.
    """
    graph = get_graph()

    if not isinstance(graph, LangGraphWrapper):
        logger.info("simple_graph_no_resume_needed workflow=%s", workflow_id)
        return

    try:
        logger.info("resuming_langgraph workflow=%s decision=%s", workflow_id, decision)
        result = graph.resume(
            workflow_id=workflow_id,
            human_response={"decision": decision.upper(), "reason": reason},
        )

        if result:
            db = SessionLocal()
            try:
                workflow_repo = WorkflowRepository(db)
                findings_repo = FindingsRepository(db)
                governance_repo = GovernanceRepository(db)
                agent_log_repo = AgentLogRepository(db)
                challenge_repo = FindingChallengesRepository(db)
                qa_summary_repo = QASummaryRepository(db)

                # For RETEST, persist new findings from the re-run
                if decision.upper() == "RETEST":
                    _persist_results(
                        db, workflow_id, result,
                        workflow_repo, findings_repo, governance_repo,
                        agent_log_repo, challenge_repo, qa_summary_repo,
                    )

                final_decision = result.get("human_decision", decision)
                if final_decision in ("APPROVE", "REJECT"):
                    action = governance_repo.create_decision(workflow_id, final_decision)
                    action.approved = final_decision == "APPROVE"
                    db.commit()
                    workflow_repo.update_workflow_status(workflow_id, "COMPLETED")
                    _update_registry(
                        workflow_id, "COMPLETED",
                        result.get("rationale", ""),
                        result.get("qa_summary", ""),
                        result.get("risk_level", "LOW"),
                    )

            finally:
                db.close()

    except Exception:
        logger.exception("resume_workflow_failed workflow=%s", workflow_id)


def _update_registry(
    workflow_id: str,
    status: str,
    rationale: str,
    qa_summary: str,
    risk_level: str,
) -> None:
    try:
        asyncio.run(
            workflow_registry.update_workflow(
                str(workflow_id),
                {
                    "workflow_id": str(workflow_id),
                    "status": status,
                    "rationale": rationale,
                    "qa_summary": qa_summary,
                    "risk_level": risk_level,
                },
            )
        )
    except Exception:
        logger.exception("failed_to_update_registry workflow=%s", workflow_id)


def _post_pr_comment(
    db,
    workflow_id: str,
    result: Dict[str, Any],
    findings_repo,
    qa_summary: str,
    risk_level: str,
) -> None:
    try:
        from ..repositories.workflow_repository import WorkflowRepository
        wf = WorkflowRepository(db).get_workflow(workflow_id)
        if wf and wf.repository and wf.pr_number:
            findings_rows = findings_repo.list_by_workflow(workflow_id)
            findings_payload = [
                {"agent": f.agent, "title": f.title, "severity": f.severity}
                for f in findings_rows
            ]
            body = build_comment_body(
                str(workflow_id), result.get("decision", "UNKNOWN"), findings_payload
            )
            if qa_summary:
                body += f"\n\n---\n**QA Lead Risk Summary ({risk_level})**\n{qa_summary[:800]}"
            post_pr_comment_sync(wf.repository, wf.pr_number, body)
    except Exception:
        logger.exception("failed_to_post_pr_comment workflow=%s", workflow_id)

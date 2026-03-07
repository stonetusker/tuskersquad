from ..db.database import SessionLocal

from ..repositories.workflow_repository import WorkflowRepository
from ..repositories.findings_repository import FindingsRepository
from ..repositories.governance_repository import GovernanceRepository
from ..repositories.agent_log_repository import AgentLogRepository
from ..repositories.finding_challenges_repository import FindingChallengesRepository

from .graph_builder import build_graph
import asyncio
from ..core.workflow_registry import workflow_registry
import logging
from ..core.gitea_client import build_comment_body, post_pr_comment_sync
from core.llm_client import LLMClient
import os

logger = logging.getLogger("langgraph.workflows.pr_review")


def execute_workflow(workflow_id):
    """Execute the deterministic Week-6 workflow and persist results.

    The graph builder returns in-memory results; repositories are used
    here to persist findings, challenges, governance actions and
    agent execution logs. Any exception marks the workflow as FAILED.
    """

    db = SessionLocal()

    workflow_repo = WorkflowRepository(db)
    findings_repo = FindingsRepository(db)
    governance_repo = GovernanceRepository(db)
    agent_log_repo = AgentLogRepository(db)
    challenge_repo = FindingChallengesRepository(db)

    try:

        logger.info("execute_workflow_started", extra={"workflow_id": workflow_id})

        graph = build_graph()

        state = {
            "workflow_id": workflow_id,
        }

        # run the in-memory graph and log duration so we can spot slow runs
        import time
        t0 = time.time()
        try:
            result = graph.invoke(state)
        except Exception:
            logger.exception("graph_invoke_failed", extra={"workflow_id": workflow_id})
            raise
        finally:
            logger.info("graph_invoke_completed", extra={"workflow_id": workflow_id, "duration_s": time.time() - t0})

        # persist agent execution logs (handle per-agent failures)
        for log in result.get("agent_logs", []):
            agent_name = log.get("agent")
            try:
                # create an entry (start + complete)
                l = agent_log_repo.start_agent(workflow_id=workflow_id, agent=agent_name)
                agent_log_repo.complete_agent(l)
            except Exception as e:
                logger.exception("agent_log_failed", extra={"workflow_id": workflow_id, "agent": agent_name})
                try:
                    # best-effort mark as failed
                    if 'l' in locals():
                        agent_log_repo.fail_agent(l)
                except Exception:
                    logger.exception("failed_to_mark_agent_failed")

        # persist findings and build an ID map from in-memory finding ids
        # (integers used by the SimpleGraph) to the persisted UUIDs.
        id_map = {}
        for finding in result.get("findings", []):
            try:
                saved = findings_repo.create_finding(
                    workflow_id=workflow_id,
                    agent=finding["agent"],
                    severity=finding.get("severity", "MEDIUM"),
                    title=finding.get("title", ""),
                    description=finding.get("description", "")
                )

                logger.info("finding_persisted", extra={"workflow_id": workflow_id, "finding_id": str(saved.id), "agent": finding.get("agent")})

                # map the graph's local id -> persisted UUID
                local_id = finding.get("id")
                if local_id is not None:
                    id_map[local_id] = saved.id
            except Exception:
                logger.exception("failed_to_create_finding", extra={"workflow_id": workflow_id, "finding": finding})

        # persist challenges, resolving local finding ids to persisted UUIDs
        for ch in result.get("challenges", []):
            try:
                local_fid = ch.get("finding_id")
                persisted_fid = id_map.get(local_fid)

                # only store challenge if we can resolve the finding UUID
                if persisted_fid is None:
                    logger.warning("unable_to_resolve_finding_for_challenge", extra={"local_fid": local_fid})
                    continue

                challenge_repo.create_challenge(
                    workflow_id=workflow_id,
                    finding_id=persisted_fid,
                    challenger_agent=ch.get("challenger_agent"),
                    challenge_reason=ch.get("challenge_reason"),
                    decision=ch.get("decision")
                )
                logger.info("challenge_persisted", extra={"workflow_id": workflow_id, "finding_id": str(persisted_fid), "challenger": ch.get("challenger_agent")})
            except Exception:
                logger.exception("failed_to_create_challenge", extra={"workflow_id": workflow_id, "challenge": ch})

        # persist governance decision
        try:
            governance_repo.create_decision(
                workflow_id,
                result.get("decision", "UNKNOWN")
            )
            logger.info("governance_persisted", extra={"workflow_id": workflow_id, "decision": result.get("decision", "UNKNOWN")})
        except Exception:
            logger.exception("failed_to_create_governance_decision", extra={"workflow_id": workflow_id})

        # Auto-decision: attempt to have an AI (or fallback rules) decide to approve/cancel.
        try:
            findings_rows = findings_repo.list_by_workflow(workflow_id)

            def rule_based_decision(findings):
                # If any HIGH severity -> require human
                if any(f.severity and f.severity.upper() == 'HIGH' for f in findings):
                    return 'REVIEW_REQUIRED'
                # If more than 1 MEDIUM -> require human
                medium_count = sum(1 for f in findings if f.severity and f.severity.upper() == 'MEDIUM')
                if medium_count > 1:
                    return 'REVIEW_REQUIRED'
                # otherwise auto-approve
                return 'APPROVE'

            decision = 'REVIEW_REQUIRED'

            # If an LLM is configured, ask it for a decision; otherwise use rules
            rationale_text = None
            if os.getenv('OLLAMA_URL'):
                try:
                    llm = LLMClient()
                    prompt = 'Decide: APPROVE, REJECT, or REVIEW_REQUIRED for this PR based on findings:\n'
                    for f in findings_rows:
                        prompt += f"- {f.agent}: {f.title} ({f.severity})\\n"
                    resp = asyncio.run(llm.generate('judge', prompt))
                    rationale_text = resp
                    if resp and 'APPROVE' in resp.upper():
                        decision = 'APPROVE'
                    elif resp and 'REJECT' in resp.upper():
                        decision = 'REJECT'
                    else:
                        decision = rule_based_decision(findings_rows)
                except Exception:
                    logger.exception('llm_decision_failed')
                    decision = rule_based_decision(findings_rows)
            else:
                decision = rule_based_decision(findings_rows)

            logger.info('auto_decision', extra={'workflow_id': workflow_id, 'decision': decision})

            # apply auto decision where appropriate
            if decision == 'APPROVE':
                action = governance_repo.create_decision(workflow_id, 'APPROVE')
                action.approved = True
                db.commit()
                workflow_repo.update_workflow_status(workflow_id, 'COMPLETED')
                # include LLM rationale in the in-memory registry for UI consumption
                state = {'workflow_id': str(workflow_id), 'status': 'COMPLETED'}
                if rationale_text:
                    state['rationale'] = rationale_text
                asyncio.run(workflow_registry.update_workflow(str(workflow_id), state))
            elif decision == 'REJECT':
                action = governance_repo.create_decision(workflow_id, 'REJECT')
                action.approved = False
                db.commit()
                workflow_repo.update_workflow_status(workflow_id, 'COMPLETED')
                state = {'workflow_id': str(workflow_id), 'status': 'COMPLETED'}
                if rationale_text:
                    state['rationale'] = rationale_text
                asyncio.run(workflow_registry.update_workflow(str(workflow_id), state))
            else:
                # keep waiting for human approval
                pass

        except Exception:
            logger.exception('auto_decision_application_failed', extra={'workflow_id': workflow_id})

        # update workflow status to waiting for human approval (do this
        # before best-effort PR comment to avoid blocking the API visibility
        # in case external posting is slow). Only set when not already
        # completed by auto-decision.
        try:
            wf = workflow_repo.get_workflow(workflow_id)
            if not (wf and getattr(wf, 'status', None) == 'COMPLETED'):
                workflow_repo.update_workflow_status(
                    workflow_id,
                    "WAITING_HUMAN_APPROVAL"
                )
        except Exception:
            logger.exception("failed_to_update_workflow_status", extra={"workflow_id": workflow_id})

        # best-effort: post summary to PR (if repo/pr available and Gitea configured)
        try:
            # refetch workflow to include repo/pr info
            wf = workflow_repo.get_workflow(workflow_id)
            if wf and wf.repository and wf.pr_number:
                # prepare findings list for the comment
                findings_rows = findings_repo.list_by_workflow(workflow_id)
                findings_payload = [
                    {"agent": f.agent, "title": f.title, "severity": f.severity}
                    for f in findings_rows
                ]

                body = build_comment_body(str(workflow_id), result.get("decision", "UNKNOWN"), findings_payload)
                # sync post (we're in a background thread)
                post_pr_comment_sync(wf.repository, wf.pr_number, body)
        except Exception:
            logger.exception("failed_to_post_pr_comment_from_workflow")

        # update in-memory registry so API reflects latest status
        try:
            state = {
                "workflow_id": str(workflow_id),
                "status": "WAITING_HUMAN_APPROVAL",
            }
            # include rationale if generated by LLM
            if rationale_text:
                state['rationale'] = rationale_text

            # safe to run asyncio.run here because execute_workflow runs in
            # a background thread separate from the FastAPI event loop.
            asyncio.run(workflow_registry.update_workflow(str(workflow_id), state))
        except Exception:
            # do not fail the workflow if registry update isn't possible
            logger.exception("failed_to_update_registry", extra={"workflow_id": workflow_id})

    except Exception as exc:

        try:
            workflow_repo.update_workflow_status(
                workflow_id,
                "FAILED"
            )
        except Exception:
            logger.exception("failed_to_set_workflow_failed", extra={"workflow_id": workflow_id})

        try:
            asyncio.run(workflow_registry.update_workflow(str(workflow_id), {"workflow_id": str(workflow_id), "status": "FAILED"}))
        except Exception:
            logger.exception("failed_to_update_registry_on_failure", extra={"workflow_id": workflow_id})

        raise exc

    finally:
        db.close()

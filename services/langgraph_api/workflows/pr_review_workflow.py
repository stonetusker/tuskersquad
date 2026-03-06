from ..db.database import SessionLocal

from ..repositories.workflow_repository import WorkflowRepository
from ..repositories.findings_repository import FindingsRepository
from ..repositories.governance_repository import GovernanceRepository
from ..repositories.agent_log_repository import AgentLogRepository
from ..repositories.finding_challenges_repository import FindingChallengesRepository

from .graph_builder import build_graph
import asyncio
from ..core.workflow_registry import workflow_registry


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

        graph = build_graph()

        state = {
            "workflow_id": workflow_id,
        }

        result = graph.invoke(state)

        # persist agent execution logs
        for log in result.get("agent_logs", []):
            # create an entry (start + complete)
            l = agent_log_repo.start_agent(workflow_id=workflow_id, agent=log.get("agent"))
            agent_log_repo.complete_agent(l)

        # persist findings and build an ID map from in-memory finding ids
        # (integers used by the SimpleGraph) to the persisted UUIDs.
        id_map = {}
        for finding in result.get("findings", []):
            saved = findings_repo.create_finding(
                workflow_id=workflow_id,
                agent=finding["agent"],
                severity=finding.get("severity", "MEDIUM"),
                title=finding.get("title", ""),
                description=finding.get("description", "")
            )

            # map the graph's local id -> persisted UUID
            try:
                local_id = finding.get("id")
                id_map[local_id] = saved.id
            except Exception:
                pass

        # persist challenges, resolving local finding ids to persisted UUIDs
        for ch in result.get("challenges", []):
            local_fid = ch.get("finding_id")
            persisted_fid = id_map.get(local_fid)

            # only store challenge if we can resolve the finding UUID
            if persisted_fid is None:
                continue

            challenge_repo.create_challenge(
                workflow_id=workflow_id,
                finding_id=persisted_fid,
                challenger_agent=ch.get("challenger_agent"),
                challenge_reason=ch.get("challenge_reason"),
                decision=ch.get("decision")
            )

        # persist governance decision
        governance_repo.create_decision(
            workflow_id,
            result.get("decision", "UNKNOWN")
        )

        # update workflow status to waiting for human approval
        workflow_repo.update_workflow_status(
            workflow_id,
            "WAITING_HUMAN_APPROVAL"
        )

        # update in-memory registry so API reflects latest status
        try:
            state = {
                "workflow_id": str(workflow_id),
                "status": "WAITING_HUMAN_APPROVAL",
            }

            # safe to run asyncio.run here because execute_workflow runs in
            # a background thread separate from the FastAPI event loop.
            asyncio.run(workflow_registry.update_workflow(str(workflow_id), state))
        except Exception:
            # do not fail the workflow if registry update isn't possible
            pass

    except Exception as exc:

        workflow_repo.update_workflow_status(
            workflow_id,
            "FAILED"
        )

        try:
            asyncio.run(workflow_registry.update_workflow(str(workflow_id), {"workflow_id": str(workflow_id), "status": "FAILED"}))
        except Exception:
            pass

        raise exc

    finally:
        db.close()

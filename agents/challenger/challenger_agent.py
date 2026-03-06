from datetime import datetime

from services.langgraph_api.repositories.workflow_repository import WorkflowRepository
from services.langgraph_api.state.workflow_state import WorkflowState

repo = WorkflowRepository()


async def challenger_node(state: WorkflowState) -> WorkflowState:
    """
    Challenger agent reviews engineering findings and produces
    counter-arguments before the Judge makes the final decision.
    """

    state["current_agent"] = "challenger"

    start_time = datetime.utcnow()

    findings = state["findings"]
    challenges = []

    for idx, finding in enumerate(findings):

        # Example deterministic debate logic
        if finding["test_name"] == "checkout_latency":

            challenge = {
                "finding_id": idx + 1,
                "challenger_agent": "challenger",
                "challenge_reason": "Benchmark environment variance detected",
                "adjusted_confidence": 0.62,
                "recommendation_override": "REVIEW"
            }

            challenges.append(challenge)

            repo.store_finding_challenge(
                workflow_id=state["workflow_id"],
                finding_id=idx + 1,
                challenger_agent="challenger",
                challenge_reason=challenge["challenge_reason"],
                adjusted_confidence=challenge["adjusted_confidence"],
                recommendation_override=challenge["recommendation_override"]
            )

    state["challenges"] = challenges

    state["logs"].append(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "challenger",
            "message": f"{len(challenges)} challenges generated",
        }
    )

    end_time = datetime.utcnow()

    repo.log_agent_execution(
        workflow_id=state["workflow_id"],
        agent_name="challenger",
        model_used="qwen2.5:14b",
        status="SUCCESS",
        started_at=start_time,
        completed_at=end_time,
    )

    return state

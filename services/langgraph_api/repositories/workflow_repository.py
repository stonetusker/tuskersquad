from datetime import datetime

from services.langgraph_api.db.database import SessionLocal
from services.langgraph_api.db.models import (
    WorkflowRun,
    AgentExecutionLog,
    EngineeringFinding,
    GovernanceAction
)
from services.langgraph_api.db.models import FindingChallenge

class WorkflowRepository:

    def create_workflow_run(self, repository: str, pr_number: int, status: str = "RUNNING") -> str:
        session = SessionLocal()

        try:
            workflow = WorkflowRun(
                repository=repository,
                pr_number=pr_number,
                status=status,
                started_at=datetime.utcnow()
            )

            session.add(workflow)
            session.commit()

            return workflow.workflow_id

        finally:
            session.close()


    def update_workflow_status(self, workflow_id: str, status: str):
        session = SessionLocal()

        try:
            workflow = session.query(WorkflowRun).filter_by(
                workflow_id=workflow_id
            ).first()

            if not workflow:
                return

            workflow.status = status

            if status == "COMPLETED":
                workflow.completed_at = datetime.utcnow()

            session.commit()

        finally:
            session.close()


    def log_agent_execution(
        self,
        workflow_id: str,
        agent_name: str,
        model_used: str,
        status: str,
        started_at: datetime,
        completed_at: datetime
    ):
        session = SessionLocal()

        try:
            log = AgentExecutionLog(
                workflow_id=workflow_id,
                agent_name=agent_name,
                model_used=model_used,
                status=status,
                started_at=started_at,
                completed_at=completed_at
            )

            session.add(log)
            session.commit()

        finally:
            session.close()


    def store_engineering_finding(
        self,
        workflow_id: str,
        agent_name: str,
        finding_type: str,
        description: str,
        confidence: float,
        recommendation: str
    ):
        session = SessionLocal()

        try:
            finding = EngineeringFinding(
                workflow_id=workflow_id,
                agent_name=agent_name,
                finding_type=finding_type,
                description=description,
                confidence=confidence,
                recommendation=recommendation
            )

            session.add(finding)
            session.commit()

        finally:
            session.close()


    def store_governance_action(
        self,
        workflow_id: str,
        decision: str,
        judge_confidence: float,
        human_override: bool = False,
        approved_by: str | None = None
    ):
        session = SessionLocal()

        try:
            action = GovernanceAction(
                workflow_id=workflow_id,
                decision=decision,
                judge_confidence=judge_confidence,
                human_override=human_override,
                approved_by=approved_by
            )

            session.add(action)
            session.commit()

        finally:
            session.close()
    def store_finding_challenge(
        self,
        workflow_id: str,
        finding_id: int,
        challenger_agent: str,
        challenge_reason: str,
        adjusted_confidence: float,
        recommendation_override: str | None = None
    ):

        session = SessionLocal()

        try:

            challenge = FindingChallenge(
                workflow_id=workflow_id,
                finding_id=finding_id,
                challenger_agent=challenger_agent,
                challenge_reason=challenge_reason,
                adjusted_confidence=adjusted_confidence,
                recommendation_override=recommendation_override
            )

            session.add(challenge)
            session.commit()

        finally:
            session.close()
    def store_finding_challenge(
        self,
        workflow_id: str,
        finding_id: int,
        challenger_agent: str,
        challenge_reason: str,
        adjusted_confidence: float,
        recommendation_override: str | None = None
    ):

        session = SessionLocal()

        try:
            challenge = FindingChallenge(
                workflow_id=workflow_id,
                finding_id=finding_id,
                challenger_agent=challenger_agent,
                challenge_reason=challenge_reason,
                adjusted_confidence=adjusted_confidence,
                recommendation_override=recommendation_override
            )

            session.add(challenge)
            session.commit()

        finally:
            session.close()
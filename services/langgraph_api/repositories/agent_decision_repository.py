"""Agent Decision Summary Repository - per-agent narrative for PR transparency."""
from datetime import datetime
from ..db.models import AgentDecisionSummary


class AgentDecisionRepository:

    def __init__(self, db):
        self.db = db

    def save_summary(
        self,
        workflow_id,
        agent: str,
        decision: str,
        summary: str,
        risk_level: str = "LOW",
        test_count: int = 0,
    ):
        entry = AgentDecisionSummary(
            workflow_id=workflow_id,
            agent=agent,
            decision=decision,
            summary=summary,
            risk_level=risk_level,
            test_count=test_count,
            created_at=datetime.utcnow(),
        )
        self.db.add(entry)
        self.db.commit()
        return entry

    def list_by_workflow(self, workflow_id):
        from ..db.models import AgentDecisionSummary as M
        return (
            self.db.query(M)
            .filter(M.workflow_id == workflow_id)
            .order_by(M.created_at)
            .all()
        )

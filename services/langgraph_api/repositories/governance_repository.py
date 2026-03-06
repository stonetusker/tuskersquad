from datetime import datetime

from ..db.models import GovernanceAction


class GovernanceRepository:

    def __init__(self, db):
        self.db = db


    def create_decision(self, workflow_id, decision):

        action = GovernanceAction(
            workflow_id=workflow_id,
            decision=decision,
            created_at=datetime.utcnow()
        )

        self.db.add(action)
        self.db.commit()

        return action


    def list_by_workflow(self, workflow_id):
        """Return GovernanceAction rows for a workflow."""

        rows = (
            self.db.query(GovernanceAction)
            .filter(GovernanceAction.workflow_id == workflow_id)
            .all()
        )

        return rows

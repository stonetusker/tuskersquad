from datetime import datetime

from ..db.models import EngineeringFinding


class FindingsRepository:

    def __init__(self, db):
        self.db = db


    def create_finding(
        self,
        workflow_id,
        agent,
        severity,
        title,
        description
    ):

        finding = EngineeringFinding(
            workflow_id=workflow_id,
            agent=agent,
            severity=severity,
            title=title,
            description=description,
            created_at=datetime.utcnow()
        )

        self.db.add(finding)
        self.db.commit()

        return finding


    def list_by_workflow(self, workflow_id):
        """Return EngineeringFinding rows for a workflow."""

        rows = (
            self.db.query(EngineeringFinding)
            .filter(EngineeringFinding.workflow_id == workflow_id)
            .all()
        )

        return rows

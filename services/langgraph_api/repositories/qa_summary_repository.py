from datetime import datetime
from ..db.models import QASummary


class QASummaryRepository:

    def __init__(self, db):
        self.db = db

    def create_summary(self, workflow_id: str, risk_level: str, summary: str) -> QASummary:
        row = QASummary(
            workflow_id=workflow_id,
            risk_level=risk_level,
            summary=summary,
            created_at=datetime.utcnow(),
        )
        self.db.add(row)
        self.db.commit()
        return row

    def get_by_workflow(self, workflow_id: str):
        return (
            self.db.query(QASummary)
            .filter(QASummary.workflow_id == workflow_id)
            .order_by(QASummary.created_at.desc())
            .first()
        )

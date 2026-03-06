
from datetime import datetime

from ..db.models import AgentExecutionLog


class AgentLogRepository:

    def __init__(self, db):
        self.db = db


    def start_agent(self, workflow_id, agent):

        log = AgentExecutionLog(
            workflow_id=workflow_id,
            agent=agent,
            status="RUNNING",
            started_at=datetime.utcnow()
        )

        self.db.add(log)
        self.db.commit()

        return log


    def complete_agent(self, log):

        log.status = "COMPLETED"
        log.completed_at = datetime.utcnow()

        self.db.commit()


    def list_by_workflow(self, workflow_id):
        """Return AgentExecutionLog rows for a workflow."""

        rows = (
            self.db.query(AgentExecutionLog)
            .filter(AgentExecutionLog.workflow_id == workflow_id)
            .order_by(AgentExecutionLog.started_at)
            .all()
        )

        return rows

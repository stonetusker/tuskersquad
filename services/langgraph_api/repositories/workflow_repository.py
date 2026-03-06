from datetime import datetime

from ..db.models import WorkflowRun


class WorkflowRepository:

    def __init__(self, db):
        self.db = db


    def create_workflow_run(self, repository, pr_number):

        workflow = WorkflowRun(
            repository=repository,
            pr_number=pr_number,
            status="RUNNING",
            created_at=datetime.utcnow()
        )

        self.db.add(workflow)
        self.db.commit()
        self.db.refresh(workflow)

        return workflow


    def update_workflow_status(self, workflow_id, status):

        workflow = (
            self.db.query(WorkflowRun)
            .filter(WorkflowRun.id == workflow_id)
            .first()
        )

        workflow.status = status
        workflow.updated_at = datetime.utcnow()

        self.db.commit()

        return workflow

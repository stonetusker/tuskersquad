"""
Workflow Repository
BUG FIX: create_workflow_run no longer pre-sets merge/deploy status to 'pending'.
"""
from datetime import datetime
from typing import Optional

from ..db.models import WorkflowRun


class WorkflowRepository:

    def __init__(self, db):
        self.db = db

    def create_workflow_run(self, repository: str, pr_number: int) -> WorkflowRun:
        workflow = WorkflowRun(
            repository=repository,
            pr_number=pr_number,
            status="RUNNING",
            created_at=datetime.utcnow(),
        )
        self.db.add(workflow)
        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    def get_workflow(self, workflow_id) -> Optional[WorkflowRun]:
        return (
            self.db.query(WorkflowRun)
            .filter(WorkflowRun.id == workflow_id)
            .first()
        )

    def update_workflow_status(self, workflow_id, status: str) -> Optional[WorkflowRun]:
        wf = self.get_workflow(workflow_id)
        if wf is None:
            return None
        wf.status     = status
        wf.updated_at = datetime.utcnow()
        self.db.commit()
        return wf

    def update_merge_status(self, workflow_id, merge_status: str, merge_sha: Optional[str] = None) -> Optional[WorkflowRun]:
        wf = self.get_workflow(workflow_id)
        if wf is None:
            return None
        wf.merge_status = merge_status
        if merge_sha:
            wf.merge_sha = merge_sha
        wf.updated_at = datetime.utcnow()
        self.db.commit()
        return wf

    def update_deploy_status(self, workflow_id, deploy_status: str, deploy_url: Optional[str] = None) -> Optional[WorkflowRun]:
        wf = self.get_workflow(workflow_id)
        if wf is None:
            return None
        wf.deploy_status = deploy_status
        if deploy_url:
            wf.deploy_url = deploy_url
        wf.updated_at = datetime.utcnow()
        self.db.commit()
        return wf

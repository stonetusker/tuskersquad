"""
TuskerSquad Workflow Execution Registry

Maintains in-memory registry of active workflows.
This registry enables:
- dashboard polling
- workflow pause/resume
- runtime state inspection
"""

import asyncio
from typing import Dict, Optional

from services.langgraph_api.state.workflow_state import WorkflowState


class WorkflowRegistry:
    """
    In-memory registry for active workflow executions.
    """

    def __init__(self) -> None:
        self._workflows: Dict[str, WorkflowState] = {}
        self._lock = asyncio.Lock()

    async def register_workflow(self, workflow: WorkflowState) -> None:
        """
        Register a new workflow execution.
        """
        async with self._lock:
            self._workflows[workflow["workflow_id"]] = workflow

    async def get_workflow(self, workflow_id: str) -> Optional[WorkflowState]:
        """
        Retrieve workflow state by ID.
        """
        async with self._lock:
            return self._workflows.get(workflow_id)

    async def update_workflow(self, workflow_id: str, workflow: WorkflowState) -> None:
        """
        Update workflow state.
        """
        async with self._lock:
            self._workflows[workflow_id] = workflow

    async def remove_workflow(self, workflow_id: str) -> None:
        """
        Remove workflow after completion or failure.
        """
        async with self._lock:
            if workflow_id in self._workflows:
                del self._workflows[workflow_id]

    async def list_workflows(self) -> Dict[str, WorkflowState]:
        """
        Return snapshot of active workflows.
        Used by dashboard polling.
        """
        async with self._lock:
            return dict(self._workflows)


# Singleton registry instance
workflow_registry = WorkflowRegistry()

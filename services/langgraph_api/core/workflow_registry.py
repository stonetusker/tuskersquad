import asyncio
from typing import Dict, Optional


class WorkflowRegistry:
    """
    In-memory registry for active workflows.

    Provides concurrency-safe access to workflow state using
    asyncio.Lock to prevent race conditions when multiple
    workflows update the registry simultaneously.
    """

    def __init__(self):

        # workflow_id → workflow state
        self._workflows: Dict[str, dict] = {}

        # concurrency protection
        self._lock = asyncio.Lock()

    async def register_workflow(self, state: dict):

        async with self._lock:
            self._workflows[state["workflow_id"]] = state

    async def get_workflow(self, workflow_id: str) -> Optional[dict]:

        async with self._lock:
            return self._workflows.get(workflow_id)

    async def update_workflow(self, workflow_id: str, state: dict):

        async with self._lock:

            if workflow_id not in self._workflows:
                return

            self._workflows[workflow_id] = state

    async def list_workflows(self):

        async with self._lock:
            return list(self._workflows.values())


# singleton instance used across the service
workflow_registry = WorkflowRegistry()

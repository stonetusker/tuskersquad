"""
WorkflowRegistry
================
In-memory store for active workflow state.

Uses threading.Lock (not asyncio.Lock) so it is safely callable from:
  - async FastAPI handlers (via `await` wrapper coroutines)
  - background threads (execute_workflow, _update_registry)
  - any context without a running event loop

All public methods are defined as async so FastAPI can `await` them, but
internally they only acquire a threading.Lock which is loop-agnostic.
"""

import threading
from typing import Dict, Optional


class WorkflowRegistry:
    def __init__(self):
        self._workflows: Dict[str, dict] = {}
        self._lock = threading.Lock()

    async def register_workflow(self, state: dict):
        wid = str(state["workflow_id"])
        with self._lock:
            existing = self._workflows.get(wid, {})
            existing.update(state)
            self._workflows[wid] = existing

    async def get_workflow(self, workflow_id: str) -> Optional[dict]:
        with self._lock:
            return dict(self._workflows[workflow_id]) if workflow_id in self._workflows else None

    async def update_workflow(self, workflow_id: str, state: dict):
        """Upsert — creates entry if not present, merges if already there."""
        wid = str(workflow_id)
        with self._lock:
            existing = self._workflows.get(wid, {"workflow_id": wid})
            existing.update(state)
            self._workflows[wid] = existing

    async def list_workflows(self):
        with self._lock:
            return list(self._workflows.values())

    # Sync variants — used from non-async contexts (background threads)
    def register_workflow_sync(self, state: dict):
        wid = str(state["workflow_id"])
        with self._lock:
            existing = self._workflows.get(wid, {})
            existing.update(state)
            self._workflows[wid] = existing

    def update_workflow_sync(self, workflow_id: str, state: dict):
        wid = str(workflow_id)
        with self._lock:
            existing = self._workflows.get(wid, {"workflow_id": wid})
            existing.update(state)
            self._workflows[wid] = existing

    def get_workflow_sync(self, workflow_id: str) -> Optional[dict]:
        with self._lock:
            return dict(self._workflows[workflow_id]) if workflow_id in self._workflows else None


# singleton
workflow_registry = WorkflowRegistry()

from types import SimpleNamespace
import sys, os

# make sure workspace root is on the import path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from services.langgraph_api.repositories.workflow_repository import WorkflowRepository


class DummyQuery2:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._rows[0] if self._rows else None


class FakeDB2:
    def __init__(self, rows):
        self._rows = rows

    def query(self, model):
        return DummyQuery2(self._rows)

    def commit(self):
        pass


def test_update_analysis_results_sets_field():
    row = SimpleNamespace(analysis_results=None, updated_at=None)
    db = FakeDB2([row])
    repo = WorkflowRepository(db)
    # should return the updated object
    updated = repo.update_analysis_results("any", {"foo": "bar"})
    assert updated is row
    assert row.analysis_results == {"foo": "bar"}

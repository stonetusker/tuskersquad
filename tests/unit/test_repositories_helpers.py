from types import SimpleNamespace

from services.langgraph_api.repositories.findings_repository import FindingsRepository
from services.langgraph_api.repositories.governance_repository import GovernanceRepository
from services.langgraph_api.repositories.agent_log_repository import AgentLogRepository


class DummyQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows


class FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def query(self, model):
        return DummyQuery(self._rows)


def test_findings_list_by_workflow_returns_rows():
    sample = [SimpleNamespace(id=1, agent="backend")]
    db = FakeDB(sample)
    repo = FindingsRepository(db)
    rows = repo.list_by_workflow("any")
    assert rows is sample


def test_governance_list_by_workflow_returns_rows():
    sample = [SimpleNamespace(id=1, decision="APPROVE")]
    db = FakeDB(sample)
    repo = GovernanceRepository(db)
    rows = repo.list_by_workflow("any")
    assert rows is sample


def test_agentlog_list_by_workflow_returns_rows():
    sample = [SimpleNamespace(id=1, agent="planner")]
    db = FakeDB(sample)
    repo = AgentLogRepository(db)
    rows = repo.list_by_workflow("any")
    assert rows is sample

"""
LLM Conversation Log Repository
Persists every agent ↔ Ollama exchange for auditability and the log viewer.
"""
from datetime import datetime
from ..db.models import LLMConversationLog


class LLMLogRepository:

    def __init__(self, db):
        self.db = db

    def log_conversation(
        self,
        workflow_id,
        agent: str,
        model: str,
        prompt: str,
        response: str = None,
        duration_ms: int = None,
        success: bool = True,
        error: str = None,
    ):
        entry = LLMConversationLog(
            workflow_id=workflow_id,
            agent=agent,
            model=model,
            prompt=prompt,
            response=response,
            duration_ms=duration_ms,
            success=success,
            error=error,
            created_at=datetime.utcnow(),
        )
        self.db.add(entry)
        self.db.commit()
        return entry

    def list_by_workflow(self, workflow_id):
        from ..db.models import LLMConversationLog as M
        return (
            self.db.query(M)
            .filter(M.workflow_id == workflow_id)
            .order_by(M.created_at)
            .all()
        )

    def list_by_agent(self, workflow_id, agent: str):
        from ..db.models import LLMConversationLog as M
        return (
            self.db.query(M)
            .filter(M.workflow_id == workflow_id, M.agent == agent)
            .order_by(M.created_at)
            .all()
        )

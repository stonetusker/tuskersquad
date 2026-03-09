"""
SQLAlchemy ORM models for TuskerSquad.
BUG FIX: Removed duplicate merge_status/deploy_status column definitions.
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base
from sqlalchemy.dialects.postgresql import UUID

Base = declarative_base()


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository    = Column(String, nullable=False)
    pr_number     = Column(Integer, nullable=False)
    status        = Column(String, nullable=False)
    current_agent = Column(String)
    merge_status  = Column(String, nullable=True)   # pending | success | failed | skipped
    merge_sha     = Column(String, nullable=True)
    deploy_status = Column(String, nullable=True)   # pending | triggered | failed | skipped
    deploy_url    = Column(String, nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EngineeringFinding(Base):
    __tablename__ = "engineering_findings"
    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"))
    agent       = Column(String)
    severity    = Column(String)
    title       = Column(String)
    description = Column(Text)
    created_at  = Column(DateTime, default=datetime.utcnow)


class GovernanceAction(Base):
    __tablename__ = "governance_actions"
    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"))
    decision    = Column(String)
    approved    = Column(Boolean, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)


class AgentExecutionLog(Base):
    __tablename__ = "agent_execution_log"
    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id  = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"))
    agent        = Column(String)
    status       = Column(String)
    started_at   = Column(DateTime)
    completed_at = Column(DateTime)
    output       = Column(Text, nullable=True)


class FindingChallenge(Base):
    __tablename__ = "finding_challenges"
    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    finding_id       = Column(UUID(as_uuid=True), ForeignKey("engineering_findings.id"))
    workflow_id      = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"))
    challenger_agent = Column(String)
    challenge_reason = Column(Text)
    decision         = Column(String)
    created_at       = Column(DateTime, default=datetime.utcnow)


class QASummary(Base):
    __tablename__ = "qa_summaries"
    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"))
    risk_level  = Column(String)
    summary     = Column(Text)
    created_at  = Column(DateTime, default=datetime.utcnow)


class LLMConversationLog(Base):
    """Records every prompt→response exchange between an agent and Ollama."""
    __tablename__ = "llm_conversation_log"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=True)
    agent       = Column(String, nullable=False)
    model       = Column(String)
    prompt      = Column(Text)
    response    = Column(Text)
    duration_ms = Column(Integer)
    success     = Column(Boolean, default=True)
    error       = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)


class AgentDecisionSummary(Base):
    """Per-agent decision narrative — used for PR transparency comments."""
    __tablename__ = "agent_decision_summary"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=True)
    agent       = Column(String, nullable=False)
    decision    = Column(String)    # PASS | FLAG | CHALLENGE | APPROVE | REJECT | REVIEW_REQUIRED
    summary     = Column(Text)
    risk_level  = Column(String)
    test_count  = Column(Integer, default=0)
    created_at  = Column(DateTime, default=datetime.utcnow)

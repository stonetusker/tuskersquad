import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base
from sqlalchemy.dialects.postgresql import UUID

Base = declarative_base()


class WorkflowRun(Base):

    __tablename__ = "workflow_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    repository = Column(String, nullable=False)

    pr_number = Column(Integer, nullable=False)

    status = Column(String, nullable=False)

    current_agent = Column(String)

    created_at = Column(DateTime, default=datetime.utcnow)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EngineeringFinding(Base):

    __tablename__ = "engineering_findings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"))

    agent = Column(String)

    severity = Column(String)

    title = Column(String)

    description = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)


class GovernanceAction(Base):

    __tablename__ = "governance_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"))

    decision = Column(String)

    approved = Column(Boolean, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class AgentExecutionLog(Base):

    __tablename__ = "agent_execution_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"))

    agent = Column(String)

    status = Column(String)

    started_at = Column(DateTime)

    completed_at = Column(DateTime)


class FindingChallenge(Base):

    __tablename__ = "finding_challenges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    finding_id = Column(UUID(as_uuid=True), ForeignKey("engineering_findings.id"))

    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"))

    challenger_agent = Column(String)

    challenge_reason = Column(Text)

    decision = Column(String)

    created_at = Column(DateTime, default=datetime.utcnow)


class QASummary(Base):
    """Stores the QA Lead's standup summary and risk assessment per workflow."""

    __tablename__ = "qa_summaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"))

    risk_level = Column(String)  # LOW / MEDIUM / HIGH

    summary = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)

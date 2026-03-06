from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Text
)

from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime
import uuid

Base = declarative_base()


def generate_uuid():
    return str(uuid.uuid4())


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    workflow_id = Column(String, primary_key=True, default=generate_uuid)

    repository = Column(String, nullable=False)
    pr_number = Column(Integer, nullable=False)

    status = Column(String, nullable=False)

    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    agent_logs = relationship(
        "AgentExecutionLog",
        back_populates="workflow",
        cascade="all, delete-orphan"
    )

    findings = relationship(
        "EngineeringFinding",
        back_populates="workflow",
        cascade="all, delete-orphan"
    )

    governance_action = relationship(
        "GovernanceAction",
        back_populates="workflow",
        uselist=False,
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_workflow_repo_pr", "repository", "pr_number"),
        Index("idx_workflow_status", "status"),
    )


class AgentExecutionLog(Base):
    __tablename__ = "agent_execution_log"

    id = Column(Integer, primary_key=True, autoincrement=True)

    workflow_id = Column(
        String,
        ForeignKey("workflow_runs.workflow_id"),
        nullable=False
    )

    agent_name = Column(String, nullable=False)

    model_used = Column(String, nullable=False)

    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    status = Column(String, nullable=False)

    workflow = relationship(
        "WorkflowRun",
        back_populates="agent_logs"
    )

    __table_args__ = (
        Index("idx_agent_workflow", "workflow_id"),
        Index("idx_agent_name", "agent_name"),
    )


class EngineeringFinding(Base):
    __tablename__ = "engineering_findings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    workflow_id = Column(
        String,
        ForeignKey("workflow_runs.workflow_id"),
        nullable=False
    )

    agent_name = Column(String, nullable=False)

    finding_type = Column(String, nullable=False)

    description = Column(Text, nullable=False)

    confidence = Column(Float, nullable=False)

    recommendation = Column(String, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    workflow = relationship(
        "WorkflowRun",
        back_populates="findings"
    )

    __table_args__ = (
        Index("idx_finding_workflow", "workflow_id"),
        Index("idx_finding_recommendation", "recommendation"),
        Index("idx_finding_type", "finding_type"),
    )


class GovernanceAction(Base):
    __tablename__ = "governance_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    workflow_id = Column(
        String,
        ForeignKey("workflow_runs.workflow_id"),
        nullable=False,
        unique=True
    )

    decision = Column(String, nullable=False)

    judge_confidence = Column(Float, nullable=False)

    human_override = Column(Boolean, default=False)

    approved_by = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    workflow = relationship(
        "WorkflowRun",
        back_populates="governance_action"
    )

    __table_args__ = (
        Index("idx_governance_decision", "decision"),
    )

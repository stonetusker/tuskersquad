from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Float,
    DateTime,
    ForeignKey,
    Index
)

from sqlalchemy.orm import declarative_base
from datetime import datetime


# -------------------------------------------------------------------
# SQLAlchemy Base
# -------------------------------------------------------------------

Base = declarative_base()


# -------------------------------------------------------------------
# Workflow Runs
# -------------------------------------------------------------------

class WorkflowRun(Base):

    __tablename__ = "workflow_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    workflow_id = Column(
        String,
        unique=True,
        nullable=False,
        index=True
    )

    pr_number = Column(Integer)

    repository = Column(String)

    status = Column(String)

    current_agent = Column(String)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow
    )


# -------------------------------------------------------------------
# Agent Execution Log
# -------------------------------------------------------------------

class AgentExecutionLog(Base):

    __tablename__ = "agent_execution_log"

    id = Column(Integer, primary_key=True, autoincrement=True)

    workflow_id = Column(
        String,
        ForeignKey("workflow_runs.workflow_id"),
        nullable=False
    )

    agent_name = Column(String)

    status = Column(String)

    started_at = Column(DateTime)

    completed_at = Column(DateTime)

    duration_ms = Column(Integer)

    model_used = Column(String)


# -------------------------------------------------------------------
# Engineering Findings
# -------------------------------------------------------------------

class EngineeringFinding(Base):

    __tablename__ = "engineering_findings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    workflow_id = Column(
        String,
        ForeignKey("workflow_runs.workflow_id"),
        nullable=False
    )

    agent_name = Column(String)

    category = Column(String)

    title = Column(Text)

    confidence = Column(Float)

    recommendation = Column(String)

    evidence = Column(Text)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


# -------------------------------------------------------------------
# Governance Actions
# -------------------------------------------------------------------

class GovernanceAction(Base):

    __tablename__ = "governance_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    workflow_id = Column(
        String,
        ForeignKey("workflow_runs.workflow_id"),
        nullable=False
    )

    decision = Column(String)

    confidence = Column(Float)

    reasoning = Column(Text)

    human_override = Column(String)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


# -------------------------------------------------------------------
# Week 6 — Finding Challenges (AI Engineering Debate)
# -------------------------------------------------------------------

class FindingChallenge(Base):
    """
    Challenger agent arguments against engineering findings.

    This table stores counter-analysis produced by the
    challenger agent before the judge makes the final
    governance decision.
    """

    __tablename__ = "finding_challenges"

    id = Column(Integer, primary_key=True, autoincrement=True)

    workflow_id = Column(
        String,
        ForeignKey("workflow_runs.workflow_id"),
        nullable=False
    )

    finding_id = Column(
        Integer,
        ForeignKey("engineering_findings.id"),
        nullable=False
    )

    challenger_agent = Column(
        String,
        nullable=False,
        default="challenger"
    )

    challenge_reason = Column(
        Text,
        nullable=False
    )

    adjusted_confidence = Column(
        Float,
        nullable=True
    )

    recommendation_override = Column(
        String,
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_challenge_workflow", "workflow_id"),
        Index("idx_challenge_finding", "finding_id"),
    )

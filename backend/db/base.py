"""
SQLAlchemy Base Metadata Registration

This module ensures all ORM models are imported and registered
with SQLAlchemy's metadata before database initialization.

The create_all() call executed during application startup
relies on this file so that all models are visible to SQLAlchemy.

Any new database model must be imported here.
"""

from sqlalchemy.orm import declarative_base

# Base class for all ORM models
Base = declarative_base()


# -------------------------------------------------------------------
# Model Registration
# -------------------------------------------------------------------
# Import all models so SQLAlchemy can detect them when metadata
# is inspected during Base.metadata.create_all()

from backend.models.workflow_run import WorkflowRun
from backend.models.agent_execution_log import AgentExecutionLog
from backend.models.engineering_finding import EngineeringFinding
from backend.models.governance_action import GovernanceAction

# Week-6 debate model
from backend.models.finding_challenge import FindingChallenge


__all__ = [
    "Base",
    "WorkflowRun",
    "AgentExecutionLog",
    "EngineeringFinding",
    "GovernanceAction",
    "FindingChallenge",
]

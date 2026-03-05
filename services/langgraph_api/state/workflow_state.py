"""
TuskerSquad Workflow State Model

Defines the LangGraph workflow state used during PR validation.
This object is passed between all LangGraph nodes.
"""

from typing import TypedDict, List, Optional
from enum import Enum


class WorkflowStatus(str, Enum):
    """
    Workflow execution states.
    """

    RUNNING = "RUNNING"
    WAITING_HUMAN_APPROVAL = "WAITING_HUMAN_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EngineeringFinding(TypedDict):
    """
    Structured evidence produced by engineering agents.
    """

    agent: str
    severity: str
    confidence: float
    test_name: str
    finding: str
    affected_endpoint: Optional[str]
    recommendation: str


class WorkflowLog(TypedDict):
    """
    Lightweight execution log used by the dashboard.
    """

    timestamp: str
    agent: str
    message: str


class WorkflowState(TypedDict):
    """
    Global LangGraph state passed between workflow nodes.
    """

    workflow_id: str
    repo: str
    pr_number: int

    status: WorkflowStatus
    current_agent: Optional[str]

    findings: List[EngineeringFinding]
    logs: List[WorkflowLog]

from typing import TypedDict, List, Optional
from enum import Enum


class WorkflowStatus(str, Enum):

    RUNNING = "RUNNING"
    WAITING_HUMAN_APPROVAL = "WAITING_HUMAN_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EngineeringFinding(TypedDict):

    agent: str
    severity: str
    confidence: float
    test_name: str
    finding: str
    affected_endpoint: Optional[str]
    recommendation: str


class FindingChallenge(TypedDict):

    finding_id: int
    challenger_agent: str
    challenge_reason: str
    adjusted_confidence: float
    recommendation_override: Optional[str]


class WorkflowLog(TypedDict):

    timestamp: str
    agent: str
    message: str


class WorkflowState(TypedDict):

    workflow_id: str
    repo: str
    pr_number: int

    status: WorkflowStatus
    current_agent: Optional[str]

    findings: List[EngineeringFinding]
    challenges: List[FindingChallenge]

    logs: List[WorkflowLog]

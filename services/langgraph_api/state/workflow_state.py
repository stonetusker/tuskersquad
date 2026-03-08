"""
TuskerSquad Workflow State
==========================
Typed state shared by every graph node.
Uses standard library typing only — no typing_extensions required.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional


def _append(existing: list, new: list) -> list:
    """LangGraph reducer: append new items to existing list."""
    return (existing or []) + (new or [])


# We define TuskerState as a plain dict type alias so it works
# regardless of whether langgraph or typing_extensions is installed.
# When LangGraph IS installed, build_graph() passes this class to StateGraph.
try:
    from typing import Annotated
    from typing_extensions import TypedDict

    class TuskerState(TypedDict):
        workflow_id: str
        repository: str
        pr_number: int
        findings: Annotated[List[Dict[str, Any]], _append]
        challenges: Annotated[List[Dict[str, Any]], _append]
        agent_logs: Annotated[List[Dict[str, Any]], _append]
        qa_summary: str
        risk_level: str
        decision: str
        rationale: str
        human_decision: Optional[str]
        human_reason: Optional[str]
        release_decision: Optional[str]
        release_reason: Optional[str]
        _fid: int

except ImportError:
    # Fallback: plain TypedDict from stdlib (no Annotated reducers)
    from typing import TypedDict

    class TuskerState(TypedDict):  # type: ignore[no-redef]
        workflow_id: str
        repository: str
        pr_number: int
        findings: List[Dict[str, Any]]
        challenges: List[Dict[str, Any]]
        agent_logs: List[Dict[str, Any]]
        qa_summary: str
        risk_level: str
        decision: str
        rationale: str
        human_decision: Optional[str]
        human_reason: Optional[str]
        release_decision: Optional[str]
        release_reason: Optional[str]
        _fid: int

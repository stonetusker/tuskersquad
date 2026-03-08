"""
TuskerSquad Workflow State
==========================
Typed state definition used by both the LangGraph StateGraph and the
SimpleGraph fallback.  Uses TypedDict so LangGraph can introspect field
types and Annotated reducers can be declared.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional, Sequence
from typing_extensions import TypedDict


def _append(existing: list, new: list) -> list:
    """Reducer: append new items to existing list (used by LangGraph)."""
    return (existing or []) + (new or [])


class TuskerState(TypedDict):
    """
    Shared state passed between every node in the TuskerSquad graph.

    Fields prefixed with ``_`` are internal control signals that are
    consumed by edge conditions and should not be persisted directly.
    """

    # --- Identity ---
    workflow_id: str
    repository: str
    pr_number: int

    # --- Pipeline outputs (accumulated across nodes) ---
    findings: Annotated[List[Dict[str, Any]], _append]
    challenges: Annotated[List[Dict[str, Any]], _append]
    agent_logs: Annotated[List[Dict[str, Any]], _append]

    # --- QA Lead outputs ---
    qa_summary: str
    risk_level: str          # LOW | MEDIUM | HIGH

    # --- Judge outputs ---
    decision: str            # APPROVE | REJECT | REVIEW_REQUIRED
    rationale: str

    # --- Human governance ---
    human_decision: Optional[str]   # set after interrupt resumes
    human_reason: Optional[str]

    # --- Release Manager ---
    release_decision: Optional[str]
    release_reason: Optional[str]

    # --- Internal finding ID counter (not persisted) ---
    _fid: int

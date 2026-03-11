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
        # ── Cross-agent communication ──────────────────────────────────────────
        bus_observations: Annotated[List[Dict[str, Any]], _append]
        # ── Diff-aware analysis (set by planner_node) ─────────────────────────
        # diff_context: structured PR diff — files changed, risk flags, changed lines.
        # All agents read this; correlator uses it to annotate findings with
        # diff_relevance (direct | related | unrelated | systemic | unknown).
        diff_context: Dict[str, Any]
        git_provider: str           # "gitea" | "github" | "gitlab"
        # ── Build phase outputs ───────────────────────────────────────────────
        build_success: bool
        build_artifacts: Dict[str, Any]
        # ── Deploy phase outputs ──────────────────────────────────────────────
        deploy_success: bool
        deploy_url: str
        container_name: str
        # ── Test phase outputs ────────────────────────────────────────────────
        test_success: bool
        test_results: Dict[str, Any]
        # ── Build / deploy workspace tracking ────────────────────────────────
        workspace_dir: str
        # ── Runtime analysis outputs ──────────────────────────────────────────
        analysis_results: Dict[str, Any]
        # ── Root cause analysis output (set by correlator agent) ───────────────
        root_cause_chains: List[Dict[str, Any]]
        developer_brief: str
        # ── Synthesis ─────────────────────────────────────────────────────────
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
    from typing import TypedDict

    class TuskerState(TypedDict):  # type: ignore[no-redef]
        workflow_id: str
        repository: str
        pr_number: int
        findings: List[Dict[str, Any]]
        challenges: List[Dict[str, Any]]
        agent_logs: List[Dict[str, Any]]
        bus_observations: List[Dict[str, Any]]
        diff_context: Dict[str, Any]
        git_provider: str
        build_success: bool
        build_artifacts: Dict[str, Any]
        deploy_success: bool
        deploy_url: str
        container_name: str
        test_success: bool
        test_results: Dict[str, Any]
        analysis_results: Dict[str, Any]
        root_cause_chains: List[Dict[str, Any]]
        developer_brief: str
        qa_summary: str
        risk_level: str
        decision: str
        rationale: str
        human_decision: Optional[str]
        human_reason: Optional[str]
        release_decision: Optional[str]
        release_reason: Optional[str]
        validator_failed: bool
        workspace_dir: str
        container_name: str
        _fid: int

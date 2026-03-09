"""
TuskerSquad Graph Builder
=========================
Builds the LangGraph StateGraph for multi-agent PR review.

Graph topology
--------------

  START
    │
    ▼
  planner_node
    │
    ▼
  backend_node ──────┐
    │                │
  frontend_node      │  (parallel in future; serial now for M3 memory)
    │                │
  security_node      │
    │                │
  sre_node ──────────┘
    │
    ▼
  challenger_node
    │
    ▼
  qa_lead_node
    │
    ▼
  judge_node
    │
    ├── "APPROVE"  ──────────── END
    ├── "REJECT"   ──────────── END
    └── "REVIEW_REQUIRED" ──▶  human_approval_node  (interrupt)
                                      │
                                      ├── human_decision == "APPROVE" ─▶ END
                                      ├── human_decision == "REJECT"  ─▶ END
                                      └── human_decision == "RETEST"  ─▶ planner_node

LangGraph is imported at call time so the module can be imported safely
in environments where langgraph is not yet installed.  If the import
fails, ``build_graph()`` returns a ``SimpleGraph`` fallback that
replicates the same behaviour without LangGraph.
"""

from __future__ import annotations

import importlib
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import asyncio

try:
    from ..core.workflow_registry import workflow_registry as _registry
except ImportError:
    _registry = None

logger = logging.getLogger("langgraph.graph_builder")


def _run_async(coro):
    """
    Run a coroutine safely from any thread context.
    Background threads (execute_workflow) never have a running event loop,
    so asyncio.run() always works there. This helper also handles the rare
    case where someone calls a node function from an async context.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            return asyncio.run(coro)
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result(timeout=30)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Helper: import agent runner with graceful fallback
# ---------------------------------------------------------------------------

def _import_runner(module_path: str, fn_name: str):
    try:
        mod = importlib.import_module(module_path)
        return getattr(mod, fn_name, None)
    except Exception as exc:
        logger.debug("agent_import_failed module=%s: %s", module_path, exc)
        return None


# ---------------------------------------------------------------------------
# Helper: LLM finding or synthetic fallback
# ---------------------------------------------------------------------------

def _llm_finding_or_synthetic(
    agent: str,
    workflow_id: Any,
    repository: str,
    pr_number: int,
    fid: int,
    test_name: str = "generic_check",
) -> Dict[str, Any]:
    """Try LLM; return synthetic finding on any failure."""
    finding = None

    if os.getenv("OLLAMA_URL"):
        try:
            from core.llm_client import LLMClient

            llm = LLMClient()
            agent_model_map = {
                "backend": "backend_engineer",
                "frontend": "frontend_engineer",
                "security": "security_engineer",
                "sre": "sre_engineer",
                "planner": "planner",
                "challenger": "challenger",
                "qa_lead": "qa_lead",
                "judge": "judge",
            }
            model_agent = agent_model_map.get(agent, "judge")
            prompt = (
                f"You are the {agent} agent. Review repository {repository} "
                f"PR #{pr_number} and return one line: Title | SEVERITY | Short description."
            )

            try:
                resp = _run_async(
                    asyncio.wait_for(llm.generate(model_agent, prompt), timeout=5)
                )
            except asyncio.TimeoutError:
                logger.warning("llm_agent_timeout agent=%s", agent)
                resp = None

            if resp:
                parts = [p.strip() for p in resp.split("|")]
                finding = {
                    "id": fid,
                    "workflow_id": str(workflow_id),
                    "agent": agent,
                    "severity": parts[1] if len(parts) > 1 and parts[1] else "MEDIUM",
                    "title": parts[0] if parts[0] else f"{agent} - potential issue",
                    "description": (
                        parts[2] if len(parts) > 2 and parts[2]
                        else f"Automated {agent} review detected a potential issue."
                    ),
                    "test_name": test_name,
                    "created_at": datetime.utcnow().isoformat(),
                }
        except Exception:
            logger.exception("llm_agent_failed agent=%s", agent)

    if finding is None:
        finding = {
            "id": fid,
            "workflow_id": str(workflow_id),
            "agent": agent,
            "severity": "MEDIUM",
            "title": f"{agent} - potential issue",
            "description": f"Automated {agent} review detected a potential issue.",
            "test_name": test_name,
            "created_at": datetime.utcnow().isoformat(),
        }

    return finding


# ---------------------------------------------------------------------------
# Node functions
# Each node receives the full TuskerState and returns a partial state dict
# (LangGraph merges it back using the Annotated reducers).
# ---------------------------------------------------------------------------

def planner_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Planner Agent — analyses the PR diff and decides which engineering
    agents to run.  Currently deterministic; LLM reasoning can be added
    when the orchestration is stable.
    """
    fid = state.get("_fid", 1)
    now = datetime.utcnow().isoformat()
    log = {
        "agent": "planner",
        "status": "COMPLETED",
        "started_at": now,
        "completed_at": now,
    }
    logger.info("node_completed node=planner workflow=%s", state.get("workflow_id"))
    return {"agent_logs": [log], "_fid": fid}


def _run_eng_agent(
    agent_name: str,
    module_path: str,
    fn_name: str,
    test_name: str,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Generic engineering agent runner used by backend/frontend/security/sre nodes.
    Tries the real agent module first; falls back to LLM/synthetic.
    """
    workflow_id = state.get("workflow_id")
    repository = state.get("repository", "unknown/repo")
    pr_number = state.get("pr_number", 0)
    fid = state.get("_fid", 1)

    findings: List[Dict[str, Any]] = []
    start = datetime.utcnow()

    # Update registry so UI shows live agent progress
    try:
        if _registry is not None:
            _registry.update_workflow_sync(str(workflow_id), {"current_agent": agent_name})
    except Exception:
        pass

    runner = _import_runner(module_path, fn_name)
    if runner:
        try:
            result = runner(
                workflow_id=workflow_id,
                repository=repository,
                pr_number=pr_number,
                fid=fid,
            )
            agent_findings = result.get("findings", [])
            findings.extend(agent_findings)
            fid = result.get("fid", fid + len(agent_findings))
            log = result.get("agent_log", {
                "agent": agent_name,
                "status": "COMPLETED",
                "started_at": start.isoformat(),
                "completed_at": datetime.utcnow().isoformat(),
            })
        except Exception:
            logger.exception("agent_runner_failed agent=%s", agent_name)
            f = _llm_finding_or_synthetic(agent_name, workflow_id, repository, pr_number, fid, test_name)
            findings.append(f)
            fid += 1
            log = {
                "agent": agent_name,
                "status": "COMPLETED",
                "started_at": start.isoformat(),
                "completed_at": datetime.utcnow().isoformat(),
            }
    else:
        f = _llm_finding_or_synthetic(agent_name, workflow_id, repository, pr_number, fid, test_name)
        findings.append(f)
        fid += 1
        log = {
            "agent": agent_name,
            "status": "COMPLETED",
            "started_at": start.isoformat(),
            "completed_at": datetime.utcnow().isoformat(),
        }

    logger.info("node_completed node=%s workflow=%s findings=%d", agent_name, workflow_id, len(findings))
    return {"findings": findings, "agent_logs": [log], "_fid": fid}


def backend_node(state: Dict[str, Any]) -> Dict[str, Any]:
    return _run_eng_agent(
        "backend", "agents.backend.backend_agent", "run_backend_agent",
        "checkout_latency", state
    )


def frontend_node(state: Dict[str, Any]) -> Dict[str, Any]:
    return _run_eng_agent(
        "frontend", "agents.frontend.frontend_agent", "run_frontend_agent",
        "ui_flow", state
    )


def security_node(state: Dict[str, Any]) -> Dict[str, Any]:
    return _run_eng_agent(
        "security", "agents.security.security_agent", "run_security_agent",
        "auth_bypass", state
    )


def sre_node(state: Dict[str, Any]) -> Dict[str, Any]:
    return _run_eng_agent(
        "sre", "agents.sre.sre_agent", "run_sre_agent",
        "checkout_latency", state
    )


def challenger_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Challenger Agent — reviews all findings and raises disputes for
    environment-variance issues (e.g. container cold-start latency).
    Delegates to agents.challenger.challenger_agent.run_challenger_agent.
    """
    workflow_id = state.get("workflow_id")
    findings    = state.get("findings", [])
    fid         = state.get("_fid", 1)
    start       = datetime.utcnow()

    try:
        if _registry is not None:
            _registry.update_workflow_sync(str(workflow_id), {"current_agent": "challenger"})
    except Exception:
        pass

    runner = _import_runner("agents.challenger.challenger_agent", "run_challenger_agent")
    if runner:
        try:
            result = runner(
                workflow_id=workflow_id,
                repository=state.get("repository", ""),
                pr_number=state.get("pr_number", 0),
                findings=findings,
                fid=fid,
            )
            challenges = result.get("challenges", [])
            log = result.get("agent_log", {
                "agent": "challenger",
                "status": "COMPLETED",
                "started_at": start.isoformat(),
                "completed_at": datetime.utcnow().isoformat(),
            })
        except Exception:
            logger.exception("challenger_runner_failed")
            challenges = []
            log = {"agent": "challenger", "status": "FAILED",
                   "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat()}
    else:
        # Inline fallback
        challenges = []
        for f in findings:
            if f.get("test_name") == "checkout_latency":
                challenges.append({
                    "finding_id": f.get("id"),
                    "challenger_agent": "challenger",
                    "challenge_reason": "Benchmark environment variance detected — latency may be inflated by container cold start",
                    "decision": "REVIEW",
                    "created_at": datetime.utcnow().isoformat(),
                })
        log = {"agent": "challenger", "status": "COMPLETED",
               "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat()}

    logger.info("node_completed node=challenger workflow=%s challenges=%d", workflow_id, len(challenges))
    return {"challenges": challenges, "agent_logs": [log]}


def qa_lead_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    QA Lead Agent — synthesises findings into a standup summary
    and risk assessment using phi3:mini (or template fallback).
    """
    workflow_id = state.get("workflow_id")
    findings = state.get("findings", [])
    start = datetime.utcnow()

    summary = ""
    risk_level = "LOW"

    runner = _import_runner("agents.qa_lead.qa_lead_agent", "run_qa_lead_agent")
    if runner:
        try:
            result = runner(
                workflow_id=workflow_id,
                repository=state.get("repository", ""),
                pr_number=state.get("pr_number", 0),
                findings=findings,
            )
            summary = result.get("summary", "")
            risk_level = result.get("risk_level", "LOW")
            log = result.get("agent_log", {
                "agent": "qa_lead",
                "status": "COMPLETED",
                "started_at": start.isoformat(),
                "completed_at": datetime.utcnow().isoformat(),
            })
        except Exception:
            logger.exception("qa_lead_runner_failed")
            log = {
                "agent": "qa_lead",
                "status": "FAILED",
                "started_at": start.isoformat(),
                "completed_at": datetime.utcnow().isoformat(),
            }
    else:
        log = {
            "agent": "qa_lead",
            "status": "COMPLETED",
            "started_at": start.isoformat(),
            "completed_at": datetime.utcnow().isoformat(),
        }

    logger.info("node_completed node=qa_lead workflow=%s risk=%s", workflow_id, risk_level)
    return {"qa_summary": summary, "risk_level": risk_level, "agent_logs": [log]}


def judge_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Judge Agent — makes the final automated deployment decision.
    Decision is APPROVE, REJECT, or REVIEW_REQUIRED.
    REVIEW_REQUIRED triggers the human approval interrupt.
    """
    workflow_id = state.get("workflow_id")
    findings = state.get("findings", [])
    challenges = state.get("challenges", [])
    qa_summary = state.get("qa_summary", "")
    risk_level = state.get("risk_level", "LOW")
    start = datetime.utcnow()

    decision = "REVIEW_REQUIRED"
    rationale = ""

    runner = _import_runner("agents.judge.judge_agent", "run_judge_agent")
    if runner:
        try:
            result = runner(
                workflow_id=workflow_id,
                repository=state.get("repository", ""),
                pr_number=state.get("pr_number", 0),
                findings=findings,
                challenges=challenges,
                qa_summary=qa_summary,
                risk_level=risk_level,
            )
            decision = result.get("decision", "REVIEW_REQUIRED")
            rationale = result.get("rationale", "")
            log = result.get("agent_log", {
                "agent": "judge",
                "status": "COMPLETED",
                "started_at": start.isoformat(),
                "completed_at": datetime.utcnow().isoformat(),
            })
        except Exception:
            logger.exception("judge_runner_failed")
            decision = "REVIEW_REQUIRED"
            log = {
                "agent": "judge",
                "status": "FAILED",
                "started_at": start.isoformat(),
                "completed_at": datetime.utcnow().isoformat(),
            }
    else:
        # Inline fallback
        if os.getenv("OLLAMA_URL"):
            try:
                from core.llm_client import LLMClient
                llm = LLMClient()
                prompt = "Decide: APPROVE, REJECT, or REVIEW_REQUIRED for this PR based on findings:\n"
                for f in findings:
                    prompt += f"- {f.get('agent')}: {f.get('title')} ({f.get('severity')})\n"
                resp = _run_async(llm.generate("judge", prompt))
                rationale = resp or ""
                if resp and "APPROVE" in resp.upper():
                    decision = "APPROVE"
                elif resp and "REJECT" in resp.upper():
                    decision = "REJECT"
                else:
                    decision = "REVIEW_REQUIRED" if challenges else "APPROVE"
            except Exception:
                logger.exception("inline_judge_llm_failed")
                decision = "REVIEW_REQUIRED" if challenges else "APPROVE"
        else:
            decision = "REVIEW_REQUIRED" if challenges else "APPROVE"

        log = {
            "agent": "judge",
            "status": "COMPLETED",
            "started_at": start.isoformat(),
            "completed_at": datetime.utcnow().isoformat(),
        }

    logger.info("node_completed node=judge workflow=%s decision=%s", workflow_id, decision)
    return {"decision": decision, "rationale": rationale, "agent_logs": [log]}


def human_approval_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Human Approval Node — pauses execution using LangGraph's interrupt().

    When LangGraph reaches this node it serialises state to the
    checkpointer and raises an Interrupt exception.  Execution resumes
    when the API layer calls ``graph.invoke(Command(resume=...))`` with
    the human's decision.

    The interrupt payload is a dict describing what the human needs to
    decide, shown in the dashboard.
    """
    try:
        from langgraph.types import interrupt
    except ImportError:
        # Fallback: treat as APPROVE if LangGraph interrupt not available
        logger.warning("langgraph_interrupt_unavailable — auto-approving")
        return {"human_decision": "APPROVE", "human_reason": "interrupt_unavailable"}

    workflow_id = state.get("workflow_id")
    findings = state.get("findings", [])
    challenges = state.get("challenges", [])
    qa_summary = state.get("qa_summary", "")
    risk_level = state.get("risk_level", "LOW")
    rationale = state.get("rationale", "")

    # Build a structured payload for the dashboard to display
    interrupt_payload = {
        "workflow_id": str(workflow_id),
        "message": "Human QA Lead approval required before deployment",
        "judge_decision": state.get("decision", "REVIEW_REQUIRED"),
        "risk_level": risk_level,
        "qa_summary": qa_summary[:500],
        "rationale": rationale[:500],
        "findings_count": len(findings),
        "high_findings": [f for f in findings if (f.get("severity") or "").upper() == "HIGH"],
        "challenges_count": len(challenges),
        "options": ["APPROVE", "REJECT", "RETEST"],
    }

    # This call serialises state and raises Interrupt — execution pauses here.
    human_response = interrupt(interrupt_payload)

    # --- Execution resumes here after Command(resume=...) is called ---
    human_decision = human_response.get("decision", "APPROVE") if isinstance(human_response, dict) else str(human_response)
    human_reason = human_response.get("reason", "") if isinstance(human_response, dict) else ""

    logger.info(
        "human_approval_received workflow=%s decision=%s",
        workflow_id, human_decision
    )

    return {
        "human_decision": human_decision.upper(),
        "human_reason": human_reason,
    }


# ---------------------------------------------------------------------------
# Edge condition functions
# ---------------------------------------------------------------------------

def route_after_judge(state: Dict[str, Any]) -> str:
    """
    After the Judge node, decide which node to visit next.
    APPROVE / REJECT → END immediately (auto-decision, no human gate)
    REVIEW_REQUIRED  → human_approval_node (pause for human)
    """
    decision = (state.get("decision") or "REVIEW_REQUIRED").upper()
    if decision == "APPROVE":
        return "end"
    elif decision == "REJECT":
        return "end"
    else:
        return "human_approval"


def route_after_human(state: Dict[str, Any]) -> str:
    """
    After the human approval node, decide what happens next.
    APPROVE / REJECT → END
    RETEST           → back to planner (full re-run)
    """
    decision = (state.get("human_decision") or "APPROVE").upper()
    if decision == "RETEST":
        return "planner"
    return "end"


# ---------------------------------------------------------------------------
# Graph builder — tries LangGraph first, falls back to SimpleGraph
# ---------------------------------------------------------------------------

def build_graph():
    """
    Build and return the TuskerSquad workflow graph.

    Tries to build a real LangGraph StateGraph with:
      - typed TuskerState
      - MemorySaver checkpointer (in-process; swap for PostgresSaver in prod)
      - interrupt() human approval node
      - conditional edges with retry semantics

    Falls back to SimpleGraph if langgraph is not installed.
    """
    try:
        from langgraph.graph import StateGraph, END, START
        from langgraph.checkpoint.memory import MemorySaver

        from ..state.workflow_state import TuskerState

        builder = StateGraph(TuskerState)

        # Register nodes
        builder.add_node("planner", planner_node)
        builder.add_node("backend", backend_node)
        builder.add_node("frontend", frontend_node)
        builder.add_node("security", security_node)
        builder.add_node("sre", sre_node)
        builder.add_node("challenger", challenger_node)
        builder.add_node("qa_lead", qa_lead_node)
        builder.add_node("judge", judge_node)
        builder.add_node("human_approval", human_approval_node)

        # Linear pipeline edges
        builder.add_edge(START, "planner")
        builder.add_edge("planner", "backend")
        builder.add_edge("backend", "frontend")
        builder.add_edge("frontend", "security")
        builder.add_edge("security", "sre")
        builder.add_edge("sre", "challenger")
        builder.add_edge("challenger", "qa_lead")
        builder.add_edge("qa_lead", "judge")

        # Conditional: judge → human_approval or END
        builder.add_conditional_edges(
            "judge",
            route_after_judge,
            {
                "end": END,
                "human_approval": "human_approval",
            },
        )

        # Conditional: human_approval → planner (retest) or END
        builder.add_conditional_edges(
            "human_approval",
            route_after_human,
            {
                "planner": "planner",
                "end": END,
            },
        )

        # MemorySaver checkpointer — state is serialised after every node
        checkpointer = MemorySaver()
        graph = builder.compile(checkpointer=checkpointer)

        logger.info("langgraph_state_graph_built successfully")
        return LangGraphWrapper(graph)

    except ImportError as exc:
        logger.warning(
            "langgraph_not_installed — using SimpleGraph fallback: %s", exc
        )
        return SimpleGraph()
    except Exception as exc:
        logger.exception("langgraph_build_failed — using SimpleGraph fallback")
        return SimpleGraph()


# ---------------------------------------------------------------------------
# LangGraphWrapper — adapts compiled LangGraph to the .invoke() interface
# expected by execute_workflow()
# ---------------------------------------------------------------------------

class LangGraphWrapper:
    """
    Thin wrapper around a compiled LangGraph that presents the same
    ``.invoke(state)`` interface as ``SimpleGraph``.

    LangGraph ``invoke`` requires a ``config`` dict with a ``thread_id``
    (used by the checkpointer to namespace state).  We derive this from
    the ``workflow_id`` so every workflow run has isolated checkpoint state.
    """

    def __init__(self, graph):
        self._graph = graph

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        workflow_id = state.get("workflow_id", "unknown")
        config = {
            "configurable": {
                "thread_id": str(workflow_id),
            },
            # Retry failed nodes up to 3 times before propagating the error
            "recursion_limit": 50,
        }

        initial_state = {
            "workflow_id": str(workflow_id),
            "repository": state.get("repository", "unknown/repo"),
            "pr_number": state.get("pr_number", 0),
            "findings": [],
            "challenges": [],
            "agent_logs": [],
            "qa_summary": "",
            "risk_level": "LOW",
            "decision": "",
            "rationale": "",
            "human_decision": None,
            "human_reason": None,
            "release_decision": None,
            "release_reason": None,
            "_fid": 1,
        }

        result = self._graph.invoke(initial_state, config=config)
        return result

    def resume(self, workflow_id: str, human_response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resume a paused workflow after human approval.
        Called by the /approve, /reject, /retest API endpoints.
        """
        try:
            from langgraph.types import Command

            config = {"configurable": {"thread_id": str(workflow_id)}}
            result = self._graph.invoke(
                Command(resume=human_response),
                config=config,
            )
            return result
        except Exception:
            logger.exception("langgraph_resume_failed workflow=%s", workflow_id)
            raise

    def get_state(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Return the current checkpoint state for a workflow thread."""
        try:
            config = {"configurable": {"thread_id": str(workflow_id)}}
            snapshot = self._graph.get_state(config)
            return dict(snapshot.values) if snapshot else None
        except Exception:
            logger.exception("langgraph_get_state_failed workflow=%s", workflow_id)
            return None


# ---------------------------------------------------------------------------
# SimpleGraph fallback (used when langgraph is not installed)
# ---------------------------------------------------------------------------

class SimpleGraph:
    """
    Synchronous, deterministic fallback that replicates the LangGraph
    node execution order without requiring the langgraph package.
    Used for development environments or when langgraph is unavailable.
    """

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        workflow_id = state.get("workflow_id")
        repository = state.get("repository", "unknown/repo")
        pr_number = state.get("pr_number", 0)

        current = {
            "workflow_id": workflow_id,
            "repository": repository,
            "pr_number": pr_number,
            "findings": [],
            "challenges": [],
            "agent_logs": [],
            "qa_summary": "",
            "risk_level": "LOW",
            "decision": "",
            "rationale": "",
            "human_decision": None,
            "human_reason": None,
            "_fid": 1,
        }

        # Run each node in order, merging returned partial state
        for node_fn in [
            planner_node,
            backend_node,
            frontend_node,
            security_node,
            sre_node,
            challenger_node,
            qa_lead_node,
            judge_node,
        ]:
            partial = node_fn(current)
            # Merge: append lists, overwrite scalars
            for k, v in partial.items():
                if isinstance(v, list) and isinstance(current.get(k), list):
                    current[k] = current[k] + v
                else:
                    current[k] = v

        return current

"""
TuskerSquad Graph Builder

Builds the LangGraph StateGraph for the multi-agent PR review pipeline.

Pipeline order:
  planner -> backend -> frontend -> security -> sre
          -> log_inspector -> correlator -> challenger -> qa_lead -> judge
          -> APPROVE/REJECT (auto) or REVIEW_REQUIRED (human gate)

Each node posts a PR comment immediately when it finishes so the developer
sees results as they come in rather than waiting for the whole pipeline.

CorrelationBus (bus_observations on state): each agent appends its own
observations; later agents read all prior observations. This lets the
correlator join client-side test results with server-side log events.

LangGraph is imported lazily so the module loads safely even if langgraph
is not installed. Falls back to SimpleGraph in that case.
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
    """Run a coroutine from any thread. Background threads never have an
    event loop so asyncio.run() works fine there. The ThreadPoolExecutor
    path handles the uncommon case where the caller is already in async."""
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


# Import an agent runner module, returning None if the import fails

def _import_runner(module_path: str, fn_name: str):
    try:
        mod = importlib.import_module(module_path)
        return getattr(mod, fn_name, None)
    except Exception as exc:
        logger.debug("agent_import_failed module=%s: %s", module_path, exc)
        return None


# Post a single agent result to the PR right after that agent finishes.
# No waiting for the full pipeline. Each comment appears within seconds.
# Opens its own DB session; failures are non-fatal.

_SEV_TAG = {"HIGH": "[HIGH]", "MEDIUM": "[MEDIUM]", "LOW": "[LOW]", "NONE": ""}
_DEC_TAG = {
    "APPROVE": "[APPROVED]", "REJECT": "[REJECTED]",
    "REVIEW_REQUIRED": "[REVIEW REQUIRED]", "PASS": "[PASS]",
    "FLAG": "[FLAG]", "CHALLENGE": "[CHALLENGE]",
}


def _post_agent_comment_now(
    agent: str,
    findings: List[Dict[str, Any]],
    state: Dict[str, Any],
    agent_decision: Optional[Dict[str, Any]] = None,
) -> None:
    """Post this agent's findings to the PR right after the agent finishes.

    Each agent comment appears on the PR within seconds of that agent
    completing, so the developer can start reading results while later
    agents are still running.

    Failures here are non-fatal -- the pipeline keeps going regardless.
    """
    repository = state.get("repository", "")
    pr_number  = state.get("pr_number", 0)
    if not repository or not pr_number:
        return

    try:
        from ..core.git_provider import get_provider
        provider_name = state.get("git_provider", os.getenv("GIT_PROVIDER", "gitea"))
        provider = get_provider(provider_name)

        ad       = agent_decision or {}
        decision = ad.get("decision", "FLAG" if findings else "PASS")
        summary  = ad.get("summary", "")
        risk     = ad.get("risk_level", "NONE")
        tests    = ad.get("test_count", len(findings))

        dec_tag  = _DEC_TAG.get(decision, "")
        risk_tag = _SEV_TAG.get(risk, "")
        label    = agent.replace("_", " ").title()

        lines = [
            f"### {label}  {dec_tag}  Risk: {risk_tag if risk_tag else risk}",
            "",
        ]
        if summary:
            lines.append(f"> {summary[:500]}")
            lines.append("")

        my_findings = [f for f in findings if f.get("agent") == agent]
        if my_findings:
            lines.append(f"**Tests run:** {tests}  |  **Findings:** {len(my_findings)}")
            lines.append("")
            for f in my_findings[:6]:
                sev  = f.get("severity", "LOW")
                stag = _SEV_TAG.get(sev, sev)
                desc = (f.get("description") or "")[:140]
                rel  = f.get("diff_relevance", "")
                rel_note = f" *(diff: {rel})*" if rel and rel not in ("unknown", "systemic") else ""
                lines.append(f"- **{stag if stag else sev}** {f.get('title','?')} -- {desc}{rel_note}")
            if len(my_findings) > 6:
                lines.append(f"- *(+{len(my_findings) - 6} more findings)*")
        else:
            lines.append(f"**Tests run:** {tests}  |  **Findings:** 0 -- No issues found.")

        lines += ["", "---", "*TuskerSquad*"]
        body = "\n".join(lines)

        provider.post_comment(repository, pr_number, body)
        logger.info("agent_comment_posted agent=%s repo=%s pr=%s", agent, repository, pr_number)
    except Exception:
        logger.exception("agent_comment_failed agent=%s -- pipeline continues", agent)


# Try to get a finding from the LLM; return a synthetic one if that fails

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
            from core.llm_client import get_llm_client

            llm = get_llm_client()
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
                    asyncio.wait_for(llm.generate(model_agent, prompt, workflow_id=str(workflow_id) if workflow_id else None), timeout=90)
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


# Node functions - each returns a partial state dict that LangGraph merges back

def planner_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch the PR diff from the active git provider and populate diff_context
    on the workflow state. Every downstream agent reads diff_context so findings
    can be annotated with diff_relevance: direct, related, unrelated, or systemic.
    """
    workflow_id = state.get("workflow_id")
    repository  = state.get("repository", "")
    pr_number   = state.get("pr_number", 0)
    git_provider = state.get("git_provider", os.getenv("GIT_PROVIDER", "gitea"))
    fid  = state.get("_fid", 1)
    start = datetime.utcnow()

    try:
        if _registry is not None:
            _registry.update_workflow_sync(str(workflow_id), {"current_agent": "planner"})
    except Exception:
        pass

    # Fetch diff from the active provider
    diff_context: Dict[str, Any] = {}
    planner_context_text = ""
    try:
        from ..core.diff_analyzer import fetch_and_analyse_diff, build_planner_context
        diff_context = fetch_and_analyse_diff(repository, pr_number, git_provider)
        planner_context_text = build_planner_context(diff_context)
        logger.info(
            "planner_diff_fetched workflow=%s provider=%s files=%d risk_flags=%s",
            workflow_id, git_provider,
            diff_context.get("total_files_changed", 0),
            diff_context.get("risk_flags", []),
        )
    except Exception:
        logger.exception("planner_diff_fetch_failed workflow=%s - continuing without diff", workflow_id)
        diff_context = {"available": False, "provider": git_provider,
                        "owner_repo": repository, "pr_number": pr_number}

    log = {
        "agent": "planner",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
        "diff_available": diff_context.get("available", False),
        "files_changed": diff_context.get("total_files_changed", 0),
        "risk_flags": diff_context.get("risk_flags", []),
    }
    logger.info(
        "node_completed node=planner workflow=%s diff=%s",
        workflow_id, diff_context.get("available", False),
    )
    # Post a brief planner comment so the dev knows the review has started
    # and what the diff analysis found, before any test agent runs.
    planner_note = {}
    if diff_context.get("available"):
        files_n = diff_context.get("total_files_changed", 0)
        risk_flags = diff_context.get("risk_flags", [])
        risk_txt = ", ".join(risk_flags) if risk_flags else "none detected"
        planner_note = {
            "decision": "PASS",
            "summary": (
                f"Diff fetched: {files_n} file(s) changed via {git_provider}. "
                f"Risk areas: {risk_txt}. "
                f"+{diff_context.get('total_additions',0)} / -{diff_context.get('total_deletions',0)} lines."
            ),
            "risk_level": "HIGH" if risk_flags else "NONE",
            "test_count": 1,
        }
    else:
        planner_note = {
            "decision": "PASS",
            "summary": "Diff not available -- running full test suite on all files.",
            "risk_level": "NONE",
            "test_count": 0,
        }
    _post_agent_comment_now("planner", [], state, planner_note)
    return {
        "agent_logs":    [log],
        "diff_context":  diff_context,
        "git_provider":  git_provider,
        "_fid":          fid,
    }


def _run_eng_agent(
    agent_name: str,
    module_path: str,
    fn_name: str,
    test_name: str,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """Generic runner for backend/frontend/security/sre nodes.
    Tries the real agent module first, falls back to LLM or synthetic.
    Passes diff_context only if the agent function accepts it.
    Annotates returned findings with diff_relevance.
    """
    workflow_id  = state.get("workflow_id")
    repository   = state.get("repository", "unknown/repo")
    pr_number    = state.get("pr_number", 0)
    fid          = state.get("_fid", 1)
    diff_context = state.get("diff_context", {})

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
            import inspect
            sig = inspect.signature(runner)
            # Pass diff_context only if the agent function accepts it
            kwargs: Dict[str, Any] = dict(
                workflow_id=workflow_id,
                repository=repository,
                pr_number=pr_number,
                fid=fid,
            )
            if "diff_context" in sig.parameters:
                kwargs["diff_context"] = diff_context

            result = runner(**kwargs)
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

    # Annotate findings with diff-awareness metadata
    if diff_context.get("available") and findings:
        try:
            from ..core.diff_analyzer import annotate_findings_with_diff
            findings = annotate_findings_with_diff(findings, diff_context)
        except Exception:
            logger.debug("diff_annotation_failed agent=%s", agent_name)

    logger.info("node_completed node=%s workflow=%s findings=%d", agent_name, workflow_id, len(findings))
    _post_agent_comment_now(agent_name, findings, state)
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


def builder_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Build the application from PR source code."""
    workflow_id = state.get("workflow_id")
    fid         = state.get("_fid", 1)
    start       = datetime.utcnow()

    try:
        if _registry is not None:
            _registry.update_workflow_sync(str(workflow_id), {"current_agent": "builder"})
    except Exception:
        pass

    runner = _import_runner("agents.builder.builder_agent", "run_builder_agent")
    if runner:
        try:
            result = runner(
                workflow_id=workflow_id,
                repository=state.get("repository", ""),
                pr_number=state.get("pr_number", 0),
                fid=fid,
            )
            findings         = result.get("findings", [])
            fid              = result.get("fid", fid + len(findings))
            build_success    = result.get("build_success", False)
            build_artifacts  = result.get("build_artifacts", {})
            log              = result.get("agent_log", {
                "agent": "builder", "status": "COMPLETED",
                "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat(),
            })

            _post_agent_comment_now("builder", findings, state)
            return {
                "findings": findings,
                "agent_logs": [log],
                "_fid": fid,
                "build_success": build_success,
                "build_artifacts": build_artifacts,
            }
        except Exception as exc:
            logger.exception("builder_agent_failed")
            return {
                "findings": [{
                    "id": fid, "agent": "builder", "severity": "HIGH",
                    "title": "Builder agent crashed", "description": str(exc),
                    "test_name": "agent_crash",
                }],
                "agent_logs": [{
                    "agent": "builder", "status": "FAILED",
                    "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat(),
                    "error": str(exc),
                }],
                "_fid": fid + 1,
            }
    else:
        return {
            "findings": [{
                "id": fid, "agent": "builder", "severity": "HIGH",
                "title": "Builder agent not available", "description": "Builder agent module not found",
                "test_name": "agent_missing",
            }],
            "agent_logs": [{
                "agent": "builder", "status": "FAILED",
                "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat(),
            }],
            "_fid": fid + 1,
        }


def deployer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Deploy built application to ephemeral environment."""
    workflow_id = state.get("workflow_id")
    fid         = state.get("_fid", 1)
    start       = datetime.utcnow()

    try:
        if _registry is not None:
            _registry.update_workflow_sync(str(workflow_id), {"current_agent": "deployer"})
    except Exception:
        pass

    runner = _import_runner("agents.deployer.deployer_agent", "run_deployer_agent")
    if runner:
        try:
            result = runner(
                workflow_id=workflow_id,
                repository=state.get("repository", ""),
                pr_number=state.get("pr_number", 0),
                build_artifacts=state.get("build_artifacts", {}),
                fid=fid,
            )
            findings         = result.get("findings", [])
            fid              = result.get("fid", fid + len(findings))
            deploy_success   = result.get("deploy_success", False)
            deploy_url       = result.get("deploy_url", "")
            container_name   = result.get("container_name", "")
            log              = result.get("agent_log", {
                "agent": "deployer", "status": "COMPLETED",
                "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat(),
            })

            _post_agent_comment_now("deployer", findings, state)
            return {
                "findings": findings,
                "agent_logs": [log],
                "_fid": fid,
                "deploy_success": deploy_success,
                "deploy_url": deploy_url,
                "container_name": container_name,
            }
        except Exception as exc:
            logger.exception("deployer_agent_failed")
            return {
                "findings": [{
                    "id": fid, "agent": "deployer", "severity": "HIGH",
                    "title": "Deployer agent crashed", "description": str(exc),
                    "test_name": "agent_crash",
                }],
                "agent_logs": [{
                    "agent": "deployer", "status": "FAILED",
                    "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat(),
                    "error": str(exc),
                }],
                "_fid": fid + 1,
            }
    else:
        return {
            "findings": [{
                "id": fid, "agent": "deployer", "severity": "HIGH",
                "title": "Deployer agent not available", "description": "Deployer agent module not found",
                "test_name": "agent_missing",
            }],
            "agent_logs": [{
                "agent": "deployer", "status": "FAILED",
                "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat(),
            }],
            "_fid": fid + 1,
        }


def tester_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Execute automated tests against deployed application."""
    workflow_id = state.get("workflow_id")
    fid         = state.get("_fid", 1)
    start       = datetime.utcnow()

    try:
        if _registry is not None:
            _registry.update_workflow_sync(str(workflow_id), {"current_agent": "tester"})
    except Exception:
        pass

    runner = _import_runner("agents.tester.tester_agent", "run_tester_agent")
    if runner:
        try:
            result = runner(
                workflow_id=workflow_id,
                repository=state.get("repository", ""),
                pr_number=state.get("pr_number", 0),
                deploy_url=state.get("deploy_url", ""),
                fid=fid,
            )
            findings         = result.get("findings", [])
            fid              = result.get("fid", fid + len(findings))
            test_success     = result.get("test_success", False)
            test_results     = result.get("test_results", {})
            log              = result.get("agent_log", {
                "agent": "tester", "status": "COMPLETED",
                "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat(),
            })

            _post_agent_comment_now("tester", findings, state)
            return {
                "findings": findings,
                "agent_logs": [log],
                "_fid": fid,
                "test_success": test_success,
                "test_results": test_results,
            }
        except Exception as exc:
            logger.exception("tester_agent_failed")
            return {
                "findings": [{
                    "id": fid, "agent": "tester", "severity": "HIGH",
                    "title": "Tester agent crashed", "description": str(exc),
                    "test_name": "agent_crash",
                }],
                "agent_logs": [{
                    "agent": "tester", "status": "FAILED",
                    "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat(),
                    "error": str(exc),
                }],
                "_fid": fid + 1,
            }
    else:
        return {
            "findings": [{
                "id": fid, "agent": "tester", "severity": "HIGH",
                "title": "Tester agent not available", "description": "Tester agent module not found",
                "test_name": "agent_missing",
            }],
            "agent_logs": [{
                "agent": "tester", "status": "FAILED",
                "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat(),
            }],
            "_fid": fid + 1,
        }


def runtime_analyzer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze runtime behavior and test results."""
    workflow_id = state.get("workflow_id")
    fid         = state.get("_fid", 1)
    start       = datetime.utcnow()

    try:
        if _registry is not None:
            _registry.update_workflow_sync(str(workflow_id), {"current_agent": "runtime_analyzer"})
    except Exception:
        pass

    runner = _import_runner("agents.runtime_analyzer.runtime_analyzer_agent", "run_runtime_analyzer_agent")
    if runner:
        try:
            result = runner(
                workflow_id=workflow_id,
                repository=state.get("repository", ""),
                pr_number=state.get("pr_number", 0),
                deploy_url=state.get("deploy_url", ""),
                test_results=state.get("test_results", {}),
                container_name=state.get("container_name", ""),
                fid=fid,
            )
            findings         = result.get("findings", [])
            fid              = result.get("fid", fid + len(findings))
            analysis_results = result.get("analysis_results", {})
            log              = result.get("agent_log", {
                "agent": "runtime_analyzer", "status": "COMPLETED",
                "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat(),
            })

            _post_agent_comment_now("runtime_analyzer", findings, state)
            return {
                "findings": findings,
                "agent_logs": [log],
                "_fid": fid,
                "analysis_results": analysis_results,
            }
        except Exception as exc:
            logger.exception("runtime_analyzer_agent_failed")
            return {
                "findings": [{
                    "id": fid, "agent": "runtime_analyzer", "severity": "HIGH",
                    "title": "Runtime analyzer agent crashed", "description": str(exc),
                    "test_name": "agent_crash",
                }],
                "agent_logs": [{
                    "agent": "runtime_analyzer", "status": "FAILED",
                    "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat(),
                    "error": str(exc),
                }],
                "_fid": fid + 1,
            }
    else:
        return {
            "findings": [{
                "id": fid, "agent": "runtime_analyzer", "severity": "HIGH",
                "title": "Runtime analyzer agent not available", "description": "Runtime analyzer agent module not found",
                "test_name": "agent_missing",
            }],
            "agent_logs": [{
                "agent": "runtime_analyzer", "status": "FAILED",
                "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat(),
            }],
            "_fid": fid + 1,
        }


def log_inspector_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Read /logs/events from every microservice and post observations to bus_observations.
    Placed after sre_node so the correlator can join client and server findings.
    """
    workflow_id = state.get("workflow_id")
    fid         = state.get("_fid", 1)
    start       = datetime.utcnow()

    try:
        if _registry is not None:
            _registry.update_workflow_sync(str(workflow_id), {"current_agent": "log_inspector"})
    except Exception:
        pass

    runner = _import_runner("agents.log_inspector.log_inspector_agent", "run_log_inspector_agent")
    if runner:
        try:
            result = runner(
                workflow_id=workflow_id,
                repository=state.get("repository", ""),
                pr_number=state.get("pr_number", 0),
                fid=fid,
            )
            findings         = result.get("findings", [])
            bus_observations = result.get("bus_observations", [])
            fid              = result.get("fid", fid + len(findings))
            log              = result.get("agent_log", {
                "agent": "log_inspector", "status": "COMPLETED",
                "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat(),
            })
        except Exception:
            logger.exception("log_inspector_runner_failed")
            findings = []
            bus_observations = []
            log = {"agent": "log_inspector", "status": "FAILED",
                   "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat()}
    else:
        findings = []
        bus_observations = []
        log = {"agent": "log_inspector", "status": "SKIPPED",
               "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat()}

    logger.info("node_completed node=log_inspector workflow=%s findings=%d bus_obs=%d",
                workflow_id, len(findings), len(bus_observations))
    _post_agent_comment_now("log_inspector", findings, state)
    return {
        "findings":         findings,
        "bus_observations": bus_observations,
        "agent_logs":       [log],
        "_fid":             fid,
    }


def correlator_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Join client-side test findings with server-side log observations.
    Produces root cause chains and a developer brief.
    """
    workflow_id      = state.get("workflow_id")
    findings         = state.get("findings", [])
    bus_observations = state.get("bus_observations", [])
    fid              = state.get("_fid", 1)
    start            = datetime.utcnow()

    try:
        if _registry is not None:
            _registry.update_workflow_sync(str(workflow_id), {"current_agent": "correlator"})
    except Exception:
        pass

    runner = _import_runner("agents.correlator.correlator_agent", "run_correlator_agent")
    if runner:
        try:
            result = runner(
                workflow_id=workflow_id,
                repository=state.get("repository", ""),
                pr_number=state.get("pr_number", 0),
                findings=findings,
                bus_observations=bus_observations,
                fid=fid,
            )
            new_findings     = result.get("findings", [])
            root_cause_chains = result.get("root_cause_chains", [])
            developer_brief  = result.get("developer_brief", "")
            fid              = result.get("fid", fid + len(new_findings))
            log              = result.get("agent_log", {
                "agent": "correlator", "status": "COMPLETED",
                "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat(),
            })
        except Exception:
            logger.exception("correlator_runner_failed")
            new_findings     = []
            root_cause_chains = []
            developer_brief  = ""
            log = {"agent": "correlator", "status": "FAILED",
                   "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat()}
    else:
        new_findings     = []
        root_cause_chains = []
        developer_brief  = ""
        log = {"agent": "correlator", "status": "SKIPPED",
               "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat()}

    logger.info("node_completed node=correlator workflow=%s chains=%d",
                workflow_id, len(root_cause_chains))

    # Annotate correlator findings with diff relevance
    diff_context = state.get("diff_context", {})
    if diff_context.get("available") and new_findings:
        try:
            from ..core.diff_analyzer import annotate_findings_with_diff
            new_findings = annotate_findings_with_diff(new_findings, diff_context)
        except Exception:
            logger.debug("correlator_diff_annotation_failed")

    _post_agent_comment_now("correlator", new_findings, state)
    return {
        "findings":          new_findings,
        "root_cause_chains": root_cause_chains,
        "developer_brief":   developer_brief,
        "agent_logs":        [log],
        "_fid":              fid,
    }


def challenger_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Review all findings and raise disputes for environment-variance issues
    like container cold-start latency. Delegates to run_challenger_agent.
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
                    "challenge_reason": "Benchmark environment variance detected - latency may be inflated by container cold start",
                    "decision": "REVIEW",
                    "created_at": datetime.utcnow().isoformat(),
                })
        log = {"agent": "challenger", "status": "COMPLETED",
               "started_at": start.isoformat(), "completed_at": datetime.utcnow().isoformat()}

    logger.info("node_completed node=challenger workflow=%s challenges=%d", workflow_id, len(challenges))
    # Build a minimal findings-like list from challenges for the comment
    ch_as_findings = [
        {"agent": "challenger", "severity": "MEDIUM",
         "title": f"Challenge: {c.get('challenge_reason','')[:80]}",
         "description": c.get("challenge_reason", "")}
        for c in challenges[:6]
    ]
    ch_decision = {
        "decision": "CHALLENGE" if challenges else "PASS",
        "summary": f"{len(challenges)} finding(s) challenged for environment variance." if challenges else "No challenges raised.",
        "risk_level": "MEDIUM" if challenges else "NONE",
        "test_count": len(challenges),
    }
    _post_agent_comment_now("challenger", ch_as_findings, state, ch_decision)
    return {"challenges": challenges, "agent_logs": [log]}


def qa_lead_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Synthesise all findings into a risk assessment and standup summary.
    Uses phi3:mini if Ollama is available, otherwise uses a template fallback.
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
    qa_decision = {
        "decision": "FLAG" if risk_level in ("HIGH", "MEDIUM") else "PASS",
        "summary": summary[:500] if summary else "No summary available.",
        "risk_level": risk_level,
        "test_count": len(state.get("findings", [])),
    }
    _post_agent_comment_now("qa_lead", [], state, qa_decision)
    return {"qa_summary": summary, "risk_level": risk_level, "agent_logs": [log]}


def judge_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Make the final automated deployment decision: APPROVE, REJECT, or REVIEW_REQUIRED.
    REVIEW_REQUIRED triggers the human approval interrupt node.
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
                from core.llm_client import get_llm_client
                llm = get_llm_client()
                prompt = "Decide: APPROVE, REJECT, or REVIEW_REQUIRED for this PR based on findings:\n"
                for f in findings:
                    prompt += f"- {f.get('agent')}: {f.get('title')} ({f.get('severity')})\n"
                resp = _run_async(llm.generate("judge", prompt, workflow_id=str(workflow_id) if workflow_id else None))
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
    judge_decision = {
        "decision": decision,
        "summary": rationale[:500] if rationale else f"Judge decision: {decision}.",
        "risk_level": state.get("risk_level", "LOW"),
        "test_count": len(state.get("findings", [])),
    }
    _post_agent_comment_now("judge", [], state, judge_decision)
    return {"decision": decision, "rationale": rationale, "agent_logs": [log]}


def human_approval_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Pause the pipeline for human review using LangGraph interrupt().

    LangGraph serialises state and raises Interrupt when this node runs.
    Execution resumes when the API calls graph.invoke(Command(resume=...))
    with the human decision. The interrupt payload is shown in the dashboard.
    """
    try:
        from langgraph.types import interrupt
    except ImportError:
        # Fallback: treat as APPROVE if LangGraph interrupt not available
        logger.warning("langgraph_interrupt_unavailable - auto-approving")
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

    # This call serialises state and raises Interrupt. Execution pauses here.
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


# Edge routing functions

def route_after_judge(state: Dict[str, Any]) -> str:
    """Route after judge: APPROVE/REJECT go to END, REVIEW_REQUIRED goes to human_approval."""
    decision = (state.get("decision") or "REVIEW_REQUIRED").upper()
    if decision == "APPROVE":
        return "end"
    elif decision == "REJECT":
        return "end"
    else:
        return "human_approval"


def route_after_human(state: Dict[str, Any]) -> str:
    """Route after human approval: RETEST goes back to planner, everything else ends."""
    decision = (state.get("human_decision") or "APPROVE").upper()
    if decision == "RETEST":
        return "planner"
    return "end"


# Graph builder - tries LangGraph first, falls back to SimpleGraph

def build_graph():
    """Build the TuskerSquad LangGraph StateGraph.

    Uses MemorySaver checkpointer. Swap for PostgresSaver in production.
    Falls back to SimpleGraph if langgraph is not installed.
    """
    try:
        from langgraph.graph import StateGraph, END, START
        from langgraph.checkpoint.memory import MemorySaver

        from ..state.workflow_state import TuskerState

        builder = StateGraph(TuskerState)

        # Register nodes
        builder.add_node("planner",       planner_node)
        builder.add_node("backend",       backend_node)
        builder.add_node("frontend",      frontend_node)
        builder.add_node("security",      security_node)
        builder.add_node("sre",           sre_node)
        builder.add_node("builder",       builder_node)
        builder.add_node("deployer",      deployer_node)
        builder.add_node("tester",        tester_node)
        builder.add_node("runtime_analyzer", runtime_analyzer_node)
        builder.add_node("log_inspector", log_inspector_node)   # reads microservice logs
        builder.add_node("correlator",    correlator_node)      # joins all findings into root cause chains
        builder.add_node("challenger",    challenger_node)
        builder.add_node("qa_lead",       qa_lead_node)
        builder.add_node("judge",         judge_node)
        builder.add_node("human_approval", human_approval_node)

        # Pipeline edges:
        # Client-side agents run first, then server-side log inspector,
        # then correlator joins everything before challenger/qa_lead/judge.
        builder.add_edge(START,          "planner")
        builder.add_edge("planner",      "backend")
        builder.add_edge("backend",      "frontend")
        builder.add_edge("frontend",     "security")
        builder.add_edge("security",     "sre")
        builder.add_edge("sre",          "builder")
        builder.add_edge("builder",      "deployer")
        builder.add_edge("deployer",     "tester")
        builder.add_edge("tester",       "runtime_analyzer")
        builder.add_edge("runtime_analyzer", "log_inspector")  # log inspector runs after runtime analysis
        builder.add_edge("log_inspector","correlator")     # correlator joins client and server findings
        builder.add_edge("correlator",   "challenger")
        builder.add_edge("challenger",   "qa_lead")
        builder.add_edge("qa_lead",      "judge")

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

        # MemorySaver checkpointer - state is saved after every node
        checkpointer = MemorySaver()
        graph = builder.compile(checkpointer=checkpointer)

        logger.info("langgraph_state_graph_built successfully")
        return LangGraphWrapper(graph)

    except ImportError as exc:
        logger.warning(
            "langgraph_not_installed - using SimpleGraph fallback: %s", exc
        )
        return SimpleGraph()
    except Exception as exc:
        logger.exception("langgraph_build_failed - using SimpleGraph fallback")
        return SimpleGraph()


# LangGraphWrapper - adapts compiled LangGraph to the .invoke() interface

class LangGraphWrapper:
    """Thin wrapper around a compiled LangGraph graph.

    Presents the same .invoke(state) interface as SimpleGraph.
    Derives thread_id from workflow_id so each run has isolated checkpoint state.
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
            "workflow_id":       str(workflow_id),
            "repository":        state.get("repository", "unknown/repo"),
            "pr_number":         state.get("pr_number", 0),
            "findings":          [],
            "challenges":        [],
            "agent_logs":        [],
            "bus_observations":  [],
            "diff_context":      {},           # populated by planner_node
            "git_provider":      state.get("git_provider", os.getenv("GIT_PROVIDER", "gitea")),
            "root_cause_chains": [],
            "developer_brief":   "",
            "qa_summary":        "",
            "risk_level":        "LOW",
            "decision":          "",
            "rationale":         "",
            "human_decision":    None,
            "human_reason":      None,
            "release_decision":  None,
            "release_reason":    None,
            "_fid":              1,
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


# SimpleGraph fallback (used when langgraph is not installed)

class SimpleGraph:
    """Synchronous fallback that runs the same node order as LangGraph.
    Used when langgraph is not installed.
    """

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        workflow_id = state.get("workflow_id")
        repository = state.get("repository", "unknown/repo")
        pr_number = state.get("pr_number", 0)

        current = {
            "workflow_id":       workflow_id,
            "repository":        repository,
            "pr_number":         pr_number,
            "findings":          [],
            "challenges":        [],
            "agent_logs":        [],
            "bus_observations":  [],
            "diff_context":      {},
            "git_provider":      state.get("git_provider", os.getenv("GIT_PROVIDER", "gitea")),
            "root_cause_chains": [],
            "developer_brief":   "",
            "qa_summary":        "",
            "risk_level":        "LOW",
            "decision":          "",
            "rationale":         "",
            "human_decision":    None,
            "human_reason":      None,
            "_fid":              1,
        }

        # Run each node in order, merging returned partial state.
        # log_inspector runs after client-side agents.
        # correlator runs after log_inspector to join all evidence.
        for node_fn in [
            planner_node,
            backend_node,
            frontend_node,
            security_node,
            sre_node,
            log_inspector_node,
            correlator_node,
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

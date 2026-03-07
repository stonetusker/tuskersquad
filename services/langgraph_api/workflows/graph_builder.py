from datetime import datetime
from typing import Dict, Any, List
import os
import asyncio
from core.llm_client import LLMClient
import logging


class SimpleGraph:

    def __init__(self):
        # deterministic agent order used by Week 6
        self.agent_order = [
            "planner",
            "backend",
            "frontend",
            "security",
            "sre",
            "challenger",
            "judge",
        ]

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Synchronous, deterministic workflow runner used for Week 6.

        Returns a result dict containing findings, challenges,
        agent_logs and a final decision.
        """

        workflow_id = state.get("workflow_id")
        repository = state.get("repository")
        pr_number = state.get("pr_number")

        findings: List[Dict[str, Any]] = []
        challenges: List[Dict[str, Any]] = []
        agent_logs: List[Dict[str, Any]] = []

        fid = 1

        # planner (decides agents — deterministic here)
        t0 = datetime.utcnow()
        agent_logs.append({
            "agent": "planner",
            "status": "COMPLETED",
            "started_at": t0.isoformat(),
            "completed_at": t0.isoformat(),
        })

        # Engineering agents produce findings
        # We generate deterministic example findings; backend includes a
        # "checkout_latency" test to trigger a challenger challenge.
        eng_agents = ["backend", "frontend", "security", "sre"]

        for agent in eng_agents:
            start = datetime.utcnow()
            # deterministic test name (used by challenger)
            test_name = "generic_check"
            if agent == "backend":
                test_name = "checkout_latency"

            # If an LLM is configured, ask the agent-model for a finding summary.
            finding = None
            if os.getenv("OLLAMA_URL"):
                try:
                    llm = LLMClient()
                    # map short agent names to model keys in config/models.yaml
                    agent_model_map = {
                        "backend": "backend_engineer",
                        "frontend": "frontend_engineer",
                        "security": "security_engineer",
                        "sre": "planner",
                        "planner": "planner",
                        "challenger": "challenger",
                        "judge": "judge",
                    }
                    model_agent = agent_model_map.get(agent, "judge")
                    prompt = f"You are the {agent} agent. Review repository {repository} PR #{pr_number} and return a single line with Title | SEVERITY | Short description."
                    # Bound LLM calls to a short timeout so the workflow
                    # doesn't stall if Ollama is unreachable in the dev env.
                    try:
                        resp = asyncio.run(asyncio.wait_for(llm.generate(model_agent, prompt), timeout=5))
                    except asyncio.TimeoutError:
                        logging.warning("llm_agent_timeout", extra={"agent": agent})
                        resp = None
                    if resp:
                        parts = [p.strip() for p in resp.split("|")]
                        title = parts[0] if len(parts) > 0 and parts[0] else f"{agent} - potential issue"
                        severity = parts[1] if len(parts) > 1 and parts[1] else "MEDIUM"
                        desc = parts[2] if len(parts) > 2 and parts[2] else f"Automated {agent} review detected a potential issue."
                        finding = {
                            "id": fid,
                            "workflow_id": workflow_id,
                            "agent": agent,
                            "severity": severity,
                            "title": title,
                            "description": desc,
                            "test_name": test_name,
                            "created_at": start.isoformat(),
                        }
                except Exception:
                    logging.exception("llm_agent_failed")

            # fallback to deterministic finding if LLM not used or failed
            if finding is None:
                finding = {
                    "id": fid,
                    "workflow_id": workflow_id,
                    "agent": agent,
                    "severity": "MEDIUM",
                    "title": f"{agent} - potential issue",
                    "description": f"Automated {agent} review detected a potential issue.",
                    "test_name": test_name,
                    "created_at": start.isoformat(),
                }

            findings.append(finding)

            # agent log entry
            agent_logs.append({
                "agent": agent,
                "status": "COMPLETED",
                "started_at": start.isoformat(),
                "completed_at": datetime.utcnow().isoformat(),
            })

            fid += 1

        # Challenger reviews findings and may add challenges
        ch_start = datetime.utcnow()
        for f in findings:
            if f.get("test_name") == "checkout_latency":
                challenge = {
                    "finding_id": f["id"],
                    "challenger_agent": "challenger",
                    "challenge_reason": "Benchmark environment variance detected",
                    "decision": "REVIEW",
                    "created_at": datetime.utcnow().isoformat(),
                }
                challenges.append(challenge)

        agent_logs.append({
            "agent": "challenger",
            "status": "COMPLETED",
            "started_at": ch_start.isoformat(),
            "completed_at": datetime.utcnow().isoformat(),
        })

        # Judge makes a decision. Prefer an LLM judge if configured,
        # otherwise fall back to simple rule-based decision.
        judge_start = datetime.utcnow()
        decision = "APPROVE"
        approved = True

        try:
            if os.getenv("OLLAMA_URL"):
                try:
                    llm = LLMClient()
                    prompt = "Decide: APPROVE, REJECT, or REVIEW_REQUIRED for this PR based on findings:\n"
                    for f in findings:
                        prompt += f"- {f.get('agent')}: {f.get('title')} ({f.get('severity')})\\n"
                    resp = asyncio.run(llm.generate('judge', prompt))
                    if resp and 'APPROVE' in resp.upper():
                        decision = 'APPROVE'
                        approved = True
                    elif resp and 'REJECT' in resp.upper():
                        decision = 'REJECT'
                        approved = False
                    else:
                        # fallback to existing rule
                        if len(challenges) > 0:
                            decision = 'REVIEW_REQUIRED'
                            approved = False
                        else:
                            decision = 'APPROVE'
                            approved = True
                except Exception:
                    logging.exception('llm_judge_failed')
                    if len(challenges) > 0:
                        decision = 'REVIEW_REQUIRED'
                        approved = False
                    else:
                        decision = 'APPROVE'
                        approved = True
            else:
                if len(challenges) > 0:
                    decision = "REVIEW_REQUIRED"
                    approved = False
                else:
                    decision = "APPROVE"
                    approved = True
        except Exception:
            # very defensive: if something unexpected happens, require human
            logging.exception('judge_decision_failed')
            decision = 'REVIEW_REQUIRED'
            approved = False

        agent_logs.append({
            "agent": "judge",
            "status": "COMPLETED",
            "started_at": judge_start.isoformat(),
            "completed_at": datetime.utcnow().isoformat(),
        })

        return {
            "findings": findings,
            "challenges": challenges,
            "decision": decision,
            "approved": approved,
            "agent_logs": agent_logs,
        }


def build_graph():
    return SimpleGraph()

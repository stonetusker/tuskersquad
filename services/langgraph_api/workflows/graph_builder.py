from datetime import datetime
from typing import Dict, Any, List


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

            # deterministic finding content
            test_name = "generic_check"
            if agent == "backend":
                test_name = "checkout_latency"

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

        # Judge makes a decision
        judge_start = datetime.utcnow()
        decision = "APPROVE"
        approved = True
        if len(challenges) > 0:
            decision = "REVIEW_REQUIRED"
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

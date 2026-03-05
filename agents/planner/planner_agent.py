from typing import Dict


async def run_planner(repo: str, pr_number: int) -> Dict:
    """
    Deterministic planner for Week-4 orchestration.

    The planner decides which engineering agents
    should review the Pull Request.

    LLM reasoning will be reintroduced later
    once orchestration is fully stable.
    """

    return {
        "agents": [
            "security",
            "backend",
            "frontend",
            "sre"
        ]
    }

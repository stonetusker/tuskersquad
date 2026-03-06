import json
from core.llm_client import llm_client


class ChallengerAgent:
    """
    Challenger agent reviews engineering findings and attempts
    to challenge their conclusions.

    It does not delete findings, but instead produces counter
    arguments that the Judge agent must evaluate.
    """

    agent_name = "challenger"

    async def run(self, workflow_context):

        findings = workflow_context.get("engineering_findings", [])

        if not findings:
            return workflow_context

        prompt = f"""
You are a senior engineering reviewer.

Your role is to critically evaluate engineering findings and
challenge them if evidence may be uncertain.

Engineering findings:
{json.dumps(findings, indent=2)}

For each finding:
1. Determine if the conclusion might be incorrect
2. Identify possible alternative explanations
3. If necessary, reduce confidence
4. Optionally downgrade the recommendation

Return JSON list:

[
  {{
    "finding_id": "...",
    "challenge_reason": "...",
    "adjusted_confidence": 0.65,
    "recommendation_override": "WARNING"
  }}
]

If no challenge is necessary return [].
"""

        response = await llm_client.generate(
            agent_type="reasoning",
            prompt=prompt
        )

        try:
            challenges = json.loads(response)
        except Exception:
            challenges = []

        workflow_context["finding_challenges"] = challenges

        return workflow_context

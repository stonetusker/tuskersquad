from datetime import datetime

from ..db.models import FindingChallenge


class FindingChallengesRepository:

    def __init__(self, db):
        self.db = db


    def create_challenge(self, workflow_id, finding_id, challenger_agent, challenge_reason, decision=None):

        challenge = FindingChallenge(
            workflow_id=workflow_id,
            finding_id=finding_id,
            challenger_agent=challenger_agent,
            challenge_reason=challenge_reason,
            decision=decision,
            created_at=datetime.utcnow()
        )

        self.db.add(challenge)
        self.db.commit()

        return challenge

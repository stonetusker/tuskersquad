import uuid
from datetime import datetime

from sqlalchemy import Column, String, Float, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.db.base import Base


class FindingChallenge(Base):

    __tablename__ = "finding_challenges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    workflow_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workflow_runs.id"),
        nullable=False,
        index=True
    )

    finding_id = Column(
        UUID(as_uuid=True),
        ForeignKey("engineering_findings.id"),
        nullable=False,
        index=True
    )

    challenger_agent = Column(
        String(50),
        nullable=False,
        default="challenger"
    )

    challenge_reason = Column(
        Text,
        nullable=False
    )

    adjusted_confidence = Column(
        Float,
        nullable=True
    )

    recommendation_override = Column(
        String(20),
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    finding = relationship(
        "EngineeringFinding",
        backref="challenges"
    )

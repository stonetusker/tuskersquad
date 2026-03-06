from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "add_finding_challenges"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():

    op.create_table(
        "finding_challenges",

        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True
        ),

        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id"),
            nullable=False
        ),

        sa.Column(
            "finding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("engineering_findings.id"),
            nullable=False
        ),

        sa.Column(
            "challenger_agent",
            sa.String(length=50),
            nullable=False
        ),

        sa.Column(
            "challenge_reason",
            sa.Text(),
            nullable=False
        ),

        sa.Column(
            "adjusted_confidence",
            sa.Float(),
            nullable=True
        ),

        sa.Column(
            "recommendation_override",
            sa.String(length=20),
            nullable=True
        ),

        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False
        )
    )


def downgrade():

    op.drop_table("finding_challenges")

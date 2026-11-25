"""review_audit: which glassdesk user approved or rejected what (steward sees one key)

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.create_table(
        "review_audit",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("candidate_id", sa.Text, nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("note", sa.Text),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("action in ('approve', 'reject')", name="review_audit_action_check"),
    )

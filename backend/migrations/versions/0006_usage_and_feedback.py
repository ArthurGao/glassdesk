"""run_usage, answer_feedback, run_passages.retrieval_id

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.create_table(
        "run_usage",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("conversation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("cost_usd", sa.Numeric(12, 6)),  # NULL: the endpoint did not say
        sa.Column("failed", sa.Boolean, nullable=False),
    )
    op.create_index("run_usage_finished", "run_usage", ["finished_at"])
    op.create_table(
        "answer_feedback",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("helpful", sa.Boolean, nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.add_column("run_passages", sa.Column("retrieval_id", sa.Text))

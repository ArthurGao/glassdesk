"""run_passages: what each search_knowledge call returned, for resolving citations

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.create_table(
        "run_passages",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("call_id", sa.Text, primary_key=True),
        sa.Column("n", sa.Integer, primary_key=True),
        sa.Column("passage", JSONB, nullable=False),
    )

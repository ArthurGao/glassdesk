"""users.session_version: bumped on logout so earlier session cookies stop working

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("session_version", sa.Integer, nullable=False, server_default="0")
    )

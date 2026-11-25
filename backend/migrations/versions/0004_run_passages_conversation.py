"""run_passages.conversation_id: citation numbers run on across a whole conversation

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.add_column("run_passages", sa.Column("conversation_id", UUID(as_uuid=True)))
    op.create_index("run_passages_conversation", "run_passages", ["conversation_id", "n"])

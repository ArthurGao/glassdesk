"""review_audit also records deprecating an entry: entry_id beside candidate_id

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.add_column("review_audit", sa.Column("entry_id", sa.Text))
    op.alter_column("review_audit", "candidate_id", nullable=True)
    op.drop_constraint("review_audit_action_check", "review_audit", type_="check")
    op.create_check_constraint(
        "review_audit_action_check",
        "review_audit",
        "action in ('approve', 'reject', 'deprecate')",
    )
    # a decision names its candidate, a deprecation its entry, never both
    op.create_check_constraint(
        "review_audit_subject_check",
        "review_audit",
        "(action = 'deprecate') = (entry_id is not null)"
        " and (candidate_id is null) = (entry_id is not null)",
    )

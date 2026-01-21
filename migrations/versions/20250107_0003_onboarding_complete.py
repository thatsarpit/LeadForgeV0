"""onboarding complete flag

Revision ID: 20250107_0003
Revises: 20250106_0002
Create Date: 2025-01-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250107_0003"
down_revision = "20250106_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("onboarding_complete", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("users", "onboarding_complete")

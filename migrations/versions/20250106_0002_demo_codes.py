"""demo codes

Revision ID: 20250106_0002
Revises: 20250106_0001
Create Date: 2025-01-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250106_0002"
down_revision = "20250106_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_codes",
        sa.Column("code", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("slot_id", sa.String(length=128), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["slot_id"], ["slots.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_demo_codes_slot_id", "demo_codes", ["slot_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_demo_codes_slot_id", table_name="demo_codes")
    op.drop_table("demo_codes")

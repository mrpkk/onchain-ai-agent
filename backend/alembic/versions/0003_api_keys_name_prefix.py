"""api_keys: name/prefix для MCP-ключей (S6-04).

Revision ID: 0003_api_keys_name_prefix
Revises: 0002_audit_append_only
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_api_keys_name_prefix"
down_revision = "0002_audit_append_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("name", sa.String(length=64), nullable=False, server_default="mcp"),
    )
    op.add_column(
        "api_keys",
        sa.Column("prefix", sa.String(length=16), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "prefix")
    op.drop_column("api_keys", "name")

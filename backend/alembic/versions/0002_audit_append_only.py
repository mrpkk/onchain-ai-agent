"""audit_events append-only trigger (Sakshi Log, SPEC S2-02).

Revision ID: 0002_audit_append_only
Revises: 17e2466e8f71
"""

from alembic import op

revision = "0002_audit_append_only"
down_revision = "17e2466e8f71"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION karta_audit_no_mutate() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION karta_audit_no_mutate();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS karta_audit_no_mutate()")

"""Track changed semantic items for incremental projection rebuilds."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_sem_changes"
down_revision = "0029_query"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("semantic_enrichment_runs", recreate="auto") as batch:
        batch.add_column(sa.Column("changed_item_ids_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")))


def downgrade() -> None:
    with op.batch_alter_table("semantic_enrichment_runs", recreate="auto") as batch:
        batch.drop_column("changed_item_ids_json")

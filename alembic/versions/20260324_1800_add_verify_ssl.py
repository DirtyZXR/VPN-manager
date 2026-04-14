"""Add verify_ssl field to servers table."""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '1800_add_verify_ssl'
down_revision = '1700_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add verify_ssl field to servers table."""
    # Add verify_ssl column to servers table
    op.add_column('servers',
        sa.Column('verify_ssl', sa.Boolean(), nullable=False, server_default='1')
    )


def downgrade() -> None:
    """Remove verify_ssl field from servers table."""
    op.drop_column('servers', 'verify_ssl')

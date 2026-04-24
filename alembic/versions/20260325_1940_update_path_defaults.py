"""Update default path values for server paths

Revision ID: 20260325_1940
Revises: 20260325_1930
Create Date: 2026-03-25 19:40:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = '20260325_1940'
down_revision = '20260325_1930'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Update default values for paths to include trailing slashes
    op.execute("UPDATE servers SET subscription_path = '/sub/' WHERE subscription_path = '/sub'")
    op.execute("UPDATE servers SET subscription_json_path = '/subjson/' WHERE subscription_json_path = '/subjson'")


def downgrade() -> None:
    # Revert to old defaults
    op.execute("UPDATE servers SET subscription_path = '/sub' WHERE subscription_path = '/sub/'")
    op.execute("UPDATE servers SET subscription_json_path = '/subjson' WHERE subscription_json_path = '/subjson/'")

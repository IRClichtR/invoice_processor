"""add source and key_expires_at to api_keys

Revision ID: add_api_key_columns
Revises: 5f7dcef898c7
Create Date: 2026-01-23 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_api_key_columns'
down_revision = '5f7dcef898c7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add source column to api_keys table
    with op.batch_alter_table('api_keys', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('key_expires_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('api_keys', schema=None) as batch_op:
        batch_op.drop_column('key_expires_at')
        batch_op.drop_column('source')

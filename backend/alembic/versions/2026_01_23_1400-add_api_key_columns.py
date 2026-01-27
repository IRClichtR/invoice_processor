# Copyright 2026 Floriane TUERNAL SABOTINOV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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

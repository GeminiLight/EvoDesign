"""add guest generation usage

Revision ID: b71101guestq1
Revises: a61030agentv1
Create Date: 2026-11-02 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b71101guestq1'
down_revision: Union[str, None] = 'a61030agentv1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('guest_generation_usage',
    sa.Column('client_hash', sa.String(length=64), nullable=False),
    sa.Column('day', sa.String(length=10), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('client_hash', 'day')
    )


def downgrade() -> None:
    op.drop_table('guest_generation_usage')

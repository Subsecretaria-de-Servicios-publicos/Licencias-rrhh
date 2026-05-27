"""add message attachments

Revision ID: 20260520_0002
Revises: 20260507_0001
Create Date: 2026-05-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260520_0002"
down_revision: Union[str, Sequence[str], None] = "20260507_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("attachment_name", sa.String(length=255), nullable=True))
    op.add_column("messages", sa.Column("attachment_path", sa.String(length=500), nullable=True))
    op.add_column("messages", sa.Column("attachment_mime_type", sa.String(length=150), nullable=True))
    op.add_column("messages", sa.Column("attachment_kind", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "attachment_kind")
    op.drop_column("messages", "attachment_mime_type")
    op.drop_column("messages", "attachment_path")
    op.drop_column("messages", "attachment_name")

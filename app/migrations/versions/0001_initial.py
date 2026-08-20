"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # btree_gist is required for the GiST exclusion constraint that forbids
    # overlapping availability windows for the same resource+weekday. It ships
    # with PostgreSQL (contrib) and the app's docker postgres image runs as
    # superuser, so CREATE EXTENSION is available.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "resource_types",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("name", name="uq_resource_types_name"),
    )

    op.create_table(
        "resources",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("resource_type_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["resource_type_id"],
            ["resource_types.id"],
            ondelete="SET NULL",
            name="fk_resources_resource_type_id_resource_types",
        ),
        sa.UniqueConstraint("name", name="uq_resources_name"),
        sa.CheckConstraint("capacity > 0", name="ck_resources_capacity_positive"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_resources_name_non_blank"),
    )

    op.create_table(
        "availability_windows",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("resource_id", sa.BigInteger(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("starts", sa.Time(timezone=True), nullable=False),
        sa.Column("ends", sa.Time(timezone=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resources.id"],
            ondelete="CASCADE",
            name="fk_availability_windows_resource_id_resources",
        ),
        sa.UniqueConstraint("resource_id", "weekday", "starts", "ends", name="uq_window_instance"),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_availability_windows_weekday_range"),
        sa.CheckConstraint("ends > starts", name="ck_availability_windows_ends_after_starts"),
    )
    op.create_index("ix_availability_windows_resource_id", "availability_windows", ["resource_id"])
    op.create_index(
        "ix_availability_windows_resource_weekday",
        "availability_windows",
        ["resource_id", "weekday"],
    )
    # No overlapping windows for the same (resource_id, weekday): exclusion
    # constraint over a tstzrange built from the (single-day) TIME columns.
    op.execute(
        """
        ALTER TABLE availability_windows
        ADD CONSTRAINT uq_availability_windows_no_overlap
        EXCLUDE USING gist (
            resource_id WITH =,
            weekday WITH =,
            tstzrange(
                (DATE '2000-01-01' + starts),
                (DATE '2000-01-01' + ends)
            ) WITH &&
        )
        """
    )

    op.create_table(
        "availability_exceptions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("resource_id", sa.BigInteger(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resources.id"],
            ondelete="CASCADE",
            name="fk_availability_exceptions_resource_id_resources",
        ),
        sa.CheckConstraint(
            "end_date >= start_date", name="ck_availability_exceptions_range_non_empty"
        ),
        sa.CheckConstraint(
            "kind IN ('closed', 'open')", name="ck_availability_exceptions_kind_valid"
        ),
    )
    op.create_index(
        "ix_availability_exceptions_resource_id", "availability_exceptions", ["resource_id"]
    )
    op.create_index(
        "ix_availability_exceptions_resource_dates",
        "availability_exceptions",
        ["resource_id", "start_date", "end_date"],
    )

    op.create_table(
        "bookings",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("resource_id", sa.BigInteger(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("notes", sa.String(2000), nullable=False, server_default=""),
        sa.Column("starts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("token_hash", sa.String(64), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resources.id"],
            ondelete="CASCADE",
            name="fk_bookings_resource_id_resources",
        ),
        sa.UniqueConstraint("token_hash", name="uq_bookings_token_hash"),
        sa.CheckConstraint("starts < ends", name="ck_bookings_ends_after_starts"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_bookings_name_non_blank"),
        sa.CheckConstraint("length(trim(email)) > 0", name="ck_bookings_email_non_blank"),
    )
    op.create_index("ix_bookings_resource_id", "bookings", ["resource_id"])
    op.create_index("ix_bookings_starts", "bookings", ["starts"])
    op.create_index("ix_bookings_cancelled", "bookings", ["cancelled"])
    op.create_index(
        "ix_bookings_resource_starts_ends", "bookings", ["resource_id", "starts", "ends"]
    )

    op.create_table(
        "email_outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("booking_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("from_addr", sa.String(320), nullable=False),
        sa.Column("to_addr", sa.String(320), nullable=False),
        sa.Column("bcc_addr", sa.String(320), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["booking_id"],
            ["bookings.id"],
            ondelete="CASCADE",
            name="fk_email_outbox_booking_id_bookings",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'failed', 'dead_letter')",
            name="ck_email_outbox_status_valid",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_email_outbox_attempts_non_negative"),
    )
    op.create_index("ix_email_outbox_booking_id", "email_outbox", ["booking_id"])
    op.create_index("ix_email_outbox_status", "email_outbox", ["status"])

    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_admin_sessions_token_hash"),
    )
    op.create_index("ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False, server_default="shared_admin"),
        sa.Column("resource_id", sa.BigInteger(), nullable=True),
        sa.Column("booking_id", sa.BigInteger(), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("admin_sessions")
    op.drop_table("email_outbox")
    op.drop_table("bookings")
    op.drop_table("availability_exceptions")
    op.drop_table("availability_windows")
    op.drop_table("resources")
    op.drop_table("resource_types")

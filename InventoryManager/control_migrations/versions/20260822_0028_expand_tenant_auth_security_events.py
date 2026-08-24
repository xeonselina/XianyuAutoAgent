"""Expand tenant auth events for D48 challenge and action outcomes.

Revision ID: 202608220028
Revises: 202608220027
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202608220028"
down_revision = "202608220027"
branch_labels = None
depends_on = None


_EVENT_TYPE_CHECK = (
    "event_type IN ("
    "'login_session_created', 'login_session_rotated', "
    "'logout_current', 'revoke_target', 'revoke_all', "
    "'session_expired', 'security_invalidated', "
    "'sensitive_challenge_requested', "
    "'sensitive_challenge_verified', "
    "'sensitive_challenge_rejected', "
    "'sensitive_action_committed', "
    "'sensitive_action_rejected')"
)

_OLD_EVENT_TYPE_CHECK = (
    "event_type IN ("
    "'login_session_created', 'login_session_rotated', "
    "'logout_current', 'revoke_target', 'revoke_all', "
    "'session_expired', 'security_invalidated')"
)


def upgrade() -> None:
    with op.batch_alter_table(
        "tenant_auth_security_events", recreate="auto"
    ) as batch:
        batch.drop_constraint(
            op.f("ck_tenant_auth_security_events_event_type_valid"),
            type_="check",
        )
        batch.add_column(
            sa.Column("target_resource_type", sa.String(64), nullable=True)
        )
        batch.add_column(
            sa.Column("target_resource_id", sa.String(36), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "expected_target_revision", sa.String(128), nullable=True
            )
        )
        batch.add_column(
            sa.Column("challenge_id", sa.String(36), nullable=True)
        )
        batch.add_column(
            sa.Column("intent_id", sa.String(36), nullable=True)
        )
        batch.add_column(
            sa.Column("action_subtype", sa.String(64), nullable=True)
        )
        batch.add_column(
            sa.Column("idempotency_reference", sa.String(128), nullable=True)
        )
        batch.add_column(
            sa.Column("safe_outcome", sa.String(64), nullable=True)
        )
        batch.create_foreign_key(
            "fk_tenant_auth_security_events_challenge_id_sms_challenges",
            "sms_challenges",
            ["challenge_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_auth_event_sensitive_intent",
            "tenant_sensitive_action_intents",
            ["intent_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            op.f("ck_tenant_auth_security_events_event_type_valid"),
            _EVENT_TYPE_CHECK,
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "tenant_auth_security_events", recreate="auto"
    ) as batch:
        batch.drop_constraint(
            op.f("ck_tenant_auth_security_events_event_type_valid"),
            type_="check",
        )
        batch.drop_constraint(
            "fk_auth_event_sensitive_intent",
            type_="foreignkey",
        )
        batch.drop_constraint(
            "fk_tenant_auth_security_events_challenge_id_sms_challenges",
            type_="foreignkey",
        )
        for column in (
            "safe_outcome",
            "idempotency_reference",
            "action_subtype",
            "intent_id",
            "challenge_id",
            "expected_target_revision",
            "target_resource_id",
            "target_resource_type",
        ):
            batch.drop_column(column)
        batch.create_check_constraint(
            op.f("ck_tenant_auth_security_events_event_type_valid"),
            _OLD_EVENT_TYPE_CHECK,
        )

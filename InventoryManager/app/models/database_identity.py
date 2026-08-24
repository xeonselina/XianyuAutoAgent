"""Immutable identity anchor for one tenant business database."""

from datetime import datetime
from uuid import UUID

from app import db


class TenantDatabaseIdentity(db.Model):
    """The single trusted identity row stored inside each tenant schema."""

    __tablename__ = "database_identity"
    __table_args__ = (
        db.CheckConstraint(
            "singleton_key = 1",
            name="ck_database_identity_singleton_key",
        ),
        db.CheckConstraint(
            "schema_generation >= 1",
            name="ck_database_identity_schema_generation_positive",
        ),
    )

    singleton_key = db.Column(
        db.SmallInteger,
        primary_key=True,
        autoincrement=False,
        default=1,
        nullable=False,
    )
    tenant_id = db.Column(db.String(36), nullable=False)
    database_uuid = db.Column(db.String(36), nullable=False, unique=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    schema_generation = db.Column(
        db.BigInteger,
        nullable=False,
        default=1,
    )

    def validate_uuid_fields(self) -> None:
        """Reject malformed or nil immutable identifiers before publication."""

        for field_name in ("tenant_id", "database_uuid"):
            try:
                parsed = UUID(getattr(self, field_name))
            except (TypeError, ValueError, AttributeError):
                raise ValueError(f"{field_name} must be a UUID") from None
            if parsed.int == 0 or str(parsed) != getattr(self, field_name):
                raise ValueError(f"{field_name} must be a canonical non-nil UUID")

        if self.schema_generation is None or self.schema_generation < 1:
            raise ValueError("schema_generation must be positive")

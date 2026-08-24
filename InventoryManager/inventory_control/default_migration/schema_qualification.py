"""Explicit-connection Alembic qualification for the authorized MySQL target.

The runner never accepts or discovers a DSN.  Before any Alembic command it
proves that the caller-bound connection selects the single explicitly
authorized MySQL 8 test schema.  Production and ambiguous targets therefore
cannot reach the migration command through this adapter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection
from sqlalchemy.schema import MetaData

from inventory_control.evidence import canonical_json_sha256

_REVISION: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$")
_MYSQL_VERSION: Final = re.compile(r"^8\.0\.(?P<patch>[0-9]+)(?:[-+].*)?$")
_REAL_TEST_DATABASE: Final = "inventory_management_test"


class DefaultSchemaQualificationError(RuntimeError):
    code = "DEFAULT_SCHEMA_QUALIFICATION_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class DefaultSchemaQualificationInputError(DefaultSchemaQualificationError):
    code = "DEFAULT_SCHEMA_QUALIFICATION_INPUT_INVALID"


class DefaultSchemaQualificationTargetError(DefaultSchemaQualificationError):
    code = "DEFAULT_SCHEMA_QUALIFICATION_TARGET_REJECTED"


class DefaultSchemaQualificationMigrationError(DefaultSchemaQualificationError):
    code = "DEFAULT_SCHEMA_QUALIFICATION_MIGRATION_FAILED"


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultSchemaQualificationTarget:
    """Non-secret mutation boundary selected by an operator/test harness."""

    mysql_database_name: str | None = None
    real_test_database_authorized: bool = False

    def __post_init__(self) -> None:
        if (
            self.mysql_database_name != _REAL_TEST_DATABASE
            or self.real_test_database_authorized is not True
        ):
            raise DefaultSchemaQualificationInputError()

    def __repr__(self) -> str:
        return "DefaultSchemaQualificationTarget(kind='real_test_mysql')"


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultSchemaQualificationReceipt:
    schema_head: str
    baseline_revision: str | None
    dialect: str
    migration_round_trip_digest: bytes
    metadata_model_match_digest: bytes
    target_identity_digest: bytes

    def __post_init__(self) -> None:
        if (
            not _revision(self.schema_head)
            or (
                self.baseline_revision is not None
                and not _revision(self.baseline_revision)
            )
            or self.dialect != "mysql"
            or not _digest(self.migration_round_trip_digest)
            or not _digest(self.metadata_model_match_digest)
            or not _digest(self.target_identity_digest)
        ):
            raise DefaultSchemaQualificationInputError()

    @property
    def digest(self) -> bytes:
        return _canonical_digest(
            {
                "baseline_revision": self.baseline_revision,
                "dialect": self.dialect,
                "metadata_model_match_digest": (self.metadata_model_match_digest.hex()),
                "migration_round_trip_digest": (self.migration_round_trip_digest.hex()),
                "schema_head": self.schema_head,
                "target_identity_digest": self.target_identity_digest.hex(),
                "version": 1,
            }
        )

    def __repr__(self) -> str:
        return f"DefaultSchemaQualificationReceipt(digest={self.digest.hex()!r})"


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultSchemaApplyReceipt:
    schema_head: str
    dialect: str
    migration_apply_digest: bytes
    metadata_model_match_digest: bytes
    target_identity_digest: bytes

    def __post_init__(self) -> None:
        if (
            not _revision(self.schema_head)
            or self.dialect != "mysql"
            or not _digest(self.migration_apply_digest)
            or not _digest(self.metadata_model_match_digest)
            or not _digest(self.target_identity_digest)
        ):
            raise DefaultSchemaQualificationInputError()

    @property
    def digest(self) -> bytes:
        return _canonical_digest(
            {
                "dialect": self.dialect,
                "metadata_model_match_digest": (self.metadata_model_match_digest.hex()),
                "migration_apply_digest": self.migration_apply_digest.hex(),
                "schema_head": self.schema_head,
                "target_identity_digest": self.target_identity_digest.hex(),
                "version": 1,
            }
        )

    def __repr__(self) -> str:
        return f"DefaultSchemaApplyReceipt(digest={self.digest.hex()!r})"


class ExplicitConnectionAlembicQualificationRunner:
    """Upgrade/downgrade/upgrade one prevalidated isolated connection."""

    def __init__(
        self,
        *,
        script_location: Path,
        target_metadata: MetaData,
        schema_head: str,
        baseline_revision: str | None = None,
    ) -> None:
        location = script_location.resolve()
        if (
            not isinstance(script_location, Path)
            or not script_location.is_absolute()
            or not location.is_dir()
            or not (location / "alembic.ini").is_file()
            or not (location / "env.py").is_file()
            or not isinstance(target_metadata, MetaData)
            or not _revision(schema_head)
            or (baseline_revision is not None and not _revision(baseline_revision))
            or baseline_revision == schema_head
        ):
            raise DefaultSchemaQualificationInputError()
        self._script_location = location
        self._metadata = target_metadata
        self._head = schema_head
        self._baseline = baseline_revision
        config = Config(str(location / "alembic.ini"))
        config.set_main_option("script_location", str(location))
        try:
            heads = ScriptDirectory.from_config(config).get_heads()
        except Exception:
            raise DefaultSchemaQualificationInputError() from None
        if heads != [schema_head]:
            raise DefaultSchemaQualificationInputError()

    def qualify(
        self,
        connection: Connection,
        *,
        target: DefaultSchemaQualificationTarget,
    ) -> DefaultSchemaQualificationReceipt:
        if (
            not isinstance(connection, Connection)
            or not isinstance(target, DefaultSchemaQualificationTarget)
            or connection.in_transaction()
        ):
            raise DefaultSchemaQualificationInputError()
        try:
            dialect, target_identity = _require_target(connection, target)
            current = _current_revision(connection)
            if current not in {self._baseline, self._head}:
                raise DefaultSchemaQualificationTargetError()
            connection.commit()
            config = self._config(connection)
            if current != self._head:
                command.upgrade(config, self._head)
            _require_revision(connection, self._head)
            _require_metadata_match(connection, self._metadata)
            connection.commit()

            command.downgrade(config, self._baseline or "base")
            _require_revision(connection, self._baseline)
            connection.commit()
            command.upgrade(config, self._head)
            _require_revision(connection, self._head)
            _require_metadata_match(connection, self._metadata)
            connection.commit()
        except DefaultSchemaQualificationError:
            connection.rollback()
            raise
        except Exception:
            connection.rollback()
            raise DefaultSchemaQualificationMigrationError() from None

        migration_digest = _canonical_digest(
            {
                "baseline_revision": self._baseline,
                "dialect": dialect,
                "operations": ["upgrade", "downgrade", "upgrade"],
                "schema_head": self._head,
                "version": 1,
            }
        )
        metadata_digest = _canonical_digest(
            {
                "dialect": dialect,
                "metadata_matches": True,
                "schema_head": self._head,
                "version": 1,
            }
        )
        return DefaultSchemaQualificationReceipt(
            schema_head=self._head,
            baseline_revision=self._baseline,
            dialect=dialect,
            migration_round_trip_digest=migration_digest,
            metadata_model_match_digest=metadata_digest,
            target_identity_digest=target_identity,
        )

    def apply(
        self,
        connection: Connection,
        *,
        target: DefaultSchemaQualificationTarget,
    ) -> DefaultSchemaApplyReceipt:
        """Move one isolated target forward only; never downgrade it."""

        if (
            not isinstance(connection, Connection)
            or not isinstance(target, DefaultSchemaQualificationTarget)
            or connection.in_transaction()
        ):
            raise DefaultSchemaQualificationInputError()
        try:
            dialect, target_identity = _require_target(connection, target)
            current = _current_revision(connection)
            if current not in {self._baseline, self._head}:
                raise DefaultSchemaQualificationTargetError()
            connection.commit()
            if current != self._head:
                command.upgrade(self._config(connection), self._head)
            _require_revision(connection, self._head)
            _require_metadata_match(connection, self._metadata)
            connection.commit()
        except DefaultSchemaQualificationError:
            connection.rollback()
            raise
        except Exception:
            connection.rollback()
            raise DefaultSchemaQualificationMigrationError() from None
        return DefaultSchemaApplyReceipt(
            schema_head=self._head,
            dialect=dialect,
            migration_apply_digest=_canonical_digest(
                {
                    "baseline_revision": self._baseline,
                    "dialect": dialect,
                    "operation": "forward_only_upgrade",
                    "schema_head": self._head,
                    "version": 1,
                }
            ),
            metadata_model_match_digest=_canonical_digest(
                {
                    "dialect": dialect,
                    "metadata_matches": True,
                    "schema_head": self._head,
                    "version": 1,
                }
            ),
            target_identity_digest=target_identity,
        )

    def _config(self, connection: Connection) -> Config:
        value = Config(str(self._script_location / "alembic.ini"))
        value.set_main_option("script_location", str(self._script_location))
        value.attributes["connection"] = connection
        value.attributes["target_metadata"] = self._metadata
        return value


def _require_target(
    connection: Connection,
    target: DefaultSchemaQualificationTarget,
) -> tuple[str, bytes]:
    dialect = connection.dialect.name
    if dialect == "mysql":
        if (
            target.mysql_database_name != _REAL_TEST_DATABASE
            or not target.real_test_database_authorized
        ):
            raise DefaultSchemaQualificationTargetError()
        row = (
            connection.execute(
                sa.text(
                    "SELECT DATABASE() AS database_name, "
                    "CAST(@@version AS CHAR) AS server_version, "
                    "CAST(@@version_comment AS CHAR) AS version_comment, "
                    "CAST(@@server_uuid AS CHAR) AS server_uuid"
                )
            )
            .mappings()
            .one()
        )
        if set(row) != {
            "database_name",
            "server_version",
            "version_comment",
            "server_uuid",
        }:
            raise DefaultSchemaQualificationTargetError()
        version = row["server_version"]
        comment = row["version_comment"]
        selected = (
            _MYSQL_VERSION.fullmatch(version) if isinstance(version, str) else None
        )
        if (
            row["database_name"] != _REAL_TEST_DATABASE
            or selected is None
            or int(selected.group("patch")) < 30
            or not isinstance(comment, str)
            or "mariadb" in version.lower()
            or "mariadb" in comment.lower()
        ):
            raise DefaultSchemaQualificationTargetError()
        try:
            server_uuid = str(UUID(row["server_uuid"]))
        except (TypeError, ValueError, AttributeError):
            raise DefaultSchemaQualificationTargetError() from None
        if server_uuid != row["server_uuid"]:
            raise DefaultSchemaQualificationTargetError()
        return dialect, _canonical_digest(
            {
                "database_name": row["database_name"],
                "dialect": dialect,
                "server_uuid": server_uuid,
                "version": 1,
            }
        )
    raise DefaultSchemaQualificationTargetError()


def _current_revision(connection: Connection) -> str | None:
    heads = tuple(MigrationContext.configure(connection).get_current_heads())
    if len(heads) > 1:
        raise DefaultSchemaQualificationTargetError()
    value = None if not heads else heads[0]
    if value is not None and not _revision(value):
        raise DefaultSchemaQualificationTargetError()
    return value


def _require_revision(connection: Connection, expected: str | None) -> None:
    if _current_revision(connection) != expected:
        raise DefaultSchemaQualificationMigrationError()


def _require_metadata_match(connection: Connection, metadata: MetaData) -> None:
    if compare_metadata(MigrationContext.configure(connection), metadata) != []:
        raise DefaultSchemaQualificationMigrationError()


def _revision(value: object) -> bool:
    return isinstance(value, str) and _REVISION.fullmatch(value) is not None


def _digest(value: object) -> bool:
    return isinstance(value, bytes) and len(value) == 32


def _canonical_digest(value: object) -> bytes:
    return canonical_json_sha256(value, allow_nan=True)


__all__ = [
    "DefaultSchemaQualificationError",
    "DefaultSchemaQualificationInputError",
    "DefaultSchemaQualificationMigrationError",
    "DefaultSchemaApplyReceipt",
    "DefaultSchemaQualificationReceipt",
    "DefaultSchemaQualificationTarget",
    "DefaultSchemaQualificationTargetError",
    "ExplicitConnectionAlembicQualificationRunner",
]

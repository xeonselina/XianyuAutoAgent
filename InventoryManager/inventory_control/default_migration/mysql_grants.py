"""Fixed-query MySQL grant and cross-schema denial observers.

These observers accept already-authenticated account connections only.  They
never accept a password/DSN, never mutate a schema, reject active roles and
all privilege sources except one exact schema-level grant set, and keep the
cross-schema smoke to a non-locking ``SELECT ... LIMIT 0``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Final, Mapping, Protocol, runtime_checkable

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError


_TOKEN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_$-]{0,63}$", re.ASCII)
_USERNAME: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,127}$", re.ASCII)
_MYSQL_VERSION: Final = re.compile(r"^8\.0\.(?P<patch>[0-9]+)(?:[-+].*)?$")
_DML_PRIVILEGES: Final = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})
_READ_PRIVILEGES: Final = frozenset({"SELECT", "SHOW VIEW"})
_DENIAL_ERROR_CODES: Final = frozenset({1044, 1142})


class DefaultMySqlGrantObservationError(RuntimeError):
    code = "DEFAULT_MYSQL_GRANT_OBSERVATION_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class DefaultMySqlGrantObservationInputError(DefaultMySqlGrantObservationError):
    code = "DEFAULT_MYSQL_GRANT_OBSERVATION_INPUT_INVALID"


class DefaultMySqlGrantObservationRejected(DefaultMySqlGrantObservationError):
    code = "DEFAULT_MYSQL_GRANT_OBSERVATION_REJECTED"


class DefaultMySqlAccountProfile(str, Enum):
    CONTROL_APP = "control_app"
    TENANT_DML = "tenant_dml"
    PLATFORM_READ = "platform_read"


@runtime_checkable
class DefaultMySqlGrantConnection(Protocol):
    dialect: object

    def execute(self, statement: object) -> object: ...

    def in_transaction(self) -> bool: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultMySqlGrantObservation:
    account_profile: DefaultMySqlAccountProfile
    username: str
    database_name: str
    privileges: tuple[str, ...]

    def __post_init__(self) -> None:
        expected = _expected_privileges(self.account_profile)
        if (
            not _username(self.username)
            or not _token(self.database_name)
            or self.privileges != tuple(sorted(expected))
        ):
            raise DefaultMySqlGrantObservationInputError()

    @property
    def digest(self) -> bytes:
        return _digest_document(
            {
                "account_profile": self.account_profile.value,
                "database_name": self.database_name,
                "privileges": list(self.privileges),
                "username": self.username,
                "version": 1,
            }
        )

    def __repr__(self) -> str:
        return f"DefaultMySqlGrantObservation(digest={self.digest.hex()!r})"


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultMySqlCrossSchemaDenialObservation:
    username: str
    database_name: str
    foreign_database_name: str
    probe_table: str

    def __post_init__(self) -> None:
        if (
            not _username(self.username)
            or not _token(self.database_name)
            or not _token(self.foreign_database_name)
            or self.database_name == self.foreign_database_name
            or not _token(self.probe_table)
        ):
            raise DefaultMySqlGrantObservationInputError()

    @property
    def digest(self) -> bytes:
        return _digest_document(
            {
                "database_name": self.database_name,
                "denied": True,
                "foreign_database_name": self.foreign_database_name,
                "probe_table": self.probe_table,
                "username": self.username,
                "version": 1,
            }
        )

    def __repr__(self) -> str:
        return (
            "DefaultMySqlCrossSchemaDenialObservation("
            f"digest={self.digest.hex()!r})"
        )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultMySqlTenantGrantMatrixObservation:
    dml_grants_digest: bytes
    platform_read_grants_digest: bytes
    cross_schema_negative_digest: bytes

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, bytes) and len(value) == 32
            for value in (
                self.dml_grants_digest,
                self.platform_read_grants_digest,
                self.cross_schema_negative_digest,
            )
        ):
            raise DefaultMySqlGrantObservationInputError()

    @property
    def digest(self) -> bytes:
        return _digest_document(
            {
                "cross_schema_negative_digest": (
                    self.cross_schema_negative_digest.hex()
                ),
                "dml_grants_digest": self.dml_grants_digest.hex(),
                "platform_read_grants_digest": (
                    self.platform_read_grants_digest.hex()
                ),
                "version": 1,
            }
        )

    def __repr__(self) -> str:
        return (
            "DefaultMySqlTenantGrantMatrixObservation("
            f"digest={self.digest.hex()!r})"
        )


_PROFILE_SQL = sa.text(
    """
    SELECT
        DATABASE() AS database_name,
        SUBSTRING_INDEX(CURRENT_USER(), '@', 1) AS username,
        CURRENT_ROLE() AS current_role,
        CAST(@@version AS CHAR) AS server_version,
        CAST(@@version_comment AS CHAR) AS version_comment
    """
)

_GRANTS_SQL = sa.text(
    """
    SELECT
        'global' AS privilege_scope,
        NULL AS object_schema,
        NULL AS object_name,
        UPPER(PRIVILEGE_TYPE) AS privilege_type,
        UPPER(IS_GRANTABLE) AS is_grantable
    FROM information_schema.USER_PRIVILEGES
    WHERE REPLACE(GRANTEE, '''', '') = CURRENT_USER()
    UNION ALL
    SELECT
        'schema' AS privilege_scope,
        TABLE_SCHEMA AS object_schema,
        NULL AS object_name,
        UPPER(PRIVILEGE_TYPE) AS privilege_type,
        UPPER(IS_GRANTABLE) AS is_grantable
    FROM information_schema.SCHEMA_PRIVILEGES
    WHERE REPLACE(GRANTEE, '''', '') = CURRENT_USER()
    UNION ALL
    SELECT
        'table' AS privilege_scope,
        TABLE_SCHEMA AS object_schema,
        TABLE_NAME AS object_name,
        UPPER(PRIVILEGE_TYPE) AS privilege_type,
        UPPER(IS_GRANTABLE) AS is_grantable
    FROM information_schema.TABLE_PRIVILEGES
    WHERE REPLACE(GRANTEE, '''', '') = CURRENT_USER()
    UNION ALL
    SELECT
        'column' AS privilege_scope,
        TABLE_SCHEMA AS object_schema,
        CONCAT(TABLE_NAME, '.', COLUMN_NAME) AS object_name,
        UPPER(PRIVILEGE_TYPE) AS privilege_type,
        UPPER(IS_GRANTABLE) AS is_grantable
    FROM information_schema.COLUMN_PRIVILEGES
    WHERE REPLACE(GRANTEE, '''', '') = CURRENT_USER()
    ORDER BY privilege_scope, object_schema, object_name, privilege_type
    """
)

# MySQL 8 does not expose INFORMATION_SCHEMA.ROUTINE_PRIVILEGES.  SHOW GRANTS
# is therefore also required: exact allow-list parsing catches routine-level,
# proxy, role, and other privilege sources that the four portable privilege
# inventory views cannot represent.
_SHOW_GRANTS_SQL = sa.text("SHOW GRANTS FOR CURRENT_USER")

_ROLES_SQL = sa.text(
    """
    SELECT
        ROLE_NAME AS role_name,
        ROLE_HOST AS role_host,
        UPPER(IS_DEFAULT) AS is_default,
        UPPER(IS_MANDATORY) AS is_mandatory
    FROM information_schema.APPLICABLE_ROLES
    WHERE REPLACE(GRANTEE, '''', '') = CURRENT_USER()
    ORDER BY ROLE_NAME, ROLE_HOST
    """
)


class DefaultMySqlGrantObserver:
    __slots__ = ()

    def observe(
        self,
        connection: DefaultMySqlGrantConnection,
        *,
        account_profile: DefaultMySqlAccountProfile,
        expected_username: str,
        expected_database_name: str,
    ) -> DefaultMySqlGrantObservation:
        _require_input(
            connection,
            account_profile,
            expected_username,
            expected_database_name,
        )
        try:
            profile = _read_profile(connection)
            if profile != (expected_database_name, expected_username):
                raise DefaultMySqlGrantObservationRejected()
            # Reject inactive/default/mandatory roles alike.  A currently
            # inactive role could otherwise be enabled after this receipt.
            if _rows(connection.execute(_ROLES_SQL)):
                raise DefaultMySqlGrantObservationRejected()
            expected = _expected_privileges(account_profile)
            rows = _rows(connection.execute(_GRANTS_SQL))
            grants: set[str] = set()
            usage_count = 0
            for row in rows:
                if set(row) != {
                    "privilege_scope",
                    "object_schema",
                    "object_name",
                    "privilege_type",
                    "is_grantable",
                }:
                    raise DefaultMySqlGrantObservationRejected()
                privilege = row["privilege_type"]
                if (
                    row["privilege_scope"] == "global"
                    and row["object_schema"] is None
                    and row["object_name"] is None
                    and privilege == "USAGE"
                    and row["is_grantable"] == "NO"
                ):
                    usage_count += 1
                    continue
                if (
                    row["privilege_scope"] != "schema"
                    or row["object_schema"] != expected_database_name
                    or row["object_name"] is not None
                    or not isinstance(privilege, str)
                    or not privilege
                    or row["is_grantable"] != "NO"
                    or privilege in grants
                ):
                    raise DefaultMySqlGrantObservationRejected()
                grants.add(privilege)
            if usage_count != 1 or grants != expected:
                raise DefaultMySqlGrantObservationRejected()
            _require_exact_show_grants(
                connection,
                expected_username=expected_username,
                expected_database_name=expected_database_name,
                expected_privileges=expected,
            )
            return DefaultMySqlGrantObservation(
                account_profile=account_profile,
                username=expected_username,
                database_name=expected_database_name,
                privileges=tuple(sorted(grants)),
            )
        except DefaultMySqlGrantObservationError:
            raise
        except Exception:
            raise DefaultMySqlGrantObservationRejected() from None
        finally:
            connection.rollback()


def _require_exact_show_grants(
    connection: DefaultMySqlGrantConnection,
    *,
    expected_username: str,
    expected_database_name: str,
    expected_privileges: frozenset[str],
) -> None:
    rows = _rows(connection.execute(_SHOW_GRANTS_SQL))
    statements: list[str] = []
    for row in rows:
        if len(row) != 1:
            raise DefaultMySqlGrantObservationRejected()
        statement = next(iter(row.values()))
        if not isinstance(statement, str):
            raise DefaultMySqlGrantObservationRejected()
        statements.append(statement)

    account = rf"`{re.escape(expected_username)}`@`[^`]+`"
    usage = re.compile(rf"^GRANT USAGE ON \*\.\* TO {account}$")
    schema = re.compile(
        rf"^GRANT (?P<privileges>[A-Z ,]+) ON "
        rf"`{re.escape(expected_database_name)}`\.\* TO {account}$"
    )
    usage_count = 0
    observed_schema: frozenset[str] | None = None
    for statement in statements:
        if usage.fullmatch(statement):
            usage_count += 1
            continue
        match = schema.fullmatch(statement)
        if match is None or observed_schema is not None:
            raise DefaultMySqlGrantObservationRejected()
        privileges = frozenset(
            item.strip() for item in match.group("privileges").split(",")
        )
        if "" in privileges:
            raise DefaultMySqlGrantObservationRejected()
        observed_schema = privileges
    if usage_count != 1 or observed_schema != expected_privileges:
        raise DefaultMySqlGrantObservationRejected()


class DefaultMySqlCrossSchemaDenialObserver:
    __slots__ = ()

    def observe(
        self,
        connection: DefaultMySqlGrantConnection,
        *,
        expected_username: str,
        expected_database_name: str,
        foreign_database_name: str,
        probe_table: str = "alembic_version",
    ) -> DefaultMySqlCrossSchemaDenialObservation:
        _require_input(
            connection,
            DefaultMySqlAccountProfile.TENANT_DML,
            expected_username,
            expected_database_name,
        )
        if (
            not _token(foreign_database_name)
            or foreign_database_name == expected_database_name
            or not _token(probe_table)
        ):
            raise DefaultMySqlGrantObservationInputError()
        try:
            if _read_profile(connection) != (
                expected_database_name,
                expected_username,
            ):
                raise DefaultMySqlGrantObservationRejected()
            connection.execute(
                sa.text(
                    f"SELECT 1 FROM `{expected_database_name}`."
                    f"`{probe_table}` LIMIT 0"
                )
            )
            try:
                connection.execute(
                    sa.text(
                        f"SELECT 1 FROM `{foreign_database_name}`."
                        f"`{probe_table}` LIMIT 0"
                    )
                )
            except DBAPIError as exc:
                if _dbapi_error_code(exc) not in _DENIAL_ERROR_CODES:
                    raise DefaultMySqlGrantObservationRejected() from None
            else:
                raise DefaultMySqlGrantObservationRejected()
            return DefaultMySqlCrossSchemaDenialObservation(
                username=expected_username,
                database_name=expected_database_name,
                foreign_database_name=foreign_database_name,
                probe_table=probe_table,
            )
        except DefaultMySqlGrantObservationError:
            raise
        except Exception:
            raise DefaultMySqlGrantObservationRejected() from None
        finally:
            connection.rollback()


class DefaultMySqlTenantGrantMatrixVerifier:
    """Observe both tenant accounts and both cross-schema denial probes."""

    def __init__(
        self,
        *,
        dml_connection_factory: Callable[[], DefaultMySqlGrantConnection],
        platform_read_connection_factory: Callable[
            [], DefaultMySqlGrantConnection
        ],
        dml_username: str,
        platform_read_username: str,
        database_name: str,
        foreign_database_name: str,
        probe_table: str = "alembic_version",
        grant_observer: DefaultMySqlGrantObserver | None = None,
        denial_observer: DefaultMySqlCrossSchemaDenialObserver | None = None,
    ) -> None:
        if (
            not callable(dml_connection_factory)
            or not callable(platform_read_connection_factory)
            or dml_connection_factory is platform_read_connection_factory
            or not _username(dml_username)
            or not _username(platform_read_username)
            or dml_username == platform_read_username
            or not _token(database_name)
            or not _token(foreign_database_name)
            or database_name == foreign_database_name
            or not _token(probe_table)
        ):
            raise DefaultMySqlGrantObservationInputError()
        self._dml_factory = dml_connection_factory
        self._platform_factory = platform_read_connection_factory
        self._dml_username = dml_username
        self._platform_username = platform_read_username
        self._database_name = database_name
        self._foreign_database_name = foreign_database_name
        self._probe_table = probe_table
        self._grants = grant_observer or DefaultMySqlGrantObserver()
        self._denial = denial_observer or DefaultMySqlCrossSchemaDenialObserver()

    def verify(self) -> DefaultMySqlTenantGrantMatrixObservation:
        dml_grants, dml_denial = self._observe_account(
            factory=self._dml_factory,
            profile=DefaultMySqlAccountProfile.TENANT_DML,
            username=self._dml_username,
        )
        platform_grants, platform_denial = self._observe_account(
            factory=self._platform_factory,
            profile=DefaultMySqlAccountProfile.PLATFORM_READ,
            username=self._platform_username,
        )
        return DefaultMySqlTenantGrantMatrixObservation(
            dml_grants_digest=dml_grants.digest,
            platform_read_grants_digest=platform_grants.digest,
            cross_schema_negative_digest=_digest_document(
                {
                    "dml_denial": dml_denial.digest.hex(),
                    "platform_read_denial": platform_denial.digest.hex(),
                    "version": 1,
                }
            ),
        )

    def _observe_account(
        self,
        *,
        factory: Callable[[], DefaultMySqlGrantConnection],
        profile: DefaultMySqlAccountProfile,
        username: str,
    ) -> tuple[
        DefaultMySqlGrantObservation,
        DefaultMySqlCrossSchemaDenialObservation,
    ]:
        try:
            connection = factory()
        except Exception:
            raise DefaultMySqlGrantObservationRejected() from None
        if not isinstance(connection, DefaultMySqlGrantConnection):
            raise DefaultMySqlGrantObservationRejected()
        try:
            grants = self._grants.observe(
                connection,
                account_profile=profile,
                expected_username=username,
                expected_database_name=self._database_name,
            )
            denial = self._denial.observe(
                connection,
                expected_username=username,
                expected_database_name=self._database_name,
                foreign_database_name=self._foreign_database_name,
                probe_table=self._probe_table,
            )
            return grants, denial
        finally:
            connection.close()

    def __repr__(self) -> str:
        return "DefaultMySqlTenantGrantMatrixVerifier(connections='<bound>')"


class DefaultMySqlControlGrantVerifier:
    """Bind the control-app exact grants and tenant-schema denial together."""

    def __init__(
        self,
        *,
        connection_factory: Callable[[], DefaultMySqlGrantConnection],
        username: str,
        control_database_name: str,
        tenant_database_name: str,
        probe_table: str = "alembic_version",
        grant_observer: DefaultMySqlGrantObserver | None = None,
        denial_observer: DefaultMySqlCrossSchemaDenialObserver | None = None,
    ) -> None:
        if (
            not callable(connection_factory)
            or not _username(username)
            or not _token(control_database_name)
            or not _token(tenant_database_name)
            or control_database_name == tenant_database_name
            or not _token(probe_table)
        ):
            raise DefaultMySqlGrantObservationInputError()
        self._factory = connection_factory
        self._username = username
        self._control_database_name = control_database_name
        self._tenant_database_name = tenant_database_name
        self._probe_table = probe_table
        self._grants = grant_observer or DefaultMySqlGrantObserver()
        self._denial = denial_observer or DefaultMySqlCrossSchemaDenialObserver()

    def __call__(self) -> bytes:
        try:
            connection = self._factory()
        except Exception:
            raise DefaultMySqlGrantObservationRejected() from None
        if not isinstance(connection, DefaultMySqlGrantConnection):
            raise DefaultMySqlGrantObservationRejected()
        try:
            grants = self._grants.observe(
                connection,
                account_profile=DefaultMySqlAccountProfile.CONTROL_APP,
                expected_username=self._username,
                expected_database_name=self._control_database_name,
            )
            denial = self._denial.observe(
                connection,
                expected_username=self._username,
                expected_database_name=self._control_database_name,
                foreign_database_name=self._tenant_database_name,
                probe_table=self._probe_table,
            )
            return _digest_document(
                {
                    "control_grants": grants.digest.hex(),
                    "tenant_schema_denial": denial.digest.hex(),
                    "version": 1,
                }
            )
        finally:
            connection.close()

    def __repr__(self) -> str:
        return "DefaultMySqlControlGrantVerifier(connection='<bound>')"


def _require_input(
    connection: DefaultMySqlGrantConnection,
    account_profile: DefaultMySqlAccountProfile,
    expected_username: str,
    expected_database_name: str,
) -> None:
    if (
        not isinstance(connection, DefaultMySqlGrantConnection)
        or getattr(connection.dialect, "name", None) != "mysql"
        or connection.in_transaction()
        or not isinstance(account_profile, DefaultMySqlAccountProfile)
        or not _username(expected_username)
        or not _token(expected_database_name)
    ):
        raise DefaultMySqlGrantObservationInputError()


def _read_profile(
    connection: DefaultMySqlGrantConnection,
) -> tuple[str, str]:
    rows = _rows(connection.execute(_PROFILE_SQL))
    if len(rows) != 1:
        raise DefaultMySqlGrantObservationRejected()
    row = rows[0]
    if set(row) != {
        "database_name",
        "username",
        "current_role",
        "server_version",
        "version_comment",
    }:
        raise DefaultMySqlGrantObservationRejected()
    version = row["server_version"]
    comment = row["version_comment"]
    selected = _MYSQL_VERSION.fullmatch(version) if isinstance(version, str) else None
    if (
        selected is None
        or int(selected.group("patch")) < 30
        or not isinstance(comment, str)
        or "mariadb" in version.lower()
        or "mariadb" in comment.lower()
        or row["current_role"] not in {None, "NONE"}
        or not _token(row["database_name"])
        or not _username(row["username"])
    ):
        raise DefaultMySqlGrantObservationRejected()
    return row["database_name"], row["username"]


def _rows(result: object) -> tuple[Mapping[str, object], ...]:
    try:
        selected = tuple(result.mappings())
    except Exception:
        raise DefaultMySqlGrantObservationRejected() from None
    if len(selected) > 128 or not all(isinstance(row, Mapping) for row in selected):
        raise DefaultMySqlGrantObservationRejected()
    return selected


def _expected_privileges(
    value: DefaultMySqlAccountProfile,
) -> frozenset[str]:
    if value in {
        DefaultMySqlAccountProfile.CONTROL_APP,
        DefaultMySqlAccountProfile.TENANT_DML,
    }:
        return _DML_PRIVILEGES
    if value is DefaultMySqlAccountProfile.PLATFORM_READ:
        return _READ_PRIVILEGES
    raise DefaultMySqlGrantObservationInputError()


def _dbapi_error_code(error: DBAPIError) -> int | None:
    args = getattr(error.orig, "args", ())
    return args[0] if args and isinstance(args[0], int) else None


def _token(value: object) -> bool:
    return isinstance(value, str) and _TOKEN.fullmatch(value) is not None


def _username(value: object) -> bool:
    return isinstance(value, str) and _USERNAME.fullmatch(value) is not None


def _digest_document(value: Mapping[str, object]) -> bytes:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).digest()


__all__ = [
    "DefaultMySqlAccountProfile",
    "DefaultMySqlCrossSchemaDenialObservation",
    "DefaultMySqlCrossSchemaDenialObserver",
    "DefaultMySqlControlGrantVerifier",
    "DefaultMySqlGrantConnection",
    "DefaultMySqlGrantObservation",
    "DefaultMySqlGrantObservationError",
    "DefaultMySqlGrantObservationInputError",
    "DefaultMySqlGrantObservationRejected",
    "DefaultMySqlGrantObserver",
    "DefaultMySqlTenantGrantMatrixObservation",
    "DefaultMySqlTenantGrantMatrixVerifier",
]

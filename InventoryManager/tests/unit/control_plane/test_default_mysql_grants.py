from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

from inventory_control.default_migration import (
    DefaultMySqlAccountProfile,
    DefaultMySqlCrossSchemaDenialObserver,
    DefaultMySqlControlGrantVerifier,
    DefaultMySqlGrantObservationInputError,
    DefaultMySqlGrantObservationRejected,
    DefaultMySqlGrantObserver,
    DefaultMySqlTenantGrantMatrixVerifier,
)


class _Result:
    def __init__(self, rows=()):
        self.rows = tuple(rows)

    def mappings(self):
        return iter(self.rows)


class _OrigError(Exception):
    pass


class _Connection:
    dialect = SimpleNamespace(name="mysql")

    def __init__(
        self,
        *,
        username="tenant_dml_1",
        database="inventory_management_test",
        role="NONE",
        grants=(),
        show_grants=None,
        applicable_roles=(),
        foreign_error=1142,
    ):
        self.username = username
        self.database = database
        self.role = role
        self.grants = tuple(grants)
        self.show_grants = show_grants
        self.applicable_roles = tuple(applicable_roles)
        self.foreign_error = foreign_error
        self.rollback_count = 0
        self.calls = []
        self.closed = False

    def in_transaction(self):
        return False

    def rollback(self):
        self.rollback_count += 1

    def close(self):
        self.closed = True

    def execute(self, statement):
        sql = str(statement)
        self.calls.append(sql)
        if "CURRENT_ROLE()" in sql:
            return _Result(
                (
                    {
                        "database_name": self.database,
                        "username": self.username,
                        "current_role": self.role,
                        "server_version": "8.0.36",
                        "version_comment": "MySQL Community Server",
                    },
                )
            )
        if "APPLICABLE_ROLES" in sql:
            return _Result(self.applicable_roles)
        if "USER_PRIVILEGES" in sql:
            return _Result(
                (
                    {
                        "privilege_scope": "global",
                        "object_schema": None,
                        "object_name": None,
                        "privilege_type": "USAGE",
                        "is_grantable": "NO",
                    },
                    *self.grants,
                )
            )
        if "SHOW GRANTS FOR CURRENT_USER" in sql:
            statements = self.show_grants
            if statements is None:
                privileges = ", ".join(
                    row["privilege_type"]
                    for row in self.grants
                    if row["privilege_scope"] == "schema"
                    and row["object_schema"] == self.database
                )
                statements = (
                    f"GRANT USAGE ON *.* TO `{self.username}`@`%`",
                    f"GRANT {privileges} ON `{self.database}`.* "
                    f"TO `{self.username}`@`%`",
                )
            return _Result(
                {"grant_statement": statement} for statement in statements
            )
        if f"`{self.database}`.`alembic_version`" in sql:
            return _Result()
        if "SELECT 1 FROM `" in sql and "`.`alembic_version`" in sql:
            if self.foreign_error is None:
                return _Result()
            raise OperationalError(
                sql,
                {},
                _OrigError(self.foreign_error, "fixed fake error"),
            )
        raise AssertionError("unexpected SQL")


def _grant(privilege, **extra):
    value = {
        "privilege_scope": "schema",
        "object_schema": "inventory_management_test",
        "object_name": None,
        "privilege_type": privilege,
        "is_grantable": "NO",
    }
    value.update(extra)
    return value


@pytest.mark.parametrize(
    ("profile", "privileges", "username"),
    [
        (
            DefaultMySqlAccountProfile.CONTROL_APP,
            ("SELECT", "INSERT", "UPDATE", "DELETE"),
            "control_app_1",
        ),
        (
            DefaultMySqlAccountProfile.TENANT_DML,
            ("SELECT", "INSERT", "UPDATE", "DELETE"),
            "tenant_dml_1",
        ),
        (
            DefaultMySqlAccountProfile.PLATFORM_READ,
            ("SELECT", "SHOW VIEW"),
            "platform_read_1",
        ),
    ],
)
def test_exact_schema_grants_produce_stable_profile_receipt(
    profile,
    privileges,
    username,
):
    connection = _Connection(
        username=username,
        grants=tuple(_grant(item) for item in reversed(privileges)),
    )

    observed = DefaultMySqlGrantObserver().observe(
        connection,
        account_profile=profile,
        expected_username=username,
        expected_database_name="inventory_management_test",
    )

    assert observed.privileges == tuple(sorted(privileges))
    assert len(observed.digest) == 32
    assert connection.rollback_count == 1
    assert len(connection.calls) == 4
    assert "password" not in repr(observed).lower()


@pytest.mark.parametrize(
    "grants,role",
    [
        (
            tuple(
                _grant(item)
                for item in ("SELECT", "INSERT", "UPDATE", "DELETE")
            )
            + (_grant("FILE", privilege_scope="global", object_schema=None),),
            "NONE",
        ),
        (
            tuple(
                _grant(item)
                for item in ("SELECT", "INSERT", "UPDATE", "DELETE")
            ),
            "`some_role`@`%`",
        ),
        (
            tuple(
                _grant(item)
                for item in ("SELECT", "INSERT", "UPDATE", "DELETE")
            )
            + (_grant("ALTER"),),
            "NONE",
        ),
        (
            tuple(
                _grant(item)
                for item in ("SELECT", "INSERT", "UPDATE")
            ),
            "NONE",
        ),
        (
            tuple(
                _grant(item)
                for item in ("SELECT", "INSERT", "UPDATE", "DELETE")
            )[:-1]
            + (_grant("DELETE", is_grantable="YES"),),
            "NONE",
        ),
    ],
)
def test_extra_missing_role_or_grant_option_authority_is_rejected(grants, role):
    connection = _Connection(grants=grants, role=role)
    with pytest.raises(DefaultMySqlGrantObservationRejected):
        DefaultMySqlGrantObserver().observe(
            connection,
            account_profile=DefaultMySqlAccountProfile.TENANT_DML,
            expected_username="tenant_dml_1",
            expected_database_name="inventory_management_test",
        )
    assert connection.rollback_count == 1


def test_inactive_applicable_role_is_also_rejected():
    connection = _Connection(
        grants=tuple(
            _grant(item)
            for item in ("SELECT", "INSERT", "UPDATE", "DELETE")
        ),
        applicable_roles=(
            {
                "role_name": "future_privileges",
                "role_host": "%",
                "is_default": "NO",
                "is_mandatory": "NO",
            },
        ),
    )
    with pytest.raises(DefaultMySqlGrantObservationRejected):
        DefaultMySqlGrantObserver().observe(
            connection,
            account_profile=DefaultMySqlAccountProfile.TENANT_DML,
            expected_username="tenant_dml_1",
            expected_database_name="inventory_management_test",
        )


def test_routine_level_grant_visible_only_in_show_grants_is_rejected():
    connection = _Connection(
        grants=tuple(
            _grant(item)
            for item in ("SELECT", "INSERT", "UPDATE", "DELETE")
        ),
        show_grants=(
            "GRANT USAGE ON *.* TO `tenant_dml_1`@`%`",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON "
            "`inventory_management_test`.* TO `tenant_dml_1`@`%`",
            "GRANT EXECUTE ON PROCEDURE `inventory_management_test`.`p` "
            "TO `tenant_dml_1`@`%`",
        ),
    )
    with pytest.raises(DefaultMySqlGrantObservationRejected):
        DefaultMySqlGrantObserver().observe(
            connection,
            account_profile=DefaultMySqlAccountProfile.TENANT_DML,
            expected_username="tenant_dml_1",
            expected_database_name="inventory_management_test",
        )


def test_cross_schema_probe_requires_positive_local_read_and_1044_or_1142_denial():
    connection = _Connection()
    observed = DefaultMySqlCrossSchemaDenialObserver().observe(
        connection,
        expected_username="tenant_dml_1",
        expected_database_name="inventory_management_test",
        foreign_database_name="foreign_tenant",
    )
    assert len(observed.digest) == 32
    assert connection.rollback_count == 1
    assert connection.calls[-2].endswith(
        "`inventory_management_test`.`alembic_version` LIMIT 0"
    )
    assert connection.calls[-1].endswith(
        "`foreign_tenant`.`alembic_version` LIMIT 0"
    )

    for error in (None, 1146, 2006):
        rejected = _Connection(foreign_error=error)
        with pytest.raises(DefaultMySqlGrantObservationRejected):
            DefaultMySqlCrossSchemaDenialObserver().observe(
                rejected,
                expected_username="tenant_dml_1",
                expected_database_name="inventory_management_test",
                foreign_database_name="foreign_tenant",
            )


def test_identifiers_are_fixed_tokens_and_no_sql_is_run_on_bad_input():
    connection = _Connection()
    with pytest.raises(DefaultMySqlGrantObservationInputError):
        DefaultMySqlCrossSchemaDenialObserver().observe(
            connection,
            expected_username="tenant_dml_1",
            expected_database_name="inventory_management_test",
            foreign_database_name="foreign_tenant` UNION SELECT secret",
        )
    assert connection.calls == []


def test_tenant_matrix_uses_distinct_bound_accounts_and_both_denial_probes():
    dml = _Connection(
        username="tenant_dml_1",
        grants=tuple(
            _grant(item)
            for item in ("SELECT", "INSERT", "UPDATE", "DELETE")
        ),
    )
    platform = _Connection(
        username="platform_read_1",
        grants=tuple(_grant(item) for item in ("SELECT", "SHOW VIEW")),
    )
    verifier = DefaultMySqlTenantGrantMatrixVerifier(
        dml_connection_factory=lambda: dml,
        platform_read_connection_factory=lambda: platform,
        dml_username="tenant_dml_1",
        platform_read_username="platform_read_1",
        database_name="inventory_management_test",
        foreign_database_name="foreign_tenant",
    )

    observed = verifier.verify()

    assert len(observed.dml_grants_digest) == 32
    assert len(observed.platform_read_grants_digest) == 32
    assert len(observed.cross_schema_negative_digest) == 32
    assert dml.closed is platform.closed is True
    assert dml.rollback_count == platform.rollback_count == 2
    assert "tenant_dml_1" not in repr(verifier)


def test_tenant_matrix_rejects_same_username_or_factory():
    factory = lambda: _Connection()
    with pytest.raises(DefaultMySqlGrantObservationInputError):
        DefaultMySqlTenantGrantMatrixVerifier(
            dml_connection_factory=factory,
            platform_read_connection_factory=factory,
            dml_username="tenant_dml_1",
            platform_read_username="platform_read_1",
            database_name="inventory_management_test",
            foreign_database_name="foreign_tenant",
        )


def test_control_grant_verifier_combines_exact_grants_and_tenant_denial():
    connection = _Connection(
        username="control_app_1",
        database="inventory_control_test",
        grants=tuple(
            _grant(
                item,
                object_schema="inventory_control_test",
            )
            for item in ("SELECT", "INSERT", "UPDATE", "DELETE")
        ),
    )
    verifier = DefaultMySqlControlGrantVerifier(
        connection_factory=lambda: connection,
        username="control_app_1",
        control_database_name="inventory_control_test",
        tenant_database_name="inventory_management_test",
    )

    observed = verifier()

    assert len(observed) == 32
    assert connection.closed is True
    assert connection.rollback_count == 2
    assert "control_app_1" not in repr(verifier)
    with pytest.raises(DefaultMySqlGrantObservationInputError):
        DefaultMySqlTenantGrantMatrixVerifier(
            dml_connection_factory=lambda: _Connection(),
            platform_read_connection_factory=lambda: _Connection(),
            dml_username="shared_account",
            platform_read_username="shared_account",
            database_name="inventory_management_test",
            foreign_database_name="foreign_tenant",
        )

import pytest
from sqlalchemy.dialects.mysql import dialect as mysql_dialect
from sqlalchemy.engine import make_url
from types import SimpleNamespace

from tests.support.test_database import (
    DatabaseWriteDisposition,
    DatabaseWriteRefused,
    DatabaseObservationProfile,
    ProductionReadCapability,
    TEST_ALEMBIC_GENERATION_SQL,
    TEST_CURRENT_ROLE_SQL,
    TEST_DATABASE_PROFILE_SQL,
    TEST_IDENTITY_GENERATION_SQL,
    TEST_MARIADB_PUBLIC_GRANTS_SQL,
    TEST_SCHEMA_ACQUIRE_LOCK_SQL,
    TEST_SCHEMA_COLUMN_INVENTORY_SQL,
    TEST_SCHEMA_EXTENSION_INVENTORY_STATEMENTS,
    TEST_SCHEMA_INVENTORY_SQL,
    TEST_SCHEMA_INDEX_INVENTORY_SQL,
    TEST_SCHEMA_RELEASE_LOCK_SQL,
    WRITABLE_TEST_DATABASE_NAME,
    assert_current_user_has_test_only_grants,
    assert_current_user_has_production_read_only_grants,
    assert_production_read_database_url,
    assert_test_database_url,
    _guard_test_statement,
    guarded_mysql_test_metadata,
    guarded_mysql_test_schema_migration,
    observe_test_database_schema,
    open_production_read_only_probe,
    preflight_test_database_write,
)


@pytest.fixture(autouse=True)
def _explicitly_enable_real_test_database_guard(monkeypatch):
    """Unit fakes exercise the opt-in gate without opening a socket."""

    monkeypatch.setenv("ALLOW_REAL_TEST_DATABASE", "true")


def test_database_write_guard_accepts_only_explicit_test_schema(monkeypatch):
    monkeypatch.setenv("TESTING", "true")

    parsed = assert_test_database_url(
        f"mysql+pymysql://tester:secret@127.0.0.1/{WRITABLE_TEST_DATABASE_NAME}"
    )

    assert parsed.database == WRITABLE_TEST_DATABASE_NAME


@pytest.mark.parametrize(
    "url",
    [
        "mysql+pymysql://tester:secret@127.0.0.1/inventory_management",
        "mysql+pymysql://tester:secret@127.0.0.1/inventory_management_test_copy",
        "mysql+pymysql://tester:secret@127.0.0.1/test",
        "sqlite:///inventory_management_test",
    ],
)
def test_database_write_guard_rejects_every_other_schema(monkeypatch, url):
    monkeypatch.setenv("TESTING", "true")

    with pytest.raises(RuntimeError):
        assert_test_database_url(url)


def test_database_write_guard_requires_testing_mode(monkeypatch):
    monkeypatch.delenv("TESTING", raising=False)

    with pytest.raises(RuntimeError, match="TESTING=true"):
        assert_test_database_url(
            "mysql+pymysql://tester:secret@127.0.0.1/" f"{WRITABLE_TEST_DATABASE_NAME}"
        )


def test_database_write_guard_requires_explicit_real_database_opt_in(
    monkeypatch,
):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.delenv("ALLOW_REAL_TEST_DATABASE", raising=False)

    with pytest.raises(RuntimeError, match="ALLOW_REAL_TEST_DATABASE=true"):
        assert_test_database_url(
            "mysql+pymysql://tester:secret@127.0.0.1/" f"{WRITABLE_TEST_DATABASE_NAME}"
        )


def test_production_read_url_requires_explicit_mode_and_never_accepts_test_db(
    monkeypatch,
):
    production_url = "mysql+pymysql://reader:secret@lan/inventory_management"
    monkeypatch.delenv("ALLOW_PRODUCTION_READ_ONLY", raising=False)
    with pytest.raises(RuntimeError, match="ALLOW_PRODUCTION_READ_ONLY"):
        assert_production_read_database_url(production_url)

    monkeypatch.setenv("ALLOW_PRODUCTION_READ_ONLY", "true")
    assert assert_production_read_database_url(production_url).database == (
        "inventory_management"
    )
    with pytest.raises(RuntimeError, match="测试库"):
        assert_production_read_database_url(
            "mysql+pymysql://reader:secret@lan/inventory_management_test"
        )


@pytest.mark.parametrize(
    "option",
    [
        "init_command=DROP%20TABLE%20rentals",
        "client_flag=65536",
        "read_default_file=/tmp/mysql.cnf",
        "local_infile=1",
        "allow_multi_statements=1",
    ],
)
def test_database_urls_reject_preconnect_execution_and_config_hooks(
    monkeypatch,
    option,
):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("ALLOW_PRODUCTION_READ_ONLY", "true")
    with pytest.raises(RuntimeError, match="连接选项"):
        assert_test_database_url(
            "mysql+pymysql://tester:secret@lan/inventory_management_test?" + option
        )
    with pytest.raises(RuntimeError, match="连接选项"):
        assert_production_read_database_url(
            "mysql+pymysql://reader:secret@lan/inventory_management?" + option
        )


_MISSING = object()


class _FakeResult:
    def __init__(self, rows=(), scalar=_MISSING):
        self.rows = tuple(rows)
        self.scalar = scalar

    def all(self):
        return list(self.rows)

    def fetchmany(self, size):
        return list(self.rows[:size])

    def scalar_one(self):
        assert self.scalar is not _MISSING
        return self.scalar

    def close(self):
        return None


class _GrantConnection:
    def __init__(
        self,
        grants,
        database="inventory_management",
        schema_rows=None,
        current_role="NONE",
        lock_result=1,
        release_result=1,
        database_version="8.0.30",
        database_version_comment="MySQL Community Server - GPL",
        public_grants=None,
    ):
        self.grants = grants
        self.database = database
        self.schema_rows = dict(schema_rows or {})
        self.current_role = current_role
        self.lock_result = lock_result
        self.release_result = release_result
        self.database_version = database_version
        self.database_version_comment = database_version_comment
        self.public_grants = (
            ["GRANT USAGE ON *.* TO PUBLIC"] if public_grants is None else public_grants
        )
        self.executed = []
        self.closed = False
        self.commit_count = 0
        self.rollback_count = 0

    def exec_driver_sql(self, statement):
        self.executed.append(statement)
        if statement.startswith("DROP TABLE IF EXISTS "):
            table_name = statement.rsplit(" ", 1)[-1].strip("`").replace("``", "`")
            for inventory_statement in (
                TEST_SCHEMA_INVENTORY_SQL,
                TEST_SCHEMA_COLUMN_INVENTORY_SQL,
                *TEST_SCHEMA_EXTENSION_INVENTORY_STATEMENTS,
            ):
                self.schema_rows[inventory_statement] = [
                    row
                    for row in self.schema_rows.get(
                        inventory_statement,
                        (),
                    )
                    if not row or row[0] != table_name
                ]
            if table_name == "alembic_version":
                self.schema_rows[TEST_ALEMBIC_GENERATION_SQL] = []
            if table_name == "database_identity":
                self.schema_rows[TEST_IDENTITY_GENERATION_SQL] = []
            return _FakeResult()
        if statement == "SELECT DATABASE()":
            return _FakeResult(scalar=self.database)
        if statement == TEST_CURRENT_ROLE_SQL:
            return _FakeResult(scalar=self.current_role)
        if statement == TEST_DATABASE_PROFILE_SQL:
            return _FakeResult([(self.database_version, self.database_version_comment)])
        if statement == "SHOW GRANTS FOR CURRENT_USER":
            return _FakeResult((grant,) for grant in self.grants)
        if statement == TEST_MARIADB_PUBLIC_GRANTS_SQL:
            return _FakeResult((grant,) for grant in self.public_grants)
        if statement == TEST_SCHEMA_ACQUIRE_LOCK_SQL:
            return _FakeResult(scalar=self.lock_result)
        if statement == TEST_SCHEMA_RELEASE_LOCK_SQL:
            return _FakeResult(scalar=self.release_result)
        return _FakeResult(self.schema_rows.get(statement, ()))

    def rollback(self):
        self.rollback_count += 1

    def commit(self):
        self.commit_count += 1

    def close(self):
        self.closed = True


class _FakeMySQLEngine:
    def __init__(self, connection):
        self.url = make_url(_test_database_url())
        self.dialect = mysql_dialect()
        self.connection = connection
        self.connection.dialect = self.dialect
        self.connect_count = 0

    def connect(self):
        self.connect_count += 1
        return self.connection


class _FakeMetadata:
    def __init__(self):
        self.calls = []
        self.tables = {
            name: SimpleNamespace(name=name, schema=None)
            for name in ("alembic_version", "database_identity", "rentals")
        }

    def create_all(self, *, bind):
        self.calls.append(("create_all", bind))
        bind.executed.append("DDL:create_all")
        bind.schema_rows = _current_schema_rows()

    def drop_all(self, *, bind):
        self.calls.append(("drop_all", bind))
        bind.executed.append("DDL:drop_all")
        bind.schema_rows = {}


class _DriftingGrantConnection(_GrantConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.inventory_round = 0

    def exec_driver_sql(self, statement):
        if statement == TEST_SCHEMA_INVENTORY_SQL:
            self.inventory_round += 1
        if statement == TEST_SCHEMA_INDEX_INVENTORY_SQL and self.inventory_round >= 2:
            self.executed.append(statement)
            return _FakeResult(
                [
                    (
                        "rentals",
                        "drifted_idx",
                        1,
                        1,
                        "id",
                        "A",
                        None,
                        "YES",
                        "BTREE",
                        "",
                        "",
                    )
                ]
            )
        return super().exec_driver_sql(statement)


def _current_schema_rows():
    return {
        TEST_SCHEMA_INVENTORY_SQL: [
            (
                "alembic_version",
                "BASE TABLE",
                "InnoDB",
                "utf8mb4_unicode_ci",
            ),
            (
                "database_identity",
                "BASE TABLE",
                "InnoDB",
                "utf8mb4_unicode_ci",
            ),
            ("rentals", "BASE TABLE", "InnoDB", "utf8mb4_unicode_ci"),
        ],
        TEST_SCHEMA_COLUMN_INVENTORY_SQL: [
            (
                "alembic_version",
                "version_num",
                1,
                "varchar(32)",
                "NO",
                None,
                "",
            ),
            (
                "database_identity",
                "singleton_key",
                1,
                "smallint",
                "NO",
                None,
                "",
            ),
            (
                "database_identity",
                "schema_generation",
                2,
                "bigint",
                "NO",
                None,
                "",
            ),
            ("rentals", "id", 1, "int", "NO", None, "auto_increment"),
        ],
        TEST_ALEMBIC_GENERATION_SQL: [("20260822_db_identity",)],
        TEST_IDENTITY_GENERATION_SQL: [(1, 17)],
    }


def _expected_inventory_statements(*, include_generations=True):
    statements = [
        TEST_DATABASE_PROFILE_SQL,
        TEST_SCHEMA_INVENTORY_SQL,
        TEST_SCHEMA_COLUMN_INVENTORY_SQL,
        *TEST_SCHEMA_EXTENSION_INVENTORY_STATEMENTS,
    ]
    if include_generations:
        statements.extend([TEST_ALEMBIC_GENERATION_SQL, TEST_IDENTITY_GENERATION_SQL])
    return statements


def _test_database_connection(*, grants=None, schema_rows=None, **connection_options):
    return _GrantConnection(
        (
            [
                "GRANT USAGE ON *.* TO `tester`@`%`",
                "GRANT ALL PRIVILEGES ON `inventory_management_test`.* "
                "TO `tester`@`%`",
            ]
            if grants is None
            else grants
        ),
        database=WRITABLE_TEST_DATABASE_NAME,
        schema_rows=(_current_schema_rows() if schema_rows is None else schema_rows),
        **connection_options,
    )


def _test_database_url(database=WRITABLE_TEST_DATABASE_NAME):
    return f"mysql+pymysql://tester:secret@lan/{database}?charset=utf8mb4"


def test_production_account_must_be_exact_database_read_only():
    assert_current_user_has_production_read_only_grants(
        _GrantConnection(
            [
                "GRANT USAGE ON *.* TO `reader`@`%`",
                "GRANT SELECT, SHOW VIEW ON `inventory_management`.* TO `reader`@`%`",
            ]
        ),
        "inventory_management",
    )

    for unsafe_grant in (
        "GRANT SELECT, UPDATE ON `inventory_management`.* TO `reader`@`%`",
        "GRANT SELECT ON *.* TO `reader`@`%`",
        "GRANT SELECT ON `inventory_management_test`.* TO `reader`@`%`",
        "GRANT SELECT ON `inventory_management`.* TO `reader`@`%` WITH GRANT OPTION",
        "GRANT USAGE ON *.* TO `reader`@`%` WITH GRANT OPTION",
    ):
        with pytest.raises(RuntimeError, match="只读账号"):
            assert_current_user_has_production_read_only_grants(
                _GrantConnection([unsafe_grant]),
                "inventory_management",
            )


def test_test_account_grants_are_scoped_to_exact_writable_test_database():
    assert_current_user_has_test_only_grants(
        _GrantConnection(
            [
                "GRANT USAGE ON *.* TO `tester`@`%`",
                "GRANT ALL PRIVILEGES ON `inventory_management_test`.* "
                "TO `tester`@`%`",
            ],
            database=WRITABLE_TEST_DATABASE_NAME,
        ),
        WRITABLE_TEST_DATABASE_NAME,
    )

    with pytest.raises(RuntimeError, match="inventory_management_test"):
        assert_current_user_has_test_only_grants(
            _GrantConnection(
                ["GRANT ALL PRIVILEGES ON `inventory_management`.* " "TO `tester`@`%`"]
            ),
            "inventory_management",
        )

    for unsafe_grants in (
        [],
        ["GRANT USAGE ON *.* TO `tester`@`%` WITH GRANT OPTION"],
        [
            "GRANT ALL PRIVILEGES ON `inventory_management_test`.* "
            "TO `tester`@`%` WITH GRANT OPTION"
        ],
    ):
        with pytest.raises(RuntimeError, match="权限"):
            assert_current_user_has_test_only_grants(
                _GrantConnection(
                    unsafe_grants,
                    database=WRITABLE_TEST_DATABASE_NAME,
                ),
                WRITABLE_TEST_DATABASE_NAME,
            )

    with pytest.raises(RuntimeError, match="测试库以外"):
        assert_current_user_has_test_only_grants(
            _GrantConnection(
                [
                    "GRANT ALL PRIVILEGES ON `inventory_management_test`.* "
                    "TO `tester`@`%`",
                    "GRANT SELECT ON `inventory_management`.* TO `tester`@`%`",
                ],
                database=WRITABLE_TEST_DATABASE_NAME,
            ),
            WRITABLE_TEST_DATABASE_NAME,
        )


def test_global_dba_test_account_requires_explicit_opt_in(monkeypatch):
    connection = _test_database_connection(
        grants=("GRANT ALL PRIVILEGES ON *.* TO `dba`@`%` WITH GRANT OPTION",)
    )
    with pytest.raises(RuntimeError):
        assert_current_user_has_test_only_grants(
            connection,
            WRITABLE_TEST_DATABASE_NAME,
        )

    monkeypatch.setenv("ALLOW_GLOBAL_DBA_TEST_ACCOUNT", "true")
    assert_current_user_has_test_only_grants(
        connection,
        WRITABLE_TEST_DATABASE_NAME,
    )


@pytest.mark.parametrize(
    "statement",
    (
        "USE inventory_management",
        "DROP DATABASE inventory_management_test",
        "GRANT SELECT ON *.* TO reader",
        "CREATE USER reader IDENTIFIED BY 'x'",
        "UPDATE `inventory_management`.`rentals` SET status='cancelled'",
    ),
)
def test_global_dba_statement_guard_rejects_instance_or_cross_schema_sql(
    statement,
):
    with pytest.raises(RuntimeError):
        _guard_test_statement(None, None, statement, None, None, False)


def test_global_dba_statement_guard_allows_selected_schema_orm_sql():
    _guard_test_statement(
        None,
        None,
        "UPDATE `inventory_management_test`.`rentals` SET status=%s",
        None,
        None,
        False,
    )


@pytest.mark.parametrize("production", [False, True])
def test_database_grant_guards_reject_any_active_or_mandatory_role(production):
    connection = _GrantConnection(
        [
            (
                "GRANT SELECT ON `inventory_management`.* TO `reader`@`%`"
                if production
                else "GRANT ALL PRIVILEGES ON `inventory_management_test`.* "
                "TO `tester`@`%`"
            )
        ],
        database=(
            "inventory_management" if production else WRITABLE_TEST_DATABASE_NAME
        ),
        current_role="`mandatory_writer`@`%`",
    )

    with pytest.raises(RuntimeError, match="role"):
        if production:
            assert_current_user_has_production_read_only_grants(
                connection,
                "inventory_management",
            )
        else:
            assert_current_user_has_test_only_grants(
                connection,
                WRITABLE_TEST_DATABASE_NAME,
            )

    assert connection.executed == ["SELECT DATABASE()", TEST_CURRENT_ROLE_SQL]


def test_test_schema_preflight_rejects_url_before_connector(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    connected = []

    with pytest.raises(RuntimeError, match="inventory_management_test"):
        preflight_test_database_write(
            _test_database_url("inventory_management"),
            lambda parsed: connected.append(parsed),
            disposition="metadata_rebuild",
        )

    assert connected == []


def test_test_schema_preflight_checks_grants_before_inventory(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    connection = _test_database_connection(
        grants=[
            "GRANT ALL PRIVILEGES ON `inventory_management_test`.* " "TO `tester`@`%`",
            "GRANT SELECT ON `inventory_management`.* TO `tester`@`%`",
        ]
    )

    with pytest.raises(RuntimeError, match="测试库以外"):
        preflight_test_database_write(
            _test_database_url(),
            lambda _parsed: connection,
            disposition="metadata_rebuild",
        )

    assert connection.executed == [
        "SELECT DATABASE()",
        TEST_CURRENT_ROLE_SQL,
        TEST_DATABASE_PROFILE_SQL,
        "SHOW GRANTS FOR CURRENT_USER",
    ]
    assert connection.closed is True


def test_nonempty_test_schema_without_disposition_fails_closed(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    connection = _test_database_connection()

    with pytest.raises(DatabaseWriteRefused, match="fail_closed") as caught:
        preflight_test_database_write(
            _test_database_url(),
            lambda _parsed: connection,
        )

    preflight = caught.value.preflight
    assert preflight.disposition is DatabaseWriteDisposition.FAIL_CLOSED
    assert preflight.is_empty is False
    assert preflight.is_drifted is False
    assert len(preflight.preflight_digest) == 64
    assert connection.closed is True


@pytest.mark.parametrize(
    ("version", "comment", "profile"),
    [
        (
            "8.0.30",
            "MySQL Community Server - GPL",
            DatabaseObservationProfile.MYSQL_8,
        ),
        (
            "8.0.36-commercial",
            "MySQL Enterprise Server - Commercial",
            DatabaseObservationProfile.MYSQL_8,
        ),
        (
            "8.0.36-0ubuntu0.22.04.1",
            "Ubuntu 22.04",
            DatabaseObservationProfile.MYSQL_8,
        ),
        (
            "8.0.36-1debian12",
            "Debian 12",
            DatabaseObservationProfile.MYSQL_8,
        ),
        (
            "8.0.36-custom",
            "Source distribution",
            DatabaseObservationProfile.MYSQL_8,
        ),
        (
            "10.11.8-MariaDB-0ubuntu0.24.04.1",
            "Ubuntu 24.04",
            DatabaseObservationProfile.MARIADB_10_11,
        ),
    ],
)
def test_schema_preflight_selects_fixed_mysql_or_mariadb_profile(
    monkeypatch,
    version,
    comment,
    profile,
):
    monkeypatch.setenv("TESTING", "true")
    connection = _test_database_connection(
        database_version=version,
        database_version_comment=comment,
    )

    preflight = preflight_test_database_write(
        _test_database_url(),
        lambda _parsed: connection,
        disposition="metadata_rebuild",
    )

    assert preflight.database_profile is profile
    assert preflight.database_version == version
    assert connection.executed.index(TEST_DATABASE_PROFILE_SQL) < (
        connection.executed.index(TEST_SCHEMA_INVENTORY_SQL)
    )
    if profile is DatabaseObservationProfile.MARIADB_10_11:
        assert TEST_MARIADB_PUBLIC_GRANTS_SQL in connection.executed
    else:
        assert TEST_MARIADB_PUBLIC_GRANTS_SQL not in connection.executed


@pytest.mark.parametrize("production", [False, True])
@pytest.mark.parametrize(
    "public_grants",
    [
        ["GRANT SELECT ON `inventory_management`.* TO PUBLIC"],
        ["GRANT ALL PRIVILEGES ON `inventory_management_test`.* TO PUBLIC"],
        ["GRANT FILE ON *.* TO PUBLIC"],
        ["GRANT `writer_role` TO PUBLIC"],
    ],
)
def test_mariadb_public_role_must_be_provably_usage_only(
    production,
    public_grants,
):
    connection = _GrantConnection(
        [
            (
                "GRANT SELECT ON `inventory_management`.* TO `reader`@`%`"
                if production
                else "GRANT ALL PRIVILEGES ON `inventory_management_test`.* "
                "TO `tester`@`%`"
            )
        ],
        database=(
            "inventory_management" if production else WRITABLE_TEST_DATABASE_NAME
        ),
        database_version="10.11.8-MariaDB-0ubuntu0.24.04.1",
        database_version_comment="Ubuntu 24.04",
        public_grants=public_grants,
    )

    with pytest.raises(RuntimeError, match="PUBLIC"):
        if production:
            assert_current_user_has_production_read_only_grants(
                connection,
                "inventory_management",
            )
        else:
            assert_current_user_has_test_only_grants(
                connection,
                WRITABLE_TEST_DATABASE_NAME,
            )

    assert TEST_MARIADB_PUBLIC_GRANTS_SQL in connection.executed
    assert "SHOW GRANTS FOR CURRENT_USER" not in connection.executed


@pytest.mark.parametrize("production", [False, True])
def test_mariadb_empty_public_grants_prove_no_inherited_privilege(production):
    connection = _GrantConnection(
        [
            (
                "GRANT SELECT ON `inventory_management`.* TO `reader`@`%`"
                if production
                else "GRANT ALL PRIVILEGES ON `inventory_management_test`.* "
                "TO `tester`@`%`"
            )
        ],
        database=(
            "inventory_management" if production else WRITABLE_TEST_DATABASE_NAME
        ),
        database_version="10.11.8-MariaDB-0ubuntu0.24.04.1",
        database_version_comment="Ubuntu 24.04",
        public_grants=[],
    )

    if production:
        assert_current_user_has_production_read_only_grants(
            connection,
            "inventory_management",
        )
    else:
        assert_current_user_has_test_only_grants(
            connection,
            WRITABLE_TEST_DATABASE_NAME,
        )

    assert TEST_MARIADB_PUBLIC_GRANTS_SQL in connection.executed
    assert "SHOW GRANTS FOR CURRENT_USER" in connection.executed


@pytest.mark.parametrize(
    ("version", "comment"),
    [
        ("5.7.44", "MySQL Community Server - GPL"),
        ("8.0.30-MariaDB-spoof", "MySQL Community Server - GPL"),
        ("10.11.8-MariaDB", "MySQL Community Server - GPL"),
        ("8.0.30", "unknown compatible server"),
        ("8.0.36-28-Percona", "Percona Server (GPL)"),
        ("8.0.36-mysql_aurora.3.07.1", "MySQL Community Server - GPL"),
        ("8.0.36-TiDB", "TiDB Server (Apache License 2.0)"),
    ],
)
def test_unknown_or_contradictory_database_profile_fails_closed(
    monkeypatch,
    version,
    comment,
):
    monkeypatch.setenv("TESTING", "true")
    connection = _test_database_connection(
        database_version=version,
        database_version_comment=comment,
    )

    with pytest.raises(RuntimeError, match="profile|标识|vendor"):
        preflight_test_database_write(
            _test_database_url(),
            lambda _parsed: connection,
            disposition="metadata_rebuild",
        )

    assert connection.closed is True


def test_metadata_rebuild_records_actual_schema_digest_and_only_reads(
    monkeypatch,
    caplog,
):
    monkeypatch.setenv("TESTING", "true")
    connection = _test_database_connection()
    caplog.set_level("WARNING", logger="tests.support.test_database")

    preflight = preflight_test_database_write(
        _test_database_url(),
        lambda _parsed: connection,
        disposition="metadata_rebuild",
    )

    assert preflight.disposition is DatabaseWriteDisposition.METADATA_REBUILD
    assert preflight.alembic_versions == ("20260822_db_identity",)
    assert preflight.identity_generations == ((1, 17),)
    assert preflight.is_drifted is False
    assert preflight.preflight_digest in caplog.text
    assert connection.executed == [
        "SELECT DATABASE()",
        TEST_CURRENT_ROLE_SQL,
        TEST_DATABASE_PROFILE_SQL,
        "SHOW GRANTS FOR CURRENT_USER",
        *_expected_inventory_statements(),
    ]
    assert all(
        statement.split(maxsplit=1)[0] in {"SELECT", "SHOW"}
        for statement in connection.executed
    )
    assert connection.closed is True


def test_metadata_rebuild_is_explicitly_allowed_for_drifted_legacy_schema(
    monkeypatch,
):
    monkeypatch.setenv("TESTING", "true")
    connection = _test_database_connection(
        schema_rows={
            TEST_SCHEMA_INVENTORY_SQL: [
                ("rentals", "BASE TABLE", "InnoDB", "utf8mb3_general_ci")
            ],
            TEST_SCHEMA_COLUMN_INVENTORY_SQL: [
                ("rentals", "id", 1, "int", "NO", None, "auto_increment")
            ],
        }
    )

    preflight = preflight_test_database_write(
        _test_database_url(),
        lambda _parsed: connection,
        disposition="metadata_rebuild",
    )

    assert preflight.is_drifted is True
    assert preflight.drift_reasons == (
        "missing_alembic_generation",
        "missing_identity_generation",
    )
    assert TEST_ALEMBIC_GENERATION_SQL not in connection.executed
    assert TEST_IDENTITY_GENERATION_SQL not in connection.executed


@pytest.mark.parametrize(
    ("view_name", "drift_reason"),
    [
        (
            "alembic_version",
            "invalid_alembic_generation_table_inventory",
        ),
        (
            "database_identity",
            "invalid_identity_generation_table_inventory",
        ),
    ],
)
def test_generation_view_inventory_never_triggers_direct_select(
    monkeypatch,
    view_name,
    drift_reason,
):
    monkeypatch.setenv("TESTING", "true")
    schema_rows = _current_schema_rows()
    schema_rows[TEST_SCHEMA_INVENTORY_SQL] = [
        (
            row[0],
            "VIEW" if row[0] == view_name else row[1],
            row[2],
            row[3],
        )
        for row in schema_rows[TEST_SCHEMA_INVENTORY_SQL]
    ]
    connection = _test_database_connection(schema_rows=schema_rows)

    preflight = preflight_test_database_write(
        _test_database_url(),
        lambda _parsed: connection,
        disposition="metadata_rebuild",
    )

    assert drift_reason in preflight.drift_reasons
    assert preflight.alembic_versions == ()
    assert preflight.identity_generations == ()
    assert TEST_ALEMBIC_GENERATION_SQL not in connection.executed
    assert TEST_IDENTITY_GENERATION_SQL not in connection.executed


def test_duplicate_table_inventory_never_triggers_generation_selects(
    monkeypatch,
):
    monkeypatch.setenv("TESTING", "true")
    schema_rows = _current_schema_rows()
    schema_rows[TEST_SCHEMA_INVENTORY_SQL] = [
        *schema_rows[TEST_SCHEMA_INVENTORY_SQL],
        ("rentals", "BASE TABLE", "InnoDB", "utf8mb4_unicode_ci"),
    ]
    connection = _test_database_connection(schema_rows=schema_rows)

    preflight = preflight_test_database_write(
        _test_database_url(),
        lambda _parsed: connection,
        disposition="metadata_rebuild",
    )

    assert "duplicate_table_inventory" in preflight.drift_reasons
    assert preflight.alembic_versions == ()
    assert preflight.identity_generations == ()
    assert TEST_ALEMBIC_GENERATION_SQL not in connection.executed
    assert TEST_IDENTITY_GENERATION_SQL not in connection.executed


def test_migrate_requires_and_verifies_observed_source_digest(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    baseline = preflight_test_database_write(
        _test_database_url(),
        lambda _parsed: _test_database_connection(),
        disposition="metadata_rebuild",
    )
    connected = []

    with pytest.raises(RuntimeError, match="必须钉住"):
        preflight_test_database_write(
            _test_database_url(),
            lambda parsed: connected.append(parsed),
            disposition="migrate",
        )
    assert connected == []

    migration_preflight = preflight_test_database_write(
        _test_database_url(),
        lambda _parsed: _test_database_connection(),
        disposition="migrate",
        expected_preflight_digest=baseline.preflight_digest,
    )
    assert migration_preflight.disposition is DatabaseWriteDisposition.MIGRATE

    drifted_rows = _current_schema_rows()
    drifted_rows[TEST_SCHEMA_COLUMN_INVENTORY_SQL] = [
        *drifted_rows[TEST_SCHEMA_COLUMN_INVENTORY_SQL],
        ("rentals", "unexpected", 2, "text", "YES", None, ""),
    ]
    drifted_connection = _test_database_connection(schema_rows=drifted_rows)
    with pytest.raises(DatabaseWriteRefused, match="digest") as caught:
        preflight_test_database_write(
            _test_database_url(),
            lambda _parsed: drifted_connection,
            disposition="migrate",
            expected_preflight_digest=baseline.preflight_digest,
        )
    assert caught.value.preflight.preflight_digest != (baseline.preflight_digest)
    assert drifted_connection.closed is True


def test_migration_observation_is_read_only_and_does_not_authorize_writes(
    monkeypatch,
):
    monkeypatch.setenv("TESTING", "true")
    connection = _test_database_connection()

    observed = observe_test_database_schema(
        _test_database_url(),
        lambda _parsed: connection,
    )

    assert observed.disposition is DatabaseWriteDisposition.FAIL_CLOSED
    assert len(observed.preflight_digest) == 64
    assert all(
        statement.split(maxsplit=1)[0] in {"SELECT", "SHOW"}
        for statement in connection.executed
    )
    assert connection.closed is True


def test_guarded_mysql_migration_pins_digest_under_shared_schema_lock(
    monkeypatch,
):
    monkeypatch.setenv("TESTING", "true")
    baseline_connection = _test_database_connection()
    observed = observe_test_database_schema(
        _test_database_url(),
        lambda _parsed: baseline_connection,
    )
    migration_connection = _test_database_connection()
    engine = _FakeMySQLEngine(migration_connection)

    with pytest.raises(ValueError, match="body failed"):
        with guarded_mysql_test_schema_migration(
            engine,
            expected_preflight_digest=observed.preflight_digest,
        ) as (connection, preflight):
            assert connection is migration_connection
            assert preflight.preflight_digest == observed.preflight_digest
            assert migration_connection.executed.index(
                TEST_SCHEMA_ACQUIRE_LOCK_SQL
            ) < migration_connection.executed.index(TEST_SCHEMA_INVENTORY_SQL)
            raise ValueError("body failed")

    assert migration_connection.executed[-1] == (TEST_SCHEMA_RELEASE_LOCK_SQL)
    assert migration_connection.commit_count == 1
    assert migration_connection.closed is True


def test_guarded_mysql_migration_rejects_drift_before_yield(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    baseline = observe_test_database_schema(
        _test_database_url(),
        lambda _parsed: _test_database_connection(),
    )
    drifted_rows = _current_schema_rows()
    drifted_rows[TEST_SCHEMA_COLUMN_INVENTORY_SQL] = [
        *drifted_rows[TEST_SCHEMA_COLUMN_INVENTORY_SQL],
        ("rentals", "unexpected", 2, "text", "YES", None, ""),
    ]
    connection = _test_database_connection(schema_rows=drifted_rows)
    engine = _FakeMySQLEngine(connection)

    with pytest.raises(DatabaseWriteRefused, match="digest"):
        with guarded_mysql_test_schema_migration(
            engine,
            expected_preflight_digest=baseline.preflight_digest,
        ):
            pytest.fail("migration guard must reject drift before yielding")

    assert TEST_SCHEMA_RELEASE_LOCK_SQL in connection.executed
    assert connection.closed is True


@pytest.mark.parametrize(
    ("statement", "width"),
    tuple(
        zip(
            TEST_SCHEMA_EXTENSION_INVENTORY_STATEMENTS,
            (11, 3, 10, 3, 10, 8, 13, 13, 8, 15),
            strict=True,
        )
    ),
)
def test_schema_digest_includes_every_extension_object_inventory(
    monkeypatch,
    statement,
    width,
):
    monkeypatch.setenv("TESTING", "true")
    baseline = preflight_test_database_write(
        _test_database_url(),
        lambda _parsed: _test_database_connection(),
        disposition="metadata_rebuild",
    )
    extension_rows = _current_schema_rows()
    extension_rows[statement] = [tuple(f"value-{index}" for index in range(width))]
    changed_connection = _test_database_connection(schema_rows=extension_rows)

    changed = preflight_test_database_write(
        _test_database_url(),
        lambda _parsed: changed_connection,
        disposition="metadata_rebuild",
    )

    assert statement in changed_connection.executed
    assert changed.preflight_digest != baseline.preflight_digest


def test_guarded_mysql_metadata_holds_one_connection_lock_through_teardown(
    monkeypatch,
):
    monkeypatch.setenv("TESTING", "true")
    connection = _test_database_connection()
    engine = _FakeMySQLEngine(connection)
    metadata = _FakeMetadata()
    drop_statement = "DROP TABLE IF EXISTS " + (
        engine.dialect.identifier_preparer.quote("rentals")
    )

    with pytest.raises(ValueError, match="body failed"):
        with guarded_mysql_test_metadata(engine, metadata) as preflight:
            assert preflight.database_name == WRITABLE_TEST_DATABASE_NAME
            assert connection.executed.index(TEST_SCHEMA_ACQUIRE_LOCK_SQL) < (
                connection.executed.index("DDL:create_all")
            )
            assert connection.executed.index(drop_statement) < (
                connection.executed.index("DDL:create_all")
            )
            raise ValueError("body failed")

    assert engine.connect_count == 1
    assert metadata.calls == [("create_all", connection)]
    assert connection.executed[-1] == TEST_SCHEMA_RELEASE_LOCK_SQL
    assert connection.executed.count(drop_statement) == 2
    assert connection.executed.index(
        drop_statement,
        connection.executed.index("DDL:create_all"),
    ) < connection.executed.index(TEST_SCHEMA_RELEASE_LOCK_SQL)
    assert connection.commit_count == 3
    assert connection.closed is True
    assert connection.executed.count(TEST_CURRENT_ROLE_SQL) >= 10


def test_guarded_mysql_metadata_revalidates_digest_before_any_ddl(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    baseline = _test_database_connection()
    connection = _DriftingGrantConnection(
        baseline.grants,
        database=WRITABLE_TEST_DATABASE_NAME,
        schema_rows=_current_schema_rows(),
    )
    engine = _FakeMySQLEngine(connection)
    metadata = _FakeMetadata()

    with pytest.raises(DatabaseWriteRefused, match="digest"):
        with guarded_mysql_test_metadata(engine, metadata):
            pytest.fail("DDL guard must fail before yielding")

    assert metadata.calls == []
    assert TEST_SCHEMA_RELEASE_LOCK_SQL in connection.executed
    assert connection.closed is True


def test_production_probe_exposes_only_one_fixed_bounded_observation(
    monkeypatch,
):
    monkeypatch.setenv("ALLOW_PRODUCTION_READ_ONLY", "true")
    connection = _GrantConnection(
        ["GRANT SELECT ON `inventory_management`.* TO `reader`@`%`"],
        schema_rows=_current_schema_rows(),
    )
    connected = []

    def connector(parsed):
        connected.append(parsed.database)
        return connection

    probe = open_production_read_only_probe(
        "mysql+pymysql://reader:secret@lan/inventory_management?charset=utf8mb4",
        connector,
    )
    assert connected == ["inventory_management"]
    observation = probe.observe(
        ProductionReadCapability.SCHEMA_METADATA_AND_GENERATIONS_V1
    )
    assert observation.schema.alembic_versions == ("20260822_db_identity",)
    assert connection.executed == [
        "SELECT DATABASE()",
        TEST_CURRENT_ROLE_SQL,
        TEST_DATABASE_PROFILE_SQL,
        "SHOW GRANTS FOR CURRENT_USER",
        *_expected_inventory_statements(),
    ]
    assert connection.closed is True
    assert connection.rollback_count == 1
    with pytest.raises(RuntimeError, match="已经关闭"):
        probe.observe(ProductionReadCapability.SCHEMA_METADATA_AND_GENERATIONS_V1)


@pytest.mark.parametrize(
    "caller_sql",
    [
        "SELECT side_effecting_function()",
        "SELECT * FROM side_effecting_definer_view",
        "SELECT service_get_write_locks('ns', 'lock', 60)",
        "SELECT sys_exec('touch /tmp/never')",
    ],
)
def test_production_probe_rejects_all_caller_sql_and_closes(
    monkeypatch,
    caller_sql,
):
    monkeypatch.setenv("ALLOW_PRODUCTION_READ_ONLY", "true")
    connection = _GrantConnection(
        ["GRANT SELECT ON `inventory_management`.* TO `reader`@`%`"]
    )
    probe = open_production_read_only_probe(
        "mysql+pymysql://reader:secret@lan/inventory_management",
        lambda _parsed: connection,
    )

    with pytest.raises(RuntimeError, match="不接受调用方 SQL"):
        probe.observe(caller_sql)

    assert connection.closed is True
    assert caller_sql not in connection.executed


def test_production_probe_rejects_driver_hook_before_connector_is_called(
    monkeypatch,
):
    monkeypatch.setenv("ALLOW_PRODUCTION_READ_ONLY", "true")
    connected = []

    with pytest.raises(RuntimeError, match="连接选项"):
        open_production_read_only_probe(
            "mysql+pymysql://reader:secret@lan/inventory_management"
            "?init_command=DELETE%20FROM%20rentals",
            lambda parsed: connected.append(parsed),
        )

    assert connected == []


def test_database_grant_guards_recheck_the_actual_selected_schema():
    test_grants = [
        "GRANT ALL PRIVILEGES ON `inventory_management_test`.* TO `tester`@`%`"
    ]
    with pytest.raises(RuntimeError, match="未选择"):
        assert_current_user_has_test_only_grants(
            _GrantConnection(test_grants, database="inventory_management"),
            WRITABLE_TEST_DATABASE_NAME,
        )

    production_grants = ["GRANT SELECT ON `inventory_management`.* TO `reader`@`%`"]
    with pytest.raises(RuntimeError, match="实际数据库"):
        assert_current_user_has_production_read_only_grants(
            _GrantConnection(
                production_grants,
                database="another_production_schema",
            ),
            "inventory_management",
        )

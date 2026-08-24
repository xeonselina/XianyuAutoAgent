from __future__ import annotations

from tests.support.run_existing_test_database import (
    DEFAULT_DATABASE_TEST_GROUPS,
)


def test_default_database_runner_has_no_four_physical_database_precondition():
    selected = {
        selector
        for group in DEFAULT_DATABASE_TEST_GROUPS
        for selector in group
    }
    assert "tests/integration/test_existing_test_database_migrations.py" in selected
    assert "tests/integration/test_default_expand_mysql_composition.py" not in selected

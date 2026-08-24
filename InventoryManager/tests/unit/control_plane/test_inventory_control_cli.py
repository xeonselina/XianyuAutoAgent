from __future__ import annotations

import io
import json

import sqlalchemy as sa

from inventory_control import ControlDatabase
from inventory_control.cli import main
from inventory_control.models import ControlBase, PlatformAdmin


def test_launcher_requires_control_database_without_echoing_configuration():
    stderr = io.StringIO()
    assert main([], environ={}, stdout=io.StringIO(), stderr=stderr) == 1
    assert stderr.getvalue() == "inventory control runtime unavailable\n"


def test_launcher_injects_only_control_database_into_platform_cli(
    mysql_control_database,
):
    database_url = mysql_control_database.engine.url.render_as_string(
        hide_password=False
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            "platform-admin",
            "create",
            "--username",
            "root.admin",
            "--setup-ttl-seconds",
            "600",
            "--os-operator-reference",
            "ops:jim",
            "--command-id",
            "command:bootstrap:launcher",
        ],
        environ={"CONTROL_DATABASE_URL": database_url},
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert payload["setup_token"].startswith("imps1_")
    with mysql_control_database.new_session() as session:
        assert session.scalar(
            sa.select(sa.func.count(PlatformAdmin.id))
        ) == 1


def test_launcher_rejects_cli_dsn_argument_without_echoing_it(
    mysql_control_database,
):
    database_url = mysql_control_database.engine.url.render_as_string(
        hide_password=False
    )
    injected_secret = "mysql://user:password@production.invalid/control"
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(
        ["platform-admin", "create", "--database-url", injected_secret],
        environ={"CONTROL_DATABASE_URL": database_url},
        stdout=stdout,
        stderr=stderr,
    ) == 2
    assert injected_secret not in stdout.getvalue()
    assert injected_secret not in stderr.getvalue()

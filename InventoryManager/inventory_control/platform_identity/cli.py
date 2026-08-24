"""Dependency-injected host CLI adapter for platform-admin bootstrap/reset."""

from __future__ import annotations

import argparse
import json
from datetime import timedelta, timezone
from functools import partial
from typing import TextIO

from inventory_control.database import ControlDatabase, read_database_utc_value

from .host_service import PlatformAdminHostService


class PlatformAdminCliApplication:
    """Parse only non-secret inputs; database authority is injected by host code."""

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        host_service: PlatformAdminHostService | None = None,
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise TypeError("control_database must be a ControlDatabase")
        self._control_database = control_database
        self._host_service = host_service or PlatformAdminHostService()

    def execute(
        self,
        argv: list[str],
        *,
        stdout: TextIO,
        stderr: TextIO,
    ) -> int:
        parser = _parser(stdout=stdout, stderr=stderr)
        try:
            arguments = parser.parse_args(argv)
        except SystemExit as exc:
            return int(exc.code)
        try:
            with self._control_database.transaction() as session:
                now = read_database_utc_value(session)
                if not hasattr(now, "tzinfo"):
                    raise RuntimeError("control database clock is invalid")
                if now.tzinfo is None:
                    now = now.replace(tzinfo=timezone.utc)
                if arguments.operation == "create":
                    issued = self._host_service.create_pending_admin(
                        session,
                        username=arguments.username,
                        setup_ttl=timedelta(
                            seconds=arguments.setup_ttl_seconds
                        ),
                        os_operator_reference=(
                            arguments.os_operator_reference
                        ),
                        command_id=arguments.command_id,
                        now=now,
                    )
                elif arguments.operation == "reset":
                    issued = self._host_service.begin_credential_recovery(
                        session,
                        username=arguments.username,
                        setup_ttl=timedelta(
                            seconds=arguments.setup_ttl_seconds
                        ),
                        os_operator_reference=(
                            arguments.os_operator_reference
                        ),
                        command_id=arguments.command_id,
                        now=now,
                    )
                else:
                    disabled = self._host_service.disable_admin(
                        session,
                        username=arguments.username,
                        os_operator_reference=(
                            arguments.os_operator_reference
                        ),
                        command_id=arguments.command_id,
                        now=now,
                    )
        except Exception:
            stderr.write("platform admin operation rejected\n")
            return 1
        if arguments.operation == "disable":
            payload = {
                "platform_admin_id": disabled.platform_admin_id,
                "revoked_session_count": disabled.revoked_session_count,
                "status": "disabled",
            }
        else:
            payload = {
                "platform_admin_id": issued.platform_admin_id,
                "setup_token": issued.plaintext_token,
                "expires_at": issued.expires_at.isoformat(),
            }
        stdout.write(
            json.dumps(
                payload,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )
        return 0


class _Parser(argparse.ArgumentParser):
    def __init__(self, *, stdout: TextIO, stderr: TextIO, **kwargs) -> None:
        self._stdout = stdout
        self._stderr = stderr
        super().__init__(**kwargs)

    def _print_message(self, message, file=None) -> None:
        if message:
            (self._stdout if file is None else self._stderr).write(message)

    def error(self, message) -> None:
        self.print_usage(self._stderr)
        self.exit(2, "inventoryctl: invalid arguments\n")


def _parser(*, stdout: TextIO, stderr: TextIO) -> argparse.ArgumentParser:
    parser = _Parser(
        stdout=stdout,
        stderr=stderr,
        prog="inventoryctl",
        description="Audited host-only Inventory Manager operations",
    )
    child_parser = partial(_Parser, stdout=stdout, stderr=stderr)
    group = parser.add_subparsers(
        dest="domain", required=True, parser_class=child_parser
    )
    platform_admin = group.add_parser("platform-admin")
    operations = platform_admin.add_subparsers(
        dest="operation", required=True, parser_class=child_parser
    )
    for name in ("create", "reset", "disable"):
        operation = operations.add_parser(name)
        operation.add_argument("--username", required=True)
        if name != "disable":
            operation.add_argument(
                "--setup-ttl-seconds",
                required=True,
                type=int,
            )
        operation.add_argument(
            "--os-operator-reference",
            required=True,
        )
        operation.add_argument("--command-id", required=True)
    return parser


__all__ = ["PlatformAdminCliApplication"]

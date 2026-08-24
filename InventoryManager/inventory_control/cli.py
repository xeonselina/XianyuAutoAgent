"""Production host launcher for credential-free Inventory Control commands."""

from __future__ import annotations

import os
import sys
from typing import Mapping, Sequence, TextIO

from .database import ControlDatabase
from .platform_identity.cli import PlatformAdminCliApplication


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] = os.environ,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Bind the host CLI to the explicitly configured control database only."""

    database_url = environ.get("CONTROL_DATABASE_URL")
    if not isinstance(database_url, str) or not database_url.strip():
        stderr.write("inventory control runtime unavailable\n")
        return 1
    database: ControlDatabase | None = None
    try:
        database = ControlDatabase.from_url(
            database_url,
            engine_options={"pool_pre_ping": True, "pool_recycle": 3600},
        )
        return PlatformAdminCliApplication(
            control_database=database
        ).execute(
            list(argv if argv is not None else sys.argv[1:]),
            stdout=stdout,
            stderr=stderr,
        )
    except Exception:
        stderr.write("inventory control runtime unavailable\n")
        return 1
    finally:
        if database is not None:
            database.dispose()


__all__ = ["main"]

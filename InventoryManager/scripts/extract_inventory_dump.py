"""Extract the production inventory schema into an explicitly test-only dump."""

from __future__ import annotations

import argparse
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path


SOURCE_DATABASE = "inventory_management"
SYSTEM_DATABASES = frozenset({
    "information_schema",
    "inventory_management",
    "mysql",
    "performance_schema",
    "sys",
})
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
USE_RE = re.compile(
    r"^\s*USE\s+(?P<identifier>`[A-Za-z0-9_$-]+`|[A-Za-z0-9_$-]+)\s*;",
    re.IGNORECASE,
)
CREATE_DATABASE_RE = re.compile(
    r"^\s*CREATE\s+DATABASE(?:\s+/\*.*?\*/)?"
    r"(?:\s+IF\s+NOT\s+EXISTS)?\s+"
    r"(?P<identifier>`[A-Za-z0-9_$-]+`|[A-Za-z0-9_$-]+)",
    re.IGNORECASE,
)
CURRENT_DATABASE_RE = re.compile(
    r"^(?P<prefix>\s*--\s*Current\s+Database:\s*)"
    r"(?P<identifier>`[A-Za-z0-9_$-]+`|[A-Za-z0-9_$-]+)(?P<suffix>.*)$",
    re.IGNORECASE,
)
DELIMITER_RE = re.compile(r"^\s*DELIMITER\s+(?P<delimiter>\S+)", re.IGNORECASE)
DATABASE_AFFECTING_RE = re.compile(
    r"^\s*(?:DROP\s+(?:DATABASE|SCHEMA)(?:\s+IF\s+EXISTS)?|"
    r"ALTER\s+(?:DATABASE|SCHEMA)|CREATE\s+SCHEMA"
    r"(?:\s+IF\s+NOT\s+EXISTS)?)\s+"
    r"(?P<identifier>`[A-Za-z0-9_$-]+`|[A-Za-z0-9_$-]+)",
    re.IGNORECASE,
)
QUALIFIED_DATABASE_RE = re.compile(
    r"`(?P<database>[A-Za-z0-9_$-]+)`\s*\.\s*`[A-Za-z0-9_$-]+`"
)
QUALIFIED_TABLE_DDL_RE = re.compile(
    r"^\s*(?:CREATE|ALTER|DROP|TRUNCATE)\s+TABLE"
    r"(?:\s+IF\s+(?:NOT\s+)?EXISTS)?\s+"
    r"(?P<database>[A-Za-z0-9_$-]+)\s*\.\s*"
    r"(?:`[A-Za-z0-9_$-]+`|[A-Za-z0-9_$-]+)",
    re.IGNORECASE,
)


class UnsafeDatabaseError(ValueError):
    """Raised when a dump extraction could affect a non-test database."""


@dataclass(frozen=True)
class DumpSummary:
    source_database: str
    target_database: str
    statements: int
    bytes_written: int


def _identifier(match: re.Match[str]) -> str:
    return match.group("identifier").strip("`").lower()


def _rewrite_identifier(line: str, match: re.Match[str], target_database: str) -> str:
    start, end = match.span("identifier")
    return f"{line[:start]}`{target_database}`{line[end:]}"


def _validate_target_database(target_database: str) -> None:
    normalized = target_database.lower()
    if not IDENTIFIER_RE.fullmatch(target_database):
        raise UnsafeDatabaseError("目标数据库名必须是安全的 MySQL 标识符")
    if "test" not in normalized:
        raise UnsafeDatabaseError("目标数据库名必须包含 test")
    if normalized in SYSTEM_DATABASES:
        raise UnsafeDatabaseError("拒绝系统库或生产默认库作为目标数据库")


def _validate_output(path: Path, target_database: str) -> None:
    target = target_database.lower()
    with path.open("r", encoding="utf-8", newline="") as output:
        for line in output:
            for matcher in (CURRENT_DATABASE_RE, CREATE_DATABASE_RE, USE_RE):
                match = matcher.match(line)
                if match and _identifier(match) != target:
                    raise UnsafeDatabaseError("提取结果仍包含其他数据库")
            _reject_unsafe_database_reference(line, target_database)


def _reject_unsafe_database_reference(line: str, target_database: str) -> None:
    target = target_database.lower()
    database_statement = DATABASE_AFFECTING_RE.match(line)
    if database_statement and _identifier(database_statement) != target:
        raise UnsafeDatabaseError("提取结果包含其他数据库引用")

    qualified_databases = [
        match.group("database").lower()
        for match in QUALIFIED_DATABASE_RE.finditer(line)
    ]
    table_ddl = QUALIFIED_TABLE_DDL_RE.match(line)
    if table_ddl:
        qualified_databases.append(table_ddl.group("database").lower())
    if any(database != target for database in qualified_databases):
        raise UnsafeDatabaseError("提取结果包含其他数据库引用")


def extract_database(
    input_path: Path,
    output_path: Path,
    target_database: str,
) -> DumpSummary:
    """Stream the fixed production database segment to an atomic test-only dump."""
    _validate_target_database(target_database)

    output_path = Path(output_path)
    temporary_path: Path | None = None
    statements = 0
    bytes_written = 0
    delimiter = ";"
    source_seen = False
    copying_source = False
    pending_create: str | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)

            def write_line(line: str) -> None:
                nonlocal bytes_written, delimiter, statements
                _reject_unsafe_database_reference(line, target_database)
                temporary.write(line)
                bytes_written += len(line.encode("utf-8"))

                delimiter_match = DELIMITER_RE.match(line)
                if delimiter_match:
                    delimiter = delimiter_match.group("delimiter")
                elif (
                    line.strip()
                    and not line.lstrip().startswith("--")
                    and line.rstrip().endswith(delimiter)
                ):
                    statements += 1

            with Path(input_path).open("r", encoding="utf-8", newline="") as source:
                for line in source:
                    current_match = CURRENT_DATABASE_RE.match(line)
                    if current_match:
                        database = _identifier(current_match)
                        copying_source = database == SOURCE_DATABASE
                        pending_create = None
                        if copying_source:
                            source_seen = True
                            write_line(
                                _rewrite_identifier(
                                    line, current_match, target_database
                                )
                            )
                        continue

                    create_match = CREATE_DATABASE_RE.match(line)
                    if create_match:
                        database = _identifier(create_match)
                        if database == SOURCE_DATABASE:
                            rewritten = _rewrite_identifier(
                                line, create_match, target_database
                            )
                            if copying_source:
                                write_line(rewritten)
                            else:
                                pending_create = rewritten
                        else:
                            copying_source = False
                            pending_create = None
                        continue

                    use_match = USE_RE.match(line)
                    if use_match:
                        database = _identifier(use_match)
                        copying_source = database == SOURCE_DATABASE
                        if copying_source:
                            source_seen = True
                            if pending_create:
                                write_line(pending_create)
                                pending_create = None
                            write_line(
                                _rewrite_identifier(line, use_match, target_database)
                            )
                        else:
                            pending_create = None
                        continue

                    if copying_source:
                        write_line(line)

        if not source_seen:
            raise UnsafeDatabaseError(
                "输入 SQL 中缺少 inventory_management 数据库段"
            )

        _validate_output(temporary_path, target_database)
        os.replace(temporary_path, output_path)
        temporary_path = None
        return DumpSummary(
            source_database=SOURCE_DATABASE,
            target_database=target_database,
            statements=statements,
            bytes_written=bytes_written,
        )
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="提取 inventory_management 到一个测试专用 SQL 文件"
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--target-database", required=True)
    args = parser.parse_args()

    summary = extract_database(args.source, args.output, args.target_database)
    print(
        f"Extracted {summary.statements} statements and "
        f"{summary.bytes_written} bytes into {summary.target_database}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

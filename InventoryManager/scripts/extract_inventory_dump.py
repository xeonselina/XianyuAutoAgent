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


class _SqlSafetyScanner:
    """Stream SQL tokens while ignoring strings and comments."""

    _OBJECT_PREFIXES = {"FROM", "JOIN", "REFERENCES", "UPDATE"}
    _OBJECT_TYPES = {"EVENT", "FUNCTION", "PROCEDURE", "TABLE", "TRIGGER", "VIEW"}
    _OBJECT_MODIFIERS = {
        "EXISTS",
        "IF",
        "LOW_PRIORITY",
        "NOT",
        "TEMPORARY",
    }

    def __init__(self, target_database: str) -> None:
        self.target_database = target_database.lower()
        self.string_quote: str | None = None
        self.in_block_comment = False
        self.in_executable_comment = False
        self.quoted_identifier: list[str] | None = None
        self.words: list[str] = []
        self.expect_database = False
        self.expect_object = False
        self.candidate_database: str | None = None
        self.candidate_has_dot = False
        self.rename_table = False
        self.object_list = False
        self.forbidden_database_candidate: str | None = None
        self.forbidden_candidate_has_dot = False

    def finish_statement(self) -> None:
        self.words.clear()
        self.expect_database = False
        self.expect_object = False
        self.candidate_database = None
        self.candidate_has_dot = False
        self.rename_table = False
        self.object_list = False
        self.forbidden_database_candidate = None
        self.forbidden_candidate_has_dot = False

    def scan(self, line: str) -> None:
        index = 0
        while index < len(line):
            if self.in_block_comment:
                end = line.find("*/", index)
                if end < 0:
                    return
                self.in_block_comment = False
                index = end + 2
                continue

            if self.string_quote:
                index = self._scan_string(line, index)
                continue

            if self.quoted_identifier is not None:
                index = self._scan_quoted_identifier(line, index)
                continue

            if self.in_executable_comment and line.startswith("*/", index):
                self.in_executable_comment = False
                index += 2
                continue

            character = line[index]
            if character in {"'", '"'}:
                self.string_quote = character
                index += 1
            elif line.startswith("/*!", index):
                self.in_executable_comment = True
                index += 3
            elif line.startswith("/*", index):
                self.in_block_comment = True
                index += 2
            elif character == "#" or (
                line.startswith("--", index)
                and (index + 2 == len(line) or line[index + 2].isspace())
            ):
                return
            elif character == "`":
                self.quoted_identifier = []
                index += 1
            elif character.isalnum() or character in {"_", "$"}:
                end = index + 1
                while end < len(line) and (
                    line[end].isalnum() or line[end] in {"_", "$"}
                ):
                    end += 1
                self._token(line[index:end])
                index = end
            elif character == ".":
                if self.candidate_database is not None:
                    self.candidate_has_dot = True
                if self.forbidden_database_candidate is not None:
                    self.forbidden_candidate_has_dot = True
                index += 1
            else:
                self._clear_unqualified_candidate()
                if character == ";":
                    self.finish_statement()
                elif character == "," and self.object_list:
                    self.expect_object = True
                index += 1

    def _scan_string(self, line: str, index: int) -> int:
        quote = self.string_quote
        while index < len(line):
            character = line[index]
            if character == "\\":
                index += 2
            elif character == quote:
                if index + 1 < len(line) and line[index + 1] == quote:
                    index += 2
                else:
                    self.string_quote = None
                    return index + 1
            else:
                index += 1
        return index

    def _scan_quoted_identifier(self, line: str, index: int) -> int:
        while index < len(line):
            character = line[index]
            if character == "`":
                if index + 1 < len(line) and line[index + 1] == "`":
                    self.quoted_identifier.append("`")
                    index += 2
                else:
                    self._token("".join(self.quoted_identifier))
                    self.quoted_identifier = None
                    return index + 1
            else:
                self.quoted_identifier.append(character)
                index += 1
        return index

    def _token(self, token: str) -> None:
        upper = token.upper()
        if self.forbidden_candidate_has_dot:
            raise UnsafeDatabaseError("提取结果包含其他数据库引用")
        self.forbidden_database_candidate = None

        if self.expect_database:
            if upper not in {"EXISTS", "IF", "NOT"}:
                if token.lower() != self.target_database:
                    raise UnsafeDatabaseError("提取结果包含其他数据库引用")
                self.expect_database = False
            self._remember(upper)
            return

        if self.expect_object:
            if self.candidate_database is None and upper in self._OBJECT_MODIFIERS:
                self._remember(upper)
                return
            if self.candidate_database is None:
                self.candidate_database = token.lower()
                self.candidate_has_dot = False
                self._remember(upper)
                return
            if self.candidate_has_dot:
                if self.candidate_database != self.target_database:
                    raise UnsafeDatabaseError("提取结果包含其他数据库引用")
                self.expect_object = False
                self.candidate_database = None
                self.candidate_has_dot = False
                self._remember(upper)
                return
            self._clear_unqualified_candidate()

        previous_words = self.words[-3:]
        if (
            upper in {"DATABASE", "SCHEMA"}
            and previous_words
            and previous_words[-1] in {"ALTER", "CREATE", "DROP"}
        ):
            self.expect_database = True
        elif upper in self._OBJECT_TYPES and (
            previous_words
            and previous_words[-1]
            in {"ALTER", "CREATE", "DROP", "RENAME", "TRUNCATE"}
            or upper == "TABLE"
            and len(previous_words) >= 2
            and previous_words[-1] == "TEMPORARY"
            and previous_words[-2] in {"CREATE", "DROP"}
        ):
            self.expect_object = True
            self.rename_table = "RENAME" in previous_words
            self.object_list = previous_words[-1] in {"DROP", "RENAME"}
        elif upper == "INTO" and previous_words and previous_words[-1] in {
            "INSERT",
            "REPLACE",
        }:
            self.expect_object = True
        elif upper in self._OBJECT_PREFIXES:
            self.expect_object = True
            self.object_list = upper == "FROM"
        elif upper == "TABLES" and previous_words and previous_words[-1] == "LOCK":
            self.expect_object = True
            self.object_list = True
        elif upper == "TO" and self.rename_table:
            self.expect_object = True
        self._remember(upper)
        if (
            token.lower() in SYSTEM_DATABASES
            and token.lower() != self.target_database
        ):
            self.forbidden_database_candidate = token.lower()

    def _clear_unqualified_candidate(self) -> None:
        if self.candidate_database is not None and not self.candidate_has_dot:
            self.candidate_database = None
            self.expect_object = False
        if not self.forbidden_candidate_has_dot:
            self.forbidden_database_candidate = None

    def _remember(self, token: str) -> None:
        self.words.append(token)
        del self.words[:-3]


def _validate_output(path: Path, target_database: str) -> None:
    target = target_database.lower()
    delimiter = ";"
    scanner = _SqlSafetyScanner(target_database)
    with path.open("r", encoding="utf-8", newline="") as output:
        for line in output:
            for matcher in (CURRENT_DATABASE_RE, CREATE_DATABASE_RE, USE_RE):
                match = matcher.match(line)
                if match and _identifier(match) != target:
                    raise UnsafeDatabaseError("提取结果仍包含其他数据库")
            scanner.scan(line)
            delimiter_match = DELIMITER_RE.match(line)
            if delimiter_match:
                delimiter = delimiter_match.group("delimiter")
                scanner.finish_statement()
            elif line.rstrip().endswith(delimiter):
                scanner.finish_statement()


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
    scanner = _SqlSafetyScanner(target_database)

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
                scanner.scan(line)
                temporary.write(line)
                bytes_written += len(line.encode("utf-8"))

                delimiter_match = DELIMITER_RE.match(line)
                if delimiter_match:
                    delimiter = delimiter_match.group("delimiter")
                    scanner.finish_statement()
                elif (
                    line.strip()
                    and not line.lstrip().startswith("--")
                    and line.rstrip().endswith(delimiter)
                ):
                    statements += 1
                    scanner.finish_statement()

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

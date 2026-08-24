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
    """Stream lexical tokens into a small database-object context parser."""

    _DDL_COMMANDS = {"ALTER", "CREATE", "DROP", "RENAME", "TRUNCATE"}
    _DATABASE_TYPES = {"DATABASE", "SCHEMA"}
    _OBJECT_TYPES = {
        "EVENT",
        "FUNCTION",
        "INDEX",
        "PROCEDURE",
        "TABLE",
        "TRIGGER",
        "VIEW",
    }
    _STORED_PROGRAM_TYPES = {"EVENT", "FUNCTION", "PROCEDURE", "TRIGGER"}
    _DDL_PREFIX_WORDS = {
        "ALGORITHM",
        "CURRENT_USER",
        "DEFINER",
        "EXISTS",
        "FULLTEXT",
        "IF",
        "IGNORE",
        "INVOKER",
        "MERGE",
        "NOT",
        "OFFLINE",
        "ONLINE",
        "OR",
        "REPLACE",
        "SECURITY",
        "SPATIAL",
        "SQL",
        "TEMPORARY",
        "TEMPTABLE",
        "UNDEFINED",
        "UNIQUE",
    }
    _OBJECT_MODIFIERS = {
        "EXISTS",
        "IF",
        "IGNORE",
        "LATERAL",
        "LOW_PRIORITY",
        "NOT",
        "ONLY",
        "TEMPORARY",
    }
    _FROM_LIST_END = {
        "EXCEPT",
        "GROUP",
        "HAVING",
        "INTERSECT",
        "INTO",
        "LIMIT",
        "ORDER",
        "PROCEDURE",
        "QUALIFY",
        "RETURNING",
        "UNION",
        "WHERE",
        "WINDOW",
    }

    def __init__(self, target_database: str) -> None:
        self.target_database = target_database.lower()
        self.string_quote: str | None = None
        self.in_block_comment = False
        self.in_executable_comment = False
        self.executable_version_pending = False
        self.quoted_identifier: list[str] | None = None

        self.statement_command: str | None = None
        self.ddl_command: str | None = None
        self.ddl_seeking_type = False
        self.ddl_object_type: str | None = None
        self.ddl_on_seen = False
        self.ddl_definer_part: str | None = None
        self.expect_database = False
        self.expect_object = False
        self.reference_first: str | None = None
        self.reference_after_dot = False
        self.object_lists: list[tuple[str, int]] = []
        self.parenthesized_objects: list[tuple[int, str]] = []
        self.parenthesis_depth = 0
        self.previous_word: str | None = None

    def finish_statement(self) -> None:
        self.statement_command = None
        self.ddl_command = None
        self.ddl_seeking_type = False
        self.ddl_object_type = None
        self.ddl_on_seen = False
        self.ddl_definer_part = None
        self.expect_database = False
        self.expect_object = False
        self.reference_first = None
        self.reference_after_dot = False
        self.object_lists.clear()
        self.parenthesized_objects.clear()
        self.parenthesis_depth = 0
        self.previous_word = None

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
                self.executable_version_pending = False
                index += 2
                continue

            if self.in_executable_comment and self.executable_version_pending:
                if line[index].isspace():
                    index += 1
                    continue
                if line[index].isdigit():
                    while index < len(line) and line[index].isdigit():
                        index += 1
                    self.executable_version_pending = False
                    continue
                self.executable_version_pending = False

            character = line[index]
            if character in {"'", '"'}:
                self.string_quote = character
                index += 1
            elif not self.in_executable_comment and (
                line.startswith("/*!", index)
                or line.startswith("/*M!", index)
            ):
                self.in_executable_comment = True
                self.executable_version_pending = True
                index += 4 if line.startswith("/*M!", index) else 3
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
                self._word(line[index:end], quoted=False)
                index = end
            elif character.isspace():
                index += 1
            else:
                self._symbol(character)
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
                    self._word("".join(self.quoted_identifier), quoted=True)
                    self.quoted_identifier = None
                    return index + 1
            else:
                self.quoted_identifier.append(character)
                index += 1
        return index

    def _word(self, token: str, *, quoted: bool) -> None:
        keyword = None if quoted else token.upper()

        if self.reference_first is not None:
            if self.reference_after_dot:
                self._finish_reference()
                return
            self._finish_reference()

        if (
            self.parenthesized_objects
            and self.parenthesized_objects[-1][0] == self.parenthesis_depth
        ):
            _, list_kind = self.parenthesized_objects.pop()
            if keyword not in {"SELECT", "VALUES", "WITH"}:
                if list_kind != "SINGLE":
                    self.object_lists.append(
                        (list_kind, self.parenthesis_depth)
                    )
                self.reference_first = token.lower()
                self.previous_word = keyword
                return

        if self.expect_database:
            if keyword in {"EXISTS", "IF", "NOT"}:
                self.previous_word = keyword
                return
            if token.lower() != self.target_database:
                raise UnsafeDatabaseError("提取结果包含其他数据库引用")
            self.expect_database = False
            self.previous_word = keyword
            return

        if self.expect_object:
            if keyword in self._OBJECT_MODIFIERS:
                self.previous_word = keyword
                return
            self.expect_object = False
            self.reference_first = token.lower()
            self.reference_after_dot = False
            self.previous_word = keyword
            return

        if self.statement_command is None and keyword is not None:
            self.statement_command = keyword
            if keyword in self._DDL_COMMANDS:
                self.ddl_command = keyword
                self.ddl_seeking_type = True
            elif keyword == "USE":
                self.expect_database = True
            elif keyword == "UPDATE":
                self._start_object_list("UPDATE")
            elif keyword in {"CALL", "HANDLER"}:
                self.expect_object = True
            self.previous_word = keyword
            return

        if self.ddl_seeking_type:
            if keyword in self._DATABASE_TYPES:
                self.ddl_seeking_type = False
                self.ddl_definer_part = None
                self.expect_database = True
                self.previous_word = keyword
                return
            if keyword in self._OBJECT_TYPES:
                self.ddl_seeking_type = False
                self.ddl_definer_part = None
                self.ddl_object_type = keyword
                if self.ddl_command in {"DROP", "RENAME"}:
                    self._start_object_list("DDL")
                else:
                    self.expect_object = True
                self.previous_word = keyword
                return
            if self.ddl_definer_part in {"HOST", "USER"}:
                self.ddl_definer_part = (
                    "AFTER_USER"
                    if self.ddl_definer_part == "USER"
                    else None
                )
                self.previous_word = keyword
                return
            if self.ddl_definer_part == "AFTER_USER":
                self.ddl_definer_part = None
            if keyword == "DEFINER":
                self.ddl_definer_part = "EQUALS"
                self.previous_word = keyword
                return
            if keyword in self._DDL_PREFIX_WORDS or keyword is None:
                self.previous_word = keyword
                return
            if self.ddl_command == "TRUNCATE":
                self.ddl_seeking_type = False
                self.ddl_object_type = "TABLE"
                self.reference_first = token.lower()
                self.previous_word = keyword
                return
            self.ddl_seeking_type = False
            self.ddl_definer_part = None

        if (
            self.statement_command == "CREATE"
            and self.ddl_object_type in self._STORED_PROGRAM_TYPES
            and (
                keyword == "BEGIN"
                or self.ddl_object_type == "EVENT" and keyword == "DO"
            )
        ):
            self.finish_statement()
            return

        self._end_object_list_at_clause(keyword)

        if keyword == "FROM":
            self._start_object_list("FROM")
        elif keyword == "JOIN" or keyword == "REFERENCES":
            self.expect_object = True
        elif keyword == "INTO" and (
            self.statement_command in {"INSERT", "REPLACE"}
            or self.previous_word in {"INSERT", "REPLACE"}
        ):
            self.expect_object = True
        elif keyword == "USING" and self.statement_command == "DELETE":
            self._start_object_list("FROM")
        elif (
            keyword == "TABLES"
            and self.statement_command == "LOCK"
            and self.previous_word == "LOCK"
        ):
            self._start_object_list("LOCK")
        elif (
            keyword == "TABLE"
            and self.statement_command == "LOAD"
            and self.previous_word == "INTO"
        ):
            self.expect_object = True
        elif (
            keyword == "TO"
            and self.ddl_object_type == "TABLE"
            and (
                self.ddl_command == "RENAME"
                or self.previous_word == "RENAME"
            )
        ):
            self.expect_object = True
        elif (
            keyword == "ON"
            and self.ddl_object_type in {"INDEX", "TRIGGER"}
            and not self.ddl_on_seen
        ):
            self.ddl_on_seen = True
            self.expect_object = True
        elif (
            keyword == "LIKE"
            and self.ddl_command == "CREATE"
            and self.ddl_object_type == "TABLE"
        ):
            self.expect_object = True

        self.previous_word = keyword

    def _symbol(self, symbol: str) -> None:
        if self.reference_first is not None:
            if symbol == "." and not self.reference_after_dot:
                if self.reference_first != self.target_database:
                    raise UnsafeDatabaseError("提取结果包含其他数据库引用")
                self.reference_after_dot = True
                return
            self._finish_reference()

        if (
            self.ddl_seeking_type
            and self.ddl_definer_part == "EQUALS"
            and symbol == "="
        ):
            self.ddl_definer_part = "USER"
        elif (
            self.ddl_seeking_type
            and self.ddl_definer_part == "AFTER_USER"
            and symbol == "@"
        ):
            self.ddl_definer_part = "HOST"

        if symbol == ";":
            self.finish_statement()
            return
        if symbol == "(":
            list_kind: str | None = None
            if self.expect_object:
                self.expect_object = False
                list_kind = "SINGLE"
                if self.object_lists:
                    active_kind, active_depth = self.object_lists[-1]
                    if active_depth == self.parenthesis_depth:
                        list_kind = active_kind
            elif (
                self.parenthesized_objects
                and self.parenthesized_objects[-1][0]
                == self.parenthesis_depth
            ):
                _, list_kind = self.parenthesized_objects.pop()
            self.parenthesis_depth += 1
            if list_kind is not None:
                self.parenthesized_objects.append(
                    (self.parenthesis_depth, list_kind)
                )
            return
        if symbol == ")":
            if self.parenthesis_depth:
                self.parenthesis_depth -= 1
            while (
                self.parenthesized_objects
                and self.parenthesized_objects[-1][0]
                > self.parenthesis_depth
            ):
                self.parenthesized_objects.pop()
            while (
                self.object_lists
                and self.object_lists[-1][1] > self.parenthesis_depth
            ):
                self.object_lists.pop()
            return
        if symbol == "," and self.object_lists:
            kind, depth = self.object_lists[-1]
            if depth == self.parenthesis_depth:
                self.expect_object = True

    def _finish_reference(self) -> None:
        self.reference_first = None
        self.reference_after_dot = False

    def _start_object_list(self, kind: str) -> None:
        while (
            self.object_lists
            and self.object_lists[-1][1] >= self.parenthesis_depth
        ):
            self.object_lists.pop()
        self.object_lists.append((kind, self.parenthesis_depth))
        self.expect_object = True

    def _end_object_list_at_clause(self, keyword: str | None) -> None:
        if not self.object_lists:
            return
        kind, depth = self.object_lists[-1]
        if depth != self.parenthesis_depth:
            return
        if kind == "FROM" and keyword in self._FROM_LIST_END:
            self.object_lists.pop()
        elif kind == "UPDATE" and keyword == "SET":
            self.object_lists.pop()


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

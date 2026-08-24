"""Portable SQL defaults shared by control models and migrations."""

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement


class MicrosecondCurrentTimestamp(FunctionElement):
    """Compile a current timestamp with the precision of DATETIME(6)."""

    inherit_cache = True


@compiles(MicrosecondCurrentTimestamp)
def _compile_current_timestamp(_element, _compiler, **_kw) -> str:
    return "CURRENT_TIMESTAMP"


@compiles(MicrosecondCurrentTimestamp, "mysql")
def _compile_mysql_current_timestamp(_element, _compiler, **_kw) -> str:
    return "CURRENT_TIMESTAMP(6)"


__all__ = ["MicrosecondCurrentTimestamp"]

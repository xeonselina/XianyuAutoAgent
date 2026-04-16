"""
Logging infrastructure using loguru.

- Console: colored text (dev) or JSON (production, LOG_FORMAT=json)
- File:    always JSON (JSONL), daily rotation → logs/backend_YYYY-MM-DD.log
- stdlib bridge: all logging.getLogger() calls are routed through loguru
"""

import sys
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from ai_kefu.config.settings import settings


# ── Log directory ──────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ── stdlib → loguru bridge (installed once) ────────────────────────────────────
class _InterceptHandler(logging.Handler):
    """Route all stdlib logging.getLogger() records through loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


_INTERCEPT_INSTALLED = False


# ── Public setup ───────────────────────────────────────────────────────────────

def setup_logging(
    level: Optional[str] = None,
    log_format: Optional[str] = None,
) -> "logger":  # type: ignore[return]
    """
    Configure application logging.

    Call once at startup (api/main.py already does this).
    Safe to call multiple times – handlers are rebuilt from scratch each call.
    """
    global _INTERCEPT_INSTALLED

    level = (level or settings.log_level).upper()
    log_format = log_format or settings.log_format

    # ── Remove all existing loguru handlers ──────────────────────────────────
    logger.remove()

    # ── Console handler ──────────────────────────────────────────────────────
    if log_format.lower() == "json":
        # serialize=True → compact JSONL on stdout, easy for log shippers
        logger.add(
            sys.stdout,
            level=level,
            serialize=True,
            colorize=False,
        )
    else:
        logger.add(
            sys.stdout,
            level=level,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                "<level>{message}</level>"
            ),
            colorize=True,
        )

    # ── File handler – always JSONL, daily rotation, 30-day retention ────────
    logger.add(
        str(LOG_DIR / "backend_{time:YYYY-MM-DD}.log"),
        level=level,
        rotation="00:00",         # rotate at midnight
        retention="30 days",
        compression="zip",
        encoding="utf-8",
        serialize=True,           # robust JSON – handles quotes/newlines in messages
        enqueue=True,             # async-safe (works with uvicorn workers)
    )

    # ── Intercept stdlib logging (installed once) ────────────────────────────
    if not _INTERCEPT_INSTALLED:
        logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
        _INTERCEPT_INSTALLED = True

    logger.info(
        f"Logging configured: level={level}, format={log_format}, "
        f"log_dir={LOG_DIR}"
    )
    return logger


def get_logger(name: str = "ai_kefu"):
    """
    Return the loguru logger.
    The ``name`` argument is accepted for API compatibility but ignored;
    loguru records the call-site module automatically.
    """
    return logger


# ── Initialise on import ────────────────────────────────────────────────────────
setup_logging()


# ── Structured-logging helpers (backward-compatible API) ───────────────────────

def log_turn_start(session_id: str, turn_counter: int, query: str) -> None:
    """Log turn start with structured fields."""
    logger.bind(
        session_id=session_id,
        event_type="turn_start",
        turn_counter=turn_counter,
        query_length=len(query),
    ).info(f"Turn {turn_counter} started")


def log_turn_end(
    session_id: str,
    turn_counter: int,
    duration_ms: int,
    success: bool,
) -> None:
    """Log turn end with structured fields."""
    logger.bind(
        session_id=session_id,
        event_type="turn_end",
        turn_counter=turn_counter,
        duration_ms=duration_ms,
        success=success,
    ).info(f"Turn {turn_counter} completed")


def log_tool_call(
    session_id: str,
    tool_name: str,
    tool_call_id: str,
    args: Dict[str, Any],
) -> None:
    """Log tool call start with structured fields."""
    logger.bind(
        session_id=session_id,
        event_type="tool_call_start",
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_args=str(args),
    ).info(f"Tool called: {tool_name}")


def log_tool_result(
    session_id: str,
    tool_name: str,
    tool_call_id: str,
    success: bool,
    duration_ms: int,
) -> None:
    """Log tool call result with structured fields."""
    logger.bind(
        session_id=session_id,
        event_type="tool_call_end",
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        success=success,
        duration_ms=duration_ms,
    ).info(f"Tool completed: {tool_name}")


def log_agent_complete(
    session_id: str,
    status: str,
    total_turns: int,
    total_duration_ms: int,
) -> None:
    """Log agent completion with structured fields."""
    logger.bind(
        session_id=session_id,
        event_type="agent_complete",
        status=status,
        total_turns=total_turns,
        total_duration_ms=total_duration_ms,
    ).info(f"Agent completed with status: {status}")

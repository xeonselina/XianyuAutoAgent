"""
Logging setup for Xianyu Interceptor.

Uses loguru with:
- Console: colored text (dev) or JSON (LOG_FORMAT=json)
- File:    always JSONL, daily rotation → logs/xianyu_YYYY-MM-DD.log
- stdlib bridge so libraries using logging.getLogger() also go to loguru
"""

import sys
import logging
from pathlib import Path

from loguru import logger
from .config import config


# ── Log directory (relative to the ai_kefu package root) ──────────────────────
_HERE = Path(__file__).parent          # xianyu_interceptor/
LOG_DIR = _HERE.parent / "logs"        # ai_kefu/logs/
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ── stdlib → loguru bridge ─────────────────────────────────────────────────────
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


def setup_logging() -> None:
    """
    Configure loguru for the Xianyu interceptor process.

    Called once from run_xianyu.py before anything else.
    """
    global _INTERCEPT_INSTALLED

    level = config.log_level.upper()
    log_format = config.log_format.lower()

    # ── Remove default loguru handler ─────────────────────────────────────────
    logger.remove()

    # ── Console handler ───────────────────────────────────────────────────────
    if log_format == "json":
        logger.add(
            sys.stderr,
            level=level,
            serialize=True,
            colorize=False,
        )
    else:
        logger.add(
            sys.stderr,
            level=level,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                "<level>{message}</level>"
            ),
            colorize=True,
        )

    # ── File handler – always JSONL, daily rotation, 30-day retention ─────────
    logger.add(
        str(LOG_DIR / "xianyu_{time:YYYY-MM-DD}.log"),
        level=level,
        rotation="00:00",         # rotate at midnight
        retention="30 days",
        compression="zip",
        encoding="utf-8",
        serialize=True,           # robust JSONL – no manual quote escaping
        enqueue=True,             # async-safe
    )

    # ── Intercept stdlib logging (installed once per process) ─────────────────
    if not _INTERCEPT_INSTALLED:
        logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
        _INTERCEPT_INSTALLED = True

    logger.info(
        f"Xianyu interceptor logging configured: "
        f"level={level}, format={log_format}, log_dir={LOG_DIR}"
    )

"""
MySQL-based storage for message ignore patterns.

Stores patterns that should be skipped by the message handler
(e.g., system messages like [图片], [买家已确认退回金额] etc.).

Includes an in-memory cache that auto-refreshes to avoid querying
MySQL on every incoming message.
"""

import threading
import time
from typing import List, Optional, Dict, Any, Set
from datetime import datetime
import pymysql
from pymysql.cursors import DictCursor
from contextlib import contextmanager

try:
    from ai_kefu.utils.logging import logger
except ImportError:
    from loguru import logger


class IgnorePattern:
    """Ignore pattern data model."""

    def __init__(
        self,
        id: Optional[int] = None,
        pattern: str = "",
        description: Optional[str] = None,
        active: bool = True,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None
    ):
        self.id = id
        self.pattern = pattern
        self.description = description
        self.active = active
        self.created_at = created_at
        self.updated_at = updated_at


class IgnorePatternStore:
    """
    MySQL-based storage for message ignore patterns.

    Features:
    - CRUD operations for ignore patterns
    - In-memory cache of active patterns (refreshed every 60s)
    - Thread-safe cache access
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        cache_ttl: int = 60
    ):
        self.config = {
            'host': host,
            'port': port,
            'user': user,
            'password': password,
            'database': database,
            'charset': 'utf8mb4',
            'cursorclass': DictCursor
        }
        self._cache_ttl = cache_ttl
        self._cache: Set[str] = set()
        self._cache_lock = threading.Lock()
        self._cache_last_refresh: float = 0.0

        # Ensure table exists
        self._ensure_table()

        # Load initial cache
        self._refresh_cache()

    @contextmanager
    def get_connection(self):
        """Get MySQL database connection with context manager."""
        conn = None
        try:
            conn = pymysql.connect(**self.config)
            yield conn
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"MySQL connection error (ignore_patterns): {e}")
            raise
        finally:
            if conn:
                conn.close()

    def _ensure_table(self):
        """Create the ignore_patterns table if it doesn't exist."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS ignore_patterns (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            pattern VARCHAR(500) NOT NULL COMMENT '要忽略的消息内容',
                            description VARCHAR(500) DEFAULT NULL COMMENT '描述说明',
                            active BOOLEAN NOT NULL DEFAULT TRUE COMMENT '是否启用',
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            UNIQUE KEY uk_pattern (pattern)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    """)
            logger.debug("ignore_patterns table ensured")
        except Exception as e:
            logger.error(f"Failed to ensure ignore_patterns table: {e}")

    # ============================================================
    # Cache
    # ============================================================

    def _refresh_cache(self):
        """Refresh the in-memory set of active patterns from MySQL."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT pattern FROM ignore_patterns WHERE active = TRUE"
                    )
                    rows = cursor.fetchall()
                    new_cache = {row['pattern'] for row in rows}

            with self._cache_lock:
                self._cache = new_cache
                self._cache_last_refresh = time.monotonic()

            logger.debug(f"Ignore pattern cache refreshed: {len(new_cache)} active patterns")
        except Exception as e:
            logger.error(f"Failed to refresh ignore pattern cache: {e}")

    def _maybe_refresh_cache(self):
        """Refresh cache if TTL has expired."""
        now = time.monotonic()
        if now - self._cache_last_refresh > self._cache_ttl:
            self._refresh_cache()

    def invalidate_cache(self):
        """Force cache refresh (call after create/update/delete)."""
        self._refresh_cache()

    def should_ignore(self, content: str) -> bool:
        """
        Check if a message content matches any active ignore pattern.

        This is the hot-path method called for every incoming message.
        Uses in-memory cache for O(1) lookup.

        Args:
            content: Message content to check

        Returns:
            True if the message should be ignored
        """
        if not content:
            return False

        self._maybe_refresh_cache()

        stripped = content.strip()
        with self._cache_lock:
            return stripped in self._cache

    # ============================================================
    # CRUD
    # ============================================================

    def create(self, pattern: IgnorePattern) -> Optional[IgnorePattern]:
        """Create a new ignore pattern."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    sql = """
                        INSERT INTO ignore_patterns (pattern, description, active, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s)
                    """
                    now = datetime.utcnow()
                    cursor.execute(sql, (
                        pattern.pattern.strip(),
                        pattern.description,
                        pattern.active,
                        now,
                        now
                    ))
                    pattern.id = cursor.lastrowid
                    pattern.created_at = now
                    pattern.updated_at = now

            self.invalidate_cache()
            logger.info(f"Created ignore pattern: id={pattern.id}, pattern='{pattern.pattern}'")
            return pattern

        except pymysql.IntegrityError:
            logger.warning(f"Ignore pattern already exists: '{pattern.pattern}'")
            return None
        except Exception as e:
            logger.error(f"Failed to create ignore pattern: {e}")
            return None

    def get(self, pattern_id: int) -> Optional[IgnorePattern]:
        """Get ignore pattern by ID."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM ignore_patterns WHERE id = %s", (pattern_id,))
                    row = cursor.fetchone()
                    return self._row_to_pattern(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get ignore pattern {pattern_id}: {e}")
            return None

    def update(self, pattern_id: int, updates: Dict[str, Any]) -> Optional[IgnorePattern]:
        """Update ignore pattern."""
        try:
            update_fields = []
            update_values = []

            for key, value in updates.items():
                if key in ('pattern', 'description', 'active'):
                    update_fields.append(f"{key} = %s")
                    if key == 'pattern':
                        value = value.strip()
                    update_values.append(value)

            if not update_fields:
                return self.get(pattern_id)

            update_values.append(pattern_id)

            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    sql = f"UPDATE ignore_patterns SET {', '.join(update_fields)}, updated_at = NOW() WHERE id = %s"
                    cursor.execute(sql, update_values)

            self.invalidate_cache()
            return self.get(pattern_id)

        except Exception as e:
            logger.error(f"Failed to update ignore pattern {pattern_id}: {e}")
            return None

    def delete(self, pattern_id: int) -> bool:
        """Delete ignore pattern by ID."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("DELETE FROM ignore_patterns WHERE id = %s", (pattern_id,))
                    deleted = cursor.rowcount > 0

            if deleted:
                self.invalidate_cache()
            return deleted

        except Exception as e:
            logger.error(f"Failed to delete ignore pattern {pattern_id}: {e}")
            return False

    def list_all(self, active_only: bool = False, limit: int = 100, offset: int = 0) -> List[IgnorePattern]:
        """List ignore patterns with optional filtering."""
        try:
            where_sql = "WHERE active = TRUE" if active_only else ""

            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    sql = f"""
                        SELECT * FROM ignore_patterns
                        {where_sql}
                        ORDER BY created_at ASC
                        LIMIT %s OFFSET %s
                    """
                    cursor.execute(sql, (limit, offset))
                    rows = cursor.fetchall()
                    return [self._row_to_pattern(row) for row in rows]

        except Exception as e:
            logger.error(f"Failed to list ignore patterns: {e}")
            return []

    def count(self, active_only: bool = False) -> int:
        """Count ignore patterns."""
        try:
            where_sql = "WHERE active = TRUE" if active_only else ""
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(f"SELECT COUNT(*) as count FROM ignore_patterns {where_sql}")
                    result = cursor.fetchone()
                    return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Failed to count ignore patterns: {e}")
            return 0

    def _row_to_pattern(self, row: Dict[str, Any]) -> IgnorePattern:
        """Convert MySQL row to IgnorePattern object."""
        return IgnorePattern(
            id=row['id'],
            pattern=row['pattern'],
            description=row.get('description'),
            active=row.get('active', True),
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at')
        )

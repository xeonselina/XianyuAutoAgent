"""
MySQL-based system prompt storage.

Supports CRUD operations, versioning, and active version management.
"""

import json
from typing import List, Optional, Dict, Any
from datetime import datetime
import pymysql
from pymysql.cursors import DictCursor
from contextlib import contextmanager

from ai_kefu.utils.logging import logger


class SystemPrompt:
    """System prompt data model."""

    def __init__(
        self,
        id: Optional[int] = None,
        prompt_key: str = "",
        title: str = "",
        content: str = "",
        description: Optional[str] = None,
        active: bool = False,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None
    ):
        self.id = id
        self.prompt_key = prompt_key
        self.title = title
        self.content = content
        self.description = description
        self.active = active
        self.created_at = created_at
        self.updated_at = updated_at


class PromptStore:
    """
    MySQL-based system prompt storage.

    Supports versioning: multiple prompts per prompt_key, only one active at a time.
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str
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
            logger.error(f"MySQL connection error: {e}")
            raise
        finally:
            if conn:
                conn.close()

    def create(self, prompt: SystemPrompt) -> Optional[SystemPrompt]:
        """
        Create a new system prompt version.

        Args:
            prompt: SystemPrompt object

        Returns:
            Created SystemPrompt with ID, or None on failure
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    sql = """
                        INSERT INTO system_prompts
                        (prompt_key, title, content, description, active, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """
                    now = datetime.utcnow()
                    cursor.execute(sql, (
                        prompt.prompt_key,
                        prompt.title,
                        prompt.content,
                        prompt.description,
                        prompt.active,
                        now,
                        now
                    ))
                    prompt.id = cursor.lastrowid
                    prompt.created_at = now
                    prompt.updated_at = now

                    # If this prompt is set as active, deactivate others with same key
                    if prompt.active:
                        cursor.execute(
                            "UPDATE system_prompts SET active = FALSE WHERE prompt_key = %s AND id != %s",
                            (prompt.prompt_key, prompt.id)
                        )

            logger.info(f"Created system prompt: id={prompt.id}, key={prompt.prompt_key}")
            return prompt

        except Exception as e:
            logger.error(f"Failed to create system prompt: {e}")
            return None

    def get(self, prompt_id: int) -> Optional[SystemPrompt]:
        """Get system prompt by ID."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM system_prompts WHERE id = %s", (prompt_id,))
                    row = cursor.fetchone()
                    return self._row_to_prompt(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get system prompt {prompt_id}: {e}")
            return None

    def get_active(self, prompt_key: str) -> Optional[SystemPrompt]:
        """
        Get the active system prompt for a given key.

        Args:
            prompt_key: Prompt identifier (e.g., 'rental_system')

        Returns:
            Active SystemPrompt, or None if not found
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT * FROM system_prompts WHERE prompt_key = %s AND active = TRUE LIMIT 1",
                        (prompt_key,)
                    )
                    row = cursor.fetchone()
                    return self._row_to_prompt(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get active prompt for key={prompt_key}: {e}")
            return None

    def update(self, prompt_id: int, updates: Dict[str, Any]) -> Optional[SystemPrompt]:
        """
        Update system prompt.

        Args:
            prompt_id: Prompt ID
            updates: Fields to update

        Returns:
            Updated SystemPrompt, or None on failure
        """
        try:
            update_fields = []
            update_values = []

            for key, value in updates.items():
                if key in ('prompt_key', 'title', 'content', 'description', 'active'):
                    update_fields.append(f"{key} = %s")
                    update_values.append(value)

            if not update_fields:
                return self.get(prompt_id)

            update_values.append(prompt_id)

            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    sql = f"UPDATE system_prompts SET {', '.join(update_fields)}, updated_at = NOW() WHERE id = %s"
                    cursor.execute(sql, update_values)

                    # If setting as active, deactivate others with same key
                    if updates.get('active') is True:
                        prompt = self.get(prompt_id)
                        if prompt:
                            cursor.execute(
                                "UPDATE system_prompts SET active = FALSE WHERE prompt_key = %s AND id != %s",
                                (prompt.prompt_key, prompt_id)
                            )

            return self.get(prompt_id)

        except Exception as e:
            logger.error(f"Failed to update system prompt {prompt_id}: {e}")
            return None

    def delete(self, prompt_id: int) -> bool:
        """Delete system prompt by ID."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("DELETE FROM system_prompts WHERE id = %s", (prompt_id,))
                    return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to delete system prompt {prompt_id}: {e}")
            return False

    def list_all(self, prompt_key: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[SystemPrompt]:
        """
        List system prompts with optional filtering.

        Args:
            prompt_key: Filter by prompt key (optional)
            limit: Max results
            offset: Pagination offset

        Returns:
            List of SystemPrompt objects
        """
        try:
            where_clauses = []
            where_values = []

            if prompt_key:
                where_clauses.append("prompt_key = %s")
                where_values.append(prompt_key)

            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    sql = f"""
                        SELECT * FROM system_prompts
                        {where_sql}
                        ORDER BY prompt_key ASC, active DESC, updated_at DESC
                        LIMIT %s OFFSET %s
                    """
                    cursor.execute(sql, where_values + [limit, offset])
                    rows = cursor.fetchall()
                    return [self._row_to_prompt(row) for row in rows]

        except Exception as e:
            logger.error(f"Failed to list system prompts: {e}")
            return []

    def count(self, prompt_key: Optional[str] = None) -> int:
        """Count system prompts."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    if prompt_key:
                        cursor.execute(
                            "SELECT COUNT(*) as count FROM system_prompts WHERE prompt_key = %s",
                            (prompt_key,)
                        )
                    else:
                        cursor.execute("SELECT COUNT(*) as count FROM system_prompts")
                    result = cursor.fetchone()
                    return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Failed to count system prompts: {e}")
            return 0

    def set_active(self, prompt_id: int) -> bool:
        """
        Set a prompt as active, deactivating all others with the same key.

        Args:
            prompt_id: Prompt ID to activate

        Returns:
            True if successful
        """
        try:
            prompt = self.get(prompt_id)
            if not prompt:
                return False

            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Deactivate all with same key
                    cursor.execute(
                        "UPDATE system_prompts SET active = FALSE WHERE prompt_key = %s",
                        (prompt.prompt_key,)
                    )
                    # Activate the specified one
                    cursor.execute(
                        "UPDATE system_prompts SET active = TRUE, updated_at = NOW() WHERE id = %s",
                        (prompt_id,)
                    )

            logger.info(f"Set prompt {prompt_id} as active for key={prompt.prompt_key}")
            return True

        except Exception as e:
            logger.error(f"Failed to set active prompt {prompt_id}: {e}")
            return False

    def _row_to_prompt(self, row: Dict[str, Any]) -> SystemPrompt:
        """Convert MySQL row to SystemPrompt object."""
        return SystemPrompt(
            id=row['id'],
            prompt_key=row['prompt_key'],
            title=row['title'],
            content=row['content'],
            description=row.get('description'),
            active=row.get('active', False),
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at')
        )

"""
MySQL-based knowledge entry storage with ChromaDB sync.

This module provides the MySQLKnowledgeStore class that maintains knowledge entries
in MySQL as the source of truth while keeping ChromaDB synchronized for vector search.
"""

import json
from typing import List, Optional, Dict, Any
from datetime import datetime
import pymysql
from pymysql.cursors import DictCursor
from contextlib import contextmanager

from ai_kefu.models.knowledge import KnowledgeEntry
from ai_kefu.llm.embeddings import generate_embedding
from ai_kefu.utils.logging import logger
import chromadb


class MySQLKnowledgeStore:
    """
    MySQL-based knowledge entry storage with ChromaDB synchronization.

    MySQL serves as the authoritative source of truth for structured data,
    while ChromaDB maintains vector embeddings for semantic search.
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        chroma_path: str
    ):
        """
        Initialize MySQL knowledge store with ChromaDB sync.

        Args:
            host: MySQL host
            port: MySQL port
            user: MySQL username
            password: MySQL password
            database: MySQL database name
            chroma_path: Path to ChromaDB persistence directory
        """
        self.config = {
            'host': host,
            'port': port,
            'user': user,
            'password': password,
            'database': database,
            'charset': 'utf8mb4',
            'cursorclass': DictCursor
        }

        # Initialize ChromaDB client
        self.chroma_client = chromadb.PersistentClient(path=chroma_path)
        self.chroma_collection = self.chroma_client.get_or_create_collection(
            name="knowledge_base",
            metadata={"description": "Customer service knowledge base"}
        )

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

    def create(self, entry: KnowledgeEntry) -> bool:
        """
        Create knowledge entry in MySQL and sync to ChromaDB.

        Args:
            entry: KnowledgeEntry object

        Returns:
            True if successful
        """
        try:
            # Insert into MySQL
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    sql = """
                        INSERT INTO knowledge_entries
                        (kb_id, title, content, category, tags, source, priority, active, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(sql, (
                        entry.id,
                        entry.title,
                        entry.content,
                        entry.category,
                        json.dumps(entry.tags) if entry.tags else None,
                        entry.source,
                        entry.priority,
                        entry.active,
                        entry.created_at,
                        entry.updated_at
                    ))

            # Generate embedding and sync to ChromaDB
            try:
                embedding = generate_embedding(entry.content, task_type="retrieval_document")
                self.chroma_collection.add(
                    ids=[entry.id],
                    embeddings=[embedding],
                    documents=[entry.content],
                    metadatas=[{
                        "title": entry.title,
                        "category": entry.category or "",
                        "tags": ",".join(entry.tags) if entry.tags else "",
                        "source": entry.source or "",
                        "priority": entry.priority,
                        "active": entry.active
                    }]
                )
            except Exception as e:
                logger.error(f"ChromaDB sync failed for {entry.id}: {e}")
                # Don't fail - MySQL is source of truth

            logger.info(f"Created knowledge entry: {entry.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to create knowledge entry {entry.id}: {e}")
            return False

    def update(self, kb_id: str, updates: Dict[str, Any], regenerate_embedding: bool = False) -> Optional[KnowledgeEntry]:
        """
        Update knowledge entry in MySQL and sync to ChromaDB.

        Args:
            kb_id: Knowledge base ID
            updates: Dict of fields to update
            regenerate_embedding: Whether to regenerate embedding (if content changed)

        Returns:
            Updated KnowledgeEntry if successful, None otherwise
        """
        try:
            # Build UPDATE query dynamically
            update_fields = []
            update_values = []

            for key, value in updates.items():
                if key == 'tags' and value is not None:
                    update_fields.append(f"{key} = %s")
                    update_values.append(json.dumps(value))
                else:
                    update_fields.append(f"{key} = %s")
                    update_values.append(value)

            update_values.append(kb_id)

            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    sql = f"UPDATE knowledge_entries SET {', '.join(update_fields)}, updated_at = NOW() WHERE kb_id = %s"
                    cursor.execute(sql, update_values)

            # Get updated entry
            entry = self.get(kb_id)
            if not entry:
                return None

            # Sync to ChromaDB
            try:
                update_data = {
                    "documents": [entry.content],
                    "metadatas": [{
                        "title": entry.title,
                        "category": entry.category or "",
                        "tags": ",".join(entry.tags) if entry.tags else "",
                        "source": entry.source or "",
                        "priority": entry.priority,
                        "active": entry.active
                    }]
                }

                if regenerate_embedding and 'content' in updates:
                    embedding = generate_embedding(entry.content, task_type="retrieval_document")
                    update_data["embeddings"] = [embedding]

                self.chroma_collection.update(
                    ids=[kb_id],
                    **update_data
                )
            except Exception as e:
                logger.error(f"ChromaDB sync failed for {kb_id}: {e}")

            logger.info(f"Updated knowledge entry: {kb_id}")
            return entry

        except Exception as e:
            logger.error(f"Failed to update knowledge entry {kb_id}: {e}")
            return None

    def delete(self, kb_id: str) -> bool:
        """
        Delete knowledge entry from MySQL and ChromaDB.

        Args:
            kb_id: Knowledge base ID

        Returns:
            True if successful
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("DELETE FROM knowledge_entries WHERE kb_id = %s", (kb_id,))
                    if cursor.rowcount == 0:
                        return False

            # Delete from ChromaDB
            try:
                self.chroma_collection.delete(ids=[kb_id])
            except Exception as e:
                logger.error(f"ChromaDB delete failed for {kb_id}: {e}")

            logger.info(f"Deleted knowledge entry: {kb_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete knowledge entry {kb_id}: {e}")
            return False

    def get(self, kb_id: str) -> Optional[KnowledgeEntry]:
        """
        Get knowledge entry by ID from MySQL.

        Args:
            kb_id: Knowledge base ID

        Returns:
            KnowledgeEntry if found, None otherwise
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM knowledge_entries WHERE kb_id = %s", (kb_id,))
                    row = cursor.fetchone()

                    if not row:
                        return None

                    return self._row_to_entry(row)

        except Exception as e:
            logger.error(f"Failed to get knowledge entry {kb_id}: {e}")
            return None

    def list_all(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[KnowledgeEntry]:
        """
        List knowledge entries with pagination and filtering.

        Args:
            filters: Optional filters (active, category)
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List of KnowledgeEntry objects
        """
        try:
            where_clauses = []
            where_values = []

            if filters:
                if 'active' in filters:
                    where_clauses.append("active = %s")
                    where_values.append(filters['active'])
                if 'category' in filters:
                    where_clauses.append("category = %s")
                    where_values.append(filters['category'])

            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    sql = f"""
                        SELECT * FROM knowledge_entries
                        {where_sql}
                        ORDER BY priority DESC, created_at DESC
                        LIMIT %s OFFSET %s
                    """
                    cursor.execute(sql, where_values + [limit, offset])
                    rows = cursor.fetchall()

                    return [self._row_to_entry(row) for row in rows]

        except Exception as e:
            logger.error(f"Failed to list knowledge entries: {e}")
            return []

    def search_semantic(
        self,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Semantic search via ChromaDB, enriched with MySQL data.

        Args:
            query: Search query
            top_k: Number of results to return
            category: Optional category filter

        Returns:
            List of search results with score and full entry data
        """
        try:
            # Generate query embedding
            query_embedding = generate_embedding(query, task_type="retrieval_query")

            # Search ChromaDB
            where = {}
            if category:
                where["category"] = category

            results = self.chroma_collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where if where else None
            )

            if not results["ids"] or len(results["ids"][0]) == 0:
                return []

            # Fetch full entries from MySQL
            kb_ids = results["ids"][0]
            distances = results["distances"][0]

            entries_map = {}
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    placeholders = ','.join(['%s'] * len(kb_ids))
                    cursor.execute(f"SELECT * FROM knowledge_entries WHERE kb_id IN ({placeholders})", kb_ids)
                    rows = cursor.fetchall()
                    for row in rows:
                        entries_map[row['kb_id']] = self._row_to_entry(row)

            # Merge results
            search_results = []
            for i, kb_id in enumerate(kb_ids):
                if kb_id in entries_map:
                    entry = entries_map[kb_id]
                    search_results.append({
                        "id": entry.id,
                        "title": entry.title,
                        "content": entry.content,
                        "category": entry.category,
                        "score": 1.0 - distances[i]  # Convert distance to similarity score
                    })

            return search_results

        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return []

    def bulk_create(self, entries: List[KnowledgeEntry]) -> Dict[str, Any]:
        """
        Bulk insert knowledge entries.

        Args:
            entries: List of KnowledgeEntry objects

        Returns:
            Summary dict with imported, skipped, errors
        """
        imported = 0
        skipped = 0
        errors = []

        for entry in entries:
            try:
                # Check if exists
                existing = self.get(entry.id)
                if existing:
                    skipped += 1
                    continue

                if self.create(entry):
                    imported += 1
                else:
                    errors.append(f"Failed to create {entry.id}")
            except Exception as e:
                errors.append(f"Error creating {entry.id}: {str(e)}")

        return {
            "imported": imported,
            "skipped": skipped,
            "errors": errors
        }

    def export_all(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """
        Export all knowledge entries as JSON-serializable dicts.

        Args:
            active_only: Whether to export only active entries

        Returns:
            List of knowledge entry dicts
        """
        try:
            filters = {"active": True} if active_only else None
            entries = self.list_all(filters=filters, limit=10000)  # Large limit for export

            return [
                {
                    "kb_id": e.id,
                    "title": e.title,
                    "content": e.content,
                    "category": e.category,
                    "tags": e.tags,
                    "source": e.source,
                    "priority": e.priority,
                    "active": e.active,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                    "updated_at": e.updated_at.isoformat() if e.updated_at else None
                }
                for e in entries
            ]

        except Exception as e:
            logger.error(f"Failed to export knowledge: {e}")
            return []

    def count(self, active_only: bool = False) -> int:
        """
        Count knowledge entries.

        Args:
            active_only: Whether to count only active entries

        Returns:
            Total count
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    where_sql = "WHERE active = TRUE" if active_only else ""
                    cursor.execute(f"SELECT COUNT(*) as count FROM knowledge_entries {where_sql}")
                    result = cursor.fetchone()
                    return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Failed to count knowledge entries: {e}")
            return 0

    def _row_to_entry(self, row: Dict[str, Any]) -> KnowledgeEntry:
        """Convert MySQL row to KnowledgeEntry object."""
        tags = json.loads(row['tags']) if row.get('tags') else []

        return KnowledgeEntry(
            id=row['kb_id'],
            title=row['title'],
            content=row['content'],
            category=row.get('category'),
            tags=tags,
            source=row.get('source'),
            priority=row.get('priority', 0),
            active=row.get('active', True),
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at')
        )

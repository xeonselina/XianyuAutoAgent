"""
Unified knowledge store interface with MySQL + ChromaDB hybrid storage.
Delegates to MySQLKnowledgeStore for CRUD operations.
"""

from typing import List, Optional, Dict, Any
from ai_kefu.models.knowledge import KnowledgeEntry
from ai_kefu.config.settings import settings
from ai_kefu.config.constants import DEFAULT_TOP_K
from ai_kefu.storage.mysql_knowledge_store import MySQLKnowledgeStore


class KnowledgeStore:
    """
    Unified knowledge store interface.

    Delegates to MySQL for CRUD operations and ChromaDB for vector search.
    Maintains backward compatibility with existing code.
    """

    def __init__(
        self,
        mysql_host: Optional[str] = None,
        mysql_port: Optional[int] = None,
        mysql_user: Optional[str] = None,
        mysql_password: Optional[str] = None,
        mysql_database: Optional[str] = None,
        persist_path: Optional[str] = None
    ):
        """
        Initialize knowledge store with MySQL backend.

        Args:
            mysql_host: MySQL host (defaults to settings)
            mysql_port: MySQL port (defaults to settings)
            mysql_user: MySQL user (defaults to settings)
            mysql_password: MySQL password (defaults to settings)
            mysql_database: MySQL database (defaults to settings)
            persist_path: ChromaDB persistence path (defaults to settings)
        """
        self.mysql_store = MySQLKnowledgeStore(
            host=mysql_host or settings.mysql_host,
            port=mysql_port or settings.mysql_port,
            user=mysql_user or settings.mysql_user,
            password=mysql_password or settings.mysql_password,
            database=mysql_database or settings.mysql_database,
            chroma_path=persist_path or settings.chroma_persist_path
        )
    
    def add(self, entry: KnowledgeEntry, embedding: Optional[List[float]] = None) -> bool:
        """
        Add knowledge entry to database.

        Args:
            entry: KnowledgeEntry object
            embedding: Vector embedding (optional, will be generated if not provided)

        Returns:
            True if successful
        """
        # Delegate to MySQL store (which handles ChromaDB sync)
        return self.mysql_store.create(entry)
    
    def search(
        self,
        query_embedding: Optional[List[float]] = None,
        query: Optional[str] = None,
        top_k: int = DEFAULT_TOP_K,
        category: Optional[str] = None,
        active_only: bool = True
    ) -> Dict[str, Any]:
        """
        Semantic search in knowledge base.

        Args:
            query_embedding: Query vector embedding (optional if query provided)
            query: Query string (optional if query_embedding provided)
            top_k: Number of results to return
            category: Filter by category (optional)
            active_only: Only return active entries

        Returns:
            Dict with 'ids', 'documents', 'metadatas', 'distances'
        """
        # If query string provided, use MySQL store's semantic search
        if query:
            results = self.mysql_store.search_semantic(query, top_k, category)
            # Convert to old format for backward compatibility
            if not results:
                return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

            return {
                "ids": [[r["id"] for r in results]],
                "documents": [[r["content"] for r in results]],
                "metadatas": [[{"title": r["title"], "category": r.get("category", "")} for r in results]],
                "distances": [[1.0 - r["score"] for r in results]]
            }

        # Legacy support: if only embedding provided, use ChromaDB directly
        if query_embedding:
            try:
                where = {}
                if active_only:
                    where["active"] = True
                if category:
                    where["category"] = category

                results = self.mysql_store.chroma_collection.query(
                    query_embeddings=[query_embedding],
                    n_results=top_k,
                    where=where if where else None
                )
                return results
            except Exception as e:
                print(f"Error searching knowledge base: {e}")
                return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
    
    def get(self, entry_id: str) -> Optional[KnowledgeEntry]:
        """
        Get knowledge entry by ID.

        Args:
            entry_id: Entry ID

        Returns:
            KnowledgeEntry if found, None otherwise
        """
        return self.mysql_store.get(entry_id)
    
    def update(self, entry: KnowledgeEntry, embedding: Optional[List[float]] = None) -> bool:
        """
        Update knowledge entry.

        Args:
            entry: Updated KnowledgeEntry object
            embedding: New embedding (optional, if content changed)

        Returns:
            True if successful
        """
        updates = {
            "title": entry.title,
            "content": entry.content,
            "category": entry.category,
            "tags": entry.tags,
            "source": entry.source,
            "priority": entry.priority,
            "active": entry.active
        }
        regenerate_embedding = embedding is not None
        result = self.mysql_store.update(entry.id, updates, regenerate_embedding)
        return result is not None
    
    def delete(self, entry_id: str) -> bool:
        """
        Delete knowledge entry.

        Args:
            entry_id: Entry ID

        Returns:
            True if successful
        """
        return self.mysql_store.delete(entry_id)
    
    def list_all(self, offset: int = 0, limit: int = 100, active_only: bool = False) -> List[KnowledgeEntry]:
        """
        List all knowledge entries.

        Args:
            offset: Offset for pagination
            limit: Limit for pagination
            active_only: Only return active entries

        Returns:
            List of KnowledgeEntry objects
        """
        filters = {"active": True} if active_only else None
        return self.mysql_store.list_all(filters=filters, limit=limit, offset=offset)
    
    def count(self, active_only: bool = False) -> int:
        """
        Count knowledge entries.

        Args:
            active_only: Only count active entries

        Returns:
            Total count
        """
        return self.mysql_store.count(active_only=active_only)

    def ping(self) -> bool:
        """
        Check MySQL connection.

        Returns:
            True if connected
        """
        try:
            self.mysql_store.count()
            return True
        except Exception:
            return False

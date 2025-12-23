"""
Chroma vector database knowledge store implementation.
Handles knowledge base CRUD and semantic search.
"""

import chromadb
from chromadb.config import Settings as ChromaSettings
from typing import List, Optional, Dict, Any
from ai_kefu.models.knowledge import KnowledgeEntry
from ai_kefu.config.settings import settings
from ai_kefu.config.constants import DEFAULT_TOP_K


class KnowledgeStore:
    """Chroma-based knowledge base storage."""
    
    def __init__(self, persist_path: Optional[str] = None):
        """
        Initialize knowledge store.
        
        Args:
            persist_path: Path for Chroma persistence (defaults to settings.chroma_persist_path)
        """
        self.persist_path = persist_path or settings.chroma_persist_path
        
        # Initialize Chroma client with persistence
        self.client = chromadb.PersistentClient(
            path=self.persist_path,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        
        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name="knowledge_base",
            metadata={"description": "Customer service knowledge base"}
        )
    
    def add(self, entry: KnowledgeEntry, embedding: List[float]) -> bool:
        """
        Add knowledge entry to database.
        
        Args:
            entry: KnowledgeEntry object
            embedding: Vector embedding for the content
            
        Returns:
            True if successful
        """
        try:
            self.collection.add(
                ids=[entry.id],
                embeddings=[embedding],
                documents=[entry.content],
                metadatas=[{
                    "title": entry.title,
                    "category": entry.category or "",
                    "tags": ",".join(entry.tags),
                    "source": entry.source or "",
                    "priority": entry.priority,
                    "active": entry.active,
                    "created_at": entry.created_at.isoformat(),
                    "updated_at": entry.updated_at.isoformat()
                }]
            )
            return True
        except Exception as e:
            print(f"Error adding knowledge entry {entry.id}: {e}")
            return False
    
    def search(
        self,
        query_embedding: List[float],
        top_k: int = DEFAULT_TOP_K,
        category: Optional[str] = None,
        active_only: bool = True
    ) -> Dict[str, Any]:
        """
        Semantic search in knowledge base.
        
        Args:
            query_embedding: Query vector embedding
            top_k: Number of results to return
            category: Filter by category (optional)
            active_only: Only return active entries
            
        Returns:
            Dict with 'ids', 'documents', 'metadatas', 'distances'
        """
        try:
            # Build where clause
            where = {}
            if active_only:
                where["active"] = True
            if category:
                where["category"] = category
            
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where if where else None
            )
            
            return results
        except Exception as e:
            print(f"Error searching knowledge base: {e}")
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
    
    def get(self, entry_id: str) -> Optional[KnowledgeEntry]:
        """
        Get knowledge entry by ID.
        
        Args:
            entry_id: Entry ID
            
        Returns:
            KnowledgeEntry if found, None otherwise
        """
        try:
            result = self.collection.get(ids=[entry_id], include=["documents", "metadatas"])
            
            if not result["ids"] or len(result["ids"]) == 0:
                return None
            
            metadata = result["metadatas"][0]
            
            return KnowledgeEntry(
                id=result["ids"][0],
                title=metadata["title"],
                content=result["documents"][0],
                category=metadata.get("category") or None,
                tags=metadata.get("tags", "").split(",") if metadata.get("tags") else [],
                source=metadata.get("source") or None,
                priority=int(metadata.get("priority", 0)),
                active=metadata.get("active", True),
                created_at=metadata.get("created_at"),
                updated_at=metadata.get("updated_at")
            )
        except Exception as e:
            print(f"Error getting knowledge entry {entry_id}: {e}")
            return None
    
    def update(self, entry: KnowledgeEntry, embedding: Optional[List[float]] = None) -> bool:
        """
        Update knowledge entry.
        
        Args:
            entry: Updated KnowledgeEntry object
            embedding: New embedding (optional, if content changed)
            
        Returns:
            True if successful
        """
        try:
            update_data = {
                "documents": [entry.content],
                "metadatas": [{
                    "title": entry.title,
                    "category": entry.category or "",
                    "tags": ",".join(entry.tags),
                    "source": entry.source or "",
                    "priority": entry.priority,
                    "active": entry.active,
                    "updated_at": entry.updated_at.isoformat()
                }]
            }
            
            if embedding:
                update_data["embeddings"] = [embedding]
            
            self.collection.update(
                ids=[entry.id],
                **update_data
            )
            return True
        except Exception as e:
            print(f"Error updating knowledge entry {entry.id}: {e}")
            return False
    
    def delete(self, entry_id: str) -> bool:
        """
        Delete knowledge entry.
        
        Args:
            entry_id: Entry ID
            
        Returns:
            True if successful
        """
        try:
            self.collection.delete(ids=[entry_id])
            return True
        except Exception as e:
            print(f"Error deleting knowledge entry {entry_id}: {e}")
            return False
    
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
        try:
            where = {"active": True} if active_only else None
            
            result = self.collection.get(
                where=where,
                include=["documents", "metadatas"],
                limit=limit,
                offset=offset
            )
            
            entries = []
            for i, entry_id in enumerate(result["ids"]):
                metadata = result["metadatas"][i]
                entries.append(KnowledgeEntry(
                    id=entry_id,
                    title=metadata["title"],
                    content=result["documents"][i],
                    category=metadata.get("category") or None,
                    tags=metadata.get("tags", "").split(",") if metadata.get("tags") else [],
                    source=metadata.get("source") or None,
                    priority=int(metadata.get("priority", 0)),
                    active=metadata.get("active", True),
                    created_at=metadata.get("created_at"),
                    updated_at=metadata.get("updated_at")
                ))
            
            return entries
        except Exception as e:
            print(f"Error listing knowledge entries: {e}")
            return []
    
    def count(self, active_only: bool = False) -> int:
        """
        Count knowledge entries.
        
        Args:
            active_only: Only count active entries
            
        Returns:
            Total count
        """
        try:
            where = {"active": True} if active_only else None
            return self.collection.count()
        except Exception:
            return 0
    
    def ping(self) -> bool:
        """
        Check Chroma connection.
        
        Returns:
            True if connected
        """
        try:
            self.collection.count()
            return True
        except Exception:
            return False

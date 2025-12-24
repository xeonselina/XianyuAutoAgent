"""
Knowledge management API routes.
T069 - CRUD endpoints for knowledge base.
"""

from fastapi import APIRouter, Depends, HTTPException
from ai_kefu.api.models import (
    KnowledgeCreateRequest,
    KnowledgeResponse,
    KnowledgeListResponse,
    KnowledgeUpdateRequest,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSearchResult
)
from ai_kefu.api.dependencies import get_knowledge_store
from ai_kefu.storage.knowledge_store import KnowledgeStore
from ai_kefu.models.knowledge import KnowledgeEntry
from ai_kefu.llm.embeddings import generate_embedding
from ai_kefu.utils.logging import logger
from datetime import datetime
import uuid


router = APIRouter()


@router.post("/", response_model=KnowledgeResponse, status_code=201)
async def create_knowledge(
    request: KnowledgeCreateRequest,
    knowledge_store: KnowledgeStore = Depends(get_knowledge_store)
):
    """Create new knowledge entry."""
    try:
        logger.info(f"Creating knowledge entry: {request.title}")
        
        # Generate ID
        entry_id = f"kb_{uuid.uuid4().hex[:12]}"
        
        # Create entry
        entry = KnowledgeEntry(
            id=entry_id,
            title=request.title,
            content=request.content,
            category=request.category,
            tags=request.tags,
            source=request.source,
            priority=request.priority,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        # Generate embedding
        embedding = generate_embedding(entry.content, task_type="retrieval_document")
        
        # Add to store
        success = knowledge_store.add(entry, embedding)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to create knowledge entry")
        
        return KnowledgeResponse(
            id=entry.id,
            title=entry.title,
            content=entry.content,
            category=entry.category,
            tags=entry.tags,
            source=entry.source,
            priority=entry.priority,
            active=entry.active,
            created_at=entry.created_at,
            updated_at=entry.updated_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating knowledge: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=KnowledgeListResponse)
async def list_knowledge(
    offset: int = 0,
    limit: int = 20,
    active_only: bool = True,
    knowledge_store: KnowledgeStore = Depends(get_knowledge_store)
):
    """List all knowledge entries."""
    try:
        entries = knowledge_store.list_all(offset=offset, limit=limit, active_only=active_only)
        total = knowledge_store.count(active_only=active_only)
        
        items = [
            KnowledgeResponse(
                id=e.id,
                title=e.title,
                content=e.content,
                category=e.category,
                tags=e.tags,
                source=e.source,
                priority=e.priority,
                active=e.active,
                created_at=e.created_at,
                updated_at=e.updated_at
            )
            for e in entries
        ]
        
        return KnowledgeListResponse(
            total=total,
            items=items,
            offset=offset,
            limit=limit
        )
        
    except Exception as e:
        logger.error(f"Error listing knowledge: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    request: KnowledgeSearchRequest,
    knowledge_store: KnowledgeStore = Depends(get_knowledge_store)
):
    """Search knowledge base."""
    try:
        # Generate query embedding
        query_embedding = generate_embedding(request.query, task_type="retrieval_query")
        
        # Search
        search_results = knowledge_store.search(
            query_embedding=query_embedding,
            top_k=request.top_k,
            category=request.category,
            active_only=True
        )
        
        # Format results
        results = []
        if search_results["ids"] and len(search_results["ids"][0]) > 0:
            for i, doc_id in enumerate(search_results["ids"][0]):
                metadata = search_results["metadatas"][0][i]
                distance = search_results["distances"][0][i]
                
                results.append(KnowledgeSearchResult(
                    id=doc_id,
                    title=metadata.get("title", ""),
                    content=search_results["documents"][0][i],
                    category=metadata.get("category"),
                    score=1.0 - distance
                ))
        
        return KnowledgeSearchResponse(
            query=request.query,
            results=results,
            total=len(results)
        )
        
    except Exception as e:
        logger.error(f"Error searching knowledge: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{entry_id}", response_model=KnowledgeResponse)
async def update_knowledge(
    entry_id: str,
    request: KnowledgeUpdateRequest,
    knowledge_store: KnowledgeStore = Depends(get_knowledge_store)
):
    """Update knowledge entry."""
    try:
        # Get existing entry
        entry = knowledge_store.get(entry_id)
        
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Knowledge entry not found: {entry_id}")
        
        # Update fields
        if request.title is not None:
            entry.title = request.title
        if request.content is not None:
            entry.content = request.content
        if request.category is not None:
            entry.category = request.category
        if request.tags is not None:
            entry.tags = request.tags
        if request.source is not None:
            entry.source = request.source
        if request.priority is not None:
            entry.priority = request.priority
        if request.active is not None:
            entry.active = request.active
        
        entry.updated_at = datetime.utcnow()
        
        # Generate new embedding if content changed
        embedding = None
        if request.content is not None:
            embedding = generate_embedding(entry.content, task_type="retrieval_document")
        
        # Update in store
        success = knowledge_store.update(entry, embedding)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update knowledge entry")
        
        return KnowledgeResponse(
            id=entry.id,
            title=entry.title,
            content=entry.content,
            category=entry.category,
            tags=entry.tags,
            source=entry.source,
            priority=entry.priority,
            active=entry.active,
            created_at=entry.created_at,
            updated_at=entry.updated_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating knowledge: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{entry_id}")
async def delete_knowledge(
    entry_id: str,
    knowledge_store: KnowledgeStore = Depends(get_knowledge_store)
):
    """Delete knowledge entry."""
    try:
        success = knowledge_store.delete(entry_id)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Knowledge entry not found: {entry_id}")
        
        return {
            "success": True,
            "message": f"Knowledge entry {entry_id} deleted"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting knowledge: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

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
    KnowledgeSearchResult,
    KnowledgeBulkImportRequest,
    KnowledgeBulkImportResponse,
    KnowledgeInitDefaultsResponse
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


# ============================================================
# Bulk Operations
# ============================================================

# Default knowledge entries (from init_knowledge.py)
DEFAULT_KNOWLEDGE = [
    {
        "id": "kb_001",
        "title": "退款政策",
        "content": "用户在收到商品后7天内可申请无理由退款。退款流程：1. 在订单页面点击申请退款 2. 填写退款原因 3. 等待审核（通常1-3个工作日）4. 审核通过后原路退回。注意：商品需保持完好，不影响二次销售。",
        "category": "售后服务",
        "tags": ["退款", "售后", "政策"],
        "source": "官方文档",
        "priority": 10
    },
    {
        "id": "kb_002",
        "title": "发货时间",
        "content": "订单通常在付款后24小时内发货。节假日可能延迟1-2天。您可以在订单详情页查看物流信息和预计送达时间。如果超过3天未发货，请联系客服。",
        "category": "物流配送",
        "tags": ["发货", "物流", "配送"],
        "source": "官方文档",
        "priority": 8
    },
    {
        "id": "kb_003",
        "title": "会员积分规则",
        "content": "每消费1元可获得1积分。积分可用于兑换优惠券或商品。积分有效期为1年，到期自动清零。会员等级分为：普通会员、银卡会员（累计消费1000元）、金卡会员（累计消费5000元）、钻石会员（累计消费10000元）。",
        "category": "会员服务",
        "tags": ["会员", "积分", "等级"],
        "source": "官方文档",
        "priority": 6
    },
    {
        "id": "kb_004",
        "title": "商品质量问题处理",
        "content": "如果收到的商品存在质量问题（破损、瑕疵、功能异常等），请在收货后48小时内联系客服并提供照片证明。我们将提供以下解决方案：1. 免费退换货 2. 部分退款 3. 重新发货。质量问题导致的退换货运费由商家承担。",
        "category": "售后服务",
        "tags": ["质量", "退换货", "售后"],
        "source": "官方文档",
        "priority": 9
    },
    {
        "id": "kb_005",
        "title": "支付方式",
        "content": "我们支持以下支付方式：1. 微信支付 2. 支付宝 3. 银联卡支付 4. 信用卡支付（支持分期）。所有支付均采用加密传输，保证交易安全。支付成功后会立即收到确认短信。",
        "category": "支付相关",
        "tags": ["支付", "付款", "方式"],
        "source": "官方文档",
        "priority": 7
    },
    {
        "id": "kb_006",
        "title": "优惠券使用规则",
        "content": "优惠券使用规则：1. 每个订单限用一张优惠券 2. 优惠券不可叠加使用 3. 部分商品不参与优惠券活动 4. 优惠券有使用期限，过期自动作废 5. 优惠券不可兑换现金。使用时在结算页面选择可用优惠券即可。",
        "category": "优惠活动",
        "tags": ["优惠券", "折扣", "活动"],
        "source": "官方文档",
        "priority": 5
    }
]


@router.post("/bulk", response_model=KnowledgeBulkImportResponse)
async def bulk_import_knowledge(
    request: KnowledgeBulkImportRequest,
    knowledge_store: KnowledgeStore = Depends(get_knowledge_store)
):
    """
    Bulk import knowledge entries from JSON.

    Supports creating multiple entries in one request with optional overwrite.
    """
    try:
        logger.info(f"Bulk importing {len(request.entries)} knowledge entries")

        imported = 0
        skipped = 0
        errors = []

        for entry_data in request.entries:
            try:
                # Check if entry exists
                existing = knowledge_store.get(entry_data.kb_id)

                if existing and not request.overwrite_existing:
                    skipped += 1
                    continue

                # Create KnowledgeEntry object
                entry = KnowledgeEntry(
                    id=entry_data.kb_id,
                    title=entry_data.title,
                    content=entry_data.content,
                    category=entry_data.category,
                    tags=entry_data.tags,
                    source=entry_data.source,
                    priority=entry_data.priority,
                    active=entry_data.active,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )

                if existing and request.overwrite_existing:
                    # Update existing entry
                    success = knowledge_store.update(entry)
                    if success:
                        imported += 1
                    else:
                        errors.append(f"Failed to update {entry_data.kb_id}")
                else:
                    # Create new entry
                    success = knowledge_store.add(entry)
                    if success:
                        imported += 1
                    else:
                        errors.append(f"Failed to create {entry_data.kb_id}")

            except Exception as e:
                errors.append(f"Error processing {entry_data.kb_id}: {str(e)}")

        return KnowledgeBulkImportResponse(
            imported=imported,
            skipped=skipped,
            errors=errors
        )

    except Exception as e:
        logger.error(f"Bulk import error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/init-defaults", response_model=KnowledgeInitDefaultsResponse)
async def initialize_default_knowledge(
    knowledge_store: KnowledgeStore = Depends(get_knowledge_store)
):
    """
    Initialize database with default 6 knowledge entries.

    Idempotent: checks if entries exist before creating.
    """
    try:
        logger.info("Initializing default knowledge entries")

        initialized = 0
        skipped = 0

        for item in DEFAULT_KNOWLEDGE:
            try:
                # Check if entry exists
                existing = knowledge_store.get(item["id"])

                if existing:
                    skipped += 1
                    continue

                # Create entry
                entry = KnowledgeEntry(
                    id=item["id"],
                    title=item["title"],
                    content=item["content"],
                    category=item["category"],
                    tags=item["tags"],
                    source=item["source"],
                    priority=item["priority"],
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )

                if knowledge_store.add(entry):
                    initialized += 1

            except Exception as e:
                logger.error(f"Error initializing {item['id']}: {e}")

        message = "Default knowledge initialized successfully"
        if skipped > 0:
            message = f"Initialized {initialized} entries, {skipped} already existed"

        return KnowledgeInitDefaultsResponse(
            initialized=initialized,
            skipped=skipped,
            message=message
        )

    except Exception as e:
        logger.error(f"Init defaults error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export")
async def export_knowledge(
    active_only: bool = True,
    knowledge_store: KnowledgeStore = Depends(get_knowledge_store)
):
    """
    Export all knowledge entries as JSON.

    Returns downloadable JSON file with all entries.
    """
    try:
        from fastapi.responses import JSONResponse

        logger.info(f"Exporting knowledge (active_only={active_only})")

        # Get all entries
        entries = knowledge_store.mysql_store.export_all(active_only=active_only)

        # Generate filename with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"knowledge_export_{timestamp}.json"

        return JSONResponse(
            content=entries,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )

    except Exception as e:
        logger.error(f"Export error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

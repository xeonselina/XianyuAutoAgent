"""
Conversation history API routes.

Provides endpoints for viewing and searching conversation records
including AI debug mode responses and agent turn-level LLM I/O.
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from ai_kefu.api.dependencies import get_conversation_store


router = APIRouter()


class ReviewRequest(BaseModel):
    rating: int  # 1 = thumbs up, -1 = thumbs down
    comment: Optional[str] = None
    session_id: Optional[str] = None


class TurnReviewRequest(BaseModel):
    rating: int  # 1 = thumbs up, -1 = thumbs down
    comment: Optional[str] = None
    session_id: str  # required so we can store it denormalised


# ─── Fixed-path routes (MUST be before /{chat_id} to avoid conflicts) ─────


@router.get("/recent")
async def get_recent_conversations(
    limit: int = Query(20, ge=1, le=100, description="Number of conversations to return"),
    offset: int = Query(0, ge=0, description="Pagination offset")
):
    """
    Get recent conversations list with pagination.
    Returns conversation summaries sorted by latest message time.
    """
    try:
        store = get_conversation_store()
        result = store.get_recent_conversations(limit=limit, offset=offset)
        
        for item in result['items']:
            for key in ('first_message_at', 'last_message_at'):
                if item.get(key) and isinstance(item[key], datetime):
                    item[key] = item[key].isoformat()
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch conversations: {str(e)}")


@router.get("/stats")
async def get_conversation_stats():
    """
    Get overall conversation statistics.
    """
    try:
        store = get_conversation_store()
        stats = store.get_conversation_stats()
        
        for key in ('earliest_message', 'latest_message'):
            if stats.get(key) and isinstance(stats[key], datetime):
                stats[key] = stats[key].isoformat()
        
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch stats: {str(e)}")


@router.get("/search")
async def search_messages(
    keyword: Optional[str] = Query(None, description="Search keyword"),
    start_time: Optional[str] = Query(None, description="Start time (ISO format)"),
    end_time: Optional[str] = Query(None, description="End time (ISO format)"),
    message_type: Optional[str] = Query(None, description="Message type filter (user/seller/system)"),
    has_agent_response: Optional[bool] = Query(None, description="Filter AI responses"),
    debug_only: bool = Query(False, description="Only show debug mode responses"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Pagination offset")
):
    """
    Search messages with various filters.
    """
    try:
        store = get_conversation_store()
        result = store.search_messages(
            keyword=keyword,
            start_time=start_time,
            end_time=end_time,
            message_type=message_type,
            has_agent_response=has_agent_response,
            debug_only=debug_only,
            limit=limit,
            offset=offset
        )
        
        for item in result['items']:
            for key in ('created_at', 'updated_at'):
                if item.get(key) and isinstance(item[key], datetime):
                    item[key] = item[key].isoformat()
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search messages: {str(e)}")


# ─── Agent Turns routes ───────────────────────────────────────────────────────


@router.get("/turns/recent")
async def get_recent_turns(
    limit: int = Query(50, ge=1, le=200, description="Number of turns to return"),
    offset: int = Query(0, ge=0, description="Pagination offset")
):
    """
    Get recent agent turn records across all sessions.
    Useful for debugging overview.
    """
    try:
        store = get_conversation_store()
        result = store.get_recent_turns(limit=limit, offset=offset)
        
        for item in result['items']:
            if item.get('created_at') and isinstance(item['created_at'], datetime):
                item['created_at'] = item['created_at'].isoformat()
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch turns: {str(e)}")


@router.get("/turns/{session_id}")
async def get_session_turns(
    session_id: str,
    limit: int = Query(100, ge=1, le=500, description="Maximum turns to return"),
    offset: int = Query(0, ge=0, description="Pagination offset")
):
    """
    Get all turn records for a specific agent session.
    Shows complete LLM input/output for each turn.
    """
    try:
        store = get_conversation_store()
        turns = store.get_turns_by_session(
            session_id=session_id,
            limit=limit,
            offset=offset
        )
        
        if not turns:
            raise HTTPException(status_code=404, detail=f"No turns found for session: {session_id}")
        
        for turn in turns:
            if turn.get('created_at') and isinstance(turn['created_at'], datetime):
                turn['created_at'] = turn['created_at'].isoformat()
        
        return {
            'session_id': session_id,
            'turns': turns,
            'total': len(turns)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch session turns: {str(e)}")


@router.post("/turns/{turn_id}/reviews")
async def save_turn_review(turn_id: int, body: TurnReviewRequest):
    """
    Save (upsert) an operator rating for a single agent turn.
    One review per turn; re-submitting updates the previous rating/comment.
    """
    if body.rating not in (1, -1):
        raise HTTPException(status_code=422, detail="rating must be 1 (thumbs up) or -1 (thumbs down)")
    try:
        store = get_conversation_store()
        row_id = store.save_turn_review(
            agent_turn_id=turn_id,
            session_id=body.session_id,
            rating=body.rating,
            comment=body.comment,
        )
        return {"ok": True, "id": row_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save turn review: {str(e)}")


@router.get("/turns/{session_id}/reviews")
async def get_turn_reviews(session_id: str):
    """
    Get all turn reviews for a specific agent session.
    Returns a dict keyed by agent_turn_id for easy lookup.
    """
    try:
        store = get_conversation_store()
        reviews = store.get_turn_reviews_by_session(session_id)
        for r in reviews:
            for key in ('created_at', 'updated_at'):
                if r.get(key) and isinstance(r[key], datetime):
                    r[key] = r[key].isoformat()
        # Build a lookup dict  {agent_turn_id: review}
        reviews_by_turn = {r['agent_turn_id']: r for r in reviews}
        return {"session_id": session_id, "reviews": reviews_by_turn}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch turn reviews: {str(e)}")


# ─── Dynamic path routes (MUST be last) ────────────────────────────────────


@router.post("/{chat_id}/reviews")
async def save_conversation_review(chat_id: str, body: ReviewRequest):
    """
    Save (upsert) an operator review for a conversation.
    One review per chat_id; re-submitting overwrites the previous rating/comment.
    """
    if body.rating not in (1, -1):
        raise HTTPException(status_code=422, detail="rating must be 1 (thumbs up) or -1 (thumbs down)")
    try:
        store = get_conversation_store()
        row_id = store.save_review(
            chat_id=chat_id,
            rating=body.rating,
            comment=body.comment,
            session_id=body.session_id,
        )
        return {"ok": True, "id": row_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save review: {str(e)}")


@router.get("/{chat_id}/reviews")
async def get_conversation_reviews(chat_id: str):
    """
    Get all reviews for a specific chat_id.
    """
    try:
        store = get_conversation_store()
        reviews = store.get_reviews_by_chat(chat_id)
        for r in reviews:
            for key in ('created_at', 'updated_at'):
                if r.get(key) and isinstance(r[key], datetime):
                    r[key] = r[key].isoformat()
        return {"chat_id": chat_id, "reviews": reviews}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch reviews: {str(e)}")


@router.get("/{chat_id}")
async def get_conversation_detail(
    chat_id: str,
    limit: int = Query(200, ge=1, le=1000, description="Maximum messages to return"),
    offset: int = Query(0, ge=0, description="Pagination offset")
):
    """
    Get full conversation history for a specific chat_id.
    Includes AI agent responses and debug mode replies.
    """
    try:
        store = get_conversation_store()
        messages = store.get_conversation_history(
            chat_id=chat_id,
            limit=limit,
            offset=offset
        )
        
        if not messages:
            raise HTTPException(status_code=404, detail=f"No messages found for chat_id: {chat_id}")
        
        # Convert to dict list with serialized datetimes
        result = []
        for msg in messages:
            msg_dict = msg.model_dump()
            for key in ('created_at', 'updated_at'):
                if msg_dict.get(key) and isinstance(msg_dict[key], datetime):
                    msg_dict[key] = msg_dict[key].isoformat()
            result.append(msg_dict)
        
        # Also fetch associated turns if session_id is available
        session_ids = set()
        for msg_dict in result:
            if msg_dict.get('session_id'):
                session_ids.add(msg_dict['session_id'])

        turns_by_session = {}
        for sid in session_ids:
            try:
                turns = store.get_turns_by_session(sid)
                for turn in turns:
                    if turn.get('created_at') and isinstance(turn['created_at'], datetime):
                        turn['created_at'] = turn['created_at'].isoformat()
                turns_by_session[sid] = turns
            except Exception:
                pass

        # Fallback: if no session_ids were found via conversations rows (e.g. all
        # responses were confidence-suppressed and no seller message was saved), query
        # agent_turns directly by chat_id so we can still show the AI reasoning.
        if not turns_by_session:
            try:
                extra = store.get_turns_by_chat_id(chat_id)
                for sid, turns in extra.items():
                    for turn in turns:
                        if turn.get('created_at') and isinstance(turn['created_at'], datetime):
                            turn['created_at'] = turn['created_at'].isoformat()
                turns_by_session.update(extra)
            except Exception:
                pass
        
        return {
            'chat_id': chat_id,
            'messages': result,
            'total': len(result),
            'turns_by_session': turns_by_session
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch conversation: {str(e)}")

# ─── AI Evaluation / Comparison ──────────────────────────────────

def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """
    Calculate Jaccard similarity based on character bigrams.
    Returns value between 0.0 and 1.0.
    """
    if not text_a or not text_b:
        return 0.0
    
    def bigrams(text: str) -> set:
        text = text.strip()
        return {text[i:i+2] for i in range(len(text) - 1)} if len(text) >= 2 else {text}
    
    set_a = bigrams(text_a)
    set_b = bigrams(text_b)
    
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def _length_ratio(text_a: str, text_b: str) -> float:
    """
    Calculate length ratio (shorter / longer).
    Returns value between 0.0 and 1.0.
    """
    if not text_a or not text_b:
        return 0.0
    la, lb = len(text_a.strip()), len(text_b.strip())
    if max(la, lb) == 0:
        return 1.0
    return min(la, lb) / max(la, lb)


@router.post("/{chat_id}/compare")
async def compare_replies(
    chat_id: str,
    message_id: Optional[int] = Query(None, description="Specific message ID to compare (if multiple)"),
):
    """
    AI evaluation: Compare human reply with AI reply for a conversation.
    
    This endpoint finds a user message and compares:
    - Human (seller) reply (if exists)
    - AI reply (if exists)
    
    Returns similarity metrics and comparison analysis.
    """
    try:
        store = get_conversation_store()
        messages = store.get_conversation_history(chat_id=chat_id)
        
        if not messages:
            raise HTTPException(status_code=404, detail=f"No messages found for chat_id: {chat_id}")
        
        # Convert ORM models to dicts
        msg_list = []
        for msg in messages:
            msg_dict = msg.model_dump()
            msg_list.append(msg_dict)
        
        # Find the user message and corresponding human/AI replies
        comparisons = []
        
        for i, msg in enumerate(msg_list):
            if msg['message_type'] != 'user':
                continue
            
            user_message = msg['message_content']
            user_msg_id = msg.get('id')
            
            # Find corresponding human reply (seller message without agent_response)
            human_reply = None
            human_reply_id = None
            for j in range(i + 1, len(msg_list)):
                if msg_list[j]['message_type'] == 'seller' and not msg_list[j].get('agent_response'):
                    human_reply = msg_list[j]['message_content']
                    human_reply_id = msg_list[j].get('id')
                    break
            
            # Find corresponding AI reply (seller message with agent_response)
            ai_reply = None
            ai_reply_id = None
            for j in range(i + 1, len(msg_list)):
                if msg_list[j]['message_type'] == 'seller' and msg_list[j].get('agent_response'):
                    ai_reply = msg_list[j]['message_content']
                    ai_reply_id = msg_list[j].get('id')
                    break
            
            # Only create comparison if we have both human and AI replies
            if human_reply and ai_reply:
                similarity = _jaccard_similarity(human_reply, ai_reply)
                length_ratio = _length_ratio(human_reply, ai_reply)
                
                comparisons.append({
                    'user_msg_id': user_msg_id,
                    'user_message': user_message,
                    'human_reply_id': human_reply_id,
                    'human_reply': human_reply,
                    'ai_reply_id': ai_reply_id,
                    'ai_reply': ai_reply,
                    'similarity': round(similarity, 4),
                    'length_ratio': round(length_ratio, 4),
                    'length_human': len(human_reply.strip()),
                    'length_ai': len(ai_reply.strip()),
                })
        
        if not comparisons:
            return {
                'chat_id': chat_id,
                'status': 'no_data',
                'message': 'No complete pairs of human and AI replies found for comparison',
                'comparisons': []
            }
        
        return {
            'chat_id': chat_id,
            'status': 'ok',
            'total_comparisons': len(comparisons),
            'comparisons': comparisons
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to compare replies: {str(e)}")

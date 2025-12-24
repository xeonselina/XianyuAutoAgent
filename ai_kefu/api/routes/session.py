"""
Session API routes.
T048 - GET /sessions/{id} and DELETE /sessions/{id} endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from ai_kefu.api.models import SessionResponse
from ai_kefu.api.dependencies import get_session_store
from ai_kefu.storage.session_store import SessionStore
from ai_kefu.utils.logging import logger


router = APIRouter()


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    session_store: SessionStore = Depends(get_session_store)
):
    """
    Get session details by ID.
    
    Args:
        session_id: Session ID
        session_store: Session store dependency
        
    Returns:
        SessionResponse with session details
    """
    try:
        logger.info(f"Get session: {session_id}")
        
        # Load session
        session = session_store.get(session_id)
        
        if session is None:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        
        # Convert messages to dict format
        messages_dict = [
            {
                "role": msg.role.value,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
                "tool_calls": [
                    {
                        "id": tc.id,
                        "name": tc.name,
                        "args": tc.args,
                        "status": tc.status.value
                    }
                    for tc in (msg.tool_calls or [])
                ],
                "tool_call_id": msg.tool_call_id,
                "tool_name": msg.tool_name
            }
            for msg in session.messages
        ]
        
        return SessionResponse(
            session_id=session.session_id,
            user_id=session.user_id,
            created_at=session.created_at,
            updated_at=session.updated_at,
            status=session.status,
            turn_counter=session.turn_counter,
            messages=messages_dict,
            context=session.context,
            terminate_reason=session.terminate_reason.value if session.terminate_reason else None,
            metadata=session.metadata
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get session error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    session_store: SessionStore = Depends(get_session_store)
):
    """
    Delete session by ID.
    
    Args:
        session_id: Session ID
        session_store: Session store dependency
        
    Returns:
        Success message
    """
    try:
        logger.info(f"Delete session: {session_id}")
        
        # Delete session
        deleted = session_store.delete(session_id)
        
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        
        return {
            "success": True,
            "message": f"Session {session_id} deleted"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete session error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

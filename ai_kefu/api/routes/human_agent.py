"""
Human agent API routes.
T058 - Human-in-the-Loop API endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from ai_kefu.api.models import (
    PendingRequestsResponse,
    HumanRequestResponse,
    HumanResponseRequest,
    HumanResponseResult
)
from ai_kefu.api.dependencies import get_session_store
from ai_kefu.storage.session_store import SessionStore
from ai_kefu.config.constants import SessionStatus, HumanRequestStatus
from ai_kefu.utils.logging import logger
from datetime import datetime


router = APIRouter()


@router.get("/pending-requests", response_model=PendingRequestsResponse)
async def get_pending_requests(
    session_store: SessionStore = Depends(get_session_store)
):
    """
    Get all pending human assistance requests.
    
    Returns:
        PendingRequestsResponse with list of pending requests
    """
    try:
        logger.info("Fetching pending human requests")
        
        # TODO: Implement actual logic to fetch pending requests
        # For now, return empty list as this requires iterating sessions
        # In production, you'd use a separate index or database query
        
        return PendingRequestsResponse(
            total=0,
            items=[]
        )
        
    except Exception as e:
        logger.error(f"Error fetching pending requests: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}/pending-request", response_model=HumanRequestResponse)
async def get_session_pending_request(
    session_id: str,
    session_store: SessionStore = Depends(get_session_store)
):
    """
    Get pending human request for a specific session.
    
    Args:
        session_id: Session ID
        
    Returns:
        HumanRequestResponse with pending request details
    """
    try:
        logger.info(f"Fetching pending request for session: {session_id}")
        
        # Load session
        session = session_store.get(session_id)
        
        if session is None:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        
        # Check if session has pending request
        if session.pending_human_request is None:
            raise HTTPException(
                status_code=404,
                detail=f"No pending human request for session: {session_id}"
            )
        
        request = session.pending_human_request
        
        # Convert options if present
        options_list = None
        if request.options:
            options_list = [
                {
                    "id": opt.id,
                    "label": opt.label,
                    "description": opt.description
                }
                for opt in request.options
            ]
        
        return HumanRequestResponse(
            request_id=request.request_id,
            session_id=session_id,
            question=request.question,
            question_type=request.question_type,
            context=request.context,
            options=options_list,
            urgency=request.urgency,
            status=request.status.value,
            created_at=request.created_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching session pending request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/human-response", response_model=HumanResponseResult)
async def submit_human_response(
    session_id: str,
    response: HumanResponseRequest,
    session_store: SessionStore = Depends(get_session_store)
):
    """
    Submit human agent response to resume agent execution.
    
    Args:
        session_id: Session ID
        response: Human response data
        
    Returns:
        HumanResponseResult with updated session status
    """
    try:
        logger.info(f"Submitting human response for session: {session_id}")
        
        # Load session
        session = session_store.get(session_id)
        
        if session is None:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        
        # Validate session is waiting for human
        if session.status != SessionStatus.WAITING_FOR_HUMAN:
            raise HTTPException(
                status_code=400,
                detail=f"Session is not waiting for human response. Status: {session.status}"
            )
        
        # Validate request ID matches
        if session.pending_human_request is None:
            raise HTTPException(status_code=400, detail="No pending human request in session")
        
        if session.pending_human_request.request_id != response.request_id:
            raise HTTPException(
                status_code=400,
                detail=f"Request ID mismatch: expected {session.pending_human_request.request_id}, got {response.request_id}"
            )
        
        # Update human request
        session.pending_human_request.status = HumanRequestStatus.ANSWERED
        session.pending_human_request.human_agent_id = response.human_agent_id
        session.pending_human_request.response = response.response
        session.pending_human_request.selected_option = response.selected_option
        session.pending_human_request.answered_at = datetime.utcnow()
        
        # Move to history
        session.human_request_history.append(session.pending_human_request)
        session.pending_human_request = None
        
        # Update session status
        session.status = SessionStatus.ACTIVE
        session.updated_at = datetime.utcnow()
        
        # Save session
        session_store.set(session)
        
        logger.info(f"Human response submitted successfully for session: {session_id}")
        
        return HumanResponseResult(
            success=True,
            message="Human response submitted successfully. Agent will continue execution.",
            session_status=session.status
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting human response: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

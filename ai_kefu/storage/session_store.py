"""
Redis session store implementation.
Handles session persistence with TTL.
"""

import redis
import json
from typing import Optional
from ai_kefu.models.session import Session
from ai_kefu.config.settings import settings


class SessionStore:
    """Redis-based session storage."""
    
    def __init__(self, redis_url: Optional[str] = None, ttl: Optional[int] = None):
        """
        Initialize session store.
        
        Args:
            redis_url: Redis connection URL (defaults to settings.redis_url)
            ttl: Session TTL in seconds (defaults to settings.redis_session_ttl)
        """
        self.redis_url = redis_url or settings.redis_url
        self.ttl = ttl or settings.redis_session_ttl
        self.client = redis.from_url(self.redis_url, decode_responses=True)
    
    def _get_key(self, session_id: str) -> str:
        """Generate Redis key for session."""
        return f"session:{session_id}"
    
    def get(self, session_id: str) -> Optional[Session]:
        """
        Retrieve session by ID.
        
        Args:
            session_id: Session ID
            
        Returns:
            Session object if found, None otherwise
        """
        key = self._get_key(session_id)
        data = self.client.get(key)
        
        if data is None:
            return None
        
        try:
            return Session.model_validate_json(data)
        except Exception as e:
            # Log error and return None
            print(f"Error deserializing session {session_id}: {e}")
            return None
    
    def set(self, session: Session) -> bool:
        """
        Save session with TTL.
        
        Args:
            session: Session object to save
            
        Returns:
            True if successful
        """
        key = self._get_key(session.session_id)
        
        try:
            data = session.model_dump_json()
            self.client.setex(key, self.ttl, data)
            return True
        except Exception as e:
            print(f"Error saving session {session.session_id}: {e}")
            return False
    
    def delete(self, session_id: str) -> bool:
        """
        Delete session.
        
        Args:
            session_id: Session ID
            
        Returns:
            True if deleted, False if not found
        """
        key = self._get_key(session_id)
        result = self.client.delete(key)
        return result > 0
    
    def exists(self, session_id: str) -> bool:
        """
        Check if session exists.
        
        Args:
            session_id: Session ID
            
        Returns:
            True if exists
        """
        key = self._get_key(session_id)
        return self.client.exists(key) > 0
    
    def get_ttl(self, session_id: str) -> int:
        """
        Get remaining TTL for session.
        
        Args:
            session_id: Session ID
            
        Returns:
            TTL in seconds, -1 if no expiration, -2 if not found
        """
        key = self._get_key(session_id)
        return self.client.ttl(key)
    
    def refresh_ttl(self, session_id: str) -> bool:
        """
        Refresh TTL for session.
        
        Args:
            session_id: Session ID
            
        Returns:
            True if successful
        """
        key = self._get_key(session_id)
        return self.client.expire(key, self.ttl)
    
    def ping(self) -> bool:
        """
        Check Redis connection.
        
        Returns:
            True if connected
        """
        try:
            return self.client.ping()
        except Exception:
            return False

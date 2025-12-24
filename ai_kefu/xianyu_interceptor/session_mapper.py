"""
Session mapping between Xianyu chat IDs and Agent session IDs.

Supports both memory-based and Redis-based storage.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict
from datetime import datetime
import uuid
import json

from .models import SessionMapping


class SessionMapper(ABC):
    """Abstract base class for session mapping."""
    
    @abstractmethod
    def get_or_create(self, chat_id: str, user_id: str, item_id: Optional[str] = None) -> str:
        """Get existing Agent session ID or create new one."""
        pass
    
    @abstractmethod
    def get_agent_session_id(self, chat_id: str) -> Optional[str]:
        """Get Agent session ID for a chat ID."""
        pass
    
    @abstractmethod
    def get_chat_id(self, session_id: str) -> Optional[str]:
        """Reverse lookup: get chat ID from Agent session ID."""
        pass
    
    @abstractmethod
    def update_activity(self, chat_id: str):
        """Update last activity timestamp."""
        pass
    
    @abstractmethod
    def set_manual_mode(self, chat_id: str, enabled: bool):
        """Set manual mode for a chat."""
        pass
    
    @abstractmethod
    def is_manual_mode(self, chat_id: str) -> bool:
        """Check if chat is in manual mode."""
        pass
    
    @abstractmethod
    def cleanup_expired(self, ttl: int):
        """Clean up expired sessions."""
        pass


class MemorySessionMapper(SessionMapper):
    """In-memory session mapper."""
    
    def __init__(self):
        self._mappings: Dict[str, SessionMapping] = {}
        self._reverse_index: Dict[str, str] = {}  # session_id -> chat_id
    
    def get_or_create(self, chat_id: str, user_id: str, item_id: Optional[str] = None) -> str:
        """Get existing Agent session ID or create new one."""
        if chat_id in self._mappings:
            mapping = self._mappings[chat_id]
            mapping.last_active = datetime.utcnow()
            return mapping.agent_session_id
        
        # Create new mapping
        agent_session_id = str(uuid.uuid4())
        mapping = SessionMapping(
            xianyu_chat_id=chat_id,
            agent_session_id=agent_session_id,
            user_id=user_id,
            item_id=item_id
        )
        
        self._mappings[chat_id] = mapping
        self._reverse_index[agent_session_id] = chat_id
        
        return agent_session_id
    
    def get_agent_session_id(self, chat_id: str) -> Optional[str]:
        """Get Agent session ID for a chat ID."""
        mapping = self._mappings.get(chat_id)
        return mapping.agent_session_id if mapping else None
    
    def get_chat_id(self, session_id: str) -> Optional[str]:
        """Reverse lookup: get chat ID from Agent session ID."""
        return self._reverse_index.get(session_id)
    
    def update_activity(self, chat_id: str):
        """Update last activity timestamp."""
        if chat_id in self._mappings:
            self._mappings[chat_id].last_active = datetime.utcnow()
    
    def set_manual_mode(self, chat_id: str, enabled: bool):
        """Set manual mode for a chat."""
        if chat_id in self._mappings:
            self._mappings[chat_id].manual_mode = enabled
            if enabled:
                self._mappings[chat_id].manual_mode_entered_at = datetime.utcnow()
            else:
                self._mappings[chat_id].manual_mode_entered_at = None
    
    def is_manual_mode(self, chat_id: str) -> bool:
        """Check if chat is in manual mode."""
        mapping = self._mappings.get(chat_id)
        return mapping.manual_mode if mapping else False
    
    def cleanup_expired(self, ttl: int):
        """Clean up expired sessions."""
        now = datetime.utcnow()
        expired_chats = []
        
        for chat_id, mapping in self._mappings.items():
            elapsed = (now - mapping.last_active).total_seconds()
            if elapsed > ttl:
                expired_chats.append(chat_id)
        
        for chat_id in expired_chats:
            mapping = self._mappings[chat_id]
            del self._reverse_index[mapping.agent_session_id]
            del self._mappings[chat_id]


class RedisSessionMapper(SessionMapper):
    """Redis-based session mapper."""
    
    def __init__(self, redis_url: str):
        try:
            import redis
            self.redis = redis.from_url(redis_url, decode_responses=True)
        except ImportError:
            raise ImportError("redis package is required for RedisSessionMapper")
    
    def _key_forward(self, chat_id: str) -> str:
        """Get forward mapping key."""
        return f"xianyu:session:{chat_id}"
    
    def _key_reverse(self, session_id: str) -> str:
        """Get reverse mapping key."""
        return f"xianyu:session:rev:{session_id}"
    
    def _key_meta(self, chat_id: str) -> str:
        """Get metadata key."""
        return f"xianyu:session:meta:{chat_id}"
    
    def get_or_create(self, chat_id: str, user_id: str, item_id: Optional[str] = None) -> str:
        """Get existing Agent session ID or create new one."""
        session_id = self.redis.get(self._key_forward(chat_id))
        
        if session_id:
            # Update activity
            self.update_activity(chat_id)
            return session_id
        
        # Create new mapping
        agent_session_id = str(uuid.uuid4())
        mapping = SessionMapping(
            xianyu_chat_id=chat_id,
            agent_session_id=agent_session_id,
            user_id=user_id,
            item_id=item_id
        )
        
        # Store in Redis
        self.redis.set(self._key_forward(chat_id), agent_session_id)
        self.redis.set(self._key_reverse(agent_session_id), chat_id)
        self.redis.setex(self._key_meta(chat_id), 3600, mapping.model_dump_json())
        
        return agent_session_id
    
    def get_agent_session_id(self, chat_id: str) -> Optional[str]:
        """Get Agent session ID for a chat ID."""
        return self.redis.get(self._key_forward(chat_id))
    
    def get_chat_id(self, session_id: str) -> Optional[str]:
        """Reverse lookup: get chat ID from Agent session ID."""
        return self.redis.get(self._key_reverse(session_id))
    
    def update_activity(self, chat_id: str):
        """Update last activity timestamp."""
        meta_json = self.redis.get(self._key_meta(chat_id))
        if meta_json:
            mapping = SessionMapping.model_validate_json(meta_json)
            mapping.last_active = datetime.utcnow()
            self.redis.setex(self._key_meta(chat_id), 3600, mapping.model_dump_json())
    
    def set_manual_mode(self, chat_id: str, enabled: bool):
        """Set manual mode for a chat."""
        meta_json = self.redis.get(self._key_meta(chat_id))
        if meta_json:
            mapping = SessionMapping.model_validate_json(meta_json)
            mapping.manual_mode = enabled
            if enabled:
                mapping.manual_mode_entered_at = datetime.utcnow()
            else:
                mapping.manual_mode_entered_at = None
            self.redis.setex(self._key_meta(chat_id), 3600, mapping.model_dump_json())
    
    def is_manual_mode(self, chat_id: str) -> bool:
        """Check if chat is in manual mode."""
        meta_json = self.redis.get(self._key_meta(chat_id))
        if meta_json:
            mapping = SessionMapping.model_validate_json(meta_json)
            return mapping.manual_mode
        return False
    
    def cleanup_expired(self, ttl: int):
        """Clean up expired sessions (handled by Redis TTL)."""
        # Redis handles expiration automatically with TTL
        pass

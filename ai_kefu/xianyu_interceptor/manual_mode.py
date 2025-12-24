"""
Manual mode manager for Xianyu Interceptor.

Allows users to manually control conversations by toggling auto-reply on/off.
"""

import time
from typing import Dict
from loguru import logger

from .models import ManualModeState


class ManualModeManager:
    """Manager for manual mode state."""
    
    def __init__(self, timeout: int = 3600):
        """
        Initialize manual mode manager.
        
        Args:
            timeout: Manual mode timeout in seconds (default: 1 hour)
        """
        self.timeout = timeout
        self.manual_sessions: Dict[str, ManualModeState] = {}
    
    def toggle_manual_mode(self, chat_id: str) -> bool:
        """
        Toggle manual mode for a conversation.
        
        Args:
            chat_id: Conversation ID
            
        Returns:
            True if manual mode is now enabled, False if disabled
        """
        if chat_id in self.manual_sessions:
            # Exit manual mode
            del self.manual_sessions[chat_id]
            logger.info(f"Chat {chat_id} exited manual mode")
            return False
        else:
            # Enter manual mode
            state = ManualModeState(
                chat_id=chat_id,
                enabled=True,
                timeout=self.timeout
            )
            self.manual_sessions[chat_id] = state
            logger.info(f"Chat {chat_id} entered manual mode")
            return True
    
    def is_manual_mode(self, chat_id: str) -> bool:
        """
        Check if conversation is in manual mode.
        
        Args:
            chat_id: Conversation ID
            
        Returns:
            True if in manual mode, False otherwise
        """
        if chat_id not in self.manual_sessions:
            return False
        
        state = self.manual_sessions[chat_id]
        
        # Check if expired
        if state.is_expired():
            logger.info(f"Chat {chat_id} manual mode timed out")
            del self.manual_sessions[chat_id]
            return False
        
        return True
    
    def refresh_activity(self, chat_id: str):
        """
        Refresh manual mode activity timestamp.
        
        Args:
            chat_id: Conversation ID
        """
        if chat_id in self.manual_sessions:
            self.manual_sessions[chat_id].refresh()
    
    def cleanup_expired(self):
        """Clean up expired manual mode sessions."""
        expired_chats = []
        
        for chat_id, state in self.manual_sessions.items():
            if state.is_expired():
                expired_chats.append(chat_id)
        
        for chat_id in expired_chats:
            logger.info(f"Cleaning up expired manual mode for chat {chat_id}")
            del self.manual_sessions[chat_id]

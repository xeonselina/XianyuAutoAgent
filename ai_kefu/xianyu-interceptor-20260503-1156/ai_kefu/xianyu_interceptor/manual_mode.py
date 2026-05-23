"""
Manual mode manager for Xianyu Interceptor.

Allows users to manually control conversations by toggling auto-reply on/off.
Also supports time-limited AI suppression (seller secret code).
"""

import time
from typing import Dict, Optional, Tuple
from loguru import logger

from .models import ManualModeState


class ManualModeManager:
    """Manager for manual mode state and AI suppression."""
    
    def __init__(self, timeout: int = 3600):
        """
        Initialize manual mode manager.
        
        Args:
            timeout: Manual mode timeout in seconds (default: 1 hour)
        """
        self.timeout = timeout
        self.manual_sessions: Dict[str, ManualModeState] = {}
        # AI suppression: chat_id -> (expire_monotonic_time, duration_seconds)
        self._suppressed: Dict[str, Tuple[float, int]] = {}
    
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
        
        # Also clean up expired suppressions
        now = time.monotonic()
        expired_suppressed = [
            cid for cid, (expire_at, _) in self._suppressed.items()
            if now >= expire_at
        ]
        for cid in expired_suppressed:
            del self._suppressed[cid]
            logger.info(f"AI suppression expired for chat {cid}")

    # ============================================================
    # AI Suppression (seller secret code)
    # ============================================================

    def suppress_ai(self, chat_id: str, duration_seconds: int = 600):
        """
        Suppress AI replies for a chat for a given duration.

        When the seller (human agent) sends the secret code, this method
        is called to temporarily stop the AI from replying.

        Args:
            chat_id: Conversation ID
            duration_seconds: How long to suppress AI (default 10 minutes)
        """
        expire_at = time.monotonic() + duration_seconds
        self._suppressed[chat_id] = (expire_at, duration_seconds)
        logger.info(
            f"🔇 AI suppressed for chat {chat_id} "
            f"for {duration_seconds}s ({duration_seconds // 60} min)"
        )

    def is_suppressed(self, chat_id: str) -> bool:
        """
        Check if AI is currently suppressed for a chat.

        Args:
            chat_id: Conversation ID

        Returns:
            True if AI replies are suppressed
        """
        if chat_id not in self._suppressed:
            return False

        expire_at, _ = self._suppressed[chat_id]
        if time.monotonic() >= expire_at:
            # Expired — clean up and return False
            del self._suppressed[chat_id]
            logger.info(f"AI suppression expired for chat {chat_id}")
            return False

        return True

    def cancel_suppression(self, chat_id: str):
        """
        Cancel AI suppression for a chat (e.g. seller sends another code).

        Args:
            chat_id: Conversation ID
        """
        if chat_id in self._suppressed:
            del self._suppressed[chat_id]
            logger.info(f"AI suppression cancelled for chat {chat_id}")

    def get_suppress_remaining(self, chat_id: str) -> Optional[int]:
        """
        Get the remaining suppression time in seconds.

        Args:
            chat_id: Conversation ID

        Returns:
            Remaining seconds, or None if not suppressed
        """
        if chat_id not in self._suppressed:
            return None

        expire_at, _ = self._suppressed[chat_id]
        remaining = expire_at - time.monotonic()
        if remaining <= 0:
            del self._suppressed[chat_id]
            return None

        return int(remaining)

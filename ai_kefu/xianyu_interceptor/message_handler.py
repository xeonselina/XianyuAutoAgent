"""
Message handler that integrates Xianyu messages with AI Agent service.

This module handles the core message processing flow:
1. Receive Xianyu message
2. Check manual mode
3. Get/create Agent session
4. Convert message format
5. Call Agent API
6. Convert response
7. Send reply
"""

import asyncio
from typing import Optional
from loguru import logger

from .models import XianyuMessage, XianyuMessageType
from .message_converter import convert_xianyu_to_agent, convert_agent_to_xianyu
from .session_mapper import SessionMapper
from .manual_mode import ManualModeManager
from .http_client import AgentClient
from .exceptions import AgentAPIError
from .config import config


class MessageHandler:
    """
    Handles message processing with AI Agent integration.
    """
    
    def __init__(
        self,
        agent_client: AgentClient,
        session_mapper: SessionMapper,
        manual_mode_manager: ManualModeManager,
        transport: Optional[any] = None
    ):
        """
        Initialize message handler.
        
        Args:
            agent_client: HTTP client for Agent service
            session_mapper: Session mapping manager
            manual_mode_manager: Manual mode manager
            transport: Message transport for sending replies (optional)
        """
        self.agent_client = agent_client
        self.session_mapper = session_mapper
        self.manual_mode_manager = manual_mode_manager
        self.transport = transport
        self.toggle_keywords = config.toggle_keywords.split(',')
    
    async def handle_message(self, message: XianyuMessage) -> Optional[str]:
        """
        Handle an incoming Xianyu message.
        
        Args:
            message: Xianyu message object
            
        Returns:
            Agent response text, or None if no response
        """
        try:
            logger.info(
                f"Received message from chat_id={message.chat_id}, "
                f"user_id={message.user_id}, content={message.content}"
            )
            
            # Skip non-chat messages
            if message.message_type != XianyuMessageType.CHAT:
                logger.debug(f"Skipping non-chat message: {message.message_type}")
                return None
            
            # Check for manual mode toggle
            if self._is_toggle_keyword(message.content):
                return await self._handle_manual_mode_toggle(message)
            
            # Check if in manual mode
            if self.manual_mode_manager.is_manual_mode(message.chat_id):
                logger.info(f"Chat {message.chat_id} is in manual mode, skipping AI")
                return None
            
            # Process with AI Agent
            return await self._process_with_agent(message)
            
        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
            return None
    
    def _is_toggle_keyword(self, content: Optional[str]) -> bool:
        """Check if message is a manual mode toggle keyword."""
        if not content:
            return False
        return content.strip() in self.toggle_keywords
    
    async def _handle_manual_mode_toggle(self, message: XianyuMessage) -> str:
        """
        Handle manual mode toggle.
        
        Args:
            message: Xianyu message
            
        Returns:
            Status message
        """
        is_manual = self.manual_mode_manager.toggle_manual_mode(message.chat_id)
        
        # Update session mapper
        self.session_mapper.set_manual_mode(message.chat_id, is_manual)
        
        mode_text = "手动" if is_manual else "自动"
        response_text = f"已切换到{mode_text}模式"
        
        logger.info(f"Chat {message.chat_id} toggled to {mode_text} mode")
        
        # Send reply if transport available
        if self.transport:
            await self._send_reply(message, response_text)
        
        return response_text
    
    async def _process_with_agent(self, message: XianyuMessage) -> Optional[str]:
        """
        Process message with AI Agent.
        
        Args:
            message: Xianyu message
            
        Returns:
            Agent response text, or None on error
        """
        try:
            # Get or create Agent session
            agent_session_id = self.session_mapper.get_or_create(
                chat_id=message.chat_id,
                user_id=message.user_id,
                item_id=message.item_id
            )
            
            logger.info(
                f"Processing with Agent: chat_id={message.chat_id}, "
                f"session_id={agent_session_id}"
            )
            
            # Convert to Agent format
            agent_request = convert_xianyu_to_agent(message, agent_session_id)
            
            # Call Agent API
            logger.info("Calling Agent API...")
            agent_response = await self.agent_client.send_message(
                query=agent_request.query,
                session_id=agent_request.session_id,
                user_id=agent_request.user_id,
                context=agent_request.context
            )
            
            logger.info(
                f"Agent response received: {agent_response.response[:100]}..."
            )
            
            # Update session activity
            self.session_mapper.update_activity(message.chat_id)
            
            # Send reply if transport available
            if self.transport:
                await self._send_reply(message, agent_response.response)
            
            return agent_response.response
            
        except AgentAPIError as e:
            logger.error(f"Agent API failed for chat {message.chat_id}: {e}")
            
            # Fallback strategy: skip reply, log error
            if config.agent_client_config.enable_fallback and \
               config.agent_client_config.fallback_message:
                fallback_msg = config.agent_client_config.fallback_message
                if self.transport:
                    await self._send_reply(message, fallback_msg)
                return fallback_msg
            
            return None
            
        except Exception as e:
            logger.error(f"Unexpected error processing message: {e}", exc_info=True)
            return None
    
    async def _send_reply(self, original_message: XianyuMessage, content: str):
        """
        Send reply through transport.
        
        Args:
            original_message: Original Xianyu message
            content: Reply content
        """
        if not self.transport:
            logger.warning("No transport available, cannot send reply")
            return
        
        try:
            success = await self.transport.send_message(
                chat_id=original_message.chat_id,
                user_id=original_message.user_id,
                content=content
            )
            
            if success:
                logger.info(f"Sent reply to chat {original_message.chat_id}")
            else:
                logger.warning(f"Failed to send reply to chat {original_message.chat_id}")
                
        except Exception as e:
            logger.error(f"Error sending reply: {e}", exc_info=True)

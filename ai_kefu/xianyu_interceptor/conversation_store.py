"""
Conversation storage layer for MySQL persistence.

This module provides the ConversationStore class for saving and retrieving
Xianyu conversation messages from MySQL database.
"""

import json
from typing import List, Optional, Dict, Any
from datetime import datetime
import pymysql
from pymysql.cursors import DictCursor
from contextlib import contextmanager
from loguru import logger

from .conversation_models import ConversationMessage, MessageType


class ConversationStore:
    """
    MySQL-based conversation storage.
    
    Handles connection pooling, message persistence, and query operations.
    """
    
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        pool_size: int = 5
    ):
        """
        Initialize the conversation store.
        
        Args:
            host: MySQL host address
            port: MySQL port
            user: MySQL username
            password: MySQL password
            database: MySQL database name
            pool_size: Connection pool size (not used with pymysql, kept for API compatibility)
        """
        self.config = {
            'host': host,
            'port': port,
            'user': user,
            'password': password,
            'database': database,
            'charset': 'utf8mb4',
            'cursorclass': DictCursor,
            'autocommit': False
        }
        self._connection = None
        logger.info(f"ConversationStore initialized for database: {database}@{host}:{port}")
    
    def _get_connection(self) -> pymysql.Connection:
        """
        Get or create a database connection with auto-reconnect.
        
        Returns:
            Active MySQL connection
        """
        if self._connection is None or not self._ping():
            try:
                self._connection = pymysql.connect(**self.config)
                logger.debug("Created new MySQL connection")
            except Exception as e:
                logger.error(f"Failed to connect to MySQL: {e}")
                raise
        return self._connection
    
    def _ping(self) -> bool:
        """
        Check if connection is alive.
        
        Returns:
            True if connection is alive, False otherwise
        """
        try:
            if self._connection:
                self._connection.ping(reconnect=False)
                return True
        except:
            pass
        return False
    
    def health_check(self) -> bool:
        """
        Perform a health check on the database connection.
        
        Returns:
            True if connection is healthy, False otherwise
        """
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            return True
        except Exception as e:
            logger.warning(f"Database health check failed: {e}")
            return False
    
    def save_message(self, message: ConversationMessage) -> int:
        """
        Save a conversation message to the database.
        
        Args:
            message: The message to save
            
        Returns:
            The ID of the inserted row
            
        Raises:
            Exception: If database operation fails
        """
        try:
            conn = self._get_connection()
            
            # Prepare context JSON
            context_json = json.dumps(message.context) if message.context else None
            
            sql = """
                INSERT INTO conversations (
                    chat_id, user_id, seller_id, item_id,
                    message_content, message_type,
                    session_id, agent_response,
                    context, created_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s
                )
            """
            
            values = (
                message.chat_id,
                message.user_id,
                message.seller_id,
                message.item_id,
                message.message_content,
                message.message_type.value if isinstance(message.message_type, MessageType) else message.message_type,
                message.session_id,
                message.agent_response,
                context_json,
                message.created_at or datetime.now()
            )
            
            with conn.cursor() as cursor:
                cursor.execute(sql, values)
                conn.commit()
                row_id = cursor.lastrowid
                
            logger.info(
                f"Saved message to database: chat_id={message.chat_id}, "
                f"type={message.message_type}, id={row_id}"
            )
            return row_id
            
        except Exception as e:
            logger.error(f"Failed to save message to database: {e}")
            if conn:
                conn.rollback()
            raise
    
    def get_conversation_history(
        self,
        chat_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[ConversationMessage]:
        """
        Retrieve conversation history for a chat.
        
        Args:
            chat_id: The chat ID to query
            limit: Maximum number of messages to return
            offset: Number of messages to skip (for pagination)
            
        Returns:
            List of ConversationMessage objects
        """
        try:
            conn = self._get_connection()
            
            sql = """
                SELECT * FROM conversations
                WHERE chat_id = %s
                ORDER BY created_at ASC
                LIMIT %s OFFSET %s
            """
            
            with conn.cursor() as cursor:
                cursor.execute(sql, (chat_id, limit, offset))
                rows = cursor.fetchall()
            
            messages = []
            for row in rows:
                # Parse context JSON
                if row.get('context'):
                    try:
                        row['context'] = json.loads(row['context'])
                    except:
                        row['context'] = None
                
                messages.append(ConversationMessage(**row))
            
            logger.debug(f"Retrieved {len(messages)} messages for chat_id={chat_id}")
            return messages
            
        except Exception as e:
            logger.error(f"Failed to retrieve conversation history: {e}")
            raise
    
    def get_recent_conversations(
        self,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get summary of recent conversations.
        
        Args:
            limit: Number of conversations to return
            
        Returns:
            List of conversation summaries
        """
        try:
            conn = self._get_connection()
            
            sql = """
                SELECT 
                    chat_id,
                    user_id,
                    seller_id,
                    item_id,
                    COUNT(*) as message_count,
                    MIN(created_at) as first_message_at,
                    MAX(created_at) as last_message_at
                FROM conversations
                GROUP BY chat_id, user_id, seller_id, item_id
                ORDER BY MAX(created_at) DESC
                LIMIT %s
            """
            
            with conn.cursor() as cursor:
                cursor.execute(sql, (limit,))
                rows = cursor.fetchall()
            
            logger.debug(f"Retrieved {len(rows)} recent conversations")
            return rows
            
        except Exception as e:
            logger.error(f"Failed to retrieve recent conversations: {e}")
            raise
    
    def close(self):
        """Close the database connection."""
        if self._connection:
            try:
                self._connection.close()
                logger.info("Closed MySQL connection")
            except Exception as e:
                logger.warning(f"Error closing MySQL connection: {e}")
            finally:
                self._connection = None
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False

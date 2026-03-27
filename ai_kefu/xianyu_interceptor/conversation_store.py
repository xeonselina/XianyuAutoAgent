"""
Conversation storage layer for MySQL persistence.

This module provides the ConversationStore class for saving and retrieving
Xianyu conversation messages from MySQL database.
"""

import json
import threading
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
        self._lock = threading.Lock()  # Protect connection from concurrent thread access
        logger.info(f"ConversationStore initialized for database: {database}@{host}:{port}")
        self._ensure_table_exists()
    
    def _ensure_table_exists(self):
        """
        Ensure the conversations and agent_turns tables exist, create them if not.
        """
        create_conversations_sql = """
            CREATE TABLE IF NOT EXISTS conversations (
                id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT 'Auto-increment primary key',
                chat_id VARCHAR(255) NOT NULL COMMENT 'Xianyu chat ID',
                user_id VARCHAR(255) NOT NULL COMMENT 'User ID who sent the message',
                seller_id VARCHAR(255) COMMENT 'Seller ID (owner of the account)',
                item_id VARCHAR(255) COMMENT 'Item ID if available',

                message_content TEXT NOT NULL COMMENT 'Message content',
                message_type ENUM('user', 'seller', 'system') NOT NULL COMMENT 'Message sender type',

                session_id VARCHAR(255) COMMENT 'AI Agent session ID if AI was used',
                agent_response TEXT COMMENT 'AI Agent response if this was an AI reply',

                context JSON COMMENT 'Additional context metadata',

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Message timestamp',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Record update timestamp',

                INDEX idx_chat_id (chat_id),
                INDEX idx_user_id (user_id),
                INDEX idx_seller_id (seller_id),
                INDEX idx_created_at (created_at),
                INDEX idx_chat_created (chat_id, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            COMMENT='Xianyu conversation history'
        """

        create_agent_turns_sql = """
            CREATE TABLE IF NOT EXISTS agent_turns (
                id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT 'Auto-increment primary key',
                session_id VARCHAR(255) NOT NULL COMMENT 'Agent session ID',
                turn_number INT NOT NULL COMMENT 'Turn sequence number within session',
                user_query TEXT COMMENT 'Original user query that triggered this agent run',

                llm_input LONGTEXT COMMENT 'Full messages array sent to LLM (JSON)',
                llm_output LONGTEXT COMMENT 'Raw LLM response (JSON)',
                response_text TEXT COMMENT 'LLM text response content',

                tool_calls JSON COMMENT 'Tool calls made in this turn (JSON array)',
                tool_results JSON COMMENT 'Tool execution results (JSON array)',

                duration_ms INT COMMENT 'Turn execution duration in milliseconds',
                success BOOLEAN DEFAULT TRUE COMMENT 'Whether turn succeeded',
                error_message TEXT COMMENT 'Error message if turn failed',

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Turn timestamp',

                INDEX idx_session_id (session_id),
                INDEX idx_session_turn (session_id, turn_number),
                INDEX idx_created_at (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            COMMENT='Agent turn-level LLM input/output records for debugging'
        """
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(create_conversations_sql)
                cursor.execute(create_agent_turns_sql)
                conn.commit()
            logger.info("Ensured 'conversations' and 'agent_turns' tables exist")
        except Exception as e:
            logger.error(f"Failed to ensure tables exist: {e}")

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
        with self._lock:
            conn = None
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
                    try:
                        conn.rollback()
                    except Exception:
                        pass
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
        limit: int = 10,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Get summary of recent conversations with pagination.
        
        Args:
            limit: Number of conversations to return
            offset: Number of conversations to skip
            
        Returns:
            Dict with 'items' (list of conversation summaries) and 'total' count
        """
        try:
            conn = self._get_connection()
            
            # Get total count
            count_sql = """
                SELECT COUNT(DISTINCT chat_id) as total
                FROM conversations
            """
            
            sql = """
                SELECT 
                    c.chat_id,
                    c.user_id,
                    c.seller_id,
                    c.item_id,
                    COUNT(*) as message_count,
                    SUM(CASE WHEN c.message_type = 'user' THEN 1 ELSE 0 END) as user_messages,
                    SUM(CASE WHEN c.message_type = 'seller' THEN 1 ELSE 0 END) as seller_messages,
                    SUM(CASE WHEN c.agent_response IS NOT NULL THEN 1 ELSE 0 END) as ai_replies,
                    SUM(CASE WHEN c.agent_response LIKE '【调试】%%' THEN 1 ELSE 0 END) as debug_replies,
                    MIN(c.created_at) as first_message_at,
                    MAX(c.created_at) as last_message_at
                FROM conversations c
                GROUP BY c.chat_id, c.user_id, c.seller_id, c.item_id
                ORDER BY MAX(c.created_at) DESC
                LIMIT %s OFFSET %s
            """
            
            with conn.cursor() as cursor:
                cursor.execute(count_sql)
                total = cursor.fetchone()['total']
                
                cursor.execute(sql, (limit, offset))
                rows = cursor.fetchall()
                
                # Get latest message content for each conversation
                for row in rows:
                    latest_sql = """
                        SELECT message_content, message_type, agent_response
                        FROM conversations 
                        WHERE chat_id = %s
                        ORDER BY created_at DESC
                        LIMIT 1
                    """
                    cursor.execute(latest_sql, (row['chat_id'],))
                    latest = cursor.fetchone()
                    if latest:
                        row['latest_message'] = latest['message_content'][:100]
                        row['latest_message_type'] = latest['message_type']
                        row['latest_agent_response'] = (latest['agent_response'] or '')[:100] if latest['agent_response'] else None
            
            logger.debug(f"Retrieved {len(rows)} recent conversations (total: {total})")
            return {'items': rows, 'total': total}
            
        except Exception as e:
            logger.error(f"Failed to retrieve recent conversations: {e}")
            raise

    def search_messages(
        self,
        keyword: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        message_type: Optional[str] = None,
        has_agent_response: Optional[bool] = None,
        debug_only: bool = False,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Search messages with various filters.
        
        Args:
            keyword: Search keyword in message content or agent response
            start_time: Start time filter (ISO format)
            end_time: End time filter (ISO format)
            message_type: Filter by message type (user/seller/system)
            has_agent_response: Filter messages that have AI responses
            debug_only: Only return debug mode responses
            limit: Maximum number of results
            offset: Pagination offset
            
        Returns:
            Dict with 'items' (list of messages) and 'total' count
        """
        try:
            conn = self._get_connection()
            
            conditions = []
            params = []
            
            if keyword:
                conditions.append("(message_content LIKE %s OR agent_response LIKE %s)")
                like_param = f"%{keyword}%"
                params.extend([like_param, like_param])
            
            if start_time:
                conditions.append("created_at >= %s")
                params.append(start_time)
            
            if end_time:
                conditions.append("created_at <= %s")
                params.append(end_time)
            
            if message_type:
                conditions.append("message_type = %s")
                params.append(message_type)
            
            if has_agent_response is True:
                conditions.append("agent_response IS NOT NULL AND agent_response != ''")
            elif has_agent_response is False:
                conditions.append("(agent_response IS NULL OR agent_response = '')")
            
            if debug_only:
                conditions.append("agent_response LIKE '【调试】%%'")
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            count_sql = f"SELECT COUNT(*) as total FROM conversations WHERE {where_clause}"
            sql = f"""
                SELECT * FROM conversations
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """
            
            with conn.cursor() as cursor:
                cursor.execute(count_sql, params)
                total = cursor.fetchone()['total']
                
                cursor.execute(sql, params + [limit, offset])
                rows = cursor.fetchall()
            
            messages = []
            for row in rows:
                if row.get('context'):
                    try:
                        row['context'] = json.loads(row['context'])
                    except:
                        row['context'] = None
                messages.append(row)
            
            logger.debug(f"Search found {total} messages (returning {len(messages)})")
            return {'items': messages, 'total': total}
            
        except Exception as e:
            logger.error(f"Failed to search messages: {e}")
            raise

    def get_conversation_stats(self) -> Dict[str, Any]:
        """
        Get overall conversation statistics.
        
        Returns:
            Dict with statistics
        """
        try:
            conn = self._get_connection()
            
            sql = """
                SELECT 
                    COUNT(*) as total_messages,
                    COUNT(DISTINCT chat_id) as total_conversations,
                    SUM(CASE WHEN message_type = 'user' THEN 1 ELSE 0 END) as user_messages,
                    SUM(CASE WHEN message_type = 'seller' THEN 1 ELSE 0 END) as seller_messages,
                    SUM(CASE WHEN agent_response IS NOT NULL THEN 1 ELSE 0 END) as ai_replies,
                    SUM(CASE WHEN agent_response LIKE '【调试】%%' THEN 1 ELSE 0 END) as debug_replies,
                    MIN(created_at) as earliest_message,
                    MAX(created_at) as latest_message
                FROM conversations
            """
            
            with conn.cursor() as cursor:
                cursor.execute(sql)
                stats = cursor.fetchone()
            
            return stats or {}
            
        except Exception as e:
            logger.error(f"Failed to get conversation stats: {e}")
            raise
    
    def save_turn(
        self,
        session_id: str,
        turn_number: int,
        user_query: Optional[str],
        llm_input: Optional[Any],
        llm_output: Optional[Any],
        response_text: Optional[str],
        tool_calls: Optional[List],
        tool_results: Optional[List],
        duration_ms: Optional[int],
        success: bool = True,
        error_message: Optional[str] = None
    ) -> int:
        """
        Save an agent turn record for debugging.
        
        Args:
            session_id: Agent session ID
            turn_number: Turn sequence number
            user_query: Original user query
            llm_input: Full messages array sent to LLM
            llm_output: Raw LLM response
            response_text: LLM text response
            tool_calls: Tool calls made in this turn
            tool_results: Tool execution results
            duration_ms: Turn duration
            success: Whether turn succeeded
            error_message: Error message if failed
            
        Returns:
            The ID of the inserted row
        """
        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                
                sql = """
                    INSERT INTO agent_turns (
                        session_id, turn_number, user_query,
                        llm_input, llm_output, response_text,
                        tool_calls, tool_results,
                        duration_ms, success, error_message
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s
                    )
                """
                
                def safe_json_dumps(obj):
                    if obj is None:
                        return None
                    try:
                        return json.dumps(obj, ensure_ascii=False, default=str)
                    except Exception:
                        return json.dumps(str(obj), ensure_ascii=False)
                
                values = (
                    session_id,
                    turn_number,
                    user_query,
                    safe_json_dumps(llm_input),
                    safe_json_dumps(llm_output),
                    response_text,
                    safe_json_dumps(tool_calls),
                    safe_json_dumps(tool_results),
                    duration_ms,
                    success,
                    error_message
                )
                
                with conn.cursor() as cursor:
                    cursor.execute(sql, values)
                    conn.commit()
                    row_id = cursor.lastrowid
                
                logger.info(
                    f"Saved turn record: session={session_id}, "
                    f"turn={turn_number}, success={success}, id={row_id}"
                )
                return row_id
                
            except Exception as e:
                logger.error(f"Failed to save turn record: {e}")
                if conn:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                # Don't raise - turn logging should not break the agent flow
                return -1

    def get_turns_by_session(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Get all turn records for a session.
        
        Args:
            session_id: Agent session ID
            limit: Maximum number of turns to return
            offset: Pagination offset
            
        Returns:
            List of turn records
        """
        try:
            conn = self._get_connection()
            
            sql = """
                SELECT * FROM agent_turns
                WHERE session_id = %s
                ORDER BY turn_number ASC
                LIMIT %s OFFSET %s
            """
            
            with conn.cursor() as cursor:
                cursor.execute(sql, (session_id, limit, offset))
                rows = cursor.fetchall()
            
            turns = []
            for row in rows:
                for json_field in ('llm_input', 'llm_output', 'tool_calls', 'tool_results'):
                    if row.get(json_field):
                        try:
                            row[json_field] = json.loads(row[json_field])
                        except:
                            pass
                turns.append(row)
            
            logger.debug(f"Retrieved {len(turns)} turns for session={session_id}")
            return turns
            
        except Exception as e:
            logger.error(f"Failed to get turns by session: {e}")
            raise

    def get_recent_turns(
        self,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Get recent turn records across all sessions for debugging overview.
        
        Args:
            limit: Maximum number of turns to return
            offset: Pagination offset
            
        Returns:
            Dict with 'items' and 'total'
        """
        try:
            conn = self._get_connection()
            
            count_sql = "SELECT COUNT(*) as total FROM agent_turns"
            sql = """
                SELECT * FROM agent_turns
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """
            
            with conn.cursor() as cursor:
                cursor.execute(count_sql)
                total = cursor.fetchone()['total']
                
                cursor.execute(sql, (limit, offset))
                rows = cursor.fetchall()
            
            turns = []
            for row in rows:
                for json_field in ('llm_input', 'llm_output', 'tool_calls', 'tool_results'):
                    if row.get(json_field):
                        try:
                            row[json_field] = json.loads(row[json_field])
                        except:
                            pass
                turns.append(row)
            
            return {'items': turns, 'total': total}
            
        except Exception as e:
            logger.error(f"Failed to get recent turns: {e}")
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

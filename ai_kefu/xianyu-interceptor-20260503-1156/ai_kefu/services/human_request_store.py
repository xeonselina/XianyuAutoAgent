"""
MySQL 持久化存储 Human-in-the-Loop 请求。

独立于 Redis Session，避免 session TTL 过期后请求丢失。
钉钉回复时通过 request_id 查找对应的 chat_id 和上下文。
"""

import json
import threading
from typing import Optional, Dict, Any, List
from datetime import datetime

import pymysql
from pymysql.cursors import DictCursor

from ai_kefu.config.settings import settings
from ai_kefu.utils.logging import logger


class HumanRequestStore:
    """MySQL-based Human Request storage."""

    _instance: Optional["HumanRequestStore"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._config = {
            "host": settings.mysql_host,
            "port": settings.mysql_port,
            "user": settings.mysql_user,
            "password": settings.mysql_password,
            "database": settings.mysql_database,
            "charset": "utf8mb4",
            "cursorclass": DictCursor,
            "autocommit": False,
        }
        self._connection: Optional[pymysql.Connection] = None
        self._db_lock = threading.Lock()
        self._ensure_table()

    @classmethod
    def get_instance(cls) -> "HumanRequestStore":
        """获取单例实例。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def _get_conn(self) -> pymysql.Connection:
        if self._connection is None or not self._ping():
            self._connection = pymysql.connect(**self._config)
        return self._connection

    def _ping(self) -> bool:
        try:
            if self._connection:
                self._connection.ping(reconnect=False)
                return True
        except Exception:
            pass
        return False

    def _ensure_table(self):
        """确保 human_requests 表存在。"""
        ddl = """
            CREATE TABLE IF NOT EXISTS human_requests (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                request_id VARCHAR(64) NOT NULL UNIQUE COMMENT '请求唯一ID (req_xxx)',
                chat_id VARCHAR(255) NOT NULL COMMENT '闲鱼 chat_id',
                session_id VARCHAR(255) COMMENT 'Agent session ID',
                user_nickname VARCHAR(255) COMMENT '用户昵称',
                question TEXT NOT NULL COMMENT 'AI 提出的问题',
                question_type VARCHAR(64) COMMENT '问题类型',
                urgency VARCHAR(16) DEFAULT 'medium' COMMENT '紧急程度',
                context_json TEXT COMMENT '上下文 JSON',
                context_summary TEXT COMMENT '对话摘要',
                status VARCHAR(32) DEFAULT 'pending' COMMENT 'pending/answered/timeout',
                human_response TEXT COMMENT '人工客服的回复',
                answered_at TIMESTAMP NULL COMMENT '回复时间',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_request_id (request_id),
                INDEX idx_chat_id (chat_id),
                INDEX idx_status (status),
                INDEX idx_created_at (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            COMMENT='Human-in-the-Loop 请求持久化'
        """
        try:
            with self._db_lock:
                conn = self._get_conn()
                with conn.cursor() as cur:
                    cur.execute(ddl)
                    conn.commit()
            logger.info("Ensured 'human_requests' table exists")
        except Exception as e:
            logger.error(f"Failed to ensure human_requests table: {e}")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_request(
        self,
        request_id: str,
        chat_id: str,
        question: str,
        question_type: str = "information_query",
        urgency: str = "medium",
        session_id: Optional[str] = None,
        user_nickname: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        context_summary: Optional[str] = None,
    ) -> bool:
        """创建一条新的 human request 记录。"""
        sql = """
            INSERT INTO human_requests (
                request_id, chat_id, session_id, user_nickname,
                question, question_type, urgency,
                context_json, context_summary, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
        """
        values = (
            request_id,
            chat_id,
            session_id,
            user_nickname,
            question,
            question_type,
            urgency,
            json.dumps(context, ensure_ascii=False) if context else None,
            context_summary,
        )
        with self._db_lock:
            try:
                conn = self._get_conn()
                with conn.cursor() as cur:
                    cur.execute(sql, values)
                    conn.commit()
                logger.info(f"Created human_request: {request_id} for chat_id={chat_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to create human_request: {e}")
                try:
                    conn.rollback()
                except Exception:
                    pass
                return False

    def get_by_request_id(self, request_id: str) -> Optional[Dict[str, Any]]:
        """根据 request_id 查询请求。"""
        sql = "SELECT * FROM human_requests WHERE request_id = %s"
        try:
            with self._db_lock:
                conn = self._get_conn()
                with conn.cursor() as cur:
                    cur.execute(sql, (request_id,))
                    row = cur.fetchone()
            if row and row.get("context_json"):
                try:
                    row["context_json"] = json.loads(row["context_json"])
                except Exception:
                    pass
            return row
        except Exception as e:
            logger.error(f"Failed to get human_request {request_id}: {e}")
            return None

    def get_latest_pending_by_chat_id(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """获取某个 chat_id 最新的 pending 状态请求。"""
        sql = """
            SELECT * FROM human_requests
            WHERE chat_id = %s AND status = 'pending'
            ORDER BY created_at DESC
            LIMIT 1
        """
        try:
            with self._db_lock:
                conn = self._get_conn()
                with conn.cursor() as cur:
                    cur.execute(sql, (chat_id,))
                    row = cur.fetchone()
            if row and row.get("context_json"):
                try:
                    row["context_json"] = json.loads(row["context_json"])
                except Exception:
                    pass
            return row
        except Exception as e:
            logger.error(f"Failed to get pending request for chat_id={chat_id}: {e}")
            return None

    def mark_answered(self, request_id: str, human_response: str) -> bool:
        """将请求标记为已回复。"""
        sql = """
            UPDATE human_requests
            SET status = 'answered',
                human_response = %s,
                answered_at = %s
            WHERE request_id = %s AND status = 'pending'
        """
        with self._db_lock:
            try:
                conn = self._get_conn()
                with conn.cursor() as cur:
                    cur.execute(sql, (human_response, datetime.utcnow(), request_id))
                    affected = cur.rowcount
                    conn.commit()
                if affected > 0:
                    logger.info(f"Marked human_request {request_id} as answered")
                    return True
                else:
                    logger.warning(f"No pending request found for {request_id}")
                    return False
            except Exception as e:
                logger.error(f"Failed to mark human_request answered: {e}")
                try:
                    conn.rollback()
                except Exception:
                    pass
                return False

    def get_pending_requests(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取所有 pending 状态的请求列表。"""
        sql = """
            SELECT * FROM human_requests
            WHERE status = 'pending'
            ORDER BY created_at DESC
            LIMIT %s
        """
        try:
            with self._db_lock:
                conn = self._get_conn()
                with conn.cursor() as cur:
                    cur.execute(sql, (limit,))
                    rows = cur.fetchall()
            for row in rows:
                if row.get("context_json"):
                    try:
                        row["context_json"] = json.loads(row["context_json"])
                    except Exception:
                        pass
            return rows
        except Exception as e:
            logger.error(f"Failed to get pending requests: {e}")
            return []

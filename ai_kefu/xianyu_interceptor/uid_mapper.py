"""
user_id ↔ encrypted_uid 双向映射缓存

闲鱼平台存在两套用户标识：
- user_id: 淘宝数字ID（如 4196460471），实时消息中使用
- encrypted_uid: 闲鱼加密UID（如 ugHmQcaOgYFpoJcDbMP+RQ==），部分API使用

本模块提供进程内双向映射缓存，支持自动发现和查找。
映射数据在进程重启后丢失（因为来源是动态的 WebSocket 消息）。
"""

import threading
from typing import Optional, Dict
from loguru import logger


class UidMapper:
    """
    user_id ↔ encrypted_uid 双向映射缓存

    线程安全的单例模式，全局共享一个映射实例。
    """

    _instance: Optional["UidMapper"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "UidMapper":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        # user_id -> encrypted_uid
        self._uid_to_encrypted: Dict[str, str] = {}
        # encrypted_uid -> user_id
        self._encrypted_to_uid: Dict[str, str] = {}
        self._rw_lock = threading.Lock()
        logger.debug("UidMapper 初始化完成")

    def record(self, user_id: str, encrypted_uid: str) -> bool:
        """
        记录一组 user_id ↔ encrypted_uid 映射

        Args:
            user_id: 淘宝数字ID
            encrypted_uid: 闲鱼加密UID

        Returns:
            bool: True 表示新增映射，False 表示已存在
        """
        if not user_id or not encrypted_uid:
            return False

        with self._rw_lock:
            existing = self._uid_to_encrypted.get(user_id)
            if existing == encrypted_uid:
                return False  # 已存在相同映射

            self._uid_to_encrypted[user_id] = encrypted_uid
            self._encrypted_to_uid[encrypted_uid] = user_id

        logger.info(
            f"🔗 记录 UID 映射: user_id={user_id} ↔ encrypted_uid={encrypted_uid[:20]}..."
        )
        return True

    def get_encrypted_uid(self, user_id: str) -> Optional[str]:
        """
        通过 user_id 查找 encrypted_uid

        Args:
            user_id: 淘宝数字ID

        Returns:
            Optional[str]: 对应的加密UID，未找到返回 None
        """
        with self._rw_lock:
            return self._uid_to_encrypted.get(user_id)

    def get_user_id(self, encrypted_uid: str) -> Optional[str]:
        """
        通过 encrypted_uid 查找 user_id

        Args:
            encrypted_uid: 闲鱼加密UID

        Returns:
            Optional[str]: 对应的淘宝数字ID，未找到返回 None
        """
        with self._rw_lock:
            return self._encrypted_to_uid.get(encrypted_uid)

    @property
    def size(self) -> int:
        """当前映射条目数"""
        with self._rw_lock:
            return len(self._uid_to_encrypted)

    def get_all_mappings(self) -> Dict[str, str]:
        """
        获取所有 user_id -> encrypted_uid 映射的副本

        Returns:
            Dict[str, str]: user_id -> encrypted_uid 映射
        """
        with self._rw_lock:
            return dict(self._uid_to_encrypted)

    def __repr__(self) -> str:
        return f"UidMapper(size={self.size})"


# 全局单例快捷访问
_mapper = UidMapper()


def record_uid_mapping(user_id: str, encrypted_uid: str) -> bool:
    """记录 user_id ↔ encrypted_uid 映射（模块级便捷函数）"""
    return _mapper.record(user_id, encrypted_uid)


def get_encrypted_uid(user_id: str) -> Optional[str]:
    """通过 user_id 查找 encrypted_uid（模块级便捷函数）"""
    return _mapper.get_encrypted_uid(user_id)


def get_user_id(encrypted_uid: str) -> Optional[str]:
    """通过 encrypted_uid 查找 user_id（模块级便捷函数）"""
    return _mapper.get_user_id(encrypted_uid)


def get_mapper() -> UidMapper:
    """获取全局 UidMapper 实例"""
    return _mapper

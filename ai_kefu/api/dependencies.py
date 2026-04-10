"""
FastAPI dependency injection providers.
"""

from typing import Generator, Optional
from ai_kefu.storage.session_store import SessionStore
from ai_kefu.storage.knowledge_store import KnowledgeStore
from ai_kefu.storage.prompt_store import PromptStore
from ai_kefu.storage.ignore_pattern_store import IgnorePatternStore
from ai_kefu.xianyu_interceptor.conversation_store import ConversationStore
from ai_kefu.xianyu_interceptor.session_mapper import SessionMapper, MemorySessionMapper, RedisSessionMapper
from ai_kefu.xianyu_interceptor.manual_mode import ManualModeManager
from ai_kefu.config.settings import settings


# Singleton instances (created once per application lifecycle)
_session_store: Optional[SessionStore] = None
_knowledge_store: Optional[KnowledgeStore] = None
_conversation_store: Optional[ConversationStore] = None
_prompt_store: Optional[PromptStore] = None
_ignore_pattern_store: Optional[IgnorePatternStore] = None
_xianyu_session_mapper: Optional[SessionMapper] = None
_manual_mode_manager: Optional[ManualModeManager] = None


def get_session_store() -> SessionStore:
    """
    Dependency: Get SessionStore instance.
    
    Returns:
        SessionStore singleton
    """
    global _session_store
    if _session_store is None:
        _session_store = SessionStore(
            redis_url=settings.redis_url,
            ttl=settings.redis_session_ttl
        )
    return _session_store


def get_knowledge_store() -> KnowledgeStore:
    """
    Dependency: Get KnowledgeStore instance.
    
    Returns:
        KnowledgeStore singleton
    """
    global _knowledge_store
    if _knowledge_store is None:
        _knowledge_store = KnowledgeStore(
            persist_path=settings.chroma_persist_path
        )
    return _knowledge_store


def get_conversation_store() -> ConversationStore:
    """
    Dependency: Get ConversationStore instance.
    
    Returns:
        ConversationStore singleton
    """
    global _conversation_store
    if _conversation_store is None:
        _conversation_store = ConversationStore(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_database
        )
    return _conversation_store


def get_prompt_store() -> PromptStore:
    """
    Dependency: Get PromptStore instance.
    
    Returns:
        PromptStore singleton
    """
    global _prompt_store
    if _prompt_store is None:
        _prompt_store = PromptStore(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_database
        )
    return _prompt_store


def get_ignore_pattern_store() -> IgnorePatternStore:
    """
    Dependency: Get IgnorePatternStore instance.

    Returns:
        IgnorePatternStore singleton
    """
    global _ignore_pattern_store
    if _ignore_pattern_store is None:
        _ignore_pattern_store = IgnorePatternStore(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_database
        )
    return _ignore_pattern_store


def get_xianyu_session_mapper() -> SessionMapper:
    """
    Dependency: Get Xianyu SessionMapper singleton.

    Uses Redis if session_mapper_type == "redis", otherwise in-memory.

    Returns:
        SessionMapper singleton
    """
    global _xianyu_session_mapper
    if _xianyu_session_mapper is None:
        if settings.session_mapper_type.lower() == "redis":
            try:
                _xianyu_session_mapper = RedisSessionMapper(settings.redis_url)
            except Exception:
                _xianyu_session_mapper = MemorySessionMapper()
        else:
            _xianyu_session_mapper = MemorySessionMapper()
    return _xianyu_session_mapper


def get_manual_mode_manager() -> ManualModeManager:
    """
    Dependency: Get ManualModeManager singleton.

    Returns:
        ManualModeManager singleton
    """
    global _manual_mode_manager
    if _manual_mode_manager is None:
        _manual_mode_manager = ManualModeManager(timeout=settings.manual_mode_timeout)
    return _manual_mode_manager

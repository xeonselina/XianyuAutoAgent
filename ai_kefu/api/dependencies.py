"""
FastAPI dependency injection providers.
"""

from typing import Generator, Optional
from ai_kefu.storage.session_store import SessionStore
from ai_kefu.storage.knowledge_store import KnowledgeStore
from ai_kefu.storage.prompt_store import PromptStore
from ai_kefu.xianyu_interceptor.conversation_store import ConversationStore
from ai_kefu.config.settings import settings


# Singleton instances (created once per application lifecycle)
_session_store: Optional[SessionStore] = None
_knowledge_store: Optional[KnowledgeStore] = None
_conversation_store: Optional[ConversationStore] = None
_prompt_store: Optional[PromptStore] = None


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


# Note: AgentExecutor dependency will be added in User Story 1 implementation
# def get_agent_executor(
#     session_store: SessionStore = Depends(get_session_store),
#     knowledge_store: KnowledgeStore = Depends(get_knowledge_store)
# ) -> AgentExecutor:
#     """Get AgentExecutor instance."""
#     return AgentExecutor(
#         session_store=session_store,
#         knowledge_store=knowledge_store
#     )

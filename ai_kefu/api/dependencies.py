"""
FastAPI dependency injection providers.
"""

from typing import Generator
from ai_kefu.storage.session_store import SessionStore
from ai_kefu.storage.knowledge_store import KnowledgeStore
from ai_kefu.config.settings import settings


# Singleton instances (created once per application lifecycle)
_session_store: SessionStore | None = None
_knowledge_store: KnowledgeStore | None = None


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

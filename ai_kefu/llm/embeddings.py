"""
Embedding service using Qwen text-embedding-v3 model.

Uses OpenAI-compatible API (Alibaba Cloud Bailian / DashScope compatible-mode).
Migrated from dashscope SDK to openai SDK (2026-04-25) — same reason as qwen_client.py:
  - dashscope SDK fails on model names containing '.' (URL construction bug)
  - openai SDK via compatible-mode endpoint has no such restriction

Performance: LRU cache for query embeddings to avoid redundant API calls.
"""

from openai import OpenAI
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
from functools import lru_cache
from typing import List, Tuple, Optional
from ai_kefu.config.settings import settings
from ai_kefu.config.constants import QWEN_API_RETRY_ATTEMPTS, QWEN_API_RETRY_DELAY
import logging

logger = logging.getLogger(__name__)

# 全局 OpenAI client（惰性初始化）
_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.model_base_url,
        )
    return _client


@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=1, min=QWEN_API_RETRY_DELAY, max=60),
    stop=stop_after_attempt(QWEN_API_RETRY_ATTEMPTS)
)
def _call_embedding_api(text: str) -> List[float]:
    """Raw embedding API call (with retry). Not cached."""
    client = _get_client()
    response = client.embeddings.create(
        model="text-embedding-v3",
        input=text,
        dimensions=1024,
        encoding_format="float",
    )
    return response.data[0].embedding


# LRU cache for query embeddings — queries repeat often (e.g. "押金政策", "归还地址").
# Cache 256 most recent (text, task_type) pairs. lru_cache needs hashable args → use tuple.
@lru_cache(maxsize=256)
def _cached_embedding(text: str, task_type: str) -> Tuple[float, ...]:
    """Cached embedding call. Returns tuple (hashable) for lru_cache compatibility."""
    embedding = _call_embedding_api(text)
    return tuple(embedding)


def generate_embedding(text: str, task_type: str = "retrieval_document") -> List[float]:
    """
    Generate vector embedding for text using Qwen text-embedding-v3.

    Uses an in-memory LRU cache (256 entries) to avoid redundant API calls.
    Typical hit: knowledge_search queries that repeat across conversations.

    Args:
        text: Input text to embed
        task_type: Task type - "retrieval_query" for queries, "retrieval_document" for documents
                   (passed through for cache keying; not sent to API in compatible-mode)

    Returns:
        Vector embedding as list of floats
    """
    cached = _cached_embedding(text, task_type)
    return list(cached)


def generate_embeddings_batch(texts: List[str], task_type: str = "retrieval_document") -> List[List[float]]:
    """
    Generate embeddings for multiple texts (batch processing).

    Args:
        texts: List of input texts
        task_type: Task type

    Returns:
        List of vector embeddings
    """
    embeddings = []
    for text in texts:
        try:
            embedding = generate_embedding(text, task_type)
            embeddings.append(embedding)
        except Exception as e:
            logger.error(f"Error generating embedding for text: {e}")
            # Return zero vector on failure
            embeddings.append([0.0] * 1024)

    return embeddings

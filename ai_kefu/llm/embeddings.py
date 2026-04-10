"""
Embedding service using Qwen text-embedding-v3 model.

Performance: LRU cache for query embeddings to avoid redundant API calls.
"""

import dashscope
from dashscope import TextEmbedding
from dashscope.common.error import RequestFailure
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
from functools import lru_cache
from typing import List, Tuple
from ai_kefu.config.settings import settings
from ai_kefu.config.constants import QWEN_API_RETRY_ATTEMPTS, QWEN_API_RETRY_DELAY
import os
import logging

logger = logging.getLogger(__name__)


def _ensure_api_key():
    """Ensure DASHSCOPE_API_KEY is set."""
    if not dashscope.api_key:
        api_key = settings.api_key
        if not api_key:
            raise ValueError(f"API key not found in settings. Please check your .env file.")
        dashscope.api_key = api_key


@retry(
    retry=retry_if_exception_type(RequestFailure),
    wait=wait_exponential(multiplier=1, min=QWEN_API_RETRY_DELAY, max=60),
    stop=stop_after_attempt(QWEN_API_RETRY_ATTEMPTS)
)
def _call_embedding_api(text: str) -> List[float]:
    """Raw embedding API call (with retry). Not cached."""
    _ensure_api_key()
    response = TextEmbedding.call(
        model="text-embedding-v3",
        input=text,
        dimension=1024  # Qwen embedding dimension
    )
    
    if response.status_code != 200:
        raise RequestFailure(f"Qwen Embedding API Error: {response.message}")
    
    return response.output["embeddings"][0]["embedding"]


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

    Returns:
        Vector embedding as list of floats

    Raises:
        RequestFailure: API request failed
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
            print(f"Error generating embedding for text: {e}")
            # Return zero vector on failure
            embeddings.append([0.0] * 1024)
    
    return embeddings

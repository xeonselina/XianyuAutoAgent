"""
Embedding service using Qwen text-embedding-v3 model.
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
from typing import List
from ai_kefu.config.settings import settings
from ai_kefu.config.constants import QWEN_API_RETRY_ATTEMPTS, QWEN_API_RETRY_DELAY
import os


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
def generate_embedding(text: str, task_type: str = "retrieval_document") -> List[float]:
    """
    Generate vector embedding for text using Qwen text-embedding-v3.

    Args:
        text: Input text to embed
        task_type: Task type - "retrieval_query" for queries, "retrieval_document" for documents

    Returns:
        Vector embedding as list of floats

    Raises:
        RequestFailure: API request failed
    """
    _ensure_api_key()
    response = TextEmbedding.call(
        model="text-embedding-v3",
        input=text,
        dimension=1024  # Qwen embedding dimension
    )
    
    if response.status_code != 200:
        raise RequestFailure(f"Qwen Embedding API Error: {response.message}")
    
    # Extract embedding from response
    embedding = response.output["embeddings"][0]["embedding"]
    return embedding


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

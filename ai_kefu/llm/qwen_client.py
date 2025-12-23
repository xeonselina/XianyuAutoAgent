"""
Qwen API client wrapper with retry logic.
Uses Alibaba Cloud DashScope SDK.
"""

from dashscope import Generation
from dashscope.common.error import RequestFailure, ServiceUnavailableError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
from typing import List, Dict, Any, Optional, AsyncGenerator
from ai_kefu.config.settings import settings
from ai_kefu.config.constants import QWEN_API_RETRY_ATTEMPTS, QWEN_API_RETRY_DELAY
import os


# Configure DashScope API key
os.environ["DASHSCOPE_API_KEY"] = settings.qwen_api_key


@retry(
    retry=retry_if_exception_type((RequestFailure, ServiceUnavailableError)),
    wait=wait_exponential(multiplier=1, min=QWEN_API_RETRY_DELAY, max=60),
    stop=stop_after_attempt(QWEN_API_RETRY_ATTEMPTS)
)
def call_qwen(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    max_tokens: Optional[int] = None
) -> Dict[str, Any]:
    """
    Call Qwen API with retry logic (synchronous).
    
    Args:
        messages: Conversation messages
        tools: Tool definitions (Function Calling)
        temperature: Sampling temperature
        top_p: Nucleus sampling parameter
        max_tokens: Maximum tokens to generate
        
    Returns:
        Response dict from Qwen API
        
    Raises:
        RequestFailure: API request failed
        ServiceUnavailableError: Service unavailable
    """
    response = Generation.call(
        model=settings.qwen_model,
        messages=messages,
        tools=tools,
        result_format='message',
        temperature=temperature or settings.qwen_temperature,
        top_p=top_p or settings.qwen_top_p,
        max_tokens=max_tokens or settings.qwen_max_tokens,
        stream=False
    )
    
    if response.status_code != 200:
        raise RequestFailure(f"Qwen API Error: {response.message}")
    
    return response.output


@retry(
    retry=retry_if_exception_type((RequestFailure, ServiceUnavailableError)),
    wait=wait_exponential(multiplier=1, min=QWEN_API_RETRY_DELAY, max=60),
    stop=stop_after_attempt(QWEN_API_RETRY_ATTEMPTS)
)
def stream_qwen(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    max_tokens: Optional[int] = None
):
    """
    Call Qwen API with streaming (generator).
    
    Args:
        messages: Conversation messages
        tools: Tool definitions
        temperature: Sampling temperature
        top_p: Nucleus sampling parameter
        max_tokens: Maximum tokens to generate
        
    Yields:
        Response chunks from Qwen API
        
    Raises:
        RequestFailure: API request failed
    """
    responses = Generation.call(
        model=settings.qwen_model,
        messages=messages,
        tools=tools,
        result_format='message',
        temperature=temperature or settings.qwen_temperature,
        top_p=top_p or settings.qwen_top_p,
        max_tokens=max_tokens or settings.qwen_max_tokens,
        stream=True,
        incremental_output=True
    )
    
    for response in responses:
        if response.status_code == 200:
            yield response.output
        else:
            raise RequestFailure(f"Qwen API Error: {response.message}")


def check_qwen_api() -> bool:
    """
    Check Qwen API connectivity.
    
    Returns:
        True if API is accessible
    """
    try:
        call_qwen(
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5
        )
        return True
    except Exception:
        return False

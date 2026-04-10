"""
Qwen API client wrapper with retry logic.
Uses OpenAI-compatible API (Alibaba Cloud Bailian / DashScope).

迁移说明 (2026-03-26):
    从 DashScope SDK 迁移到 OpenAI SDK，原因：
    - DashScope SDK 无法调用 qwen3.5-plus 等新模型（模型名含 '.' 导致内部 URL 构造出错）
    - OpenAI SDK 通过百炼 compatible-mode 接口调用，不受此限制
    - 返回值格式保持与旧版完全一致（dict: {"choices": [{"message": {...}}]}），下游零改动
"""

from openai import OpenAI, APIError, APITimeoutError, APIConnectionError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
from typing import List, Dict, Any, Optional
from ai_kefu.config.settings import settings
from ai_kefu.config.constants import (
    QWEN_API_RETRY_ATTEMPTS,
    QWEN_API_RETRY_DELAY,
    QWEN_API_RETRY_MAX_DELAY,
    QWEN_API_TIMEOUT
)
import logging

logger = logging.getLogger(__name__)

# 可重试的异常类型
_RETRYABLE_ERRORS = (APIError, APITimeoutError, APIConnectionError)

# 全局 OpenAI client（惰性初始化）
_client: Optional[OpenAI] = None
# Fast client: 短超时、无内部重试，用于辅助调用（置信度、摘要）
_fast_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    """获取或创建 OpenAI client（单例）。"""
    global _client
    if _client is None:
        api_key = settings.api_key
        if not api_key:
            raise ValueError("API key not found in settings. Please check your .env file.")
        _client = OpenAI(
            api_key=api_key,
            base_url=settings.model_base_url,
            timeout=settings.qwen_api_timeout or QWEN_API_TIMEOUT,
        )
    return _client


def _get_fast_client(timeout: float = 10.0) -> OpenAI:
    """获取或创建 fast OpenAI client（单例，短超时、无内部重试）。"""
    global _fast_client
    if _fast_client is None:
        api_key = settings.api_key
        if not api_key:
            raise ValueError("API key not found in settings. Please check your .env file.")
        _fast_client = OpenAI(
            api_key=api_key,
            base_url=settings.model_base_url,
            timeout=timeout,
            max_retries=0,  # 禁用 OpenAI SDK 内部重试
        )
    return _fast_client


def _completion_to_dict(completion) -> Dict[str, Any]:
    """
    将 OpenAI ChatCompletion 对象转换为与旧版 DashScope SDK 兼容的 dict 格式。
    
    旧格式 (下游代码依赖):
        {"choices": [{"message": {"role": "assistant", "content": "...", "tool_calls": [...]}}]}
    """
    choice = completion.choices[0]
    msg = choice.message
    
    message_dict: Dict[str, Any] = {
        "role": msg.role or "assistant",
        "content": msg.content or "",
    }
    
    if msg.tool_calls:
        message_dict["tool_calls"] = [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
            }
            for tc in msg.tool_calls
        ]
    
    return {"choices": [{"message": message_dict}]}


@retry(
    retry=retry_if_exception_type(_RETRYABLE_ERRORS),
    wait=wait_exponential(multiplier=1, min=QWEN_API_RETRY_DELAY, max=QWEN_API_RETRY_MAX_DELAY),
    stop=stop_after_attempt(QWEN_API_RETRY_ATTEMPTS)
)
def call_qwen(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Call Qwen API with retry logic (synchronous).

    Args:
        messages: Conversation messages
        tools: Tool definitions (Function Calling)
        temperature: Sampling temperature
        top_p: Nucleus sampling parameter
        max_tokens: Maximum tokens to generate
        model: Model name override (默认使用 settings.model_name；
               传入 settings.model_name_light 可使用轻量模型降低成本)

    Returns:
        Response dict: {"choices": [{"message": {"content": "...", "tool_calls": [...]}}]}
        与旧版 DashScope SDK 返回格式完全一致，下游代码无需修改。

    Raises:
        APIError: API request failed
        APITimeoutError: Request timeout
        APIConnectionError: Connection failed
    
    Timeout 策略:
        单次调用超时: QWEN_API_TIMEOUT (默认 30s)
        重试次数: QWEN_API_RETRY_ATTEMPTS (默认 3 次)
        重试延迟: 指数退避 QWEN_API_RETRY_DELAY ~ QWEN_API_RETRY_MAX_DELAY (1s ~ 10s)
        最坏总耗时: 约 30+1+30+3+30 ≈ 94s，在 interceptor 120s 窗口内
    """
    client = _get_client()
    
    effective_model = model or settings.model_name
    
    kwargs: Dict[str, Any] = {
        "model": effective_model,
        "messages": messages,
        "temperature": temperature or settings.qwen_temperature,
        "top_p": top_p or settings.qwen_top_p,
        "max_tokens": max_tokens or settings.qwen_max_tokens,
        "stream": False,
    }
    if tools:
        kwargs["tools"] = tools
    
    completion = client.chat.completions.create(**kwargs)
    return _completion_to_dict(completion)


def call_qwen_fast(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None,
    timeout: float = 15.0
) -> Dict[str, Any]:
    """
    Fast, no-retry variant of call_qwen for low-priority auxiliary calls
    (e.g. confidence guard, context summarisation).

    Differences from call_qwen:
    - No retry on failure — neither tenacity nor OpenAI SDK internal retries
    - Short timeout (default 15s), and that's a **hard** ceiling
    - Uses a singleton fast client (max_retries=0)

    Note: the `timeout` parameter is only used on first initialisation of the
    singleton fast client.  Subsequent calls reuse the same client regardless
    of the timeout value passed.  In practice all callers should use the same
    default (15s).

    Args:
        messages: Conversation messages
        tools: Tool definitions
        temperature: Sampling temperature
        top_p: Nucleus sampling parameter
        max_tokens: Maximum tokens to generate
        model: Model name override
        timeout: Hard timeout in seconds (default 15s).

    Returns:
        Response dict (same format as call_qwen)

    Raises:
        APIError, APITimeoutError, APIConnectionError on failure (no retry)
    """
    fast_client = _get_fast_client(timeout=timeout)
    
    effective_model = model or settings.model_name
    
    kwargs: Dict[str, Any] = {
        "model": effective_model,
        "messages": messages,
        "temperature": temperature or settings.qwen_temperature,
        "top_p": top_p or settings.qwen_top_p,
        "max_tokens": max_tokens or settings.qwen_max_tokens,
        "stream": False,
    }
    if tools:
        kwargs["tools"] = tools
    
    completion = fast_client.chat.completions.create(**kwargs)
    return _completion_to_dict(completion)


@retry(
    retry=retry_if_exception_type(_RETRYABLE_ERRORS),
    wait=wait_exponential(multiplier=1, min=QWEN_API_RETRY_DELAY, max=QWEN_API_RETRY_MAX_DELAY),
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
        Response chunks dict: {"choices": [{"message": {"content": "...", "tool_calls": [...]}}]}

    Raises:
        APIError: API request failed
    """
    client = _get_client()
    
    kwargs: Dict[str, Any] = {
        "model": settings.model_name,
        "messages": messages,
        "temperature": temperature or settings.qwen_temperature,
        "top_p": top_p or settings.qwen_top_p,
        "max_tokens": max_tokens or settings.qwen_max_tokens,
        "stream": True,
    }
    if tools:
        kwargs["tools"] = tools
    
    stream = client.chat.completions.create(**kwargs)
    
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta:
            delta = chunk.choices[0].delta
            message_dict: Dict[str, Any] = {
                "role": delta.role or "assistant",
                "content": delta.content or "",
            }
            if delta.tool_calls:
                message_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in delta.tool_calls
                ]
            yield {"choices": [{"message": message_dict}]}


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

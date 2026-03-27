"""
HTTP client for communicating with AI Agent service.

Provides synchronous and streaming message sending with retry logic and metrics tracking.
"""

import httpx
import time
from typing import Optional, Dict, AsyncIterator
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    retry_if_exception,
    before_sleep_log
)
from loguru import logger
import logging

from .models import (
    AgentChatRequest,
    AgentChatResponse,
    AgentClientConfig,
    HTTPClientMetrics
)
from .exceptions import AgentAPIError


# Standard logger for tenacity before_sleep_log (it uses stdlib logging)
_std_logger = logging.getLogger("ai_kefu.http_client")


def _is_retryable_error(exception: BaseException) -> bool:
    """判断异常是否值得重试。
    
    可重试的情况:
    - 连接错误 (ConnectError)
    - 连接池超时 (PoolTimeout)
    - 服务端错误 (HTTP 500/502/503/504)
    - 读取超时 (ReadTimeout)
    
    不可重试的情况:
    - 客户端错误 (4xx) — 请求本身有问题
    - 其他未知异常
    """
    if isinstance(exception, (httpx.ConnectError, httpx.PoolTimeout, httpx.ReadTimeout)):
        return True
    if isinstance(exception, httpx.HTTPStatusError):
        return exception.response.status_code in (500, 502, 503, 504)
    return False


class AgentClient:
    """HTTP client for AI Agent service."""
    
    def __init__(self, config: AgentClientConfig):
        """
        Initialize Agent HTTP client.
        
        Args:
            config: Client configuration
        """
        self.config = config
        # Ensure base_url has trailing slash to avoid redirect issues
        base_url = config.base_url.rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(
                timeout=config.timeout,
                connect=config.connect_timeout
            ),
            follow_redirects=True
        )
        self.metrics = HTTPClientMetrics()
    
    async def send_message(
        self,
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        context: Optional[Dict] = None
    ) -> AgentChatResponse:
        """
        Send message to AI Agent (synchronous mode).
        
        Args:
            query: User query
            session_id: Agent session ID
            user_id: User ID
            context: Additional context
            
        Returns:
            Agent response
            
        Raises:
            AgentAPIError: If API call fails
        """
        request = AgentChatRequest(
            query=query,
            session_id=session_id,
            user_id=user_id,
            context=context or {}
        )
        
        start_time = time.time()
        
        try:
            response = await self._send_with_retry(request)
            response_time = time.time() - start_time
            
            self.metrics.add_request(success=True, response_time=response_time)
            logger.info(
                f"Agent API success: session={session_id}, "
                f"response_time={response_time:.2f}s"
            )
            
            return response
            
        except Exception as e:
            response_time = time.time() - start_time
            error_type = type(e).__name__
            
            self.metrics.add_request(
                success=False,
                response_time=response_time,
                error=error_type
            )
            
            logger.error(
                f"Agent API failed: session={session_id}, "
                f"error={error_type}, response_time={response_time:.2f}s"
            )
            
            raise AgentAPIError(f"Agent API call failed: {str(e)}") from e
    
    @retry(
        retry=retry_if_exception(_is_retryable_error),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        before_sleep=before_sleep_log(_std_logger, logging.WARNING),
        reraise=True
    )
    async def _send_with_retry(self, request: AgentChatRequest) -> AgentChatResponse:
        """
        Send request with retry logic.
        
        Args:
            request: Chat request
            
        Returns:
            Chat response
        """
        try:
            response = await self.client.post(
                "/chat/",
                json=request.model_dump(exclude_none=True)
            )
            
            if response.status_code != 200:
                body = response.text
                logger.error(
                    f"Agent API returned {response.status_code}: {body[:500]}"
                )
            
            response.raise_for_status()
            
            data = response.json()
            return AgentChatResponse(**data)
            
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            if _is_retryable_error(e):
                logger.warning(
                    f"HTTP {status_code} from Agent API (retryable), "
                    f"body={e.response.text[:300]}"
                )
            else:
                logger.error(
                    f"HTTP {status_code} from Agent API (not retryable), "
                    f"body={e.response.text[:500]}"
                )
            raise
        except httpx.HTTPError as e:
            logger.warning(f"HTTP error during Agent API call (will retry if applicable): {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during Agent API call: {e}")
            raise
    
    async def stream_message(
        self,
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        context: Optional[Dict] = None
    ) -> AsyncIterator[str]:
        """
        Send message to AI Agent (streaming mode).
        
        Args:
            query: User query
            session_id: Agent session ID
            user_id: User ID
            context: Additional context
            
        Yields:
            Text chunks from Agent response
        """
        request = AgentChatRequest(
            query=query,
            session_id=session_id,
            user_id=user_id,
            context=context or {}
        )
        
        try:
            async with self.client.stream(
                "POST",
                "/chat/stream",
                json=request.model_dump(exclude_none=True)
            ) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        import json
                        data = json.loads(line[6:])
                        if data.get("type") == "chunk":
                            yield data["text"]
                            
        except httpx.HTTPError as e:
            logger.error(f"Streaming error: {e}")
            raise AgentAPIError(f"Streaming failed: {str(e)}") from e
    
    async def health_check(self) -> bool:
        """
        Check if Agent service is healthy.
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            response = await self.client.get(self.config.health_check_path)
            is_healthy = response.status_code == 200
            
            self.metrics.is_healthy = is_healthy
            self.metrics.last_health_check = time.time()
            
            return is_healthy
            
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            self.metrics.is_healthy = False
            return False
    
    def get_metrics(self) -> HTTPClientMetrics:
        """Get client metrics."""
        return self.metrics
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

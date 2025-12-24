"""
Custom exceptions for Xianyu Interceptor.
"""


class XianyuInterceptorError(Exception):
    """Base exception for Xianyu Interceptor errors."""
    pass


class AgentAPIError(XianyuInterceptorError):
    """Raised when Agent API call fails."""
    
    def __init__(self, message: str):
        self.message = message
        super().__init__(f"Agent API Error: {message}")


class SessionMapperError(XianyuInterceptorError):
    """Raised when session mapping operation fails."""
    
    def __init__(self, message: str):
        self.message = message
        super().__init__(f"Session Mapper Error: {message}")


class MessageConversionError(XianyuInterceptorError):
    """Raised when message format conversion fails."""
    
    def __init__(self, message: str):
        self.message = message
        super().__init__(f"Message Conversion Error: {message}")


class BrowserControlError(XianyuInterceptorError):
    """Raised when browser control operation fails."""
    
    def __init__(self, message: str):
        self.message = message
        super().__init__(f"Browser Control Error: {message}")


class InterceptorConfigError(XianyuInterceptorError):
    """Raised when configuration is invalid."""
    
    def __init__(self, message: str):
        self.message = message
        super().__init__(f"Configuration Error: {message}")

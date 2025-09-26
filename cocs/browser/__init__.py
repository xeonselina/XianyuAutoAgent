# 模块化架构的导入
from .page_manager import PageManager
from .data_persistence import DataPersistence
from .message_monitor import MessageMonitor
from .goofish_browser import GoofishBrowser

# 为了向后兼容，也可以从旧模块导入
# from .goofish_browser_legacy import GoofishBrowser as GoofishBrowserLegacy

__all__ = [
    'GoofishBrowser',
    'PageManager',
    'DataPersistence',
    'MessageMonitor'
]
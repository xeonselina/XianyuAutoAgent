"""
xianyu_provider — 闲鱼 API 统一 provider 层
==============================================

调用方只依赖抽象接口 XianyuProvider，不感知底层实现细节。
将来整体替换底层库时，只需换 GoofishProvider 的实现即可。

用法::

    from ai_kefu.xianyu_provider import get_provider
    provider = get_provider()           # 使用全局单例
    token   = await provider.get_token()
    item    = await provider.get_item_info("1234567")
    order   = await provider.get_order_detail("9876543210")
    await provider.send_message(ws, cid, toid, message)
"""

from ai_kefu.xianyu_provider.base import XianyuProvider
from ai_kefu.xianyu_provider.goofish_provider import GoofishProvider

_provider_instance: XianyuProvider | None = None


def get_provider() -> XianyuProvider:
    """
    返回全局 provider 单例（懒初始化）。
    若要在进程启动时预先初始化，可调用 init_provider()。
    """
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = _build_default_provider()
    return _provider_instance


def init_provider(provider: XianyuProvider | None = None) -> XianyuProvider:
    """
    显式初始化全局 provider 单例。
    可传入自定义实例（用于测试 mock 或替换实现）；
    不传则用默认实现。
    """
    global _provider_instance
    _provider_instance = provider or _build_default_provider()
    return _provider_instance


def _build_default_provider() -> XianyuProvider:
    """构造默认实现（GoofishProvider），从 settings 中读取 cookie。"""
    from ai_kefu.config.settings import settings
    cookie = getattr(settings, "xianyu_cookie", "")
    if not cookie:
        raise ValueError(
            "xianyu_cookie 未配置。请在 .env 文件中设置 XIANYU_COOKIE。"
        )
    return GoofishProvider(cookies_str=cookie)


__all__ = [
    "XianyuProvider",
    "GoofishProvider",
    "get_provider",
    "init_provider",
]

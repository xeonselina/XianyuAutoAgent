"""
XianyuProvider — 闲鱼 API 抽象接口
====================================

所有调用方只依赖这个 ABC，不感知底层实现。
替换上游库时只需新建一个实现类并在 __init__.py 中切换。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class XianyuProvider(ABC):
    """闲鱼 API provider 抽象基类。"""

    # ──────────────────────────────────────────────
    # 认证 / Token
    # ──────────────────────────────────────────────

    @abstractmethod
    async def get_token(self) -> dict[str, Any]:
        """
        获取 WebSocket 访问令牌。

        Returns::

            {
                "success": bool,
                "access_token": str,   # 成功时
                "error": str,          # 失败时
            }
        """

    @abstractmethod
    async def refresh_token(self) -> dict[str, Any]:
        """
        刷新登录态（保持长连接不掉线）。

        Returns::

            {"success": bool, ...}
        """

    # ──────────────────────────────────────────────
    # 商品 / 订单
    # ──────────────────────────────────────────────

    @abstractmethod
    async def get_item_info(self, item_id: str) -> dict[str, Any]:
        """
        获取商品详情。

        Returns::

            {
                "success": bool,
                "item_id": str,
                "title": str,
                "price": str,
                "desc": str,
                "category": str,
                "image_url": str,
                "item_status": int,   # 0=在售, 1=已售, 2=下架
                "seller_id": str,
                "location": str,
                "error": str,         # 仅失败时
            }
        """

    @abstractmethod
    async def get_buyer_info(self, buyer_id: str) -> dict[str, Any]:
        """
        获取买家信息，包括购买历史统计和用户地区信息。

        Args:
            buyer_id: 买家用户 ID

        Returns::

            {
                "success": bool,
                "buyer_id": str,
                "buyer_nick": str,
                "buy_count": int,        # 买家总购买次数
                "deal_count": int,       # 买家成交次数
                "trade_count": int,      # 交易总数
                "has_bought": bool,      # 是否从当前卖家购买过
                "user_type": int,        # 1=买家, 2=卖家
                "location": str,         # 用户地区信息
                "error": str,            # 仅失败时
            }
        """

    @abstractmethod
    async def get_order_detail(self, order_id: str) -> dict[str, Any]:
        """
        获取订单详情。

        Returns::

            {
                "success": bool,
                "order_id": str,
                "item_id": str,
                "item_title": str,
                "sku": str,
                "quantity": str,
                "amount": str,
                "status": str,
                "status_label": str,
                "buyer_id": str,
                "buyer_nickname": str,
                "create_time": str,
                "error": str,         # 仅失败时
            }
        """

    # ──────────────────────────────────────────────
    # 消息发送
    # ──────────────────────────────────────────────

    @abstractmethod
    async def send_message(
        self,
        websocket: Any,
        cid: str,
        toid: str,
        message: dict[str, Any],
    ) -> None:
        """
        向已建立的 WebSocket 连接发送消息。

        Args:
            websocket: 已连接的 WebSocket 对象（上层持有）。
            cid:       会话 ID（不含 @goofish 后缀）。
            toid:      接收方用户 ID（不含 @goofish 后缀）。
            message:   消息对象，格式见 message/types.py（make_text / make_image）。
        """

    @abstractmethod
    async def send_message_once(
        self,
        cid: str,
        buyer_id: str,
        text: str,
    ) -> dict[str, Any]:
        """
        无需已有 WebSocket 连接，自行建立短连接发送单条文本消息后断开。

        Args:
            cid:      会话 ID（不含 @goofish 后缀）。
            buyer_id: 买家用户 ID（不含 @goofish 后缀）。
            text:     要发送的文本内容。

        Returns::

            {"success": bool, "chat_id": str, "message": str, "error": str}
        """

    # ──────────────────────────────────────────────
    # 媒体上传
    # ──────────────────────────────────────────────

    @abstractmethod
    async def upload_media(self, media_path: str) -> dict[str, Any]:
        """
        上传图片，返回可用于发送的 URL。

        Returns::

            {"success": bool, "url": str, "width": int, "height": int, "error": str}
        """

    # ──────────────────────────────────────────────
    # WebSocket 辅助（init / heartbeat）
    # ──────────────────────────────────────────────

    @abstractmethod
    async def ws_init(self, websocket: Any) -> None:
        """注册 WebSocket 会话（发送 /reg 帧 + ackDiff）。"""

    @abstractmethod
    async def ws_heartbeat(self, websocket: Any) -> None:
        """持续发送心跳帧，直到连接断开。每 15 秒发一次。"""

    # ──────────────────────────────────────────────
    # Cookie / Session 访问
    # ──────────────────────────────────────────────

    @property
    @abstractmethod
    def my_user_id(self) -> str:
        """当前卖家的用户 ID（从 cookie 中的 'unb' 字段读取）。"""

    @property
    @abstractmethod
    def device_id(self) -> str:
        """当前设备 ID（每次初始化后固定）。"""

    @property
    @abstractmethod
    def ws_url(self) -> str:
        """WebSocket 连接地址。"""

    @abstractmethod
    def get_ws_headers(self) -> dict[str, str]:
        """返回建立 WebSocket 连接所需的 HTTP headers（含 Cookie）。"""

    # ──────────────────────────────────────────────
    # 会话管理
    # ──────────────────────────────────────────────

    @abstractmethod
    async def list_all_conversations(self, cid: str) -> list[dict[str, Any]]:
        """
        拉取指定会话 ID 的全部历史消息（自动翻页）。

        Args:
            cid: 会话 ID（不含 @goofish 后缀）。

        Returns:
            消息列表，每项格式::

                {
                    "send_user_id": str,
                    "send_user_name": str,
                    "message": dict,   # 解码后的消息体（含 contentType 等字段）
                }
        """

    @abstractmethod
    async def create_chat(
        self,
        websocket: Any,
        toid: str,
        item_id: str,
    ) -> None:
        """
        在已建立的 WebSocket 上发起与买家的新会话。

        Args:
            websocket: 已连接的 WebSocket 对象。
            toid:      买家用户 ID（不含 @goofish 后缀）。
            item_id:   关联的商品 ID。
        """

    # ──────────────────────────────────────────────
    # 登录状态 / Cookie 管理
    # ──────────────────────────────────────────────

    @abstractmethod
    async def has_login(self) -> bool:
        """
        检查当前 cookie 的登录状态。

        Returns:
            True 表示 cookie 有效、已登录；False 表示已失效。
        """

    @abstractmethod
    def update_env_cookies(self) -> None:
        """
        将 session 中最新的 cookie 回写到工作目录下的 .env 文件（COOKIES_STR 字段）。
        可在每次成功请求后调用，防止 cookie 过期后需要手动维护。
        """

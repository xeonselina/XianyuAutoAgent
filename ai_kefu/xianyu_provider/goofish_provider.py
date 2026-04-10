"""
GoofishProvider — 基于 cv-cat/XianYuApis 的薄适配层
======================================================

所有 Xianyu API 调用委托给上游 git submodule（ai_kefu/xianyu_provider/upstream/）。
上游替换时只需执行 ``git submodule update``，无需修改本文件之外的任何代码。

上游仓库: https://github.com/cv-cat/XianYuApis

依赖说明:
    - PyExecJS>=4.1.0         (execjs — 上游 JS 加签)
    - blackboxprotobuf>=2.0.0 (上游消息解密)
    - Node.js >= 18            (execjs 运行时)
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import sys
import time
from typing import Any

try:
    import websockets
except ImportError:
    websockets = None  # type: ignore[assignment]

# ──────────────────────────────────────────────────────────────────────────────
# 上游子模块导入
# ──────────────────────────────────────────────────────────────────────────────
# goofish_utils.py 在 *模块加载阶段* 以 CWD 相对路径打开 JS 文件：
#   open(r'static/goofish_js_version_2.js', ...)
# 因此必须在 import 之前将 CWD 切换到 upstream 目录，之后再还原。

_UPSTREAM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upstream")

if _UPSTREAM_DIR not in sys.path:
    sys.path.insert(0, _UPSTREAM_DIR)

_orig_cwd = os.getcwd()
try:
    os.chdir(_UPSTREAM_DIR)
    from goofish_apis import XianyuApis  # type: ignore[import]
    from utils.goofish_utils import (  # type: ignore[import]
        generate_mid,
        generate_uuid,
        generate_sign,
        generate_device_id as _upstream_generate_device_id,
        trans_cookies,
        get_session_cookies_str,
    )
finally:
    os.chdir(_orig_cwd)

from ai_kefu.xianyu_provider.base import XianyuProvider
from ai_kefu.utils.logging import logger


# ──────────────────────────────────────────────────────────────────────────────
# 常量（与上游保持一致）
# ──────────────────────────────────────────────────────────────────────────────

_APP_KEY = "34839810"
_APP_CONFIG_APP_KEY = "444e9908a51d1cb236a27862abc769c9"
_WS_URL = "wss://wss-goofish.dingtalk.com/"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)
_UA_DINGTALK = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 "
    "DingTalk(2.1.5) OS(Windows/10) Browser(Chrome/133.0.0.0) "
    "DingWeb/2.1.5 IMPaaS DingWeb/2.1.5"
)

_ORDER_STATUS_MAP = {
    "WAIT_BUYER_PAY": "等待买家付款",
    "WAIT_SELLER_SEND_GOODS": "等待卖家发货",
    "WAIT_BUYER_CONFIRM_GOODS": "等待买家确认收货",
    "TRADE_FINISHED": "交易完成",
    "TRADE_CLOSED": "交易关闭",
    "TRADE_CLOSED_BY_TAOBAO": "交易关闭（系统）",
    "WAIT_SELLER_DECIDE": "等待卖家处理退款",
    "REFUND_SUCCESS": "退款成功",
}

# 订单详情接口（上游 XianyuApis 未提供，此处保留）
_ORDER_DETAIL_URL = "https://h5api.m.goofish.com/h5/mtop.taobao.idle.order.detail/1.0/"


# ──────────────────────────────────────────────────────────────────────────────
# Provider 实现
# ──────────────────────────────────────────────────────────────────────────────

class GoofishProvider(XianyuProvider):
    """
    基于 cv-cat/XianYuApis 子模块的闲鱼 API 薄适配层。

    - 所有 HTTP API 调用委托给上游 ``XianyuApis`` 实例。
    - 响应按 ``XianyuProvider`` ABC 约定的 dict 格式规范化后返回。
    - 订单详情（上游未实现）由本文件保留实现，复用上游的 session 和签名函数。
    - 所有同步调用通过 ``run_in_executor`` 暴露为 async 接口。
    """

    def __init__(self, cookies_str: str) -> None:
        self._cookies_str = cookies_str
        cookies_dict: dict[str, str] = trans_cookies(cookies_str)
        self._my_user_id_val: str = cookies_dict.get("unb", "")
        self._device_id_val: str = _upstream_generate_device_id(self._my_user_id_val)
        # 核心：上游 XianyuApis 管理 requests.Session + cookie 刷新
        self._apis = XianyuApis(cookies_dict, self._device_id_val)

    # ── 只读属性 ──────────────────────────────────────────────────────────────

    @property
    def my_user_id(self) -> str:
        return self._my_user_id_val

    @property
    def device_id(self) -> str:
        return self._device_id_val

    @property
    def ws_url(self) -> str:
        return _WS_URL

    def get_ws_headers(self) -> dict[str, str]:
        """使用上游 session 中最新 cookie 构造 WebSocket 握手 headers。"""
        return {
            "Cookie": get_session_cookies_str(self._apis.session),
            "Host": "wss-goofish.dingtalk.com",
            "Connection": "Upgrade",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "User-Agent": _UA,
            "Origin": "https://www.goofish.com",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

    # ── 认证 ──────────────────────────────────────────────────────────────────

    def _sync_get_token(self) -> dict[str, Any]:
        """委托给上游 XianyuApis.get_token()，规范化响应。"""
        res = self._apis.get_token()
        if isinstance(res.get("data"), dict) and "accessToken" in res["data"]:
            return {"success": True, "access_token": res["data"]["accessToken"], "_raw": res}
        return {"success": False, "error": str(res.get("ret", res)), "_raw": res}

    async def get_token(self) -> dict[str, Any]:
        return await asyncio.get_event_loop().run_in_executor(None, self._sync_get_token)

    def _sync_refresh_token(self) -> dict[str, Any]:
        """委托给上游 XianyuApis.refresh_token()，规范化响应。"""
        res = self._apis.refresh_token()
        return {"success": True, "_raw": res}

    async def refresh_token(self) -> dict[str, Any]:
        return await asyncio.get_event_loop().run_in_executor(None, self._sync_refresh_token)

    # ── 商品详情 ──────────────────────────────────────────────────────────────

    def _sync_get_item_info(self, item_id: str) -> dict[str, Any]:
        """委托给上游 XianyuApis.get_item_info()，规范化响应。"""
        res = self._apis.get_item_info(item_id)
        ret = res.get("ret", [])
        if not any("SUCCESS" in r for r in ret):
            return {"success": False, "error": f"API returned: {ret}", "raw_ret": ret}

        result_data = res.get("data", {})
        item_do = result_data.get("itemDO", {})
        detail = item_do.get("detail", {}) or {}
        price_raw = (
            item_do.get("soldPrice")
            or detail.get("soldPrice")
            or item_do.get("price")
            or ""
        )
        return {
            "success": True,
            "item_id": str(item_id),
            "title": item_do.get("title") or detail.get("title", ""),
            "price": price_raw,
            "desc": item_do.get("desc") or detail.get("desc", ""),
            "category": item_do.get("category") or "",
            "image_url": (item_do.get("picInfo") or {}).get("picUrl", ""),
            "item_status": item_do.get("itemStatus", -1),
            "seller_id": str(item_do.get("userId") or ""),
            "location": item_do.get("area") or "",
        }

    async def get_item_info(self, item_id: str) -> dict[str, Any]:
        return await asyncio.get_event_loop().run_in_executor(
            None, self._sync_get_item_info, str(item_id)
        )

    # ── 买家信息（购买历史、地区等）────────────────────────────────────────────

    def _sync_get_buyer_info(self, buyer_id: str) -> dict[str, Any]:
        """
        获取买家信息，包括购买历史统计和用户地区信息。
        
        使用 mtop.taobao.idlemessage.pc.user.query (v4.0) API。
        
        Args:
            buyer_id: 买家用户 ID
            
        Returns:
            dict with keys:
            - success: bool
            - buyer_id: 买家 ID
            - buyer_nick: 买家昵称
            - buy_count: 买家购买次数
            - deal_count: 买家成交次数
            - trade_count: 交易总数（可能与 deal_count 相同或不同）
            - has_bought: 是否从当前卖家购买过 (bool)
            - user_type: 用户类型 (1=买家, 2=卖家)
            - location: 用户地区信息 (字符串或空)
            - error: 错误信息（仅当 success=False 时）
            - _raw_api_response: 完整 API 响应（用于调试）
        """
        data_val = json.dumps(
            {"type": 1, "userId": str(buyer_id)}, 
            ensure_ascii=False, 
            separators=(",", ":")
        )
        t = str(int(time.time()) * 1000)
        token = self._apis.session.cookies.get("_m_h5_tk", "").split("_")[0]
        sign = generate_sign(t, token, data_val)

        params = {
            "jsv": "2.7.2",
            "appKey": _APP_KEY,
            "t": t,
            "sign": sign,
            "v": "4.0",  # 版本 4.0 用于 pc.user.query
            "type": "originaljson",
            "accountSite": "xianyu",
            "dataType": "json",
            "timeout": "20000",
            "api": "mtop.taobao.idlemessage.pc.user.query",
            "sessionOption": "AutoLoginOnly",
        }
        
        user_query_url = "https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.pc.user.query/4.0/"
        resp = self._apis.session.post(
            user_query_url,
            params=params,
            data={"data": data_val},
        )
        
        res = resp.json()
        ret = res.get("ret", [])
        if not any("SUCCESS" in r for r in ret):
            return {"success": False, "error": f"API returned: {ret}", "raw_ret": ret}

        data = res.get("data", {})
        user_info = data.get("userInfo", {}) or {}

        # 解析扩展字段中的交易统计信息
        ext_str = user_info.get("ext", "{}")
        trade_status = {}
        try:
            if isinstance(ext_str, str):
                trade_status = json.loads(ext_str)
            elif isinstance(ext_str, dict):
                trade_status = ext_str
        except (json.JSONDecodeError, TypeError):
            trade_status = {}

        # 安全的值获取函数
        def _get(*keys: str, default: Any = "") -> Any:
            node = user_info
            for k in keys:
                if not isinstance(node, dict):
                    return default
                node = node.get(k, default)
            return node if node is not None else default

        # 提取用户基本信息
        buyer_nick = _get("fishNick") or _get("nick", "")
        user_type = _get("type", 1)  # 1=买家, 2=卖家
        
        # 从 tradeStatus 提取购买统计信息
        buy_count_str = trade_status.get("buyCount", "0")
        deal_count_str = trade_status.get("dealCount", "0")
        trade_count_str = trade_status.get("tradeCount", "0")
        has_bought = trade_status.get("hasBought", False)
        
        # 类型转换
        try:
            buy_count = int(buy_count_str) if buy_count_str else 0
            deal_count = int(deal_count_str) if deal_count_str else 0
            trade_count = int(trade_count_str) if trade_count_str else 0
        except (ValueError, TypeError):
            buy_count = 0
            deal_count = 0
            trade_count = 0

        # 处理 has_bought（可能是字符串 "true"/"false" 或布尔值）
        if isinstance(has_bought, str):
            has_bought = has_bought.lower() in ("true", "1", "yes")
        else:
            has_bought = bool(has_bought)

        # 尝试从其他字段提取地区信息（如果 API 返回地区数据）
        location = _get("area") or _get("location", "")

        return {
            "success": True,
            "buyer_id": str(buyer_id),
            "buyer_nick": buyer_nick,
            "buy_count": buy_count,
            "deal_count": deal_count,
            "trade_count": trade_count,
            "has_bought": has_bought,
            "user_type": user_type,
            "location": location,
            "_raw_api_response": data,  # 完整 API 响应用于调试
        }

    async def get_buyer_info(self, buyer_id: str) -> dict[str, Any]:
        """
        异步包装：获取买家信息。
        
        Args:
            buyer_id: 买家用户 ID
            
        Returns:
            dict - 买家信息和交易统计
        """
        return await asyncio.get_event_loop().run_in_executor(
            None, self._sync_get_buyer_info, str(buyer_id)
        )


    # ── 订单详情（上游未实现，复用上游 session 和 generate_sign）──────────────

    def _sync_get_order_detail(self, order_id: str) -> dict[str, Any]:
        """
        订单详情。上游 XianyuApis 未提供此接口，使用上游 session 直接调用 h5api。
        签名函数复用上游 generate_sign（JS-based via execjs）。
        """
        data_val = json.dumps(
            {"orderId": str(order_id)}, ensure_ascii=False, separators=(",", ":")
        )
        t = str(int(time.time()) * 1000)
        token = self._apis.session.cookies.get("_m_h5_tk", "").split("_")[0]
        sign = generate_sign(t, token, data_val)

        params = {
            "jsv": "2.7.2",
            "appKey": _APP_KEY,
            "t": t,
            "sign": sign,
            "v": "1.0",
            "type": "originaljson",
            "accountSite": "xianyu",
            "dataType": "json",
            "timeout": "20000",
            "api": "mtop.taobao.idle.order.detail",
            "sessionOption": "AutoLoginOnly",
        }
        resp = self._apis.session.post(
            _ORDER_DETAIL_URL,
            params=params,
            data={"data": data_val},
        )
        res = resp.json()
        ret = res.get("ret", [])
        if not any("SUCCESS" in r for r in ret):
            return {"success": False, "error": f"API returned: {ret}", "raw_ret": ret}

        data = res.get("data", {})
        order_info = data.get("orderInfo", {}) or data

        def _get(*keys: str, default: Any = "") -> Any:
            node = order_info
            for k in keys:
                if not isinstance(node, dict):
                    return default
                node = node.get(k, default)
            return node if node is not None else default

        raw_status = _get("orderStatus") or _get("status")
        status_label = _ORDER_STATUS_MAP.get(str(raw_status), str(raw_status))

        sku_list = _get("skuInfoList") or []
        sku_text = ""
        if isinstance(sku_list, list) and sku_list:
            parts = []
            for sku in sku_list:
                if isinstance(sku, dict):
                    name = sku.get("name") or sku.get("specName", "")
                    value = sku.get("value") or sku.get("specValue", "")
                    if name:
                        parts.append(f"{name}: {value}")
            sku_text = "；".join(parts)

        return {
            "success": True,
            "order_id": str(order_id),
            "item_id": str(_get("itemId") or _get("goodsId") or ""),
            "item_title": _get("itemTitle") or _get("goodsTitle") or _get("title") or "",
            "sku": sku_text,
            "quantity": str(_get("buyAmount") or _get("quantity") or "1"),
            "amount": str(_get("actualFee") or _get("payment") or _get("totalAmount") or ""),
            "status": raw_status,
            "status_label": status_label,
            "buyer_id": str(_get("buyerId") or _get("userId") or ""),
            "buyer_nickname": _get("buyerNick") or _get("buyerName") or "",
            "create_time": str(_get("gmtCreate") or _get("createTime") or ""),
            "_raw_api_response": data,  # full raw API data for archival
        }

    async def get_order_detail(self, order_id: str) -> dict[str, Any]:
        return await asyncio.get_event_loop().run_in_executor(
            None, self._sync_get_order_detail, str(order_id)
        )

    # ── 媒体上传 ──────────────────────────────────────────────────────────────

    def _sync_upload_media(self, media_path: str) -> dict[str, Any]:
        """委托给上游 XianyuApis.upload_media()，规范化响应。"""
        res = self._apis.upload_media(media_path)
        obj = res.get("object", {})
        url = obj.get("url", "")
        pix = obj.get("pix", "0x0")
        try:
            width, height = (int(x) for x in pix.split("x"))
        except Exception:
            width, height = 0, 0
        if url:
            return {"success": True, "url": url, "width": width, "height": height, "_raw": res}
        return {"success": False, "error": str(res), "_raw": res}

    async def upload_media(self, media_path: str) -> dict[str, Any]:
        return await asyncio.get_event_loop().run_in_executor(
            None, self._sync_upload_media, media_path
        )

    # ── WebSocket 辅助 ────────────────────────────────────────────────────────

    async def ws_init(self, websocket: Any) -> None:
        """注册 WebSocket 会话（与上游 XianyuLive.init 对齐）。"""
        token_result = await self.get_token()
        if not token_result.get("success"):
            logger.error(
                f"[GoofishProvider.ws_init] 获取 token 失败: {token_result.get('error')}"
            )
            return

        reg_msg = {
            "lwp": "/reg",
            "headers": {
                "cache-header": "app-key token ua wv",
                "app-key": _APP_CONFIG_APP_KEY,
                "token": token_result["access_token"],
                "ua": _UA_DINGTALK,
                "dt": "j",
                "wv": "im:3,au:3,sy:6",
                "sync": "0,0;0;0;",
                "did": self._device_id_val,
                "mid": generate_mid(),
            },
        }
        await websocket.send(json.dumps(reg_msg))

        current_time = int(time.time() * 1000)
        ack_msg = {
            "lwp": "/r/SyncStatus/ackDiff",
            "headers": {"mid": generate_mid()},
            "body": [
                {
                    "pipeline": "sync",
                    "tooLong2Tag": "PNM,1",
                    "channel": "sync",
                    "topic": "sync",
                    "highPts": 0,
                    "pts": current_time * 1000,
                    "seq": 0,
                    "timestamp": current_time,
                }
            ],
        }
        await websocket.send(json.dumps(ack_msg))
        logger.info("[GoofishProvider.ws_init] WebSocket 初始化完成")

    async def ws_heartbeat(self, websocket: Any) -> None:
        """持续心跳（与上游 XianyuLive.heart_beat 对齐，每 15 秒一次）。"""
        while True:
            await websocket.send(json.dumps({"lwp": "/!", "headers": {"mid": generate_mid()}}))
            await asyncio.sleep(15)

    # ── 消息发送（共享 WebSocket）─────────────────────────────────────────────

    async def send_message(
        self,
        websocket: Any,
        cid: str,
        toid: str,
        message: dict[str, Any],
    ) -> None:
        """
        向已建立的 WebSocket 发送消息（与上游 XianyuLive.send_msg 对齐）。

        ``message`` 格式：``make_text(str)`` 或 ``make_image(url, w, h)``。
        """
        msg_type = message.get("type")
        wire: dict[str, Any] = {
            "lwp": "/r/MessageSend/sendByReceiverScope",
            "headers": {"mid": generate_mid()},
            "body": [
                {
                    "uuid": generate_uuid(),
                    "cid": f"{cid}@goofish",
                    "conversationType": 1,
                    "content": {
                        "contentType": 101,
                        "custom": {"type": None, "data": None},
                    },
                    "redPointPolicy": 0,
                    "extension": {"extJson": "{}"},
                    "ctx": {"appVersion": "1.0", "platform": "web"},
                    "mtags": {},
                    "msgReadStatusSetting": 1,
                },
                {
                    "actualReceivers": [
                        f"{toid}@goofish",
                        f"{self._my_user_id_val}@goofish",
                    ]
                },
            ],
        }

        if msg_type == "text":
            payload = {"contentType": 1, "text": {"text": message["text"]}}
            b64 = base64.b64encode(
                json.dumps(payload, ensure_ascii=False).encode("utf-8")
            ).decode("utf-8")
            wire["body"][0]["content"]["custom"]["type"] = 1
            wire["body"][0]["content"]["custom"]["data"] = b64

        elif msg_type == "image":
            payload = {
                "contentType": 2,
                "image": {
                    "pics": [
                        {
                            "type": 0,
                            "url": message["image_url"],
                            "width": message["width"],
                            "height": message["height"],
                        }
                    ]
                },
            }
            b64 = base64.b64encode(
                json.dumps(payload, ensure_ascii=False).encode("utf-8")
            ).decode("utf-8")
            wire["body"][0]["content"]["custom"]["type"] = 2
            wire["body"][0]["content"]["custom"]["data"] = b64

        else:
            logger.error(f"[GoofishProvider.send_message] 不支持的消息类型: {msg_type}")
            return

        await websocket.send(json.dumps(wire))

    # ── 消息发送（临时 WebSocket）─────────────────────────────────────────────

    # ── 会话列表 / 历史消息 ───────────────────────────────────────────────────

    async def list_all_conversations(self, cid: str) -> list[dict[str, Any]]:
        """
        拉取指定会话的全部历史消息（自动翻页）。
        与上游 XianyuLive.list_all_conversations 逻辑对齐，通过临时 WebSocket 连接执行。
        """
        if websockets is None:
            logger.error("[GoofishProvider.list_all_conversations] websockets 库未安装")
            return []

        ws_headers = self.get_ws_headers()
        token_result = await self.get_token()
        if not token_result.get("success"):
            logger.error(
                f"[GoofishProvider.list_all_conversations] 获取 token 失败: "
                f"{token_result.get('error')}"
            )
            return []

        reg_msg = {
            "lwp": "/reg",
            "headers": {
                "cache-header": "app-key token ua wv",
                "app-key": _APP_CONFIG_APP_KEY,
                "token": token_result["access_token"],
                "ua": _UA_DINGTALK,
                "dt": "j",
                "wv": "im:3,au:3,sy:6",
                "sync": "0,0;0;0;",
                "did": self._device_id_val,
                "mid": generate_mid(),
            },
        }

        user_message_models: list[dict[str, Any]] = []
        send_mid = generate_mid()
        list_msg: dict[str, Any] = {
            "lwp": "/r/MessageManager/listUserMessages",
            "headers": {"mid": send_mid},
            "body": [f"{cid}@goofish", False, 9007199254740991, 20, False],
        }

        async def _run(kwarg_name: str) -> list[dict[str, Any]]:
            nonlocal send_mid, list_msg
            collected: list[dict[str, Any]] = []
            async with websockets.connect(_WS_URL, **{kwarg_name: ws_headers}) as ws:
                await ws.send(json.dumps(reg_msg))
                vulcan_done = False
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue

                    # ACK every server message
                    try:
                        ack: dict[str, Any] = {
                            "code": 200,
                            "headers": {
                                "mid": msg.get("headers", {}).get("mid", generate_mid()),
                                "sid": msg.get("headers", {}).get("sid", ""),
                            },
                        }
                        for k in ("app-key", "ua", "dt"):
                            if k in msg.get("headers", {}):
                                ack["headers"][k] = msg["headers"][k]
                        await ws.send(json.dumps(ack))
                    except Exception:
                        pass

                    # Wait for /s/vulcan to fire the list request once
                    if not vulcan_done and msg.get("lwp") == "/s/vulcan":
                        await ws.send(json.dumps(list_msg))
                        vulcan_done = True
                        continue

                    recv_mid = msg.get("headers", {}).get("mid", "")
                    if recv_mid != send_mid:
                        continue

                    # Parse the listUserMessages response
                    try:
                        body = msg.get("body", {})
                        has_more = body.get("hasMore") == 1
                        next_cursor = body.get("nextCursor")
                        for user_msg in body.get("userMessageModels", []):
                            try:
                                ext = user_msg.get("message", {}).get("extension", {})
                                send_user_name = ext.get("reminderTitle", "")
                                send_user_id = ext.get("senderUserId", "")
                                raw_b64 = (
                                    user_msg.get("message", {})
                                    .get("content", {})
                                    .get("custom", {})
                                    .get("data", "")
                                )
                                decoded = json.loads(
                                    base64.b64decode(raw_b64).decode("utf-8")
                                )
                                collected.insert(
                                    0,
                                    {
                                        "send_user_id": send_user_id,
                                        "send_user_name": send_user_name,
                                        "message": decoded,
                                    },
                                )
                            except Exception as inner_e:
                                logger.debug(
                                    f"[list_all_conversations] 解析单条消息失败: {inner_e}"
                                )
                        if has_more and next_cursor:
                            send_mid = generate_mid()
                            list_msg["headers"]["mid"] = send_mid
                            list_msg["body"][2] = next_cursor
                            await ws.send(json.dumps(list_msg))
                        else:
                            return collected
                    except Exception as e:
                        logger.warning(
                            f"[list_all_conversations] 解析响应体失败: {e}"
                        )
                        return collected
            return collected

        try:
            try:
                user_message_models = await _run("extra_headers")
            except TypeError:
                user_message_models = await _run("additional_headers")
            logger.info(
                f"[GoofishProvider.list_all_conversations] 拉取完成: "
                f"cid={cid}, count={len(user_message_models)}"
            )
        except Exception as exc:
            logger.error(
                f"[GoofishProvider.list_all_conversations] 失败: {exc}", exc_info=True
            )
        return user_message_models

    # ── 主动发起会话 ──────────────────────────────────────────────────────────

    async def create_chat(
        self,
        websocket: Any,
        toid: str,
        item_id: str,
    ) -> None:
        """
        在已建立的 WebSocket 上向买家发起新会话（与上游 XianyuLive.create_chat 对齐）。
        """
        msg = {
            "lwp": "/r/SingleChatConversation/create",
            "headers": {"mid": generate_mid()},
            "body": [
                {
                    "pairFirst": f"{toid}@goofish",
                    "pairSecond": f"{self._my_user_id_val}@goofish",
                    "bizType": "1",
                    "extension": {"itemId": item_id},
                    "ctx": {"appVersion": "1.0", "platform": "web"},
                }
            ],
        }
        await websocket.send(json.dumps(msg))
        logger.info(
            f"[GoofishProvider.create_chat] 发起会话: toid={toid}, item_id={item_id}"
        )

    # ── 登录状态检查 ──────────────────────────────────────────────────────────

    def _sync_has_login(self, retry_count: int = 0) -> bool:
        """
        检查当前 cookie 登录状态，最多重试 2 次。
        逻辑来自 legacy/XianyuApis.py hasLogin()。
        """
        if retry_count >= 2:
            logger.error("[GoofishProvider.has_login] 登录检查失败，重试次数过多")
            return False
        try:
            url = "https://passport.goofish.com/newlogin/hasLogin.do"
            params = {"appName": "xianyu", "fromSite": "77"}
            session = self._apis.session
            data = {
                "hid": session.cookies.get("unb", ""),
                "ltl": "true",
                "appName": "xianyu",
                "appEntrance": "web",
                "_csrf_token": session.cookies.get("XSRF-TOKEN", ""),
                "umidToken": "",
                "hsiz": session.cookies.get("cookie2", ""),
                "bizParams": "taobaoBizLoginFrom=web",
                "mainPage": "false",
                "isMobile": "false",
                "lang": "zh_CN",
                "returnUrl": "",
                "fromSite": "77",
                "isIframe": "true",
                "documentReferer": "https://www.goofish.com/",
                "defaultView": "hasLogin",
                "umidTag": "SERVER",
                "deviceId": session.cookies.get("cna", ""),
            }
            response = session.post(url, params=params, data=data)
            res_json = response.json()
            if res_json.get("content", {}).get("success"):
                logger.info("[GoofishProvider.has_login] Cookie 有效，已登录")
                self.update_env_cookies()
                return True
            logger.warning(f"[GoofishProvider.has_login] 登录检查失败: {res_json}")
            time.sleep(0.5)
            return self._sync_has_login(retry_count + 1)
        except Exception as e:
            logger.error(f"[GoofishProvider.has_login] 请求异常: {e}")
            time.sleep(0.5)
            return self._sync_has_login(retry_count + 1)

    async def has_login(self) -> bool:
        return await asyncio.get_event_loop().run_in_executor(
            None, self._sync_has_login, 0
        )

    # ── Cookie 持久化 ─────────────────────────────────────────────────────────

    def update_env_cookies(self) -> None:
        """
        将 session 当前 cookie 回写到 .env 文件的 COOKIES_STR 字段。
        逻辑来自 legacy/XianyuApis.py update_env_cookies()。
        """
        try:
            cookie_str = "; ".join(
                f"{c.name}={c.value}" for c in self._apis.session.cookies
            )
            env_path = os.path.join(os.getcwd(), ".env")
            if not os.path.exists(env_path):
                logger.warning(
                    "[GoofishProvider.update_env_cookies] .env 文件不存在，跳过"
                )
                return
            with open(env_path, "r", encoding="utf-8") as fh:
                env_content = fh.read()
            if "COOKIES_STR=" not in env_content:
                logger.warning(
                    "[GoofishProvider.update_env_cookies] .env 中未找到 COOKIES_STR，跳过"
                )
                return
            new_content = re.sub(
                r"COOKIES_STR=.*", f"COOKIES_STR={cookie_str}", env_content
            )
            with open(env_path, "w", encoding="utf-8") as fh:
                fh.write(new_content)
            logger.debug("[GoofishProvider.update_env_cookies] .env 已更新")
        except Exception as e:
            logger.warning(f"[GoofishProvider.update_env_cookies] 更新失败: {e}")

    # ── 消息发送（临时 WebSocket）─────────────────────────────────────────────

    async def send_message_once(
        self,
        cid: str,
        buyer_id: str,
        text: str,
    ) -> dict[str, Any]:
        """
        建立临时 WebSocket 连接，发送单条文本消息后断开。
        上游无此功能，本文件保留实现。
        """
        if websockets is None:
            return {"success": False, "error": "websockets 库未安装"}

        token_result = await self.get_token()
        if not token_result.get("success"):
            return {
                "success": False,
                "error": f"获取 token 失败: {token_result.get('error')}",
            }

        reg_msg = {
            "lwp": "/reg",
            "headers": {
                "cache-header": "app-key token ua wv",
                "app-key": _APP_CONFIG_APP_KEY,
                "token": token_result["access_token"],
                "ua": _UA_DINGTALK,
                "dt": "j",
                "wv": "im:3,au:3,sy:6",
                "sync": "0,0;0;0;",
                "did": self._device_id_val,
                "mid": generate_mid(),
            },
        }

        payload = {"contentType": 1, "text": {"text": text}}
        b64 = base64.b64encode(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        ).decode("utf-8")
        chat_msg = {
            "lwp": "/r/MessageSend/sendByReceiverScope",
            "headers": {"mid": generate_mid()},
            "body": [
                {
                    "uuid": generate_uuid(),
                    "cid": f"{cid}@goofish",
                    "conversationType": 1,
                    "content": {
                        "contentType": 101,
                        "custom": {"type": 1, "data": b64},
                    },
                    "redPointPolicy": 0,
                    "extension": {"extJson": "{}"},
                    "ctx": {"appVersion": "1.0", "platform": "web"},
                    "mtags": {},
                    "msgReadStatusSetting": 1,
                },
                {
                    "actualReceivers": [
                        f"{buyer_id}@goofish",
                        f"{self._my_user_id_val}@goofish",
                    ]
                },
            ],
        }

        ws_headers = self.get_ws_headers()

        async def _do_send(kwarg_name: str) -> None:
            async with websockets.connect(_WS_URL, **{kwarg_name: ws_headers}) as ws:
                await ws.send(json.dumps(reg_msg))
                await asyncio.sleep(0.8)
                await ws.send(json.dumps(chat_msg))
                await asyncio.sleep(0.3)

        try:
            try:
                await _do_send("extra_headers")
            except TypeError:
                await _do_send("additional_headers")

            logger.info(
                f"[GoofishProvider.send_message_once] 发送成功: "
                f"cid={cid}, buyer_id={buyer_id}, text={text[:60]!r}"
            )
            return {"success": True, "chat_id": cid, "message": text}

        except Exception as exc:
            err = f"WebSocket 发送失败: {exc}"
            logger.error(f"[GoofishProvider.send_message_once] {err}", exc_info=True)
            return {"success": False, "error": err}

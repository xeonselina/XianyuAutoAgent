"""
Xianyu (闲鱼) tool package for ai_kefu.

Provides tools for interacting with the Xianyu platform:
- get_item_info:       Fetch item details (title, price, description, stock)
- get_order_detail:    Fetch order details (SKU, amount, buyer info, status)
- get_buyer_info:      Fetch buyer information (purchase history, location)
- send_xianyu_message: Send a text message to a chat session
- upload_media:        Upload a local image to Xianyu CDN
- list_conversations:  Fetch full chat history for a session
- create_chat:         Proactively initiate a new chat with a buyer

Authentication is handled via xianyu_cookie configured in settings.
"""

from ai_kefu.tools.xianyu.get_item_info import (
    get_item_info,
    get_tool_definition as get_item_info_definition,
)
from ai_kefu.tools.xianyu.get_order_detail import (
    get_order_detail,
    get_tool_definition as get_order_detail_definition,
)
from ai_kefu.tools.xianyu.get_buyer_info import (
    get_buyer_info,
    get_tool_definition as get_buyer_info_definition,
)
from ai_kefu.tools.xianyu.send_message import (
    send_xianyu_message,
    get_tool_definition as send_message_definition,
)
from ai_kefu.tools.xianyu.upload_media import (
    upload_media,
    get_tool_definition as upload_media_definition,
)
from ai_kefu.tools.xianyu.list_conversations import (
    list_conversations,
    get_tool_definition as list_conversations_definition,
)
from ai_kefu.tools.xianyu.create_chat import (
    create_chat,
    get_tool_definition as create_chat_definition,
)

__all__ = [
    "get_item_info",
    "get_item_info_definition",
    "get_order_detail",
    "get_order_detail_definition",
    "get_buyer_info",
    "get_buyer_info_definition",
    "send_xianyu_message",
    "send_message_definition",
    "upload_media",
    "upload_media_definition",
    "list_conversations",
    "list_conversations_definition",
    "create_chat",
    "create_chat_definition",
]

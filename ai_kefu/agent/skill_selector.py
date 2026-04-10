"""
Skill selector — maps user query intent to relevant tool skill groups.

Skills:
  core   (always loaded) : knowledge_search, complete_task, ask_human_agent
  rental (租借/租赁/可租) : parse_date, check_availability, calculate_logistics,
                           calculate_price, collect_rental_info
  order  (订单/物流/退货) : get_order_status, get_order_detail, get_return_address
  xianyu (平台/商品/消息) : get_item_info, send_xianyu_message, upload_media,
                           list_conversations
"""

from __future__ import annotations

SKILL_TOOL_MAP: dict[str, list[str]] = {
    "core": ["knowledge_search", "complete_task", "ask_human_agent"],
    "rental": [
        "parse_date",
        "check_availability",
        "calculate_logistics",
        "calculate_price",
        "collect_rental_info",
    ],
    "order": ["get_order_status", "get_order_detail", "get_return_address"],
    "xianyu": [
        "get_item_info",
        "send_xianyu_message",
        "upload_media",
        "list_conversations",
    ],
}

_RENTAL_KEYWORDS = frozenset({
    "租", "租借", "租赁", "可租", "档期", "日期", "天数", "运费", "押金",
    "归还", "发货", "寄", "租金", "租期", "出租",
})
_ORDER_KEYWORDS = frozenset({
    "订单", "物流", "快递", "退货", "退款", "地址", "收货", "状态",
    "付款", "下单", "发货", "已付", "待发", "包裹", "查件", "查快递",
})
_XIANYU_KEYWORDS = frozenset({
    "商品", "价格", "库存", "闲鱼", "图片", "消息", "上架", "下架",
    "评价", "聊天记录", "宝贝", "详情", "链接", "发图",
})


def detect_skills(query: str, session_context: dict | None = None) -> set[str]:
    """
    Detect which skill groups are relevant for the current turn.

    Always includes ``core``.  Additional skills are activated by keyword
    matching against *query* and by inspecting persistent keys in
    *session_context* (e.g. ``rental_info`` set by a previous tool call).

    Args:
        query:           The user's raw message for this turn.
        session_context: Optional dict of session-level state (from
                         ``session.context`` or similar).

    Returns:
        A set of skill names, always containing at least ``{"core"}``.
    """
    skills: set[str] = {"core"}
    ctx = session_context or {}

    for kw in _RENTAL_KEYWORDS:
        if kw in query:
            skills.add("rental")
            break

    for kw in _ORDER_KEYWORDS:
        if kw in query:
            skills.add("order")
            break

    for kw in _XIANYU_KEYWORDS:
        if kw in query:
            skills.add("xianyu")
            break

    # Sticky activation: if session already carries rental or order context
    # keep those skill groups so tool-continuation turns work correctly.
    if ctx.get("rental_info") or ctx.get("rental_dates"):
        skills.add("rental")
    if ctx.get("order_id") or ctx.get("order_info"):
        skills.add("order")

    return skills


def get_active_tool_names(skills: set[str]) -> set[str]:
    """
    Flatten a set of skill names into the union of their tool names.

    Args:
        skills: Skill names (from :func:`detect_skills`).

    Returns:
        Set of tool names to expose to the LLM for this turn.
    """
    names: set[str] = set()
    for skill in skills:
        names.update(SKILL_TOOL_MAP.get(skill, []))
    return names

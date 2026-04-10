"""
Xianyu inbound message endpoint.

POST /xianyu/inbound receives a decoded XianyuMessage from the interceptor
(which is now a thin transport relay), applies all business logic, and returns
{reply: str | null}.

Business logic handled here:
- Message direction detection (seller vs buyer)
- Ignore pattern filtering
- Manual mode toggle / check
- AI suppression (seller secret code)
- Order placed detection → rental summary + order detail recording
- AI Agent call (via /chat/ endpoint logic)
- Confidence guard suppression passthrough
- Conversation logging to MySQL
"""

import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ai_kefu.api.dependencies import (
    get_conversation_store,
    get_ignore_pattern_store,
    get_manual_mode_manager,
    get_xianyu_session_mapper,
)
from ai_kefu.xianyu_interceptor.conversation_store import ConversationStore
from ai_kefu.xianyu_interceptor.conversation_models import ConversationMessage, MessageType
from ai_kefu.xianyu_interceptor.session_mapper import SessionMapper
from ai_kefu.xianyu_interceptor.manual_mode import ManualModeManager
from ai_kefu.storage.ignore_pattern_store import IgnorePatternStore
from ai_kefu.config.settings import settings
from ai_kefu.utils.logging import logger


router = APIRouter()

# ──────────────────────────────────────────────────────────────
# Request / Response models
# ──────────────────────────────────────────────────────────────

class XianyuInboundRequest(BaseModel):
    """Decoded Xianyu message payload POSTed by the interceptor transport."""
    chat_id: str
    user_id: str
    content: Optional[str] = None
    item_id: Optional[str] = None
    user_nickname: Optional[str] = None
    encrypted_uid: Optional[str] = None
    is_self_sent: bool = False
    message_id: Optional[str] = None
    item_title: Optional[str] = None
    item_price: Optional[str] = None
    timestamp: Optional[int] = None
    raw_data: Optional[dict] = None
    metadata: Optional[dict] = Field(default_factory=dict)


class XianyuInboundResponse(BaseModel):
    """Response returned to the interceptor."""
    reply: Optional[str] = None


# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

_ORDER_PLACED_KEYWORDS = [
    "[我已拍下，待付款]",
    "[我已付款，等待你发货]",
]


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _is_toggle_keyword(content: Optional[str]) -> bool:
    if not content:
        return False
    keywords = [k.strip() for k in settings.toggle_keywords.split(',') if k.strip()]
    return content.strip() in keywords


def _is_suppress_keyword(content: Optional[str]) -> bool:
    if not content:
        return False
    keywords = [k.strip() for k in settings.suppress_keywords.split(',') if k.strip()]
    return content.strip() in keywords


def _is_order_placed_message(content: Optional[str]) -> bool:
    if not content:
        return False
    return content.strip() in _ORDER_PLACED_KEYWORDS


async def _log_message(
    req: XianyuInboundRequest,
    message_type: MessageType,
    conversation_store: ConversationStore,
    agent_response: Optional[str] = None,
    session_id: Optional[str] = None,
    is_manual_mode: bool = False,
    extra_context: Optional[dict] = None,
):
    """Persist a conversation message to MySQL."""
    try:
        context = {
            "item_title": req.item_title,
            "item_price": req.item_price,
            "message_id": req.message_id,
            "is_self_sent": req.is_self_sent,
            "encrypted_uid": req.encrypted_uid,
        }
        if extra_context:
            context.update(extra_context)

        conversation_msg = ConversationMessage(
            chat_id=req.chat_id,
            user_id=req.user_id,
            user_nickname=req.user_nickname,
            seller_id=None,
            item_id=req.item_id,
            message_content=agent_response if agent_response else req.content,
            message_type=message_type,
            session_id=session_id,
            agent_response=agent_response,
            context=context,
            created_at=datetime.now(),
        )

        await asyncio.to_thread(conversation_store.save_message, conversation_msg)

        logger.debug(
            f"Logged message: chat_id={req.chat_id}, type={message_type}, manual={is_manual_mode}"
        )
    except Exception as e:
        logger.error(f"Failed to log message: {e}", exc_info=True)


async def _record_order_detail(
    req: XianyuInboundRequest,
    order_id: Optional[str],
    conversation_store: ConversationStore,
):
    """Fire-and-forget: fetch order detail from Xianyu API and persist to xianyu_orders table."""
    if not order_id:
        logger.warning(
            f"[record_order_detail] chat_id={req.chat_id}: "
            "无法从 raw_data 提取 order_id，跳过订单详情记录"
        )
        return

    try:
        from ai_kefu.tools.xianyu import get_order_detail

        logger.info(
            f"[record_order_detail] 拉取订单详情: "
            f"chat_id={req.chat_id}, order_id={order_id}"
        )
        detail = await asyncio.to_thread(get_order_detail, order_id)

        if not detail.get("success"):
            logger.warning(
                f"[record_order_detail] get_order_detail 失败: "
                f"order_id={order_id}, error={detail.get('error')}"
            )
            return

        await asyncio.to_thread(
            conversation_store.save_order_detail,
            chat_id=req.chat_id,
            user_id=req.user_id,
            order_id=order_id,
            item_id=req.item_id,
            order_detail=detail,
        )
    except Exception as e:
        logger.error(
            f"[record_order_detail] 订单详情记录失败: "
            f"chat_id={req.chat_id}, order_id={order_id}, error={e}",
            exc_info=True,
        )


def _summarize_rental_context(conversation_text: str) -> Optional[str]:
    """Call lightweight LLM to extract rental order key info from conversation history."""
    from ai_kefu.llm.qwen_client import call_qwen

    prompt = f"""你是一个租赁订单助手。用户刚刚拍下了租赁商品，请根据以下对话记录，提取并总结租机订单的关键信息。

请从对话中提取以下信息（如果对话中提到了的话）：
1. **收货日期**：用户期望收到设备的日期
2. **寄回日期**：用户计划归还设备的日期
3. **价格**：商定的租赁价格
4. **收货地址**：用户的收货地址
5. **特殊要求**：任何额外的要求（如配件、免押条件、特定型号等）

输出格式要求：
- 使用简洁的中文，像客服发给买家的确认消息
- 如果某项信息在对话中没有提到，标注"待确认"
- 不要编造信息，只提取对话中实际提到的内容
- 整体控制在 200 字以内
- 开头用"📋 订单信息确认："

对话记录：
{conversation_text}

请输出订单摘要："""

    try:
        response = call_qwen(
            messages=[
                {"role": "system", "content": "你是一个专业的租赁订单助手，负责从对话中提取订单关键信息。"},
                {"role": "user", "content": prompt},
            ],
            tools=None,
            max_tokens=400,
            temperature=0.2,
            model=settings.model_name_light,
        )
        summary = response["choices"][0]["message"].get("content", "")
        return summary.strip() if summary else None
    except Exception as e:
        logger.error(f"Failed to call LLM for rental summary: {e}")
        return None


async def _handle_order_placed(
    req: XianyuInboundRequest,
    session_mapper: SessionMapper,
    conversation_store: ConversationStore,
) -> Optional[str]:
    """
    Triggered when buyer places an order (拍下待付款).
    1. Fire-and-forget: fetch + record order detail.
    2. Generate rental summary from conversation history.
    Returns the summary string (to be sent by the caller), or None.
    """
    logger.info(f"📦 用户拍下商品: chat_id={req.chat_id}, 准备生成租机摘要")

    # Extract order_id from raw_data.
    # Priority order:
    #   1. reminderUrl  ?orderId=<id>   (拍下待付款 card)
    #   2. extJson.updateKey   "<chat_id>:<order_id>:<seq>:<status>:<ct>"  (付款完成 card)
    #   3. targetUrl in the nested dxCard JSON  ?orderId=<id> or id=<id>
    order_id: Optional[str] = None
    try:
        import json as _json
        raw = req.raw_data or {}
        msg_meta = raw.get("1", {}) if isinstance(raw.get("1"), dict) else {}
        meta_10 = msg_meta.get("10", {}) if isinstance(msg_meta.get("10"), dict) else {}

        # ── Method 1: reminderUrl query param ───────────────────────────────
        reminder_url = meta_10.get("reminderUrl", "")
        if "orderId=" in reminder_url:
            order_id = reminder_url.split("orderId=")[1].split("&")[0]
            logger.info(f"📦 [order_id] 从 reminderUrl 提取: {order_id!r}")

        # ── Method 2: extJson.updateKey  <chat_id>:<order_id>:… ─────────────
        if not order_id:
            ext_json_str = meta_10.get("extJson", "")
            if ext_json_str:
                try:
                    ext = _json.loads(ext_json_str)
                    update_key = ext.get("updateKey", "")
                    if update_key:
                        parts = update_key.split(":")
                        # format: "chat_id:order_id:seq:status:contentType"
                        if len(parts) >= 2:
                            candidate = parts[1]
                            if candidate.isdigit() and len(candidate) >= 10:
                                order_id = candidate
                                logger.info(
                                    f"📦 [order_id] 从 extJson.updateKey 提取: {order_id!r} "
                                    f"(updateKey={update_key!r})"
                                )
                except Exception as _je:
                    logger.debug(f"[order_placed] 解析 extJson 失败: {_je}")

        # ── Method 3: nested dxCard JSON in content field  ──────────────────
        if not order_id:
            content_field = msg_meta.get("6", {})
            if isinstance(content_field, dict):
                nested_str = content_field.get("3", {}).get("5", "") if isinstance(content_field.get("3"), dict) else ""
                if not nested_str:
                    # some frames have it at msg_meta["6"]["3"]["5"]
                    try:
                        nested_str = str(content_field)
                    except Exception:
                        pass
                for segment in [nested_str]:
                    if "orderId=" in segment:
                        order_id = segment.split("orderId=")[1].split("&")[0].split('"')[0].split("'")[0]
                        logger.info(f"📦 [order_id] 从 dxCard 内嵌 URL 提取: {order_id!r}")
                        break
                    if '"id":"' in segment or '"id":' in segment:
                        # fleamarket://order_detail?id=<order_id>&role=Seller
                        if "order_detail?id=" in segment:
                            order_id = segment.split("order_detail?id=")[1].split("&")[0].split('"')[0]
                            logger.info(f"📦 [order_id] 从 order_detail URL 提取: {order_id!r}")
                            break

        if not order_id:
            logger.warning(
                f"[order_placed] chat_id={req.chat_id}: "
                f"所有方法均无法提取 order_id，raw_data keys={list(raw.keys())}"
            )
    except Exception as _e:
        logger.debug(f"[order_placed] 无法从 raw_data 提取 order_id: {_e}")

    # Fire-and-forget: record order detail
    asyncio.ensure_future(
        _record_order_detail(req=req, order_id=order_id, conversation_store=conversation_store)
    )

    try:
        history = await asyncio.to_thread(
            conversation_store.get_conversation_history,
            chat_id=req.chat_id,
            limit=50,
        )
        if not history:
            logger.info(f"No conversation history for chat_id={req.chat_id}, skipping summary")
            return None

        conversation_lines = []
        for msg in history:
            content = msg.message_content or ""
            if not content.strip():
                continue
            if content.startswith("【调试】"):
                content = content[4:]
            if "[Agent API Error]" in content or "[Unexpected Error]" in content:
                continue
            msg_type = msg.message_type
            type_str = msg_type.value if hasattr(msg_type, "value") else str(msg_type)
            if type_str == "user":
                conversation_lines.append(f"买家: {content}")
            elif type_str == "seller":
                conversation_lines.append(f"客服: {content}")

        if not conversation_lines:
            logger.info("No meaningful conversation content, skipping summary")
            return None

        summary = await asyncio.to_thread(
            _summarize_rental_context, "\n".join(conversation_lines)
        )
        if not summary:
            logger.warning("Failed to generate rental summary")
            return None

        logger.info(f"📋 租机摘要生成成功 ({len(summary)} chars)")

        # Log summary to DB
        agent_session_id = session_mapper.get_or_create(
            chat_id=req.chat_id,
            user_id=req.user_id,
            item_id=req.item_id,
        )
        await _log_message(
            req=req,
            message_type=MessageType.SELLER,
            conversation_store=conversation_store,
            agent_response=summary,
            session_id=agent_session_id,
            is_manual_mode=False,
        )

        return summary

    except Exception as e:
        logger.error(f"Failed to handle order placed summary: {e}", exc_info=True)
        return None


async def _process_with_agent(
    req: XianyuInboundRequest,
    session_mapper: SessionMapper,
    conversation_store: ConversationStore,
) -> Optional[str]:
    """Call the AI agent via /chat/ and return the reply (or None)."""
    from ai_kefu.agent.executor import AgentExecutor
    from ai_kefu.api.dependencies import get_session_store

    is_debug_mode = not settings.enable_ai_reply

    agent_session_id = session_mapper.get_or_create(
        chat_id=req.chat_id,
        user_id=req.user_id,
        item_id=req.item_id,
    )

    logger.info(
        f"Processing with Agent: chat_id={req.chat_id}, "
        f"session_id={agent_session_id}, debug_mode={is_debug_mode}"
    )

    # Build context (mirrors convert_xianyu_to_agent)
    ctx: dict = {
        "conversation_id": req.chat_id,
        "source": "xianyu",
        "item_id": req.item_id,
        "item_title": req.item_title,
        "item_price": req.item_price,
        "timestamp": req.timestamp,
        "message_type": "chat",
        **(req.metadata or {}),
    }
    if not ctx.get("user_nickname"):
        ctx["user_nickname"] = (
            req.user_nickname
            or (req.metadata or {}).get("reminder_title")
            or None
        )

    try:
        session_store = get_session_store()
        executor = AgentExecutor(session_store=session_store, conversation_store=conversation_store)

        logger.info(
            f"[agent] ▶ executor.run: chat_id={req.chat_id}, "
            f"session_id={agent_session_id}, query={req.content!r}"
        )
        agent_result = await asyncio.to_thread(
            executor.run,
            query=req.content or "",
            session_id=agent_session_id,
            user_id=req.user_id,
            context=ctx,
        )

        response_text: str = agent_result.get("response", "")
        metadata: dict = agent_result.get("metadata", {})
        logger.info(
            f"[agent] ◀ executor.run done: chat_id={req.chat_id}, "
            f"response_len={len(response_text)}, "
            f"suppressed={metadata.get('response_suppressed', False)}, "
            f"error={metadata.get('error')}"
        )

    except Exception as e:
        logger.error(f"Agent call failed for chat {req.chat_id}: {e}", exc_info=True)
        error_note = f"[Agent Error] {e}"
        await _log_message(
            req=req,
            message_type=MessageType.SELLER,
            conversation_store=conversation_store,
            agent_response=error_note,
            session_id=agent_session_id,
        )
        return None

    # Empty response (e.g. confidence guard suppression with no fallback)
    if not response_text.strip() and not metadata.get("error"):
        logger.warning(
            f"Agent returned empty response for chat {req.chat_id}, "
            f"response_suppressed={metadata.get('response_suppressed', False)}"
        )
        return None

    # Agent returned error status
    agent_error = metadata.get("error")
    if agent_error:
        logger.warning(f"Agent returned error for chat {req.chat_id}: {agent_error}")
        if response_text:
            reply = f"【调试】{response_text}" if is_debug_mode else response_text
            await _log_message(
                req=req,
                message_type=MessageType.SELLER,
                conversation_store=conversation_store,
                agent_response=reply,
                session_id=agent_session_id,
            )
            return None if is_debug_mode else reply
        return None

    session_mapper.update_activity(req.chat_id)

    original_response = metadata.get("original_response")
    response_suppressed = metadata.get("response_suppressed", False)
    confidence_context: dict = {}

    if original_response:
        prefix = "【调试】【置信度抑制】" if is_debug_mode else "【置信度抑制】"
        db_response = f"{prefix}{original_response}"
        confidence_context = {
            "confidence_suppressed": True,
            "confidence_percent": metadata.get("confidence_percent"),
            "original_response": original_response,
            "user_query": req.content,
        }
    else:
        db_response = f"【调试】{response_text}" if is_debug_mode else response_text

    # Always enrich the stored context with AI's conversation-level awareness
    agent_context: dict = {}
    if metadata.get("context_summary"):
        agent_context["context_summary"] = metadata["context_summary"]
    if metadata.get("is_returning_customer") is not None:
        agent_context["is_returning_customer"] = metadata["is_returning_customer"]
    if metadata.get("receive_date"):
        agent_context["receive_date"] = metadata["receive_date"]
    if metadata.get("return_date"):
        agent_context["return_date"] = metadata["return_date"]
    if metadata.get("destination"):
        agent_context["destination"] = metadata["destination"]
    if confidence_context:
        agent_context.update(confidence_context)

    await _log_message(
        req=req,
        message_type=MessageType.SELLER,
        conversation_store=conversation_store,
        agent_response=db_response,
        session_id=agent_session_id,
        extra_context=agent_context if agent_context else None,
    )

    if is_debug_mode:
        logger.info(f"Debug mode: AI reply logged but not sent. chat_id={req.chat_id}")
        return None

    if response_suppressed:
        logger.info(
            f"置信度抑制：不发送消息给用户，仅记录数据库。chat_id={req.chat_id}"
        )
        return None

    return response_text


# ──────────────────────────────────────────────────────────────
# Main endpoint
# ──────────────────────────────────────────────────────────────

@router.post("/inbound", response_model=XianyuInboundResponse)
async def xianyu_inbound(
    req: XianyuInboundRequest,
    conversation_store: ConversationStore = Depends(get_conversation_store),
    ignore_pattern_store: IgnorePatternStore = Depends(get_ignore_pattern_store),
    session_mapper: SessionMapper = Depends(get_xianyu_session_mapper),
    manual_mode_manager: ManualModeManager = Depends(get_manual_mode_manager),
):
    """
    Receive a decoded Xianyu message from the interceptor relay, apply all
    business logic, and return an optional reply string.

    The interceptor sends the message here and, if reply is non-null, sends
    it back to the buyer via WebSocket.
    """
    try:
        logger.info(
            f"[xianyu/inbound] ▶ chat_id={req.chat_id}, user_id={req.user_id}, "
            f"is_self_sent={req.is_self_sent}, item_id={req.item_id!r}, "
            f"item_title={req.item_title!r}, content={req.content!r}"
        )

        # ── Ignore pattern check ─────────────────────────────────────────────
        if req.content and ignore_pattern_store.should_ignore(req.content):
            logger.info(
                f"[xianyu/inbound] ✋ ignored by pattern: chat_id={req.chat_id}, "
                f"content='{req.content[:50]}'"
            )
            return XianyuInboundResponse(reply=None)

        # ── Message direction detection ──────────────────────────────────────
        if not settings.seller_user_id:
            logger.warning(
                "⚠️ seller_user_id 未配置！无法准确判断消息方向，"
                "人工客服的消息可能被误当作用户消息处理。"
            )

        is_seller_message = req.is_self_sent or (
            bool(settings.seller_user_id)
            and str(req.user_id).strip() == str(settings.seller_user_id).strip()
        )

        logger.info(
            f"消息方向判断: user_id={req.user_id!r}, "
            f"seller_user_id={settings.seller_user_id!r}, "
            f"is_self_sent={req.is_self_sent}, "
            f"is_seller_message={is_seller_message}"
        )

        if is_seller_message:
            # Seller / human agent message: log only, handle suppression toggle
            logger.info(
                f"[xianyu/inbound] 🧑‍💼 seller message: chat_id={req.chat_id}, user_id={req.user_id}, "
                f"is_self={req.is_self_sent}, logging only"
            )

            if _is_suppress_keyword(req.content):
                if manual_mode_manager.is_suppressed(req.chat_id):
                    manual_mode_manager.cancel_suppression(req.chat_id)
                    logger.info(
                        f"🔊 Seller sent suppress keyword again in chat {req.chat_id}, "
                        f"AI suppression CANCELLED"
                    )
                else:
                    manual_mode_manager.suppress_ai(
                        req.chat_id, duration_seconds=settings.suppress_duration
                    )
                    logger.info(
                        f"🔇 Seller sent suppress keyword in chat {req.chat_id}, "
                        f"AI suppressed for {settings.suppress_duration}s"
                    )

            await _log_message(
                req=req,
                message_type=MessageType.SELLER,
                conversation_store=conversation_store,
                is_manual_mode=manual_mode_manager.is_manual_mode(req.chat_id),
            )
            return XianyuInboundResponse(reply=None)

        # ── Buyer message: log first ─────────────────────────────────────────
        await _log_message(
            req=req,
            message_type=MessageType.USER,
            conversation_store=conversation_store,
            is_manual_mode=manual_mode_manager.is_manual_mode(req.chat_id),
        )

        # ── History-only messages: log only, no AI ───────────────────────────
        # The interceptor sets metadata.history_only=True for replayed history
        # frames so they are persisted to the DB but never trigger the AI agent.
        if (req.metadata or {}).get("history_only"):
            logger.debug(
                f"[xianyu/inbound] history_only message logged, no AI: "
                f"chat_id={req.chat_id}"
            )
            return XianyuInboundResponse(reply=None)

        # ── Manual mode toggle ───────────────────────────────────────────────
        if _is_toggle_keyword(req.content):
            is_manual = manual_mode_manager.toggle_manual_mode(req.chat_id)
            session_mapper.set_manual_mode(req.chat_id, is_manual)
            mode_text = "手动" if is_manual else "自动"
            reply_text = f"已切换到{mode_text}模式"
            logger.info(f"Chat {req.chat_id} toggled to {mode_text} mode")
            return XianyuInboundResponse(reply=reply_text)

        # ── Manual mode check ────────────────────────────────────────────────
        if manual_mode_manager.is_manual_mode(req.chat_id):
            logger.info(f"[xianyu/inbound] 🤚 manual mode active, skipping AI: chat_id={req.chat_id}")
            return XianyuInboundResponse(reply=None)

        # ── AI suppression check ─────────────────────────────────────────────
        if manual_mode_manager.is_suppressed(req.chat_id):
            remaining = manual_mode_manager.get_suppress_remaining(req.chat_id)
            logger.info(
                f"[xianyu/inbound] 🔇 AI suppressed, remaining {remaining}s: chat_id={req.chat_id}"
            )
            return XianyuInboundResponse(reply=None)

        # ── Order placed: generate rental summary first ──────────────────────
        if _is_order_placed_message(req.content):
            summary = await _handle_order_placed(
                req=req,
                session_mapper=session_mapper,
                conversation_store=conversation_store,
            )
            # If we got a summary and AI reply is enabled, send it directly
            if summary and settings.enable_ai_reply:
                # Still fall through to also run agent (it will reply to the order event)
                pass

        # ── AI Agent processing ──────────────────────────────────────────────
        logger.info(
            f"[xianyu/inbound] 🤖 calling agent: chat_id={req.chat_id}, "
            f"enable_ai_reply={settings.enable_ai_reply}"
        )
        reply = await _process_with_agent(
            req=req,
            session_mapper=session_mapper,
            conversation_store=conversation_store,
        )

        logger.info(
            f"[xianyu/inbound] ✅ done: chat_id={req.chat_id}, "
            f"reply={'<none>' if reply is None else repr(reply[:80])}"
        )
        return XianyuInboundResponse(reply=reply)

    except Exception as e:
        logger.error(f"[xianyu/inbound] Unhandled error: {e}", exc_info=True)
        return XianyuInboundResponse(reply=None)

"""
钉钉回复处理服务。

负责：
1. 解析钉钉群里人工客服的回复（#reply request_id 回复内容）
2. 从 MySQL 查找对应的 human_request 和 chat_id
3. 调用 AI 组织语言（把人工客服的简短回答组织成自然的客服回复）
4. 通过闲鱼 transport 发送给用户
5. 更新 human_request 状态为 answered
6. 在钉钉群里发送反馈确认
"""

import re
from typing import Optional, Tuple

from ai_kefu.config.settings import settings
from ai_kefu.utils.logging import logger


# 解析回复格式：#reply <request_id> <回复内容>
_REPLY_PATTERN = re.compile(
    r"#reply\s+(req_[a-f0-9]+)\s+(.+)",
    re.IGNORECASE | re.DOTALL,
)


def parse_dingtalk_reply(text: str) -> Optional[Tuple[str, str]]:
    """
    解析钉钉消息中的回复指令。

    Args:
        text: 钉钉消息文本

    Returns:
        (request_id, human_response) 元组，解析失败返回 None
    """
    if not text:
        return None
    text = text.strip()
    m = _REPLY_PATTERN.match(text)
    if m:
        return m.group(1), m.group(2).strip()
    return None


def compose_reply_with_ai(
    human_response: str,
    original_question: str,
    user_nickname: Optional[str] = None,
    context_summary: Optional[str] = None,
) -> str:
    """
    调用 AI 将人工客服的简短回复组织成自然、友好的客服回复。

    Args:
        human_response: 人工客服的原始回复
        original_question: AI 当初向人工客服提的问题
        user_nickname: 用户昵称
        context_summary: 对话上下文摘要

    Returns:
        组织好的客服回复文本
    """
    from ai_kefu.llm.qwen_client import call_qwen

    context_block = ""
    if context_summary:
        context_block = f"\n对话背景：{context_summary[:500]}\n"

    nickname_block = ""
    if user_nickname:
        nickname_block = f"（用户昵称：{user_nickname}）"

    prompt = f"""你是一个专业的闲鱼租赁客服助手。人工客服刚刚给出了一段回复信息，请你将其组织成一段自然、友好的客服回复，直接发送给用户。

要求：
1. 保留人工客服提供的所有关键信息，不要添加虚假内容
2. 语气亲切自然，像真人客服在聊天
3. 如果人工的回复内容已经足够完整和友好，可以直接使用不做大幅修改
4. 不要使用"人工客服回复"、"为您查到"等暴露内部流程的措辞
5. 控制在 200 字以内
6. 直接输出回复内容，不要加引号或额外说明

AI之前提出的问题：{original_question}
{context_block}
人工客服{nickname_block}的回复：{human_response}

请输出给用户的回复："""

    try:
        response = call_qwen(
            messages=[
                {"role": "system", "content": "你是一个专业的闲鱼租赁客服。请将人工客服的回复组织成自然的客服消息。"},
                {"role": "user", "content": prompt},
            ],
            tools=None,
            max_tokens=300,
            temperature=0.3,
            model=settings.model_name_light,
        )
        content = response["choices"][0]["message"].get("content", "").strip()
        if content:
            return content
    except Exception as e:
        logger.warning(f"AI compose reply failed, using raw human response: {e}")

    # 降级：直接使用人工客服的原始回复
    return human_response


async def handle_dingtalk_reply(text: str) -> str:
    """
    处理一条钉钉回复的完整流程。

    Args:
        text: 钉钉消息文本

    Returns:
        反馈文本（将作为钉钉 Outgoing Webhook 的响应发回群里）
    """
    # 1. 解析回复
    parsed = parse_dingtalk_reply(text)
    if parsed is None:
        return ""  # 非回复指令，不做处理

    request_id, human_response = parsed
    logger.info(f"收到钉钉回复: request_id={request_id}, response={human_response[:100]}")

    # 2. 从 MySQL 查找请求
    from ai_kefu.services.human_request_store import HumanRequestStore
    store = HumanRequestStore.get_instance()
    req = store.get_by_request_id(request_id)

    if req is None:
        return f"❌ 未找到请求 `{request_id}`，请检查 ID 是否正确。"

    if req["status"] != "pending":
        return f"⚠️ 请求 `{request_id}` 已处理过（状态：{req['status']}）。"

    chat_id = req["chat_id"]
    if not chat_id:
        return f"❌ 请求 `{request_id}` 缺少 chat_id，无法发送回复。"

    # 3. AI 组织语言
    composed_reply = compose_reply_with_ai(
        human_response=human_response,
        original_question=req["question"],
        user_nickname=req.get("user_nickname"),
        context_summary=req.get("context_summary"),
    )
    logger.info(f"AI 组织后的回复: {composed_reply[:200]}")

    # 4. 通过闲鱼 transport 发送
    send_success = await _send_to_xianyu(chat_id, composed_reply)

    # 5. 更新 MySQL 状态
    store.mark_answered(request_id, human_response)

    # 6. 记录到 conversations 表
    try:
        from ai_kefu.api.dependencies import get_conversation_store
        conv_store = get_conversation_store()
        from ai_kefu.xianyu_interceptor.conversation_models import ConversationMessage, MessageType
        from datetime import datetime
        msg = ConversationMessage(
            chat_id=chat_id,
            user_id="human_agent",
            user_nickname=None,
            seller_id=None,
            item_id=None,
            message_content=composed_reply,
            message_type=MessageType.SELLER,
            session_id=req.get("session_id"),
            agent_response=composed_reply,
            context={"source": "dingtalk_reply", "request_id": request_id, "raw_human_response": human_response},
            created_at=datetime.now(),
        )
        conv_store.save_message(msg)
    except Exception as e:
        logger.warning(f"记录钉钉回复到 conversations 失败（不影响主流程）: {e}")

    # 7. 返回反馈
    if send_success:
        nickname = req.get("user_nickname") or chat_id[:8]
        return f"✅ 已回复用户 **{nickname}**\n\n> {composed_reply[:200]}"
    else:
        return f"⚠️ 请求已记录，但发送到闲鱼失败。\n\n> 回复内容：{composed_reply[:200]}"


async def _send_to_xianyu(chat_id: str, content: str) -> bool:
    """
    通过全局 transport 实例发送消息到闲鱼。

    transport 是在 run_xianyu.py 中初始化的 BrowserTransport，
    通过全局引用获取。
    """
    try:
        transport = _get_global_transport()
        if transport is None:
            logger.error("闲鱼 transport 未初始化，无法发送钉钉回复到闲鱼")
            return False

        # transport.send_message 需要 chat_id 和 user_id
        # user_id 对于发送来说不是必须的（发到 chat_id 对应的会话即可）
        # 但接口可能需要它，先尝试从 session_mapper 获取
        user_id = _get_user_id_for_chat(chat_id) or "unknown"

        success = await transport.send_message(
            chat_id=chat_id,
            user_id=user_id,
            content=content,
        )
        if success:
            logger.info(f"钉钉回复已发送到闲鱼: chat_id={chat_id}")
        else:
            logger.warning(f"发送钉钉回复到闲鱼失败: chat_id={chat_id}")
        return success
    except Exception as e:
        logger.error(f"发送钉钉回复到闲鱼异常: {e}", exc_info=True)
        return False


# ------------------------------------------------------------------
# 全局 transport 引用
# 在 run_xianyu.py 启动时设置
# ------------------------------------------------------------------
_global_transport = None


def set_global_transport(transport):
    """由 run_xianyu.py 在启动时调用，注入 transport 引用。"""
    global _global_transport
    _global_transport = transport
    logger.info("钉钉回复服务已注入全局 transport")


def _get_global_transport():
    return _global_transport


def _get_user_id_for_chat(chat_id: str) -> Optional[str]:
    """尝试从 conversation_store 获取最近一条用户消息的 user_id。"""
    try:
        from ai_kefu.api.dependencies import get_conversation_store
        store = get_conversation_store()
        history = store.get_conversation_history(chat_id=chat_id, limit=5)
        for msg in reversed(history):
            msg_type = msg.message_type
            type_str = msg_type.value if hasattr(msg_type, "value") else str(msg_type)
            if type_str == "user":
                return msg.user_id
    except Exception as e:
        logger.debug(f"Failed to get user_id for chat_id={chat_id}: {e}")
    return None

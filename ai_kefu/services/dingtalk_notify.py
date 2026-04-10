"""
钉钉群聊机器人通知服务。

独立模块，可被多个场景复用：
- ask_human_agent: AI 请求人工协助时通知
- 置信度抑制: AI 回复被置信度门控抑制时通知
- 其他需要通知人工客服的场景
"""

import hmac
import hashlib
import base64
import time
import urllib.parse
from typing import Optional, List, Dict, Any

import requests

from ai_kefu.config.settings import settings
from ai_kefu.utils.logging import logger


# ──────────────────────────────────────────────
# 底层发送
# ──────────────────────────────────────────────

def _build_signed_url(webhook_url: str, secret: str) -> str:
    """为钉钉 Webhook 生成带签名的 URL。"""
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return f"{webhook_url}&timestamp={timestamp}&sign={sign}"


def send_dingtalk_message(
    title: str,
    content: str,
    at_mobiles: Optional[List[str]] = None,
    is_at_all: bool = False,
) -> bool:
    """
    发送钉钉群聊机器人消息（Markdown 格式）。

    Args:
        title:      消息标题（钉钉通知栏显示）
        content:    Markdown 格式正文
        at_mobiles: 需要 @ 的手机号列表
        is_at_all:  是否 @所有人

    Returns:
        是否发送成功
    """
    webhook_url = getattr(settings, "dingtalk_webhook_url", "")
    secret = getattr(settings, "dingtalk_secret", "")

    if not webhook_url:
        logger.warning("钉钉 Webhook URL 未配置（DINGTALK_WEBHOOK_URL），跳过通知")
        return False

    # 加签
    if secret:
        webhook_url = _build_signed_url(webhook_url, secret)

    # 钉钉 Markdown 消息要求：@所有人 必须同时出现在 text 正文中才能生效
    text = content
    if is_at_all and "@所有人" not in text:
        text = text + "\n\n@所有人"
    if at_mobiles:
        for mobile in at_mobiles:
            if f"@{mobile}" not in text:
                text = text + f"\n\n@{mobile}"

    payload: Dict[str, Any] = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": text,
        },
        "at": {
            "atMobiles": at_mobiles or [],
            "isAtAll": is_at_all,
        },
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=5)
        result = resp.json()
        if result.get("errcode") == 0:
            logger.info(f"钉钉消息发送成功: {title}")
            return True
        else:
            logger.error(f"钉钉消息发送失败: {result}")
            return False
    except Exception as e:
        logger.error(f"钉钉消息发送异常: {e}")
        return False


# ──────────────────────────────────────────────
# 高层业务通知（各场景直接调用）
# ──────────────────────────────────────────────

def notify_human_agent_request(
    request_id: str,
    question: str,
    question_type: str,
    urgency: str = "medium",
    context: Optional[Dict[str, Any]] = None,
    chat_id: Optional[str] = None,
    user_nickname: Optional[str] = None,
    context_summary: Optional[str] = None,
) -> bool:
    """
    通知人工客服：AI 请求协助（ask_human_agent 场景）。

    Args:
        request_id:      请求唯一 ID
        question:        AI 提出的问题
        question_type:   问题类型
        urgency:         紧急程度 low/medium/high
        context:         附加上下文
        chat_id:         闲鱼会话 ID（可选）
        user_nickname:   用户昵称（可选）
        context_summary: 上下文总结（可选）
    """
    urgency_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(urgency, "🟡")
    urgency_label = {"high": "紧急", "medium": "普通", "low": "低"}.get(urgency, urgency)
    type_label = {
        "information_query": "信息查询",
        "decision_required": "需要决策",
        "risk_confirmation": "风险确认",
        "knowledge_gap": "知识缺失",
    }.get(question_type, question_type)

    lines = [
        f"### {urgency_emoji} AI客服请求人工协助",
        "",
    ]

    # 用户昵称（优先展示，方便快速识别）
    if user_nickname:
        lines.append(f"**用户昵称**: {user_nickname}")
        lines.append("")

    lines.extend([
        f"**请求ID**: `{request_id}`",
        "",
        f"**问题类型**: {type_label}",
        "",
        f"**紧急程度**: {urgency_label}",
        "",
        f"**问题**: {question}",
    ])

    if chat_id:
        lines.append("")
        lines.append(f"**会话ID**: `{chat_id}`")

    if context:
        user_q = context.get("user_question")
        relevant = context.get("relevant_info")
        if user_q:
            lines.append("")
            lines.append(f"**用户原始问题**: {user_q}")
        if relevant:
            lines.append("")
            lines.append(f"**已知信息**: {relevant}")

    # 上下文总结（帮助人工客服快速了解对话背景）
    if context_summary:
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("**📋 对话上下文**:")
        lines.append("")
        # 按行拆分，每行作为独立段落，确保钉钉 Markdown 正确换行
        for ctx_line in context_summary[:500].split("\n"):
            ctx_line = ctx_line.strip()
            if ctx_line:
                lines.append(f"> {ctx_line}")
                lines.append("")

    # 回复指引
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("**💬 回复方式**: 在群里直接回复，格式：")
    lines.append("")
    lines.append(f"> #reply {request_id} 你的回复内容")
    lines.append("")
    lines.append("AI 会根据你的回复组织语言发给闲鱼用户。")

    content = "\n".join(lines)
    return send_dingtalk_message(
        title=f"AI客服求助 - {type_label}",
        content=content,
        is_at_all=True,
    )


def notify_confidence_suppression(
    chat_id: str,
    user_message: str,
    original_response: str,
    confidence_percent: int,
    threshold_percent: int,
    fallback_response: str = "",
    user_nickname: Optional[str] = None,
    context_summary: Optional[str] = None,
) -> bool:
    """
    通知人工客服：AI 回复被置信度门控抑制（静默处理，未发送消息给用户）。

    Args:
        chat_id:             闲鱼会话 ID
        user_message:        用户消息
        original_response:   被抑制的原始 AI 回复
        confidence_percent:  置信度评分
        threshold_percent:   抑制阈值
        fallback_response:   (已废弃，保留参数兼容性)
        user_nickname:       用户昵称（可选）
        context_summary:     上下文总结（可选）
    """
    lines = [
        "### ⚠️ AI回复被置信度抑制（未发送消息给用户）",
        "",
    ]

    # 用户昵称（优先展示，方便快速识别）
    if user_nickname:
        lines.append(f"**用户昵称**: {user_nickname}")
        lines.append("")

    lines.extend([
        f"**会话ID**: `{chat_id}`",
        "",
        f"**置信度**: {confidence_percent}%（阈值 {threshold_percent}%）",
        "",
        f"**用户消息**: {user_message[:200]}",
        "",
        f"**被抑制的AI回复**: {original_response[:300]}",
        "",
        "**处理方式**: 🔇 静默处理，未发送任何消息给用户",
    ])

    # 上下文总结（帮助人工客服快速了解对话背景）
    if context_summary:
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("**📋 对话上下文**:")
        lines.append("")
        # 按行拆分，每行作为独立段落，确保钉钉 Markdown 正确换行
        for ctx_line in context_summary[:500].split("\n"):
            ctx_line = ctx_line.strip()
            if ctx_line:
                lines.append(f"> {ctx_line}")
                lines.append("")

    lines.append("")
    lines.append("> 请人工跟进此会话，用户正在等待回复")

    content = "\n".join(lines)
    return send_dingtalk_message(
        title="置信度抑制 - 需人工跟进",
        content=content,
        is_at_all=True,
    )

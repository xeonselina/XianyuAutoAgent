"""
钉钉 Outgoing Webhook 接收端点（兼容模式）。

⚠️ 推荐使用 Stream 模式（见 services/dingtalk_stream_client.py），
   无需公网回调地址，配置更简单。

本端点作为兼容备选，仍然可用：
- 如果你已经配置了 Outgoing Webhook，本端点继续工作
- 如果使用 Stream 模式，本端点可以忽略

接收钉钉群聊中人工客服的回复，并触发闲鱼消息发送。

回复格式：
    #reply req_xxxxxxxxxxxx 你的回复内容
"""

import hmac
import hashlib
import base64
from typing import Any, Dict

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from ai_kefu.config.settings import settings
from ai_kefu.utils.logging import logger


router = APIRouter()


def _verify_outgoing_signature(timestamp: str, sign: str) -> bool:
    """
    验证钉钉 Outgoing Webhook 的签名。
    
    钉钉在请求头中附带 timestamp 和 sign，
    sign = Base64(HmacSHA256(timestamp + "\\n" + token, token))
    """
    token = settings.dingtalk_outgoing_token
    if not token:
        # 未配置 token 时跳过验证（开发模式）
        logger.warning("DINGTALK_OUTGOING_TOKEN 未配置，跳过签名验证")
        return True

    try:
        string_to_sign = f"{timestamp}\n{token}"
        hmac_code = hmac.new(
            token.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        expected_sign = base64.b64encode(hmac_code).decode("utf-8")
        return hmac.compare_digest(sign, expected_sign)
    except Exception as e:
        logger.error(f"钉钉签名验证异常: {e}")
        return False


@router.post("/webhook")
async def dingtalk_outgoing_webhook(request: Request):
    """
    接收钉钉 Outgoing Webhook 消息。

    钉钉机器人会将群里 @机器人 的消息通过 POST 发送到此端点。
    """
    try:
        # 获取请求头中的签名信息
        timestamp = request.headers.get("timestamp", "")
        sign = request.headers.get("sign", "")

        # 验证签名
        if settings.dingtalk_outgoing_token and not _verify_outgoing_signature(timestamp, sign):
            logger.warning("钉钉 Outgoing Webhook 签名验证失败")
            raise HTTPException(status_code=403, detail="Invalid signature")

        # 解析请求体
        body: Dict[str, Any] = await request.json()
        logger.info(f"收到钉钉 Outgoing 消息: {body}")

        # 提取消息文本
        msg_type = body.get("msgtype", "")
        text_content = ""

        if msg_type == "text":
            text_content = body.get("text", {}).get("content", "").strip()
        else:
            logger.info(f"忽略非文本消息: msgtype={msg_type}")
            return JSONResponse(content={"msgtype": "empty"})

        if not text_content:
            return JSONResponse(content={"msgtype": "empty"})

        # 处理回复
        from ai_kefu.services.dingtalk_reply_handler import handle_dingtalk_reply
        feedback = await handle_dingtalk_reply(text_content)

        if not feedback:
            # 非回复指令，忽略
            return JSONResponse(content={"msgtype": "empty"})

        # 返回 Markdown 格式反馈到群里
        return JSONResponse(content={
            "msgtype": "markdown",
            "markdown": {
                "title": "回复结果",
                "text": feedback,
            },
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"钉钉 Outgoing Webhook 处理异常: {e}", exc_info=True)
        return JSONResponse(
            content={
                "msgtype": "text",
                "text": {"content": f"❌ 处理异常: {str(e)[:200]}"},
            }
        )

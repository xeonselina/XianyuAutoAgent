"""
Tool: upload_media
上传本地图片到闲鱼 CDN，返回可直接用于发消息的图片 URL。
底层调用由 xianyu_provider 层统一管理。
"""

import asyncio
from typing import Dict, Any

from ai_kefu.xianyu_provider import get_provider
from ai_kefu.utils.logging import logger


def upload_media(media_path: str) -> Dict[str, Any]:
    """
    Upload a local image/file to Xianyu CDN.

    Args:
        media_path: Absolute or relative path to the local image file.

    Returns:
        {
            "success": bool,
            "url": str,        # CDN URL, usable in send_message image payloads
            "width": int,
            "height": int,
            "error": str       # only when success=False
        }
    """
    try:
        logger.info(f"[upload_media] Uploading: {media_path}")
        provider = get_provider()
        result = asyncio.run(provider.upload_media(media_path))

        if result["success"]:
            logger.info(
                f"[upload_media] OK: url={result.get('url')!r}, "
                f"size={result.get('width')}x{result.get('height')}"
            )
        else:
            logger.warning(
                f"[upload_media] FAILED: path={media_path}, error={result.get('error')}"
            )
        return result

    except ValueError as e:
        msg = str(e)
        logger.error(f"[upload_media] Config error: {msg}")
        return {"success": False, "error": msg}

    except Exception as e:
        msg = f"upload_media failed: {e}"
        logger.error(msg, exc_info=True)
        return {"success": False, "error": msg}


def get_tool_definition() -> Dict[str, Any]:
    """Return the Qwen function-calling tool definition."""
    return {
        "name": "upload_media",
        "description": (
            "上传本地图片到闲鱼 CDN，获取图片 URL。\n\n"
            "使用场景：\n"
            "- 需要向买家发送图片（商品实拍、说明书、快递截图等）时，先调用此工具上传图片，\n"
            "  再用返回的 URL 通过 send_xianyu_message（图片类型）发出\n\n"
            "注意：media_path 为服务器本地文件路径，需确保文件存在且可读。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "media_path": {
                    "type": "string",
                    "description": "本地图片文件路径（绝对路径或相对于工作目录的路径）",
                }
            },
            "required": ["media_path"],
        },
    }

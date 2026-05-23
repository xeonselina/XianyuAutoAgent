"""
图片处理模块

用于提取、下载和保存闲鱼聊天中的图片
"""

import os
import asyncio
import aiohttp
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from loguru import logger


class ImageHandler:
    """
    图片处理器

    负责从闲鱼消息中提取图片 URL，下载并保存图片
    """

    def __init__(self, save_dir: str = "./xianyu_images"):
        """
        初始化图片处理器

        Args:
            save_dir: 图片保存目录
        """
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"图片保存目录: {self.save_dir.absolute()}")

    def extract_image_urls(self, raw_data: Dict[str, Any]) -> List[str]:
        """
        从原始消息数据中提取图片 URL

        【重要】闲鱼图片消息的可能字段：
        - message["1"]["10"]["content"] - 可能包含图片数据
        - message["1"]["10"]["reminderUrl"] - 可能包含图片链接
        - message["1"]["6"] - 消息体，可能包含图片信息
        - message["1"]["10"]["ext"] - 扩展字段，可能包含图片元数据

        Args:
            raw_data: 消息的原始数据（来自 XianyuMessage.raw_data）

        Returns:
            List[str]: 提取到的图片 URL 列表
        """
        urls = []

        try:
            # 方法 1: 从 reminderUrl 提取（通常用于分享链接）
            if "1" in raw_data and isinstance(raw_data["1"], dict):
                if "10" in raw_data["1"] and isinstance(raw_data["1"]["10"], dict):
                    reminder_url = raw_data["1"]["10"].get("reminderUrl", "")
                    if reminder_url and ("jpg" in reminder_url or "png" in reminder_url or "webp" in reminder_url):
                        urls.append(reminder_url)

                # 方法 2: 从 content 字段提取
                # 图片消息的 content 可能包含 JSON 或特殊格式
                if "10" in raw_data["1"] and isinstance(raw_data["1"]["10"], dict):
                    content = raw_data["1"]["10"].get("content", "")
                    if content and content != "[图片]":
                        # 尝试解析 content 中的图片信息
                        import json
                        try:
                            content_data = json.loads(content)
                            # 递归查找所有包含 http 的字段
                            urls.extend(self._find_urls_in_dict(content_data))
                        except:
                            # 不是 JSON，可能是直接的 URL
                            if content.startswith("http"):
                                urls.append(content)

                # 方法 3: 从消息体（6 字段）提取
                if "6" in raw_data["1"]:
                    message_body = raw_data["1"]["6"]
                    if isinstance(message_body, str):
                        try:
                            body_data = json.loads(message_body)
                            urls.extend(self._find_urls_in_dict(body_data))
                        except:
                            pass

                # 方法 4: 从扩展字段提取
                if "10" in raw_data["1"] and isinstance(raw_data["1"]["10"], dict):
                    ext = raw_data["1"]["10"].get("ext", "")
                    if ext:
                        try:
                            ext_data = json.loads(ext)
                            urls.extend(self._find_urls_in_dict(ext_data))
                        except:
                            pass

            # 去重
            urls = list(set(urls))

            if urls:
                logger.info(f"从消息中提取到 {len(urls)} 个图片 URL")
                for url in urls:
                    logger.debug(f"  - {url}")

        except Exception as e:
            logger.error(f"提取图片 URL 失败: {e}", exc_info=True)

        return urls

    def _find_urls_in_dict(self, data: Any, urls: Optional[List[str]] = None) -> List[str]:
        """
        递归查找字典中的所有 URL

        Args:
            data: 要搜索的数据（dict, list, str 等）
            urls: URL 列表（用于递归）

        Returns:
            List[str]: 找到的 URL 列表
        """
        if urls is None:
            urls = []

        if isinstance(data, dict):
            for key, value in data.items():
                # 检查键名是否包含 url, image, pic, photo 等
                if any(keyword in key.lower() for keyword in ["url", "image", "pic", "photo", "img"]):
                    if isinstance(value, str) and value.startswith("http"):
                        if any(ext in value.lower() for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
                            urls.append(value)
                # 递归搜索
                self._find_urls_in_dict(value, urls)
        elif isinstance(data, list):
            for item in data:
                self._find_urls_in_dict(item, urls)
        elif isinstance(data, str):
            # 检查字符串本身是否为图片 URL
            if data.startswith("http") and any(ext in data.lower() for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
                urls.append(data)

        return urls

    async def download_image(
        self,
        url: str,
        chat_id: str,
        user_id: str,
        timestamp: Optional[int] = None
    ) -> Optional[str]:
        """
        下载图片

        Args:
            url: 图片 URL
            chat_id: 会话 ID
            user_id: 发送者用户 ID
            timestamp: 消息时间戳

        Returns:
            Optional[str]: 保存的文件路径，失败返回 None
        """
        try:
            # 生成文件名
            ts = timestamp or int(datetime.now().timestamp() * 1000)
            dt_str = datetime.fromtimestamp(ts / 1000).strftime("%Y%m%d_%H%M%S")

            # 从 URL 提取文件扩展名
            ext = ".jpg"  # 默认
            if ".png" in url.lower():
                ext = ".png"
            elif ".webp" in url.lower():
                ext = ".webp"
            elif ".gif" in url.lower():
                ext = ".gif"

            # 创建子目录：chat_id/user_id/
            chat_dir = self.save_dir / chat_id / user_id
            chat_dir.mkdir(parents=True, exist_ok=True)

            filename = f"{dt_str}_{ts}{ext}"
            filepath = chat_dir / filename

            # 下载图片
            logger.info(f"正在下载图片: {url}")
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        content = await response.read()
                        with open(filepath, "wb") as f:
                            f.write(content)
                        logger.info(f"图片已保存: {filepath}")
                        return str(filepath)
                    else:
                        logger.warning(f"下载图片失败: HTTP {response.status}")
                        return None

        except Exception as e:
            logger.error(f"下载图片失败 ({url}): {e}")
            return None

    async def handle_image_message(
        self,
        raw_data: Dict[str, Any],
        chat_id: str,
        user_id: str,
        timestamp: Optional[int] = None
    ) -> List[str]:
        """
        处理图片消息（提取 URL 并下载）

        Args:
            raw_data: 消息原始数据
            chat_id: 会话 ID
            user_id: 发送者用户 ID
            timestamp: 消息时间戳

        Returns:
            List[str]: 保存的文件路径列表
        """
        # 提取图片 URL
        urls = self.extract_image_urls(raw_data)

        if not urls:
            logger.debug("消息中未找到图片 URL")
            return []

        # 下载所有图片
        saved_files = []
        for url in urls:
            filepath = await self.download_image(url, chat_id, user_id, timestamp)
            if filepath:
                saved_files.append(filepath)

        if saved_files:
            logger.info(f"成功保存 {len(saved_files)} 张图片")

        return saved_files


# 全局实例
_image_handler: Optional[ImageHandler] = None


def get_image_handler(save_dir: str = "./xianyu_images") -> ImageHandler:
    """
    获取全局图片处理器实例

    Args:
        save_dir: 图片保存目录

    Returns:
        ImageHandler: 图片处理器实例
    """
    global _image_handler
    if _image_handler is None:
        _image_handler = ImageHandler(save_dir=save_dir)
    return _image_handler

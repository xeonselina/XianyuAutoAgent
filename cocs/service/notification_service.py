import httpx
import json
from typing import Dict, Optional
from loguru import logger
from datetime import datetime
import os


class WechatNotificationService:
    """微信通知服务"""
    
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.client = httpx.AsyncClient(timeout=10.0)
    
    async def notify_human_required(self, message_data: Dict) -> bool:
        """通知需要人工介入"""
        try:
            # 构建通知内容
            notification = self._build_notification(message_data)
            
            # 发送微信通知
            success = await self._send_wechat_message(notification)
            
            if success:
                logger.info("微信通知发送成功")
                return True
            else:
                logger.error("微信通知发送失败")
                return False
                
        except Exception as e:
            logger.error(f"发送微信通知异常: {e}")
            return False
    
    def _build_notification(self, message_data: Dict) -> Dict:
        """构建通知内容"""
        sender = message_data.get('sender', '未知客户')
        text = message_data.get('text', '')
        timestamp = message_data.get('timestamp', datetime.now().isoformat())
        confidence_score = message_data.get('confidence_score', 0.0)
        ai_response = message_data.get('ai_response', '')
        
        # 构建markdown格式的消息
        content = f"""## 🔔 咸鱼客服需要人工介入

**客户:** {sender}
**时间:** {timestamp}
**消息内容:** 
> {text}

**AI回复建议:** 
> {ai_response if ai_response else '暂无AI回复'}

**置信度:** {confidence_score:.2f}

**处理建议:** 请及时登录咸鱼客服系统处理此消息"""

        return {
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }
    
    async def _send_wechat_message(self, message: Dict) -> bool:
        """发送微信消息"""
        try:
            response = await self.client.post(
                self.webhook_url,
                json=message,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("errcode") == 0:
                    return True
                else:
                    logger.error(f"微信API返回错误: {result}")
                    return False
            else:
                logger.error(f"微信API请求失败: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"发送微信消息异常: {e}")
            return False
    
    async def send_system_alert(self, alert_type: str, message: str) -> bool:
        """发送系统告警"""
        try:
            content = f"""## ⚠️ 咸鱼客服系统告警

**告警类型:** {alert_type}
**时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**详情:** {message}

请检查系统状态并及时处理。"""

            notification = {
                "msgtype": "markdown",
                "markdown": {
                    "content": content
                }
            }
            
            return await self._send_wechat_message(notification)
            
        except Exception as e:
            logger.error(f"发送系统告警异常: {e}")
            return False
    
    async def send_daily_summary(self, summary_data: Dict) -> bool:
        """发送每日总结"""
        try:
            total_messages = summary_data.get('total_messages', 0)
            ai_handled = summary_data.get('ai_handled', 0)
            human_required = summary_data.get('human_required', 0)
            avg_confidence = summary_data.get('avg_confidence', 0.0)
            
            content = f"""## 📊 咸鱼客服每日总结

**日期:** {datetime.now().strftime('%Y-%m-%d')}

**消息统计:**
- 总消息数: {total_messages}
- AI处理: {ai_handled} ({ai_handled/total_messages*100:.1f}%)
- 人工介入: {human_required} ({human_required/total_messages*100:.1f}%)
- 平均置信度: {avg_confidence:.2f}

系统运行正常，继续监控中..."""

            notification = {
                "msgtype": "markdown",
                "markdown": {
                    "content": content
                }
            }
            
            return await self._send_wechat_message(notification)
            
        except Exception as e:
            logger.error(f"发送每日总结异常: {e}")
            return False
    
    async def close(self):
        """关闭HTTP客户端"""
        await self.client.aclose()


class EmailNotificationService:
    """邮件通知服务（备用）"""
    
    def __init__(self, smtp_server: str, smtp_port: int, username: str, password: str, recipients: list):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.recipients = recipients
    
    async def notify_human_required(self, message_data: Dict) -> bool:
        """发送邮件通知"""
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            # 构建邮件内容
            subject = f"咸鱼客服需要人工介入 - {message_data.get('sender', '未知客户')}"
            
            body = f"""
咸鱼客服系统检测到需要人工介入的消息：

客户：{message_data.get('sender', '未知客户')}
时间：{message_data.get('timestamp', datetime.now().isoformat())}
消息内容：{message_data.get('text', '')}

AI回复建议：{message_data.get('ai_response', '暂无')}
置信度：{message_data.get('confidence_score', 0.0):.2f}

请及时登录咸鱼客服系统处理此消息。
            """
            
            # 创建邮件
            msg = MIMEMultipart()
            msg['From'] = self.username
            msg['To'] = ', '.join(self.recipients)
            msg['Subject'] = subject
            
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            # 发送邮件
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.username, self.password)
            
            for recipient in self.recipients:
                server.send_message(msg, to_addrs=[recipient])
            
            server.quit()
            
            logger.info("邮件通知发送成功")
            return True
            
        except Exception as e:
            logger.error(f"发送邮件通知失败: {e}")
            return False


class NotificationManager:
    """通知管理器"""
    
    def __init__(self):
        self.services = []
        self.enabled = True
    
    def add_service(self, service):
        """添加通知服务"""
        self.services.append(service)
        logger.info(f"添加通知服务: {service.__class__.__name__}")
    
    async def notify_human_required(self, message_data: Dict) -> bool:
        """通知所有服务需要人工介入"""
        if not self.enabled:
            logger.info("通知服务已禁用")
            return True
        
        success_count = 0
        
        for service in self.services:
            try:
                success = await service.notify_human_required(message_data)
                if success:
                    success_count += 1
            except Exception as e:
                logger.error(f"通知服务 {service.__class__.__name__} 发送失败: {e}")
        
        return success_count > 0
    
    async def send_system_alert(self, alert_type: str, message: str) -> bool:
        """发送系统告警到所有支持的服务"""
        if not self.enabled:
            return True
        
        success_count = 0
        
        for service in self.services:
            try:
                if hasattr(service, 'send_system_alert'):
                    success = await service.send_system_alert(alert_type, message)
                    if success:
                        success_count += 1
            except Exception as e:
                logger.error(f"系统告警发送失败 {service.__class__.__name__}: {e}")
        
        return success_count > 0
    
    def enable(self):
        """启用通知"""
        self.enabled = True
        logger.info("通知服务已启用")
    
    def disable(self):
        """禁用通知"""
        self.enabled = False
        logger.info("通知服务已禁用")
    
    async def close(self):
        """关闭所有通知服务"""
        for service in self.services:
            try:
                if hasattr(service, 'close'):
                    await service.close()
            except Exception as e:
                logger.error(f"关闭通知服务失败 {service.__class__.__name__}: {e}")
        
        self.services.clear()
        logger.info("所有通知服务已关闭")
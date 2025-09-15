import asyncio
import json
from typing import Dict, List, Optional
from datetime import datetime
from loguru import logger
from fastapi import FastAPI
from pydantic import BaseModel
import uuid


class Message(BaseModel):
    id: str
    text: str
    sender: str
    timestamp: str
    chat_id: str
    message_type: str = "received"  # received, sent
    processed: bool = False
    ai_response: Optional[str] = None
    confidence_score: Optional[float] = None
    require_human: bool = False


class ChatSession(BaseModel):
    chat_id: str
    contact_name: str
    last_message_time: str
    message_count: int = 0
    active: bool = True


class MessageService:
    def __init__(self):
        self.app = FastAPI()
        self.messages: Dict[str, Message] = {}
        self.chat_sessions: Dict[str, ChatSession] = {}
        self.ai_service = None
        self.notification_service = None
        
        # AI处理锁，确保串行处理
        self.ai_processing_lock = asyncio.Lock()
        
        # 设置路由
        self._setup_routes()
    
    def _setup_routes(self):
        """设置FastAPI路由"""
        
        @self.app.post("/messages")
        async def receive_message(message_data: dict):
            """接收新消息"""
            try:
                message = await self.process_incoming_message(message_data)
                
                if message:
                    # 异步处理消息，但不使用BackgroundTasks以确保串行处理
                    await self._handle_message_async(message)
                    
                    return {"status": "success", "message_id": message.id}
                else:
                    return {"status": "error", "message": "Failed to process message"}
                    
            except Exception as e:
                logger.error(f"接收消息失败: {e}")
                return {"status": "error", "message": str(e)}
        
        @self.app.get("/messages/{chat_id}")
        async def get_chat_messages(chat_id: str, limit: int = 50):
            """获取聊天消息"""
            messages = [
                msg for msg in self.messages.values() 
                if msg.chat_id == chat_id
            ]
            # 按时间排序
            messages.sort(key=lambda x: x.timestamp)
            return messages[-limit:]
        
        @self.app.get("/chats")
        async def get_chat_sessions():
            """获取所有聊天会话"""
            return list(self.chat_sessions.values())
        
        @self.app.post("/messages/{message_id}/response")
        async def send_ai_response(message_id: str, response_data: dict):
            """发送AI回复"""
            try:
                if message_id not in self.messages:
                    return {"status": "error", "message": "Message not found"}
                
                message = self.messages[message_id]
                message.ai_response = response_data.get("response")
                message.confidence_score = response_data.get("confidence_score")
                message.processed = True
                
                # 发送回复到浏览器
                if self.browser_service:
                    success = await self.browser_service.send_message(message.ai_response)
                    if success:
                        return {"status": "success"}
                    else:
                        return {"status": "error", "message": "Failed to send message to browser"}
                else:
                    return {"status": "error", "message": "Browser service not available"}
                    
            except Exception as e:
                logger.error(f"发送AI回复失败: {e}")
                return {"status": "error", "message": str(e)}
    
    async def process_incoming_message(self, message_data: dict) -> Optional[Message]:
        """处理传入的消息"""
        try:
            # 生成消息ID
            message_id = str(uuid.uuid4())
            
            # 生成聊天ID（基于联系人）
            contact_name = message_data.get('sender', 'unknown')
            chat_id = f"chat_{contact_name}_{datetime.now().strftime('%Y%m%d')}"
            
            # 创建消息对象
            message = Message(
                id=message_id,
                text=message_data.get('text', ''),
                sender=contact_name,
                timestamp=message_data.get('timestamp', datetime.now().isoformat()),
                chat_id=chat_id,
                message_type="received"
            )
            
            # 保存消息
            self.messages[message_id] = message
            
            # 更新聊天会话
            await self._update_chat_session(chat_id, contact_name)
            
            logger.info(f"收到新消息: {message.text} (来自: {message.sender})")
            
            return message
            
        except Exception as e:
            logger.error(f"处理传入消息失败: {e}")
            return None
    
    async def _update_chat_session(self, chat_id: str, contact_name: str):
        """更新聊天会话"""
        if chat_id in self.chat_sessions:
            session = self.chat_sessions[chat_id]
            session.message_count += 1
            session.last_message_time = datetime.now().isoformat()
        else:
            session = ChatSession(
                chat_id=chat_id,
                contact_name=contact_name,
                last_message_time=datetime.now().isoformat(),
                message_count=1
            )
            self.chat_sessions[chat_id] = session
    
    async def _handle_message_async(self, message: Message):
        """异步处理消息，确保AI处理串行"""
        try:
            # 如果需要AI处理，使用锁确保串行处理
            if self.ai_service and not message.processed:
                async with self.ai_processing_lock:
                    logger.info(f"开始串行AI处理消息: {message.text}")
                    await self._process_with_ai(message)
                    logger.info(f"AI处理完成: {message.text}")
                
        except Exception as e:
            logger.error(f"异步处理消息失败: {e}")
    
    async def _process_with_ai(self, message: Message):
        """使用AI处理消息"""
        try:
            logger.info(f"开始AI处理消息: {message.text}")
            
            # 获取聊天历史
            chat_history = await self._get_chat_history(message.chat_id, limit=10)
            
            # 调用AI服务
            ai_result = await self.ai_service.process_message(
                message.text,
                chat_history=chat_history,
                sender=message.sender
            )
            
            if ai_result:
                message.ai_response = ai_result.get('response')
                message.confidence_score = ai_result.get('confidence_score', 0.0)
                message.require_human = ai_result.get('require_human', False)
                message.processed = True
                
                # 如果置信度足够高，直接发送回复
                if message.confidence_score >= 0.7 and not message.require_human:
                    if self.browser_service:
                        success = await self.browser_service.send_message(message.ai_response)
                        if success:
                            logger.info(f"AI回复已发送: {message.ai_response}")
                        else:
                            logger.error("发送AI回复失败")
                else:
                    # 置信度不够，通知人工介入
                    if self.notification_service:
                        await self.notification_service.notify_human_required(message)
                        logger.info(f"已通知人工介入处理消息: {message.text}")
            
        except Exception as e:
            logger.error(f"AI处理消息失败: {e}")
            message.processed = False
    
    async def _get_chat_history(self, chat_id: str, limit: int = 10) -> List[Dict]:
        """获取聊天历史"""
        messages = [
            {
                'text': msg.text,
                'sender': msg.sender,
                'timestamp': msg.timestamp,
                'type': msg.message_type
            }
            for msg in self.messages.values()
            if msg.chat_id == chat_id
        ]
        
        # 按时间排序并限制数量
        messages.sort(key=lambda x: x['timestamp'])
        return messages[-limit:]
    
    def set_ai_service(self, ai_service):
        """设置AI服务"""
        self.ai_service = ai_service
        logger.info("AI服务已设置")
    
    def set_browser_service(self, browser_service):
        """设置浏览器服务"""
        self.browser_service = browser_service
        logger.info("浏览器服务已设置")
    
    def set_notification_service(self, notification_service):
        """设置通知服务"""
        self.notification_service = notification_service
        logger.info("通知服务已设置")
    
    async def start_server(self, host: str = "127.0.0.1", port: int = 8000):
        """启动消息服务器"""
        import uvicorn
        
        logger.info(f"启动消息服务器: http://{host}:{port}")
        
        config = uvicorn.Config(
            app=self.app,
            host=host,
            port=port,
            log_level="info"
        )
        
        server = uvicorn.Server(config)
        await server.serve()
    
    async def shutdown(self):
        """关闭服务"""
        logger.info("消息服务正在关闭...")
        # 清理资源
        self.messages.clear()
        self.chat_sessions.clear()

import httpx
import json
from typing import Dict, List, Optional
from loguru import logger
from pydantic import BaseModel
import os
from datetime import datetime


class AIResponse(BaseModel):
    response: str
    confidence_score: float
    require_human: bool = False
    reasoning: Optional[str] = None


class DifyAIService:
    def __init__(self, dify_api_url: str, api_key: str):
        self.dify_api_url = dify_api_url.rstrip('/')
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30.0)
        self.conversation_id = None
        
    async def process_message(self, 
                            message: str, 
                            chat_history: List[Dict] = None, 
                            sender: str = "客户") -> Optional[Dict]:
        """使用Dify处理消息"""
        try:
            logger.info(f"开始处理消息: {message}")
            
            # 构建上下文
            context = self._build_context(message, chat_history, sender)
            
            # 调用Dify API
            dify_response = await self._call_dify_api(context)
            
            if dify_response:
                # 解析响应
                ai_result = self._parse_dify_response(dify_response)
                
                logger.info(f"AI处理完成 - 回复: {ai_result['response'][:50]}... 置信度: {ai_result['confidence_score']}")
                
                return ai_result
            else:
                logger.error("Dify API调用失败")
                return None
                
        except Exception as e:
            logger.error(f"AI处理消息失败: {e}")
            return None
    
    def _build_context(self, message: str, chat_history: List[Dict], sender: str) -> Dict:
        """构建AI处理上下文"""
        context = {
            "query": message,
            "inputs": {
                "sender": sender,
                "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "chat_history": self._format_chat_history(chat_history) if chat_history else ""
            },
            "response_mode": "blocking",
            "user": sender
        }
        
        if self.conversation_id:
            context["conversation_id"] = self.conversation_id
            
        return context
    
    def _format_chat_history(self, chat_history: List[Dict]) -> str:
        """格式化聊天历史"""
        if not chat_history:
            return ""
        
        formatted = []
        for msg in chat_history[-5:]:  # 只取最近5条
            role = "客户" if msg.get('type') == 'received' else "客服"
            formatted.append(f"{role}: {msg.get('text', '')}")
        
        return "\\n".join(formatted)
    
    async def _call_dify_api(self, context: Dict) -> Optional[Dict]:
        """调用Dify API"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            # Dify聊天完成API端点
            url = f"{self.dify_api_url}/v1/chat-messages"
            
            logger.debug(f"调用Dify API: {url}")
            logger.debug(f"请求数据: {json.dumps(context, ensure_ascii=False)}")
            
            response = await self.client.post(
                url,
                json=context,
                headers=headers
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # 保存会话ID
                if result.get("conversation_id"):
                    self.conversation_id = result["conversation_id"]
                
                return result
            else:
                logger.error(f"Dify API调用失败: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"调用Dify API异常: {e}")
            return None
    
    def _parse_dify_response(self, dify_response: Dict) -> Dict:
        """解析Dify响应"""
        try:
            # 获取AI回复
            answer = dify_response.get("answer", "")
            
            # 分析置信度（简单规则）
            confidence_score = self._calculate_confidence_score(answer, dify_response)
            
            # 判断是否需要人工介入
            require_human = self._should_require_human(answer, confidence_score)
            
            return {
                "response": answer,
                "confidence_score": confidence_score,
                "require_human": require_human,
                "reasoning": self._get_reasoning(dify_response)
            }
            
        except Exception as e:
            logger.error(f"解析Dify响应失败: {e}")
            return {
                "response": "抱歉，我现在无法处理您的问题，请稍后再试。",
                "confidence_score": 0.0,
                "require_human": True,
                "reasoning": f"解析错误: {str(e)}"
            }
    
    def _calculate_confidence_score(self, answer: str, dify_response: Dict) -> float:
        """计算置信度分数"""
        try:
            # 基础分数
            base_score = 0.5
            
            # 如果有明确的回答，提高分数
            if answer and len(answer.strip()) > 0:
                base_score += 0.2
            
            # 如果回答长度合适，提高分数
            if 10 <= len(answer) <= 200:
                base_score += 0.1
            
            # 如果没有不确定词汇，提高分数
            uncertain_words = ['可能', '也许', '不确定', '不知道', '不清楚', '抱歉']
            if not any(word in answer for word in uncertain_words):
                base_score += 0.1
            
            # 如果包含具体信息，提高分数
            specific_indicators = ['价格', '规格', '尺寸', '颜色', '品牌', '型号']
            if any(indicator in answer for indicator in specific_indicators):
                base_score += 0.1
            
            # 限制在0-1范围内
            return min(1.0, max(0.0, base_score))
            
        except Exception as e:
            logger.warning(f"计算置信度失败: {e}")
            return 0.5
    
    def _should_require_human(self, answer: str, confidence_score: float) -> bool:
        """判断是否需要人工介入"""
        try:
            # 置信度太低
            if confidence_score < 0.6:
                return True
            
            # 包含敏感关键词
            sensitive_keywords = [
                '退款', '投诉', '差评', '纠纷', '法律', '起诉',
                '质量问题', '假货', '欺诈', '诈骗', '报警'
            ]
            
            if any(keyword in answer for keyword in sensitive_keywords):
                return True
            
            # 明确表示无法处理的回答
            unable_indicators = [
                '无法处理', '不能解决', '联系客服', '人工处理',
                '不在我的能力范围', '需要专人处理'
            ]
            
            if any(indicator in answer for indicator in unable_indicators):
                return True
            
            return False
            
        except Exception as e:
            logger.warning(f"判断人工介入失败: {e}")
            return True
    
    def _get_reasoning(self, dify_response: Dict) -> str:
        """获取推理过程"""
        try:
            # Dify可能返回的推理信息
            metadata = dify_response.get("metadata", {})
            usage = dify_response.get("usage", {})
            
            reasoning_parts = []
            
            if metadata:
                reasoning_parts.append(f"元数据: {json.dumps(metadata, ensure_ascii=False)}")
            
            if usage:
                reasoning_parts.append(f"使用情况: {json.dumps(usage, ensure_ascii=False)}")
            
            return " | ".join(reasoning_parts) if reasoning_parts else ""
            
        except Exception as e:
            logger.warning(f"获取推理过程失败: {e}")
            return ""
    
    async def close(self):
        """关闭HTTP客户端"""
        await self.client.aclose()


class QwenAIService:
    """直接调用阿里云Qwen模型的服务"""
    
    def __init__(self, api_key: str, model_name: str = "qwen-turbo"):
        self.api_key = api_key
        self.model_name = model_name
        self.client = httpx.AsyncClient(timeout=30.0)
        self.base_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
    
    async def process_message(self, 
                            message: str, 
                            chat_history: List[Dict] = None, 
                            sender: str = "客户") -> Optional[Dict]:
        """使用Qwen模型处理消息"""
        try:
            logger.info(f"使用Qwen模型处理消息: {message}")
            
            # 构建消息
            messages = self._build_messages(message, chat_history, sender)
            
            # 调用Qwen API
            qwen_response = await self._call_qwen_api(messages)
            
            if qwen_response:
                ai_result = self._parse_qwen_response(qwen_response)
                logger.info(f"Qwen处理完成 - 回复: {ai_result['response'][:50]}... 置信度: {ai_result['confidence_score']}")
                return ai_result
            else:
                return None
                
        except Exception as e:
            logger.error(f"Qwen处理消息失败: {e}")
            return None
    
    def _build_messages(self, message: str, chat_history: List[Dict], sender: str) -> List[Dict]:
        """构建对话消息"""
        messages = [
            {
                "role": "system",
                "content": """你是一个专业的咸鱼客服AI助手。你的任务是：
1. 友好、专业地回复客户咨询
2. 提供准确的商品信息和服务支持
3. 处理订单、物流、售后等问题
4. 如果遇到复杂问题或投诉，建议联系人工客服

请用简洁、友好的语气回复，控制在100字以内。"""
            }
        ]
        
        # 添加聊天历史
        if chat_history:
            for msg in chat_history[-3:]:  # 只取最近3条
                role = "user" if msg.get('type') == 'received' else "assistant"
                messages.append({
                    "role": role,
                    "content": msg.get('text', '')
                })
        
        # 添加当前消息
        messages.append({
            "role": "user",
            "content": message
        })
        
        return messages
    
    async def _call_qwen_api(self, messages: List[Dict]) -> Optional[Dict]:
        """调用Qwen API"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": self.model_name,
                "input": {
                    "messages": messages
                },
                "parameters": {
                    "temperature": 0.7,
                    "max_tokens": 200,
                    "top_p": 0.9
                }
            }
            
            response = await self.client.post(
                self.base_url,
                json=data,
                headers=headers
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Qwen API调用失败: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"调用Qwen API异常: {e}")
            return None
    
    def _parse_qwen_response(self, qwen_response: Dict) -> Dict:
        """解析Qwen响应"""
        try:
            output = qwen_response.get("output", {})
            text = output.get("text", "")
            
            # 简单的置信度计算
            confidence_score = 0.8 if text and len(text.strip()) > 5 else 0.3
            
            # 判断是否需要人工介入
            require_human = self._should_require_human(text, confidence_score)
            
            return {
                "response": text,
                "confidence_score": confidence_score,
                "require_human": require_human,
                "reasoning": f"模型: {self.model_name}"
            }
            
        except Exception as e:
            logger.error(f"解析Qwen响应失败: {e}")
            return {
                "response": "抱歉，我现在无法处理您的问题，请稍后再试。",
                "confidence_score": 0.0,
                "require_human": True
            }
    
    def _should_require_human(self, answer: str, confidence_score: float) -> bool:
        """判断是否需要人工介入"""
        if confidence_score < 0.6:
            return True
        
        sensitive_keywords = ['投诉', '退款', '纠纷', '质量问题']
        return any(keyword in answer for keyword in sensitive_keywords)
    
    async def close(self):
        """关闭HTTP客户端"""
        await self.client.aclose()
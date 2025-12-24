"""
Ask human agent tool implementation.
T057 - ask_human_agent tool for Human-in-the-Loop.
"""

import uuid
from typing import Dict, Any, List, Optional
from ai_kefu.config.constants import HumanRequestType, Urgency
from ai_kefu.utils.logging import logger


def ask_human_agent(
    question: str,
    question_type: str,
    context: Optional[Dict[str, Any]] = None,
    options: Optional[List[Dict[str, str]]] = None,
    urgency: str = "medium"
) -> Dict[str, Any]:
    """
    Request human agent assistance (Human-in-the-Loop).
    
    This tool creates a request for human assistance and pauses agent execution.
    The agent will wait for human response before continuing.
    
    Args:
        question: Specific question to ask human agent
        question_type: Type of question (information_query, decision_required, etc.)
        context: Context information for human agent
        options: List of options if this is a multiple choice question
        urgency: Urgency level (low, medium, high)
        
    Returns:
        Dict with request status:
        {
            "success": bool,
            "status": "pending",
            "request_id": str,
            "message": str,
            "urgency": str,
            "options": list (if provided)
        }
    """
    try:
        # Generate unique request ID
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        
        logger.info(f"Creating human assistance request: {request_id}")
        logger.info(f"Question type: {question_type}, Urgency: {urgency}")
        
        # Build result
        result = {
            "success": True,
            "status": "pending",
            "request_id": request_id,
            "question": question,
            "question_type": question_type,
            "context": context or {},
            "urgency": urgency,
            "message": "已创建人工协助请求，等待回复"
        }
        
        if options:
            result["options"] = options
        
        # Note: In actual implementation, this would:
        # 1. Create HumanRequest object
        # 2. Update session status to waiting_for_human
        # 3. Store pending request in session
        # 4. Pause agent execution
        
        return result
        
    except Exception as e:
        error_msg = f"Failed to create human assistance request: {str(e)}"
        logger.error(error_msg)
        return {
            "success": False,
            "error": error_msg
        }


def get_tool_definition() -> Dict[str, Any]:
    """
    Get ask_human_agent tool definition for Qwen Function Calling.
    
    Returns:
        Tool definition dict
    """
    return {
        "name": "ask_human_agent",
        "description": """向人工客服请求帮助 (Human-in-the-Loop 模式)。

**使用场景**:
1. 需要访问外部系统数据（订单、库存、物流等）
2. 需要人工决策（退款审批、特殊请求等）
3. 知识库无相关信息，需要补充
4. 高风险操作需要确认

**重要**: 这不是转接人工，而是请求协助。你仍然负责回答用户。
调用后应告知用户: "正在为您核实信息，请稍候..."

**示例场景**:
- 查询订单信息: question_type="information_query"
- 退款审批决策: question_type="decision_required" (提供 options)
- 风险操作确认: question_type="risk_confirmation"
- 知识缺失补充: question_type="knowledge_gap"
""",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "向人工提出的具体问题或请求（清晰描述需要什么帮助）"
                },
                "question_type": {
                    "type": "string",
                    "enum": [
                        "information_query",
                        "decision_required",
                        "risk_confirmation",
                        "knowledge_gap"
                    ],
                    "description": "问题类型"
                },
                "context": {
                    "type": "object",
                    "description": "提供给人工的上下文信息（如订单号、用户问题等）",
                    "properties": {
                        "user_question": {
                            "type": "string",
                            "description": "用户的原始问题"
                        },
                        "relevant_info": {
                            "type": "string",
                            "description": "已知的相关信息"
                        }
                    }
                },
                "options": {
                    "type": "array",
                    "description": "如果是选择题，提供选项列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "选项ID"},
                            "label": {"type": "string", "description": "选项标签"},
                            "description": {"type": "string", "description": "选项说明"}
                        },
                        "required": ["id", "label"]
                    }
                },
                "urgency": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "default": "medium",
                    "description": "紧急程度"
                }
            },
            "required": ["question", "question_type"]
        }
    }

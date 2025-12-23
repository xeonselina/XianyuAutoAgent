"""
Intent recognition service.
T038 - Extract user intent from messages.
"""

from enum import Enum
from ai_kefu.llm.qwen_client import call_qwen
from ai_kefu.prompts.workflow_prompts import INTENT_EXTRACTION_PROMPT
from ai_kefu.utils.logging import logger


class IntentType(str, Enum):
    """User intent types."""
    CONSULTATION = "consultation"  # 咨询
    COMPLAINT = "complaint"  # 投诉
    REFUND = "refund"  # 退款
    LOGISTICS = "logistics"  # 物流
    AFTER_SALES = "after_sales"  # 售后
    OTHER = "other"  # 其他


def extract_intent(user_message: str) -> IntentType:
    """
    Extract user intent from message.
    
    Args:
        user_message: User's message
        
    Returns:
        IntentType enum value
    """
    try:
        logger.debug(f"Extracting intent from: {user_message}")
        
        # Build prompt
        prompt = INTENT_EXTRACTION_PROMPT.format(user_message=user_message)
        
        # Call Qwen
        response = call_qwen(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0.1  # Low temperature for classification
        )
        
        # Extract intent from response
        intent_str = response["choices"][0]["message"]["content"].strip().lower()
        
        # Map to enum
        intent_mapping = {
            "consultation": IntentType.CONSULTATION,
            "complaint": IntentType.COMPLAINT,
            "refund": IntentType.REFUND,
            "logistics": IntentType.LOGISTICS,
            "after_sales": IntentType.AFTER_SALES,
            "other": IntentType.OTHER
        }
        
        intent = intent_mapping.get(intent_str, IntentType.OTHER)
        logger.info(f"Extracted intent: {intent.value}")
        
        return intent
        
    except Exception as e:
        logger.error(f"Intent extraction failed: {e}")
        return IntentType.OTHER

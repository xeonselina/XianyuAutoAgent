"""
Sentiment analysis service.
T039 - Analyze user sentiment from messages.
"""

from enum import Enum
from ai_kefu.llm.qwen_client import call_qwen
from ai_kefu.prompts.workflow_prompts import SENTIMENT_ANALYSIS_PROMPT
from ai_kefu.utils.logging import logger


class SentimentType(str, Enum):
    """User sentiment types."""
    POSITIVE = "positive"  # 积极
    NEUTRAL = "neutral"  # 中性
    NEGATIVE = "negative"  # 消极


def analyze_sentiment(user_message: str) -> SentimentType:
    """
    Analyze sentiment from user message.
    
    Args:
        user_message: User's message
        
    Returns:
        SentimentType enum value
    """
    try:
        logger.debug(f"Analyzing sentiment from: {user_message}")
        
        # Build prompt
        prompt = SENTIMENT_ANALYSIS_PROMPT.format(user_message=user_message)
        
        # Call Qwen
        response = call_qwen(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0.1  # Low temperature for classification
        )
        
        # Extract sentiment from response
        sentiment_str = response["choices"][0]["message"]["content"].strip().lower()
        
        # Map to enum
        sentiment_mapping = {
            "positive": SentimentType.POSITIVE,
            "neutral": SentimentType.NEUTRAL,
            "negative": SentimentType.NEGATIVE
        }
        
        sentiment = sentiment_mapping.get(sentiment_str, SentimentType.NEUTRAL)
        logger.info(f"Analyzed sentiment: {sentiment.value}")
        
        return sentiment
        
    except Exception as e:
        logger.error(f"Sentiment analysis failed: {e}")
        return SentimentType.NEUTRAL

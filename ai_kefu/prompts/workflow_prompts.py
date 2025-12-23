"""
Workflow-specific prompts and templates.
"""

# Prompt for extracting user intent
INTENT_EXTRACTION_PROMPT = """分析以下用户消息，提取用户意图。

用户消息：{user_message}

请识别以下意图类别之一：
- 咨询（consultation）：询问产品信息、政策、流程等
- 投诉（complaint）：对产品或服务不满
- 退款（refund）：申请退款退货
- 物流（logistics）：查询订单发货、物流信息
- 售后（after_sales）：产品使用问题、维修等
- 其他（other）：无法归类的问题

只返回意图类别的英文代码，不要解释。
"""

# Prompt for sentiment analysis
SENTIMENT_ANALYSIS_PROMPT = """分析以下用户消息的情绪倾向。

用户消息：{user_message}

请识别情绪：
- positive（积极）：满意、开心、感谢等
- neutral（中性）：平静的询问、陈述等
- negative（消极）：不满、愤怒、失望等

只返回情绪类别的英文代码，不要解释。
"""

# Prompt for summarizing conversations
CONVERSATION_SUMMARY_PROMPT = """请总结以下客服对话的核心内容。

对话历史：
{conversation_history}

要求：
1. 简洁概括用户的主要问题
2. 说明是否已解决
3. 如有未解决的问题，简要说明
4. 不超过 100 字

总结：
"""

# Template for human agent requests
HUMAN_AGENT_REQUEST_TEMPLATE = """## 人工协助请求

**用户问题**：{user_question}

**需要协助的内容**：{assistance_needed}

**上下文信息**：
{context}

**紧急程度**：{urgency}

请提供相关信息或决策建议，谢谢！
"""

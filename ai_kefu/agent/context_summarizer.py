"""
Context summarizer for conversation history.

When conversation messages grow too long, summarize older messages into a
compact context summary so the LLM can still understand the conversation
history without exceeding the context window.
"""

import json
from typing import List, Dict, Any, Optional
from ai_kefu.llm.qwen_client import call_qwen_fast
from ai_kefu.models.session import Session, Message
from ai_kefu.config.constants import MessageRole
from ai_kefu.config.settings import settings
from ai_kefu.utils.logging import logger


# The prompt used to ask the LLM to summarize conversation history
CONTEXT_SUMMARY_PROMPT = """你是一个对话摘要助手。请将以下客服对话历史压缩成一段简洁的上下文摘要。

要求：
1. 保留关键信息：用户的核心需求、已确认的订单/租赁信息、价格、日期等
2. 保留对话状态：当前进展到哪一步、还有哪些待确认的事项
3. 保留用户偏好和情绪倾向
4. 去掉冗余的寒暄、重复的信息
5. 使用第三人称描述（"用户"、"客服"）
6. **重要**：如果之前的摘要中包含【老客户】或【新客户】标记，必须在新摘要开头保留该标记
7. 如果对话中出现"我已付款，等待你发货"等付款记录，在摘要开头标注【老客户】
8. 控制在 300 字以内

对话历史：
{conversation_history}

{previous_summary_section}

请输出压缩后的上下文摘要："""


def estimate_message_tokens(messages: List[Message]) -> int:
    """
    Rough estimation of token count for a list of messages.
    Chinese characters ≈ 1.5 tokens each, English words ≈ 1 token.
    This is a rough heuristic, not exact.
    
    Args:
        messages: List of Message objects
        
    Returns:
        Estimated token count
    """
    total_chars = 0
    for msg in messages:
        total_chars += len(msg.content or "")
        if msg.tool_calls:
            for tc in msg.tool_calls:
                total_chars += len(json.dumps(tc.args, ensure_ascii=False))
                if tc.result:
                    total_chars += len(json.dumps(tc.result, ensure_ascii=False, default=str))
    
    # Rough estimate: ~1.5 tokens per Chinese char, ~0.75 tokens per English char
    # Use a middle ground of ~1.2 tokens per char
    return int(total_chars * 1.2)


def should_summarize(session: Session, max_message_tokens: int = 4000) -> bool:
    """
    Determine if the session's message history should be summarized.
    
    Args:
        session: Current session
        max_message_tokens: Token threshold above which summarization is triggered
        
    Returns:
        True if summarization is needed
    """
    if len(session.messages) < 6:
        # Too few messages, no need to summarize
        return False
    
    estimated_tokens = estimate_message_tokens(session.messages)
    logger.debug(
        f"Session {session.session_id}: {len(session.messages)} messages, "
        f"~{estimated_tokens} estimated tokens (threshold: {max_message_tokens})"
    )
    return estimated_tokens > max_message_tokens


def summarize_context(
    session: Session,
    keep_recent_count: int = 4,
    max_summary_tokens: int = 500
) -> Optional[str]:
    """
    Summarize older conversation messages into a compact context summary.
    
    Strategy:
    - Keep the most recent `keep_recent_count` messages intact (they're 
      needed for immediate context)
    - Summarize all older messages + any existing summary into a new summary
    
    Args:
        session: Current session with messages
        keep_recent_count: Number of recent messages to keep verbatim
        max_summary_tokens: Max tokens for the summary output
        
    Returns:
        Summary string, or None if summarization failed
    """
    messages = session.messages
    existing_summary = session.context.get("context_summary", "")
    
    if len(messages) <= keep_recent_count:
        logger.debug("Not enough messages to summarize, skipping")
        return existing_summary or None
    
    # Split messages: older ones to summarize, recent ones to keep
    messages_to_summarize = messages[:-keep_recent_count]
    
    # Build conversation text from messages to summarize
    conversation_lines = []
    for msg in messages_to_summarize:
        if msg.role == MessageRole.USER:
            conversation_lines.append(f"用户: {msg.content}")
        elif msg.role == MessageRole.ASSISTANT:
            if msg.content:
                conversation_lines.append(f"客服: {msg.content}")
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    conversation_lines.append(f"  [调用工具 {tc.name}({json.dumps(tc.args, ensure_ascii=False)})]")
        elif msg.role == MessageRole.TOOL:
            # Truncate long tool results
            content = msg.content
            if len(content) > 200:
                content = content[:200] + "..."
            conversation_lines.append(f"  [工具结果: {content}]")
    
    conversation_history = "\n".join(conversation_lines)
    
    # 检测是否老客户：当前消息或已有摘要中是否有付款记录
    is_returning = session.context.get("is_returning_customer", False)
    if not is_returning:
        # 在当前轮消息中检测付款标记
        for msg in messages_to_summarize:
            if msg.role == MessageRole.USER and "我已付款，等待你发货" in (msg.content or ""):
                is_returning = True
                session.context["is_returning_customer"] = True
                break
    if not is_returning and "【老客户】" in existing_summary:
        is_returning = True
        session.context["is_returning_customer"] = True
    
    # Include previous summary if exists
    previous_summary_section = ""
    if existing_summary:
        previous_summary_section = f"之前的对话摘要（请整合到新摘要中）：\n{existing_summary}"
    
    # Build the summarization prompt
    prompt = CONTEXT_SUMMARY_PROMPT.format(
        conversation_history=conversation_history,
        previous_summary_section=previous_summary_section
    )
    
    try:
        logger.info(
            f"Summarizing context for session {session.session_id}: "
            f"{len(messages_to_summarize)} messages to summarize, "
            f"keeping {keep_recent_count} recent messages"
        )
        
        response = call_qwen_fast(
            messages=[
                {"role": "system", "content": "你是一个专业的对话摘要助手。"},
                {"role": "user", "content": prompt}
            ],
            tools=None,
            max_tokens=max_summary_tokens,
            temperature=0.3,  # Low temperature for more deterministic summaries
            model=settings.model_name_light,  # 摘要任务，使用 flash 模型降低成本
        )
        
        summary = response["choices"][0]["message"].get("content", "")
        
        if summary:
            summary = summary.strip()
            # 兜底保护：确保老客户标记不被 LLM 遗漏
            if is_returning and "【老客户】" not in summary:
                summary = "【老客户】该用户之前有过付款记录。\n\n" + summary
            logger.info(
                f"Context summary generated for session {session.session_id}: "
                f"{len(summary)} chars, returning_customer={is_returning}"
            )
            return summary
        else:
            logger.warning("Empty summary returned from LLM")
            return existing_summary or None
            
    except Exception as e:
        logger.error(f"Failed to generate context summary: {e}", exc_info=True)
        # Return existing summary as fallback
        return existing_summary or None


def _find_safe_trim_index(messages: list, keep_recent_count: int) -> int:
    """
    Find a safe index to split messages so that no assistant+tool pair is broken.

    The naive approach ``messages[-keep_recent_count:]`` may land in the middle of
    an assistant→tool sequence, leaving "orphan" tool messages whose
    ``tool_call_id`` has no matching assistant message.  This helper adjusts the
    split point **backwards** (i.e. keeps more messages) until the first kept
    message is NOT an orphan tool message.

    Returns:
        The index into *messages* from which to keep (inclusive).
        Everything before this index can be summarised / discarded.
    """
    if len(messages) <= keep_recent_count:
        return 0

    candidate = len(messages) - keep_recent_count

    # Walk backwards: if messages[candidate] is a tool message whose matching
    # assistant message would be discarded, include the assistant too.
    while candidate > 0:
        msg = messages[candidate]
        if msg.role != MessageRole.TOOL:
            break
        # It's a tool message – its assistant must be *before* candidate.
        # Check whether any kept assistant message already contains the id.
        tool_call_id = getattr(msg, "tool_call_id", None)
        if tool_call_id is None:
            break
        # Search kept slice for a matching assistant
        found = False
        for m in messages[candidate:]:
            if m.role == MessageRole.ASSISTANT and m.tool_calls:
                if any(tc.id == tool_call_id for tc in m.tool_calls):
                    found = True
                    break
        if found:
            break
        # Not found – include one more message (the preceding assistant)
        candidate -= 1

    return candidate


def apply_summary_to_session(session: Session, summary: str, keep_recent_count: int = 4):
    """
    Apply the summary to session: store summary in context and trim old messages.
    
    This modifies the session in-place:
    - Stores the summary in session.context["context_summary"]
    - Removes summarized messages, keeping only recent ones
    - Ensures assistant+tool message pairs are never split apart
    
    Args:
        session: Session to modify
        summary: The generated summary text
        keep_recent_count: Number of recent messages to keep
    """
    if not summary:
        return
    
    # Store summary
    session.context["context_summary"] = summary
    
    # Keep only recent messages, but never break assistant+tool pairs
    if len(session.messages) > keep_recent_count:
        trim_idx = _find_safe_trim_index(session.messages, keep_recent_count)
        removed_count = trim_idx
        session.messages = session.messages[trim_idx:]
        logger.info(
            f"Trimmed {removed_count} old messages from session {session.session_id}, "
            f"kept {len(session.messages)} recent messages"
        )

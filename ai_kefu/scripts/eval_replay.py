#!/usr/bin/env python3
"""
Eval Replay - 批量回放评估工具

从 conversations 表中提取真实的用户对话，用当前 Agent 系统重新生成回复，
将结果写入 eval_runs 表。用于新 prompt / 新模型的效果测试。

过滤规则 (固化在代码中，无需手动指定):
    - 输入消息: message_type='user' 且 user_id 不是卖家 (只取真正的买家消息)
    - human_reply: (user_id='2200687521877' OR message_type='seller') AND NOT LIKE '【调试】%'
      即真正的人类客服回复（排除 AI 调试回复和 Error 消息）

用法:
    # 回放最近 50 条满足过滤条件的对话 (串行)
    python -m ai_kefu.scripts.eval_replay

    # 并行回放 (5 线程并发, 推荐值 3-8)
    python -m ai_kefu.scripts.eval_replay --limit 100 -j 5

    # 指定回放数量和标签
    python -m ai_kefu.scripts.eval_replay --limit 100 --tag "qwen-plus-v2-prompt-v3"

    # 只回放指定 chat_id 的对话
    python -m ai_kefu.scripts.eval_replay --chat-id "xxx"

    # 指定模型 (覆盖 .env 中的 model_name)
    python -m ai_kefu.scripts.eval_replay --model "qwen-max" --tag "qwen-max-test" -j 5
"""

import argparse
import json
import sys
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Dict, Any, Optional

import pymysql
from pymysql.cursors import DictCursor
from loguru import logger

# ------------------------------------------------------------------
# 在 import agent 组件之前先配置 logger
# ------------------------------------------------------------------
logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<7} | {message}")


def get_db_connection(settings) -> pymysql.Connection:
    """创建数据库连接。"""
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset='utf8mb4',
        cursorclass=DictCursor,
        autocommit=False
    )


def ensure_eval_tables(conn: pymysql.Connection):
    """确保评估相关表存在。"""

    create_eval_runs_sql = """
        CREATE TABLE IF NOT EXISTS eval_runs (
            id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',

            run_id VARCHAR(255) NOT NULL COMMENT '本次评估运行的批次 ID',
            tag VARCHAR(255) DEFAULT '' COMMENT '标签 (如 prompt 版本、模型名)',

            -- 原始对话信息
            source_conversation_id BIGINT NOT NULL COMMENT 'conversations 表的 id',
            chat_id VARCHAR(255) NOT NULL COMMENT '原始 chat_id',
            user_message TEXT NOT NULL COMMENT '用户原始消息',
            human_reply TEXT COMMENT '人类客服的回复 (非调试、非Error的卖家消息)',

            -- 上下文
            context_messages JSON COMMENT '该条消息之前的对话上下文 (JSON array)',

            -- AI 回放结果
            ai_reply TEXT COMMENT 'Agent 回放生成的回复',
            ai_session_id VARCHAR(255) COMMENT 'Agent 回放使用的 session_id',
            ai_turn_count INT COMMENT 'Agent 回放使用的轮次数',
            ai_tool_calls JSON COMMENT 'Agent 回放触发的工具调用 (JSON array)',
            ai_duration_ms INT COMMENT 'Agent 回放耗时 (毫秒)',
            ai_model VARCHAR(255) COMMENT '使用的模型名称',

            -- 状态
            status ENUM('pending', 'success', 'error', 'skipped') DEFAULT 'pending' COMMENT '回放状态',
            error_message TEXT COMMENT '错误信息',

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

            INDEX idx_run_id (run_id),
            INDEX idx_chat_id (chat_id),
            INDEX idx_tag (tag),
            INDEX idx_status (status),
            INDEX idx_source_id (source_conversation_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        COMMENT='Prompt / 模型 A/B 测试回放评估结果'
    """

    with conn.cursor() as cursor:
        cursor.execute(create_eval_runs_sql)
        conn.commit()
    logger.info("✅ eval_runs 表已就绪")


def fetch_eval_candidates(
    conn: pymysql.Connection,
    limit: int = 50,
    chat_id: Optional[str] = None,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    从 conversations 表中提取待评估的 (买家消息, 人类客服回复) 配对。

    过滤规则 (固化在代码中):
    - 输入消息: message_type='user' 且 user_id 不是卖家本人 (只取真正的买家消息)
    - human_reply: 同 chat_id 中紧跟着的人类客服回复
      定义: (user_id='2200687521877' OR message_type='seller') AND NOT LIKE '【调试】%'
      同时排除 Agent API Error / Unexpected Error
    """
    # 核心过滤: 只取买家消息（排除卖家本人发的消息）
    filter_condition = "(c.message_type = 'user' AND c.user_id != '2200687521877')"

    conditions = [filter_condition]
    params: list = []

    if chat_id:
        conditions.append("c.chat_id = %s")
        params.append(chat_id)

    where = " AND ".join(conditions)

    # 取消息，并 join 同 chat_id 中紧跟着的 seller 回复
    sql = f"""
        SELECT
            c.id AS source_conversation_id,
            c.chat_id,
            c.user_id,
            c.seller_id,
            c.item_id,
            c.message_type,
            c.message_content AS user_message,
            c.created_at AS user_msg_time,
            (
                SELECT s.message_content
                FROM conversations s
                WHERE s.chat_id = c.chat_id
                  AND (s.user_id = '2200687521877' OR s.message_type = 'seller')
                  AND s.message_content NOT LIKE '【调试】%%'
                  AND s.message_content NOT LIKE '%%Agent API Error%%'
                  AND s.message_content NOT LIKE '%%Unexpected Error%%'
                  AND s.created_at > c.created_at
                ORDER BY s.created_at ASC
                LIMIT 1
            ) AS human_reply
        FROM conversations c
        WHERE {where}
        HAVING human_reply IS NOT NULL
        ORDER BY c.created_at DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        rows = list(cursor.fetchall())

    logger.info(f"找到 {len(rows)} 条待评估候选 (limit={limit}, offset={offset})")
    return rows


def fetch_context_messages(
    conn: pymysql.Connection,
    chat_id: str,
    before_time: datetime,
    context_limit: int = 20
) -> List[Dict[str, str]]:
    """获取某条消息之前的对话上下文。"""
    sql = """
        SELECT message_type, message_content, agent_response, created_at
        FROM conversations
        WHERE chat_id = %s AND created_at < %s
        ORDER BY created_at DESC
        LIMIT %s
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, (chat_id, before_time, context_limit))
        rows = list(cursor.fetchall())

    # 反转为时间正序
    rows.reverse()

    context = []
    for row in rows:
        role = "user" if row["message_type"] == "user" else "seller"
        context.append({
            "role": role,
            "content": row["message_content"],
            "time": str(row["created_at"])
        })
    return context


def replay_single(
    candidate: Dict[str, Any],
    context_messages: List[Dict[str, str]],
    settings,
    model_override: Optional[str] = None
) -> Dict[str, Any]:
    """
    对单条用户消息执行 Agent 回放。

    Returns:
        包含 ai_reply, ai_session_id, ai_turn_count, ai_tool_calls, ai_duration_ms, status, error_message 的 dict
    """
    from ai_kefu.storage.session_store import SessionStore
    from ai_kefu.xianyu_interceptor.conversation_store import ConversationStore
    from ai_kefu.agent.executor import AgentExecutor

    result = {
        "ai_reply": None,
        "ai_session_id": None,
        "ai_turn_count": None,
        "ai_tool_calls": None,
        "ai_duration_ms": None,
        "ai_model": model_override or settings.model_name,
        "status": "pending",
        "error_message": None,
    }

    # 使用指定模型或默认模型（不修改共享的 settings 对象，保证线程安全）
    effective_model = model_override or settings.model_name

    try:
        session_store = SessionStore(
            redis_url=settings.redis_url,
            ttl=300  # 短 TTL，评估完就过期
        )
        conversation_store = ConversationStore(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_database,
        )

        executor = AgentExecutor(
            session_store=session_store,
            conversation_store=conversation_store
        )

        # 构建上下文 — 把历史对话摘要注入到 context
        context_summary = ""
        if context_messages:
            lines = []
            for cm in context_messages[-15:]:  # 最多取 15 条
                role_label = "用户" if cm["role"] == "user" else "客服"
                lines.append(f"{role_label}: {cm['content']}")
            context_summary = "\n".join(lines)

        # 生成独立 session_id，避免污染正式数据
        eval_session_id = f"eval_{uuid.uuid4().hex[:12]}"

        context = {}
        if candidate.get("chat_id"):
            context["conversation_id"] = candidate["chat_id"]

        # 预先在 Redis 中创建 session，避免 _get_or_create_session 走慢路径
        # （慢路径会查 MySQL + 调 LLM 做摘要，耗时数秒到数十秒）
        from ai_kefu.models.session import Session
        from ai_kefu.config.constants import SessionStatus
        pre_context = {}
        if context_summary:
            pre_context["context_summary"] = f"以下是与该用户之前的对话记录：\n{context_summary}"
        else:
            # 设置占位符，防止 executor 的 _get_or_create_session 再次
            # 走 _load_history_as_context 慢路径（查 MySQL + 调 LLM 摘要）
            pre_context["context_summary"] = "(无历史对话)"
        pre_session = Session(
            session_id=eval_session_id,
            user_id=candidate.get("user_id"),
            status=SessionStatus.ACTIVE,
            context=pre_context
        )
        session_store.set(pre_session)

        start_ms = time.time()
        agent_result = executor.run(
            query=candidate["user_message"],
            session_id=eval_session_id,
            user_id=candidate.get("user_id"),
            context=context
        )
        duration_ms = int((time.time() - start_ms) * 1000)

        metadata = agent_result.get("metadata", {}) if isinstance(agent_result, dict) else {}
        confidence_percent = metadata.get("confidence_percent")
        response_suppressed = bool(metadata.get("response_suppressed"))
        has_error = bool(agent_result.get("error"))

        if response_suppressed:
            # 置信度门控抑制 — 正常行为，不是 error
            result["ai_reply"] = "confidence 抑制"
            result["status"] = "success"
            result["error_message"] = None
        elif has_error:
            # 有明确的 error 信息（如 API 超时、异常等）
            result["ai_reply"] = agent_result.get("response") or ""
            result["status"] = "error"
            result["error_message"] = agent_result.get("error")
        else:
            # 正常情况: 有回复 or 无回复但无 error（如 LLM 返回空 content）
            result["ai_reply"] = agent_result.get("response") or ""
            result["status"] = "success"
            result["error_message"] = None

        result["ai_session_id"] = agent_result.get("session_id")
        result["ai_turn_count"] = agent_result.get("turn_counter")
        result["ai_duration_ms"] = duration_ms
        result["ai_model"] = effective_model

        # 从 agent_turns 表获取 tool_calls 信息
        try:
            turns = conversation_store.get_turns_by_session(eval_session_id)
            all_tool_calls = []
            for t in turns:
                if t.get("tool_calls"):
                    tc_list = t["tool_calls"] if isinstance(t["tool_calls"], list) else json.loads(t["tool_calls"])
                    for tc in tc_list:
                        all_tool_calls.append({
                            "name": tc.get("name") or tc.get("function", {}).get("name"),
                            "args": tc.get("args") or tc.get("function", {}).get("arguments"),
                        })
            if all_tool_calls:
                result["ai_tool_calls"] = all_tool_calls
        except Exception as e:
            logger.warning(f"获取 tool_calls 失败 (非致命): {e}")

    except Exception as e:
        result["status"] = "error"
        result["error_message"] = str(e)
        logger.error(f"回放失败: {e}", exc_info=True)

    return result


def save_eval_result(
    conn: pymysql.Connection,
    run_id: str,
    tag: str,
    candidate: Dict[str, Any],
    context_messages: List[Dict[str, str]],
    replay_result: Dict[str, Any]
):
    """将评估结果写入 eval_runs 表。"""
    sql = """
        INSERT INTO eval_runs (
            run_id, tag,
            source_conversation_id, chat_id, user_message, human_reply,
            context_messages,
            ai_reply, ai_session_id, ai_turn_count, ai_tool_calls, ai_duration_ms, ai_model,
            status, error_message
        ) VALUES (
            %s, %s,
            %s, %s, %s, %s,
            %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s
        )
    """
    values = (
        run_id,
        tag,
        candidate["source_conversation_id"],
        candidate["chat_id"],
        candidate["user_message"],
        candidate.get("human_reply"),
        json.dumps(context_messages, ensure_ascii=False) if context_messages else None,
        replay_result.get("ai_reply"),
        replay_result.get("ai_session_id"),
        replay_result.get("ai_turn_count"),
        json.dumps(replay_result.get("ai_tool_calls"), ensure_ascii=False) if replay_result.get("ai_tool_calls") else None,
        replay_result.get("ai_duration_ms"),
        replay_result.get("ai_model"),
        replay_result.get("status", "error"),
        replay_result.get("error_message"),
    )

    with conn.cursor() as cursor:
        cursor.execute(sql, values)
        conn.commit()


def _replay_worker(
    index: int,
    total: int,
    candidate: Dict[str, Any],
    conn_factory,
    settings,
    run_id: str,
    tag: str,
    model_override: Optional[str],
    context_limit: int,
    counters: Dict[str, Any],
) -> Dict[str, Any]:
    """
    单条回放的 worker 函数，在线程池中执行。

    每个 worker 使用独立的 DB 连接，保证线程安全。
    """
    thread_conn = None
    try:
        logger.info(f"[{index}/{total}] 开始回放 chat_id={candidate['chat_id']}")
        logger.info(f"  用户消息: {candidate['user_message'][:80]}")
        logger.info(f"  人类回复: {(candidate.get('human_reply') or 'N/A')[:80]}")

        # 每个线程独立的 DB 连接
        thread_conn = conn_factory()

        # 获取上下文
        context_msgs = fetch_context_messages(
            thread_conn,
            chat_id=candidate["chat_id"],
            before_time=candidate["user_msg_time"],
            context_limit=context_limit
        )

        # 执行回放
        replay_result = replay_single(
            candidate=candidate,
            context_messages=context_msgs,
            settings=settings,
            model_override=model_override
        )

        logger.info(f"[{index}/{total}] AI 回复: {(replay_result.get('ai_reply') or 'N/A')[:80]}")
        logger.info(f"[{index}/{total}] 状态: {replay_result['status']} | 耗时: {replay_result.get('ai_duration_ms', 0)}ms")

        # 保存结果（每个线程用自己的连接写入）
        save_eval_result(thread_conn, run_id, tag, candidate, context_msgs, replay_result)

        # 线程安全的计数
        with counters["lock"]:
            if replay_result["status"] == "success":
                counters["success"] += 1
            else:
                counters["error"] += 1
            done = counters["success"] + counters["error"]
            logger.info(f"  进度: {done}/{total} (成功={counters['success']}, 失败={counters['error']})")

        return replay_result

    except Exception as e:
        logger.error(f"[{index}/{total}] worker 异常: {e}", exc_info=True)
        with counters["lock"]:
            counters["error"] += 1
        return {"status": "error", "error_message": str(e)}
    finally:
        if thread_conn:
            try:
                thread_conn.close()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="Eval Replay - 批量回放评估工具")
    parser.add_argument("--limit", type=int, default=50, help="回放数量 (默认 50)")
    parser.add_argument("--offset", type=int, default=0, help="跳过前 N 条")
    parser.add_argument("--chat-id", type=str, default=None, help="只回放指定 chat_id")
    parser.add_argument("--tag", type=str, default="", help="标签 (如 prompt 版本)")
    parser.add_argument("--model", type=str, default=None, help="覆盖模型名 (如 qwen-max)")
    parser.add_argument("--context-limit", type=int, default=20, help="每条消息的上下文条数 (默认 20)")
    parser.add_argument("--concurrency", "-j", type=int, default=10, help="并行工作线程数 (默认 10, 设为 1 则串行)")
    parser.add_argument("--dry-run", action="store_true", help="只查看候选，不真正回放")
    args = parser.parse_args()

    from ai_kefu.config.settings import settings

    run_id = f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    tag = args.tag or f"{args.model or settings.model_name}"

    logger.info(f"=== Eval Replay 开始 ===")
    logger.info(f"  run_id      : {run_id}")
    logger.info(f"  tag         : {tag}")
    logger.info(f"  model       : {args.model or settings.model_name}")
    logger.info(f"  limit       : {args.limit}")
    logger.info(f"  concurrency : {args.concurrency}")

    no_mock_availability = bool(getattr(args, "no_mock_availability", False))
    settings.eval_mock_availability = not no_mock_availability
    settings.eval_mock_availability_available_ratio = 0.80
    logger.info(f"  mock_slot   : {'ON(80/20)' if settings.eval_mock_availability else 'OFF'}")

    conn = get_db_connection(settings)
    ensure_eval_tables(conn)

    # 过滤规则说明
    logger.info(f"  过滤规则: 输入=买家消息, human_reply=(user_id=卖家 OR seller) 且非调试非Error")

    # 提取候选（过滤规则已固化在 fetch_eval_candidates 中）
    candidates = fetch_eval_candidates(
        conn, limit=args.limit, chat_id=args.chat_id, offset=args.offset
    )

    if not candidates:
        logger.warning("没有找到可评估的对话候选，退出。")
        conn.close()
        return

    if args.dry_run:
        logger.info(f"[dry-run] 以下是 {len(candidates)} 条候选:")
        for i, c in enumerate(candidates):
            logger.info(
                f"  [{i+1}] chat_id={c['chat_id']} | "
                f"user: {c['user_message'][:60]}... | "
                f"human: {(c.get('human_reply') or '')[:60]}..."
            )
        conn.close()
        return

    # 主连接不再需要（每个 worker 创建自己的连接）
    conn.close()

    # 连接工厂，供每个 worker 线程创建独立连接
    def conn_factory():
        return get_db_connection(settings)

    # 线程安全的计数器
    counters = {
        "success": 0,
        "error": 0,
        "lock": threading.Lock(),
    }

    total = len(candidates)
    concurrency = max(1, args.concurrency)
    start_time = time.time()

    if concurrency == 1:
        # 串行模式：向后兼容，不启动线程池
        logger.info(f"串行模式，共 {total} 条")
        for i, candidate in enumerate(candidates):
            _replay_worker(
                index=i + 1,
                total=total,
                candidate=candidate,
                conn_factory=conn_factory,
                settings=settings,
                run_id=run_id,
                tag=tag,
                model_override=args.model,
                context_limit=args.context_limit,
                counters=counters,
            )
    else:
        # 并行模式
        logger.info(f"并行模式，{concurrency} 线程，共 {total} 条")
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = []
            for i, candidate in enumerate(candidates):
                fut = pool.submit(
                    _replay_worker,
                    index=i + 1,
                    total=total,
                    candidate=candidate,
                    conn_factory=conn_factory,
                    settings=settings,
                    run_id=run_id,
                    tag=tag,
                    model_override=args.model,
                    context_limit=args.context_limit,
                    counters=counters,
                )
                futures.append(fut)

            # 等待所有任务完成
            for fut in as_completed(futures):
                try:
                    fut.result()  # 触发异常上报
                except Exception as e:
                    logger.error(f"Future 异常: {e}")

    elapsed = time.time() - start_time
    logger.info(f"=== Eval Replay 完成 ===")
    logger.info(f"  总数: {total} | 成功: {counters['success']} | 失败: {counters['error']}")
    logger.info(f"  总耗时: {elapsed:.1f}s | 平均: {elapsed/max(total,1):.1f}s/条")
    logger.info(f"  run_id: {run_id}")
    logger.info(f"  查看结果: python -m ai_kefu.scripts.eval_analyze --run-id {run_id}")


if __name__ == "__main__":
    main()

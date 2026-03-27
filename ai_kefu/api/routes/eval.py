"""
Eval replay viewer API routes.

Provides endpoints for listing eval runs and viewing eval results
as conversation-style chat records.
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from ai_kefu.config.settings import settings
import pymysql
import json

router = APIRouter()


def _get_connection():
    """Get a MySQL connection using app settings."""
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def _serialize_row(row: dict) -> dict:
    """Convert datetime/bytes fields to JSON-safe types."""
    for k, v in row.items():
        if isinstance(v, datetime):
            row[k] = v.isoformat()
        elif isinstance(v, bytes):
            row[k] = v.decode("utf-8", errors="replace")
    # Parse JSON string fields
    for json_field in ("context_messages", "ai_tool_calls"):
        val = row.get(json_field)
        if isinstance(val, str):
            try:
                row[json_field] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return row


@router.get("/runs")
async def list_eval_runs(
    limit: int = Query(50, ge=1, le=200, description="Number of runs to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """
    List all distinct eval runs with summary statistics.
    """
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            # Count distinct runs
            cur.execute("SELECT COUNT(DISTINCT run_id) AS total FROM eval_runs")
            total = cur.fetchone()["total"]

            # Get run summaries
            cur.execute(
                """
                SELECT
                    run_id,
                    tag,
                    ai_model,
                    MIN(created_at) AS started_at,
                    MAX(updated_at) AS finished_at,
                    COUNT(*)        AS total_items,
                    SUM(status = 'success')  AS success_count,
                    SUM(status = 'error')    AS error_count,
                    SUM(status = 'skipped')  AS skipped_count,
                    AVG(CASE WHEN status = 'success' THEN ai_duration_ms END) AS avg_duration_ms
                FROM eval_runs
                GROUP BY run_id, tag, ai_model
                ORDER BY MIN(created_at) DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            items = cur.fetchall()

            for item in items:
                _serialize_row(item)
                # Round average duration
                if item.get("avg_duration_ms") is not None:
                    item["avg_duration_ms"] = round(item["avg_duration_ms"])

        return {"total": total, "items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list eval runs: {e}")
    finally:
        conn.close()


@router.get("/runs/{run_id}")
async def get_eval_run_detail(
    run_id: str,
    status_filter: Optional[str] = Query(
        None, description="Filter by status: success, error, skipped"
    ),
    chat_id_filter: Optional[str] = Query(None, description="Filter by chat_id"),
    limit: int = Query(500, ge=1, le=2000, description="Page size"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """
    Get all eval items for a specific run_id, sorted by chat_id then source order.
    Each item contains user_message, human_reply, ai_reply, context_messages, etc.
    """
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            # Build WHERE clause
            conditions = ["run_id = %s"]
            params = [run_id]

            if status_filter:
                conditions.append("status = %s")
                params.append(status_filter)
            if chat_id_filter:
                conditions.append("chat_id = %s")
                params.append(chat_id_filter)

            where = " AND ".join(conditions)

            # Count
            cur.execute(f"SELECT COUNT(*) AS total FROM eval_runs WHERE {where}", params)
            total = cur.fetchone()["total"]

            if total == 0:
                raise HTTPException(status_code=404, detail=f"No eval data for run_id: {run_id}")

            # Fetch items
            cur.execute(
                f"""
                SELECT
                    id, run_id, tag, chat_id,
                    source_conversation_id,
                    user_message, human_reply, ai_reply,
                    context_messages, ai_tool_calls,
                    ai_session_id, ai_turn_count, ai_duration_ms, ai_model,
                    status, error_message,
                    created_at, updated_at
                FROM eval_runs
                WHERE {where}
                ORDER BY chat_id, source_conversation_id
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            items = cur.fetchall()

            for item in items:
                _serialize_row(item)

            # Summary stats for this run
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_items,
                    SUM(status = 'success')  AS success_count,
                    SUM(status = 'error')    AS error_count,
                    tag, ai_model,
                    MIN(created_at) AS started_at,
                    MAX(updated_at) AS finished_at
                FROM eval_runs
                WHERE run_id = %s
                GROUP BY tag, ai_model
                """,
                (run_id,),
            )
            summary = cur.fetchone()
            if summary:
                _serialize_row(summary)

        return {
            "run_id": run_id,
            "summary": summary,
            "total": total,
            "offset": offset,
            "limit": limit,
            "items": items,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch eval run: {e}")
    finally:
        conn.close()


@router.get("/runs/{run_id}/chats")
async def get_eval_run_chat_ids(run_id: str):
    """
    Get distinct chat_ids within a run for navigation/grouping.
    """
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    chat_id,
                    COUNT(*) AS message_count,
                    SUM(status = 'success') AS success_count,
                    SUM(status = 'error')   AS error_count
                FROM eval_runs
                WHERE run_id = %s
                GROUP BY chat_id
                ORDER BY chat_id
                """,
                (run_id,),
            )
            items = cur.fetchall()

        return {"run_id": run_id, "chats": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch chat list: {e}")
    finally:
        conn.close()

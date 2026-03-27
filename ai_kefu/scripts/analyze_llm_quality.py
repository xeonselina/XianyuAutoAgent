#!/usr/bin/env python3
"""
LLM 回复质量分析工具 v3 — 基于 eval_runs 表

从 eval_runs 表中读取 eval_replay 产生的 (用户消息, 人工回复, AI 回复) 三元组，
用 LLM 对每一条进行多维度评分，最终生成汇总报告。

数据来源：eval_runs 表（由 eval_replay.py 写入）
评分维度：简洁度 / 自然度 / 准确性 / 理解力 / 转化力 / 综合

用法:
    # 分析最近一次 eval run（在线推理 + 并发）
    python -m ai_kefu.scripts.analyze_llm_quality

    # 指定 run_id + 10 线程并发评分
    python -m ai_kefu.scripts.analyze_llm_quality --run-id "eval_20260326_140000_abc123" -j 10

    # 调整并发线程数
    python -m ai_kefu.scripts.analyze_llm_quality -j 12

    # 跳过 LLM 评分，仅做统计分析
    python -m ai_kefu.scripts.analyze_llm_quality --no-llm-eval

    # 指定报告输出路径
    python -m ai_kefu.scripts.analyze_llm_quality --output reports/my_report.md

    # 列出可用的 eval runs
    python -m ai_kefu.scripts.analyze_llm_quality --list-runs
"""

import argparse
import json
import os
import re
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

import pymysql
from pymysql.cursors import DictCursor
from loguru import logger

# ------------------------------------------------------------------
# Logger 配置
# ------------------------------------------------------------------
logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<7} | {message}")


# ------------------------------------------------------------------
# Data models
# ------------------------------------------------------------------

@dataclass
class EvalScore:
    """单条 LLM 评分结果"""
    conciseness: float = 0       # 简洁度
    naturalness: float = 0       # 自然度
    accuracy: float = 0          # 准确性
    understanding: float = 0     # 理解力
    conversion: float = 0        # 转化力
    overall_score: float = 0     # 综合
    key_differences: List[str] = field(default_factory=list)
    ai_problems: List[str] = field(default_factory=list)
    prompt_improvements: List[str] = field(default_factory=list)
    raw_json: Optional[Dict] = None


@dataclass
class EvalItem:
    """一条待评估的数据"""
    id: int
    run_id: str
    chat_id: str
    user_message: str
    human_reply: Optional[str]
    ai_reply: Optional[str]
    context_messages: Optional[List[Dict]] = None
    ai_duration_ms: Optional[int] = None
    ai_model: Optional[str] = None
    ai_tool_calls: Optional[List[Dict]] = None
    status: str = "success"
    # 评分结果（LLM 评分后填入）
    score: Optional[EvalScore] = None


# ------------------------------------------------------------------
# Database
# ------------------------------------------------------------------

def get_connection(settings) -> pymysql.Connection:
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset='utf8mb4',
        cursorclass=DictCursor,
    )


def list_runs(conn: pymysql.Connection, limit: int = 20) -> List[Dict]:
    """列出最近的 eval runs。"""
    sql = """
        SELECT
            run_id, tag, ai_model,
            COUNT(*) AS total,
            SUM(status = 'success') AS success_count,
            SUM(status = 'error') AS error_count,
            AVG(ai_duration_ms) AS avg_duration_ms,
            MIN(created_at) AS started_at,
            MAX(created_at) AS ended_at
        FROM eval_runs
        GROUP BY run_id, tag, ai_model
        ORDER BY MIN(created_at) DESC
        LIMIT %s
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, (limit,))
        return cursor.fetchall()


def get_latest_run_id(conn: pymysql.Connection) -> Optional[str]:
    sql = "SELECT run_id FROM eval_runs ORDER BY created_at DESC LIMIT 1"
    with conn.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()
    return row["run_id"] if row else None


def fetch_eval_items(conn: pymysql.Connection, run_id: str) -> List[EvalItem]:
    """读取 eval_runs 表中指定 run_id 的所有成功记录。"""
    sql = """
        SELECT id, run_id, chat_id, user_message, human_reply, ai_reply,
               context_messages, ai_duration_ms, ai_model, ai_tool_calls, status
        FROM eval_runs
        WHERE run_id = %s AND status = 'success'
          AND ai_reply IS NOT NULL AND human_reply IS NOT NULL
        ORDER BY id ASC
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, (run_id,))
        rows = cursor.fetchall()

    items = []
    for r in rows:
        # 解析 JSON 字段
        ctx = r.get("context_messages")
        if ctx and isinstance(ctx, str):
            try:
                ctx = json.loads(ctx)
            except Exception:
                ctx = None

        tc = r.get("ai_tool_calls")
        if tc and isinstance(tc, str):
            try:
                tc = json.loads(tc)
            except Exception:
                tc = None

        items.append(EvalItem(
            id=r["id"],
            run_id=r["run_id"],
            chat_id=r["chat_id"],
            user_message=r["user_message"],
            human_reply=r["human_reply"],
            ai_reply=r["ai_reply"],
            context_messages=ctx,
            ai_duration_ms=r.get("ai_duration_ms"),
            ai_model=r.get("ai_model"),
            ai_tool_calls=tc,
            status=r.get("status", "success"),
        ))

    return items


# ------------------------------------------------------------------
# LLM 评分
# ------------------------------------------------------------------

EVAL_PROMPT = """你是一个专业的客服质量评估专家。以下是闲鱼平台上手机/数码租赁客服的一条真实对话。

买家发了一条消息，分别有「人工客服」和「AI 客服」各自的回复。请对比两者差异并评分。

## 上下文（对话历史）
{context_text}

## 当前轮次

**👤 买家消息**：{user_message}

**👨‍💼 人工客服回复**：{human_reply}

**🤖 AI 客服回复**：{ai_reply}

## 评分要求

请从以下 5 个维度对 **AI 客服** 的回复进行评分（1-10 分），以人工客服为参照：

1. **简洁度** (conciseness): AI 回复是否像人工一样简洁直接，而非冗长啰嗦
2. **自然度** (naturalness): AI 回复是否像真人说话，不机械、不模板化
3. **准确性** (accuracy): AI 回复信息是否正确，有没有编造或错误
4. **理解力** (understanding): AI 是否正确理解了买家的意图和需求
5. **转化力** (conversion): AI 的回复是否有助于促成交易（而非让买家跑掉）

## 输出格式

请严格按以下 JSON 格式返回，不要输出任何其他内容：

```json
{{
    "conciseness": 7,
    "naturalness": 6,
    "accuracy": 8,
    "understanding": 7,
    "conversion": 6,
    "overall_score": 6.8,
    "key_differences": [
        "差异1",
        "差异2"
    ],
    "ai_problems": [
        "问题1"
    ],
    "prompt_improvements": [
        "改进建议1"
    ]
}}
```"""


def _build_context_text(context_messages: Optional[List[Dict]], max_turns: int = 8) -> str:
    """将上下文消息格式化为文本。"""
    if not context_messages:
        return "（无前文上下文）"

    lines = []
    for cm in context_messages[-max_turns:]:
        role = cm.get("role", "?")
        content = cm.get("content", "")
        if len(content) > 150:
            content = content[:150] + "..."
        label = "👤 买家" if role == "user" else "👨‍💼 客服"
        lines.append(f"{label}：{content}")

    return "\n".join(lines) if lines else "（无前文上下文）"


def _parse_eval_json(content: str) -> Optional[Dict]:
    """
    从 LLM 返回的文本中解析评分 JSON，三层容错：

    1. 直接提取 JSON 并解析
    2. 修复常见格式问题后重试（末尾逗号、中文引号、未转义换行等）
    3. 正则逐字段提取数值兜底（至少拿到分数）
    """
    if not content:
        return None

    # --- 第一层：直接解析 ---
    json_match = re.search(r'\{[\s\S]*\}', content)
    if json_match:
        raw = json_match.group()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # --- 第二层：修复常见格式问题 ---
        fixed = raw
        # 替换中文引号
        fixed = fixed.replace('\u201c', '"').replace('\u201d', '"')
        fixed = fixed.replace('\u2018', "'").replace('\u2019', "'")
        # 移除尾随逗号 (如 [1, 2,] 或 {"a": 1,})
        fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
        # 修复数组元素间缺少逗号的情况（"xxx"\n    "yyy" → "xxx",\n    "yyy"）
        fixed = re.sub(r'"\s*\n(\s*")', r'",\n\1', fixed)
        # 处理字符串值中的未转义换行
        # 逐行处理：如果一行不是完整的 JSON 结构，可能是断行的字符串
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # 尝试更激进的修复：移除字符串数组中有问题的元素
        try:
            # 只保留数值字段，把数组字段替换为空数组
            cleaned = re.sub(
                r'"(key_differences|ai_problems|prompt_improvements)"\s*:\s*\[[\s\S]*?\]',
                lambda m: f'"{m.group(1)}": []',
                fixed
            )
            data = json.loads(cleaned)
            # 数值字段解析成功，尝试单独恢复数组字段
            for arr_field in ["key_differences", "ai_problems", "prompt_improvements"]:
                arr_match = re.search(
                    rf'"{arr_field}"\s*:\s*\[([\s\S]*?)\]', raw
                )
                if arr_match:
                    items = re.findall(r'"([^"]*)"', arr_match.group(1))
                    data[arr_field] = items
            return data
        except json.JSONDecodeError:
            pass

    # --- 第三层：正则逐字段提取数值（兜底） ---
    score_fields = ["conciseness", "naturalness", "accuracy", "understanding", "conversion", "overall_score"]
    extracted = {}
    for field_name in score_fields:
        m = re.search(rf'"{field_name}"\s*:\s*([0-9]+(?:\.[0-9]+)?)', content)
        if m:
            extracted[field_name] = float(m.group(1))

    if extracted and "overall_score" in extracted:
        # 尝试提取字符串数组
        for arr_field in ["key_differences", "ai_problems", "prompt_improvements"]:
            arr_match = re.search(rf'"{arr_field}"\s*:\s*\[([\s\S]*?)\]', content)
            if arr_match:
                items = re.findall(r'"([^"]*)"', arr_match.group(1))
                extracted[arr_field] = items
            else:
                extracted[arr_field] = []
        logger.debug(f"JSON 解析失败，正则兜底提取到 {len(extracted)} 个字段")
        return extracted

    return None


def _call_llm_for_eval(messages: List[Dict], max_retries: int = 5, timeout: float = 120) -> Dict:
    """在线调用 LLM（带重试），用于实时并发评分。"""
    from openai import OpenAI, APIError, APITimeoutError, APIConnectionError
    from ai_kefu.config.settings import settings
    import random

    client = OpenAI(
        api_key=settings.api_key,
        base_url=settings.model_base_url,
        timeout=timeout,
    )

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            completion = client.chat.completions.create(
                model=settings.model_name,
                messages=messages,
                temperature=0.3,
                max_tokens=1500,
                stream=False,
            )
            msg = completion.choices[0].message
            return {"choices": [{"message": {"role": msg.role or "assistant", "content": msg.content or ""}}]}
        except (APITimeoutError, APIConnectionError, APIError) as e:
            last_error = e
            delay = min(2 ** attempt + random.uniform(0, 2), 30)
            logger.warning(f"LLM 调用失败 (attempt {attempt}/{max_retries}): {type(e).__name__}: {e} | 等待 {delay:.1f}s")
            time.sleep(delay)

    raise last_error


def evaluate_single(item: EvalItem) -> EvalScore:
    """在线推理：单条评分。"""
    context_text = _build_context_text(item.context_messages)
    user_msg = item.user_message[:500] if item.user_message else ""
    human = item.human_reply[:800] if item.human_reply else "（无）"
    ai = item.ai_reply[:800] if item.ai_reply else "（无）"

    prompt = EVAL_PROMPT.format(
        context_text=context_text,
        user_message=user_msg,
        human_reply=human,
        ai_reply=ai,
    )

    try:
        response = _call_llm_for_eval(
            messages=[
                {"role": "system", "content": "你是客服质量评估专家。只输出 JSON，不要输出任何其他文字。"},
                {"role": "user", "content": prompt},
            ],
        )
        content = response["choices"][0]["message"].get("content", "")
        data = _parse_eval_json(content)
        if not data:
            logger.warning(f"LLM 返回无法解析 (id={item.id}): {content[:200]}")
            return EvalScore()

        return EvalScore(
            conciseness=float(data.get("conciseness", 0)),
            naturalness=float(data.get("naturalness", 0)),
            accuracy=float(data.get("accuracy", 0)),
            understanding=float(data.get("understanding", 0)),
            conversion=float(data.get("conversion", 0)),
            overall_score=float(data.get("overall_score", 0)),
            key_differences=data.get("key_differences", []),
            ai_problems=data.get("ai_problems", []),
            prompt_improvements=data.get("prompt_improvements", []),
            raw_json=data,
        )
    except Exception as e:
        logger.error(f"LLM 评分失败 (id={item.id}): {e}")
        return EvalScore()


def evaluate_batch(items: List[EvalItem], concurrency: int = 10) -> List[EvalItem]:
    """在线并发评分（带限速）。"""
    total = len(items)
    counters = {"done": 0, "success": 0, "fail": 0, "lock": threading.Lock()}

    # 启动节流：每秒最多发出 concurrency 个请求
    rate_limiter = threading.Semaphore(max(1, concurrency))

    def _release_after_delay():
        time.sleep(1.0)
        rate_limiter.release()

    def _worker(item: EvalItem) -> EvalItem:
        rate_limiter.acquire()
        threading.Thread(target=_release_after_delay, daemon=True).start()

        score = evaluate_single(item)
        item.score = score

        with counters["lock"]:
            counters["done"] += 1
            if score.overall_score > 0:
                counters["success"] += 1
            else:
                counters["fail"] += 1
            done = counters["done"]
            success = counters["success"]
            fail = counters["fail"]

        logger.info(
            f"  [{done}/{total}] id={item.id} | 综合={score.overall_score:.1f} "
            f"简洁={score.conciseness:.0f} 自然={score.naturalness:.0f} 准确={score.accuracy:.0f} "
            f"| 成功={success} 失败={fail}"
        )
        return item

    logger.info(f"LLM 评分：{total} 条，{concurrency} 线程并行")
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(_worker, item) for item in items]
        for fut in as_completed(futures):
            fut.result()

    logger.info(f"评分完成：{counters['success']} 成功 / {counters['fail']} 失败 / {total} 总计")
    return items


# ------------------------------------------------------------------
# 统计分析
# ------------------------------------------------------------------

def compute_stats(items: List[EvalItem]) -> Dict[str, Any]:
    """汇总统计。"""
    scored = [it for it in items if it.score and it.score.overall_score > 0]

    if not scored:
        return {"total": len(items), "scored": 0}

    def _avg(field: str) -> float:
        vals = [getattr(it.score, field) for it in scored if getattr(it.score, field, 0) > 0]
        return sum(vals) / len(vals) if vals else 0

    # 回复长度统计
    human_lens = [len(it.human_reply) for it in items if it.human_reply]
    ai_lens = [len(it.ai_reply) for it in items if it.ai_reply]

    # 汇总问题和建议（去重）
    all_differences = []
    all_problems = []
    all_improvements = []
    for it in scored:
        all_differences.extend(it.score.key_differences)
        all_problems.extend(it.score.ai_problems)
        all_improvements.extend(it.score.prompt_improvements)

    def _dedup(items_list: List[str], max_items: int = 30) -> List[str]:
        seen = set()
        result = []
        for s in items_list:
            key = s[:40]
            if key not in seen:
                seen.add(key)
                result.append(s)
                if len(result) >= max_items:
                    break
        return result

    return {
        "total": len(items),
        "scored": len(scored),
        "avg_conciseness": round(_avg("conciseness"), 2),
        "avg_naturalness": round(_avg("naturalness"), 2),
        "avg_accuracy": round(_avg("accuracy"), 2),
        "avg_understanding": round(_avg("understanding"), 2),
        "avg_conversion": round(_avg("conversion"), 2),
        "avg_overall": round(_avg("overall_score"), 2),
        "human_avg_len": round(sum(human_lens) / len(human_lens), 1) if human_lens else 0,
        "ai_avg_len": round(sum(ai_lens) / len(ai_lens), 1) if ai_lens else 0,
        "key_differences": _dedup(all_differences),
        "ai_problems": _dedup(all_problems),
        "prompt_improvements": _dedup(all_improvements),
    }


# ------------------------------------------------------------------
# 报告：终端
# ------------------------------------------------------------------

def print_terminal_report(run_id: str, items: List[EvalItem], stats: Dict[str, Any]):
    """终端简要报告。"""
    print("\n" + "=" * 72)
    print(f"  📊 AI 客服 vs 人工客服 LLM 质量分析报告")
    print(f"  run_id : {run_id}")
    print(f"  模型   : {items[0].ai_model if items else 'N/A'}")
    print("=" * 72)

    print(f"\n📈 总体统计:")
    print(f"  评估条数  : {stats['total']}")
    print(f"  成功评分  : {stats['scored']}")
    print(f"  人工平均长度: {stats.get('human_avg_len', 0):.0f} 字")
    print(f"  AI 平均长度 : {stats.get('ai_avg_len', 0):.0f} 字")
    ratio = stats.get('ai_avg_len', 0) / max(stats.get('human_avg_len', 1), 1)
    print(f"  AI/人工长度比: {ratio:.1f}x")

    if stats["scored"] > 0:
        print(f"\n🎯 LLM 评分平均 (1-10):")
        print(f"  🏆 综合评分  : {stats['avg_overall']:.1f}")
        print(f"  📏 简洁度    : {stats['avg_conciseness']:.1f}")
        print(f"  🗣️ 自然度    : {stats['avg_naturalness']:.1f}")
        print(f"  ✅ 准确性    : {stats['avg_accuracy']:.1f}")
        print(f"  🧠 理解力    : {stats['avg_understanding']:.1f}")
        print(f"  💰 转化力    : {stats['avg_conversion']:.1f}")

    # 评分最低的 5 条
    scored = [it for it in items if it.score and it.score.overall_score > 0]
    if scored:
        worst = sorted(scored, key=lambda x: x.score.overall_score)[:5]
        print(f"\n⚠️  评分最低的 5 条:")
        print("-" * 72)
        for i, it in enumerate(worst):
            print(f"  [{i+1}] 综合={it.score.overall_score:.1f} | chat={it.chat_id}")
            print(f"      👤 用户: {it.user_message[:80]}")
            print(f"      👨‍💼 人工: {(it.human_reply or '')[:80]}")
            print(f"      🤖 AI  : {(it.ai_reply or '')[:80]}")

        best = sorted(scored, key=lambda x: x.score.overall_score, reverse=True)[:5]
        print(f"\n✅ 评分最高的 5 条:")
        print("-" * 72)
        for i, it in enumerate(best):
            print(f"  [{i+1}] 综合={it.score.overall_score:.1f} | chat={it.chat_id}")
            print(f"      👤 用户: {it.user_message[:80]}")
            print(f"      👨‍💼 人工: {(it.human_reply or '')[:80]}")
            print(f"      🤖 AI  : {(it.ai_reply or '')[:80]}")

    print("\n" + "=" * 72)


# ------------------------------------------------------------------
# 报告：Markdown
# ------------------------------------------------------------------

def generate_md_report(
    run_id: str,
    items: List[EvalItem],
    stats: Dict[str, Any],
    output_path: str,
):
    """生成 Markdown 分析报告。"""
    lines = []
    lines.append("# 📊 AI 客服 vs 人工客服 — LLM 质量分析报告")
    lines.append("")
    lines.append(f"> 分析时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> run_id：`{run_id}`")
    lines.append(f"> 模型：`{items[0].ai_model if items else 'N/A'}`")
    lines.append(f"> 数据来源：eval_runs 表（eval_replay 产生）")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ========== 一、总体统计 ==========
    lines.append("## 一、总体统计")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 评估条数 | {stats['total']} |")
    lines.append(f"| 成功评分 | {stats['scored']} |")
    lines.append(f"| 人工平均回复长度 | {stats.get('human_avg_len', 0):.0f} 字 |")
    lines.append(f"| AI 平均回复长度 | {stats.get('ai_avg_len', 0):.0f} 字 |")
    ratio = stats.get('ai_avg_len', 0) / max(stats.get('human_avg_len', 1), 1)
    lines.append(f"| AI/人工长度比 | {ratio:.1f}x |")
    lines.append("")

    # ========== 二、LLM 评分汇总 ==========
    if stats["scored"] > 0:
        lines.append("## 二、LLM 评分汇总")
        lines.append("")
        lines.append("| 维度 | 平均分 (1-10) |")
        lines.append("|------|:---:|")
        lines.append(f"| 🏆 **综合评分** | **{stats['avg_overall']:.1f}** |")
        lines.append(f"| 📏 简洁度 | {stats['avg_conciseness']:.1f} |")
        lines.append(f"| 🗣️ 自然度 | {stats['avg_naturalness']:.1f} |")
        lines.append(f"| ✅ 准确性 | {stats['avg_accuracy']:.1f} |")
        lines.append(f"| 🧠 理解力 | {stats['avg_understanding']:.1f} |")
        lines.append(f"| 💰 转化力 | {stats['avg_conversion']:.1f} |")
        lines.append("")

        # 分数分布
        scored = [it for it in items if it.score and it.score.overall_score > 0]
        if scored:
            bins = {"≤3 (差)": 0, "4-5 (一般)": 0, "6-7 (中等)": 0, "8-9 (良好)": 0, "10 (完美)": 0}
            for it in scored:
                s = it.score.overall_score
                if s <= 3:
                    bins["≤3 (差)"] += 1
                elif s <= 5:
                    bins["4-5 (一般)"] += 1
                elif s <= 7:
                    bins["6-7 (中等)"] += 1
                elif s <= 9:
                    bins["8-9 (良好)"] += 1
                else:
                    bins["10 (完美)"] += 1

            lines.append("### 评分分布")
            lines.append("")
            lines.append("| 分数段 | 数量 | 占比 |")
            lines.append("|--------|:---:|:---:|")
            for label, count in bins.items():
                pct = count / len(scored) * 100 if scored else 0
                bar = "█" * int(pct / 5)
                lines.append(f"| {label} | {count} | {pct:.0f}% {bar} |")
            lines.append("")

    # ========== 三、人工 vs AI 关键差异 ==========
    if stats.get("key_differences"):
        lines.append("## 三、人工 vs AI 关键差异")
        lines.append("")
        for d in stats["key_differences"][:20]:
            lines.append(f"- {d}")
        lines.append("")

    # ========== 四、AI 问题汇总 ==========
    if stats.get("ai_problems"):
        lines.append("## 四、AI 常见问题")
        lines.append("")
        for p in stats["ai_problems"][:20]:
            lines.append(f"- {p}")
        lines.append("")

    # ========== 五、Prompt 改进建议 ==========
    if stats.get("prompt_improvements"):
        lines.append("## 五、Prompt 改进建议")
        lines.append("")
        for p in stats["prompt_improvements"][:20]:
            lines.append(f"- {p}")
        lines.append("")

    # ========== 六、评分最低案例 ==========
    scored = [it for it in items if it.score and it.score.overall_score > 0]
    if scored:
        worst = sorted(scored, key=lambda x: x.score.overall_score)[:15]
        lines.append("## 六、评分最低案例（需重点优化）")
        lines.append("")
        for i, it in enumerate(worst, 1):
            sc = it.score
            lines.append(f"### 案例 {i}（综合 {sc.overall_score:.1f} | 简洁={sc.conciseness:.0f} 自然={sc.naturalness:.0f} 准确={sc.accuracy:.0f} 理解={sc.understanding:.0f} 转化={sc.conversion:.0f}）")
            lines.append("")
            lines.append(f"- **chat_id**: `{it.chat_id}`")

            # 上下文
            if it.context_messages:
                lines.append(f"- **上下文**:")
                for cm in (it.context_messages or [])[-5:]:
                    role = cm.get("role", "?")
                    content = cm.get("content", "")[:120]
                    label = "👤 买家" if role == "user" else "👨‍💼 客服"
                    lines.append(f"  > {label}：{content}")

            lines.append(f"- **👤 买家**：{it.user_message[:200]}")
            lines.append(f"- **👨‍💼 人工**（{len(it.human_reply or '')}字）：{(it.human_reply or '')[:300]}")
            ai_display = (it.ai_reply or '')[:500]
            lines.append(f"- **🤖 AI**（{len(it.ai_reply or '')}字）：{ai_display}")

            if sc.key_differences:
                lines.append(f"- **差异**：{'；'.join(sc.key_differences[:3])}")
            if sc.ai_problems:
                lines.append(f"- **问题**：{'；'.join(sc.ai_problems[:3])}")
            lines.append("")

        # 评分最高案例
        best = sorted(scored, key=lambda x: x.score.overall_score, reverse=True)[:10]
        lines.append("## 七、评分最高案例（AI 表现良好）")
        lines.append("")
        for i, it in enumerate(best, 1):
            sc = it.score
            lines.append(f"### 案例 {i}（综合 {sc.overall_score:.1f}）")
            lines.append("")
            lines.append(f"- **chat_id**: `{it.chat_id}`")
            lines.append(f"- **👤 买家**：{it.user_message[:200]}")
            lines.append(f"- **👨‍💼 人工**（{len(it.human_reply or '')}字）：{(it.human_reply or '')[:200]}")
            lines.append(f"- **🤖 AI**（{len(it.ai_reply or '')}字）：{(it.ai_reply or '')[:200]}")
            lines.append("")

    # ========== 八、逐条评分明细 ==========
    lines.append("## 八、逐条评分明细")
    lines.append("")
    lines.append("| # | chat_id | 综合 | 简洁 | 自然 | 准确 | 理解 | 转化 | 人工长度 | AI长度 | 倍数 |")
    lines.append("|---|---------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")
    for i, it in enumerate(scored, 1):
        sc = it.score
        h_len = len(it.human_reply or '')
        a_len = len(it.ai_reply or '')
        r = a_len / max(h_len, 1)
        lines.append(
            f"| {i} | `{it.chat_id[:20]}` | {sc.overall_score:.1f} | "
            f"{sc.conciseness:.0f} | {sc.naturalness:.0f} | {sc.accuracy:.0f} | "
            f"{sc.understanding:.0f} | {sc.conversion:.0f} | "
            f"{h_len} | {a_len} | {r:.1f}x |"
        )
    lines.append("")

    # 写入文件
    content = "\n".join(lines)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"📄 MD 报告已生成：{output_path}")
    return content


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LLM 回复质量分析 — 基于 eval_runs 表")
    parser.add_argument("--run-id", type=str, default=None, help="分析指定 run_id（默认最近一次）")
    parser.add_argument("--list-runs", action="store_true", help="列出可用的 eval runs")
    parser.add_argument("--concurrency", "-j", type=int, default=10, help="在线评分并发线程数 (默认 10)")
    parser.add_argument("--no-llm-eval", action="store_true", help="跳过 LLM 评分，仅做统计分析")
    parser.add_argument("--output", type=str, default=None, help="MD 报告输出路径")
    parser.add_argument("--no-terminal", action="store_true", help="不输出终端报告")
    args = parser.parse_args()

    from ai_kefu.config.settings import settings

    conn = get_connection(settings)

    # 列出 runs
    if args.list_runs:
        runs = list_runs(conn)
        if not runs:
            print("没有找到 eval 记录。请先运行 eval_replay。")
            return
        print(f"\n{'run_id':<40} {'tag':<20} {'model':<18} {'total':>5} {'ok':>4} {'err':>4} {'avg_ms':>8} {'time'}")
        print("-" * 130)
        for r in runs:
            print(
                f"  {r['run_id']:<38} {(r.get('tag') or ''):<18} "
                f"{(r.get('ai_model') or ''):<16} {r['total']:>5} "
                f"{int(r.get('success_count') or 0):>4} {int(r.get('error_count') or 0):>4} "
                f"{r.get('avg_duration_ms', 0):>8.0f} {r.get('started_at', '')}"
            )
        conn.close()
        return

    # 确定 run_id
    run_id = args.run_id or get_latest_run_id(conn)
    if not run_id:
        print("没有找到 eval 记录。请先运行 eval_replay。")
        conn.close()
        return

    logger.info(f"=== LLM 质量分析开始 ===")
    logger.info(f"  run_id      : {run_id}")
    logger.info(f"  llm_mode    : online")
    logger.info(f"  concurrency : {args.concurrency}")

    # 读取数据
    items = fetch_eval_items(conn, run_id)
    conn.close()

    if not items:
        print(f"run_id '{run_id}' 没有可分析的成功记录（需要同时有 ai_reply 和 human_reply）。")
        return

    logger.info(f"  找到 {len(items)} 条有效配对")

    # LLM 评分
    start_time = time.time()
    if not args.no_llm_eval:
        items = evaluate_batch(items, concurrency=args.concurrency)
        elapsed = time.time() - start_time
        logger.info(f"  LLM 评分完成，耗时 {elapsed:.1f}s")
    else:
        logger.info("  跳过 LLM 评分（--no-llm-eval）")

    # 统计
    stats = compute_stats(items)

    # 终端报告
    if not args.no_terminal:
        print_terminal_report(run_id, items, stats)

    # Markdown 报告
    output_path = args.output or os.path.join(
        os.path.dirname(__file__), '..', 'reports',
        f'llm_quality_{run_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.md'
    )
    generate_md_report(run_id, items, stats, output_path)

    logger.info(f"=== LLM 质量分析完成 ===")


if __name__ == "__main__":
    main()

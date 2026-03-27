#!/usr/bin/env python3
"""
Eval Analyze - 评估结果分析工具

分析 eval_runs 表中的回放结果，与人类回复做对比，
生成统计报告和典型样例。

用法:
    # 分析最近一次评估
    python -m ai_kefu.scripts.eval_analyze

    # 分析指定 run_id
    python -m ai_kefu.scripts.eval_analyze --run-id "eval_20260326_140000_abc123"

    # 对比两次评估
    python -m ai_kefu.scripts.eval_analyze --compare "run_id_a" "run_id_b"

    # 导出详细结果为 JSON
    python -m ai_kefu.scripts.eval_analyze --run-id "xxx" --export results.json

    # 导出样例 (markdown)
    python -m ai_kefu.scripts.eval_analyze --run-id "xxx" --export-samples samples.md
"""

import argparse
import json
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional

import pymysql
from pymysql.cursors import DictCursor
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<7} | {message}")


def get_db_connection(settings) -> pymysql.Connection:
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


# ------------------------------------------------------------------
# 数据查询
# ------------------------------------------------------------------

def list_runs(conn: pymysql.Connection, limit: int = 20) -> List[Dict]:
    """列出最近的评估运行。"""
    sql = """
        SELECT
            run_id,
            tag,
            ai_model,
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


def fetch_run_results(conn: pymysql.Connection, run_id: str) -> List[Dict]:
    """获取某次评估的所有结果。"""
    sql = """
        SELECT *
        FROM eval_runs
        WHERE run_id = %s
        ORDER BY id ASC
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, (run_id,))
        rows = cursor.fetchall()

    for row in rows:
        for json_field in ('context_messages', 'ai_tool_calls'):
            if row.get(json_field) and isinstance(row[json_field], str):
                try:
                    row[json_field] = json.loads(row[json_field])
                except:
                    pass
    return rows


def get_latest_run_id(conn: pymysql.Connection) -> Optional[str]:
    """获取最近一次 run_id。"""
    sql = "SELECT run_id FROM eval_runs ORDER BY created_at DESC LIMIT 1"
    with conn.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()
    return row["run_id"] if row else None


# ------------------------------------------------------------------
# 文本相似度 (简单 Jaccard)
# ------------------------------------------------------------------

def jaccard_similarity(text_a: str, text_b: str) -> float:
    """基于字符 bigram 的 Jaccard 相似度。"""
    if not text_a or not text_b:
        return 0.0

    def bigrams(text: str) -> set:
        text = text.strip()
        return {text[i:i+2] for i in range(len(text) - 1)} if len(text) >= 2 else {text}

    set_a = bigrams(text_a)
    set_b = bigrams(text_b)

    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def length_ratio(text_a: str, text_b: str) -> float:
    """长度比 (短 / 长)。"""
    if not text_a or not text_b:
        return 0.0
    la, lb = len(text_a.strip()), len(text_b.strip())
    if max(la, lb) == 0:
        return 1.0
    return min(la, lb) / max(la, lb)


# ------------------------------------------------------------------
# 分析 & 报告
# ------------------------------------------------------------------

def analyze_run(results: List[Dict]) -> Dict[str, Any]:
    """分析一次评估的结果。"""
    total = len(results)
    success = [r for r in results if r["status"] == "success"]
    errors = [r for r in results if r["status"] == "error"]

    # 相似度
    similarities = []
    length_ratios = []
    for r in success:
        if r.get("ai_reply") and r.get("human_reply"):
            sim = jaccard_similarity(r["ai_reply"], r["human_reply"])
            lr = length_ratio(r["ai_reply"], r["human_reply"])
            r["_similarity"] = sim
            r["_length_ratio"] = lr
            similarities.append(sim)
            length_ratios.append(lr)

    avg_sim = sum(similarities) / len(similarities) if similarities else 0
    avg_lr = sum(length_ratios) / len(length_ratios) if length_ratios else 0

    # 耗时
    durations = [r["ai_duration_ms"] for r in success if r.get("ai_duration_ms")]
    avg_dur = sum(durations) / len(durations) if durations else 0

    # 工具调用
    tool_usage = {}
    for r in success:
        if r.get("ai_tool_calls"):
            calls = r["ai_tool_calls"] if isinstance(r["ai_tool_calls"], list) else []
            for tc in calls:
                name = tc.get("name", "unknown")
                tool_usage[name] = tool_usage.get(name, 0) + 1

    # 找出最不相似的 (potential issues)
    low_sim = sorted(
        [r for r in success if "_similarity" in r],
        key=lambda x: x["_similarity"]
    )[:10]

    # 找出最相似的 (best matches)
    high_sim = sorted(
        [r for r in success if "_similarity" in r],
        key=lambda x: x["_similarity"],
        reverse=True
    )[:10]

    return {
        "total": total,
        "success_count": len(success),
        "error_count": len(errors),
        "avg_similarity": round(avg_sim, 4),
        "avg_length_ratio": round(avg_lr, 4),
        "avg_duration_ms": round(avg_dur, 1),
        "tool_usage": tool_usage,
        "low_similarity_samples": low_sim,
        "high_similarity_samples": high_sim,
        "errors": errors[:5],  # 前 5 条错误
    }


def print_report(run_id: str, tag: str, analysis: Dict[str, Any]):
    """打印分析报告到 stdout。"""
    print("\n" + "=" * 72)
    print(f"  📊 评估分析报告")
    print(f"  run_id : {run_id}")
    print(f"  tag    : {tag}")
    print("=" * 72)

    print(f"\n📈 总体统计:")
    print(f"  总数      : {analysis['total']}")
    print(f"  成功      : {analysis['success_count']}")
    print(f"  失败      : {analysis['error_count']}")
    print(f"  平均相似度: {analysis['avg_similarity']:.2%}")
    print(f"  平均长度比: {analysis['avg_length_ratio']:.2%}")
    print(f"  平均耗时  : {analysis['avg_duration_ms']:.0f}ms")

    if analysis["tool_usage"]:
        print(f"\n🔧 工具调用统计:")
        for name, count in sorted(analysis["tool_usage"].items(), key=lambda x: -x[1]):
            print(f"  {name}: {count} 次")

    # 打印低相似度样例
    if analysis["low_similarity_samples"]:
        print(f"\n⚠️  低相似度样例 (AI 回复与人类差异最大):")
        print("-" * 72)
        for i, s in enumerate(analysis["low_similarity_samples"][:5]):
            print(f"\n  [{i+1}] 相似度: {s.get('_similarity', 0):.2%} | chat_id: {s['chat_id']}")
            print(f"  👤 用户: {s['user_message'][:100]}")
            print(f"  🧑 人类: {(s.get('human_reply') or 'N/A')[:100]}")
            print(f"  🤖 AI  : {(s.get('ai_reply') or 'N/A')[:100]}")

    # 打印高相似度样例
    if analysis["high_similarity_samples"]:
        print(f"\n✅ 高相似度样例 (AI 回复与人类最接近):")
        print("-" * 72)
        for i, s in enumerate(analysis["high_similarity_samples"][:5]):
            print(f"\n  [{i+1}] 相似度: {s.get('_similarity', 0):.2%} | chat_id: {s['chat_id']}")
            print(f"  👤 用户: {s['user_message'][:100]}")
            print(f"  🧑 人类: {(s.get('human_reply') or 'N/A')[:100]}")
            print(f"  🤖 AI  : {(s.get('ai_reply') or 'N/A')[:100]}")

    # 错误
    if analysis["errors"]:
        print(f"\n❌ 错误样例:")
        print("-" * 72)
        for i, e in enumerate(analysis["errors"]):
            print(f"  [{i+1}] chat_id={e['chat_id']}: {(e.get('error_message') or 'unknown')[:120]}")

    print("\n" + "=" * 72)


def print_comparison(run_a: str, analysis_a: Dict, run_b: str, analysis_b: Dict):
    """打印两次评估的对比报告。"""
    print("\n" + "=" * 72)
    print(f"  📊 评估对比报告")
    print(f"  A: {run_a}")
    print(f"  B: {run_b}")
    print("=" * 72)

    metrics = [
        ("成功率", 
         f"{analysis_a['success_count']}/{analysis_a['total']}",
         f"{analysis_b['success_count']}/{analysis_b['total']}"),
        ("平均相似度",
         f"{analysis_a['avg_similarity']:.2%}",
         f"{analysis_b['avg_similarity']:.2%}"),
        ("平均长度比",
         f"{analysis_a['avg_length_ratio']:.2%}",
         f"{analysis_b['avg_length_ratio']:.2%}"),
        ("平均耗时",
         f"{analysis_a['avg_duration_ms']:.0f}ms",
         f"{analysis_b['avg_duration_ms']:.0f}ms"),
    ]

    print(f"\n{'指标':<12} {'A':<20} {'B':<20} {'对比'}")
    print("-" * 60)
    for name, val_a, val_b in metrics:
        print(f"  {name:<10} {val_a:<18} {val_b:<18}")

    print("\n" + "=" * 72)


def export_samples_md(results: List[Dict], filepath: str):
    """导出样例为 Markdown 格式。"""
    success = [r for r in results if r["status"] == "success" and r.get("ai_reply") and r.get("human_reply")]

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# 评估样例报告\n\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"总数: {len(success)}\n\n")
        f.write("---\n\n")

        for i, r in enumerate(success):
            sim = jaccard_similarity(r["ai_reply"], r["human_reply"])
            f.write(f"## 样例 {i+1} (相似度: {sim:.2%})\n\n")
            f.write(f"**chat_id**: `{r['chat_id']}`\n\n")

            # 上下文
            if r.get("context_messages"):
                ctx = r["context_messages"] if isinstance(r["context_messages"], list) else []
                if ctx:
                    f.write(f"### 上下文\n\n")
                    for cm in ctx[-5:]:  # 最多 5 条上下文
                        role = "👤 用户" if cm["role"] == "user" else "🧑 客服"
                        f.write(f"> {role}: {cm['content']}\n\n")

            f.write(f"### 用户消息\n\n")
            f.write(f"{r['user_message']}\n\n")

            f.write(f"### 人类回复\n\n")
            f.write(f"{r['human_reply']}\n\n")

            f.write(f"### AI 回复\n\n")
            f.write(f"{r['ai_reply']}\n\n")

            if r.get("ai_tool_calls"):
                calls = r["ai_tool_calls"] if isinstance(r["ai_tool_calls"], list) else []
                if calls:
                    f.write(f"### 工具调用\n\n")
                    for tc in calls:
                        f.write(f"- `{tc.get('name', '?')}`: `{json.dumps(tc.get('args', {}), ensure_ascii=False)}`\n")
                    f.write("\n")

            f.write("---\n\n")

    logger.info(f"✅ 样例已导出到 {filepath}")


def export_json(results: List[Dict], filepath: str):
    """导出结果为 JSON。"""
    clean_results = []
    for r in results:
        clean = {}
        for k, v in r.items():
            if k.startswith("_"):
                continue
            if isinstance(v, datetime):
                clean[k] = v.isoformat()
            else:
                clean[k] = v
        clean_results.append(clean)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(clean_results, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"✅ 结果已导出到 {filepath}")


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Eval Analyze - 评估结果分析工具")
    parser.add_argument("--run-id", type=str, default=None, help="分析指定 run_id")
    parser.add_argument("--compare", nargs=2, metavar=("RUN_A", "RUN_B"), help="对比两次评估")
    parser.add_argument("--list-runs", action="store_true", help="列出最近的评估运行")
    parser.add_argument("--export", type=str, default=None, help="导出为 JSON 文件")
    parser.add_argument("--export-samples", type=str, default=None, help="导出样例为 Markdown")
    args = parser.parse_args()

    from ai_kefu.config.settings import settings
    conn = get_db_connection(settings)

    # 列出 runs
    if args.list_runs:
        runs = list_runs(conn)
        if not runs:
            print("没有找到评估记录。")
            return
        print(f"\n{'run_id':<40} {'tag':<20} {'model':<15} {'total':>5} {'ok':>4} {'err':>4} {'avg_ms':>8} {'time'}")
        print("-" * 120)
        for r in runs:
            print(
                f"  {r['run_id']:<38} {(r.get('tag') or ''):<18} "
                f"{(r.get('ai_model') or ''):<13} {r['total']:>5} "
                f"{int(r.get('success_count') or 0):>4} {int(r.get('error_count') or 0):>4} "
                f"{r.get('avg_duration_ms', 0):>8.0f} {r.get('started_at', '')}"
            )
        return

    # 对比模式
    if args.compare:
        run_a_id, run_b_id = args.compare
        results_a = fetch_run_results(conn, run_a_id)
        results_b = fetch_run_results(conn, run_b_id)
        if not results_a:
            print(f"run_id '{run_a_id}' 未找到结果。")
            return
        if not results_b:
            print(f"run_id '{run_b_id}' 未找到结果。")
            return
        analysis_a = analyze_run(results_a)
        analysis_b = analyze_run(results_b)
        print_comparison(run_a_id, analysis_a, run_b_id, analysis_b)
        return

    # 单次分析
    run_id = args.run_id or get_latest_run_id(conn)
    if not run_id:
        print("没有找到评估记录。请先运行 eval_replay。")
        return

    results = fetch_run_results(conn, run_id)
    if not results:
        print(f"run_id '{run_id}' 未找到结果。")
        return

    tag = results[0].get("tag", "")
    analysis = analyze_run(results)
    print_report(run_id, tag, analysis)

    # 导出
    if args.export:
        export_json(results, args.export)

    if args.export_samples:
        export_samples_md(results, args.export_samples)

    conn.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
XianyuAutoAgent — Database restore script (Python版)
用 PyMySQL 连接，绕过本地 mysql 客户端的版本兼容问题。

Usage:
    python restore.py                          # 从 ../.env 读取配置
    python restore.py --host 127.0.0.1 --port 3306 --user root --password xxx
    python restore.py --sql /path/to/dump.sql
    python restore.py --env /path/to/.env
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

try:
    import pymysql
    import pymysql.cursors
except ImportError:
    sys.exit("❌  缺少 pymysql，请先激活项目 venv：source .venv/bin/activate")

# ── 默认值 ────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
DEFAULT_SQL  = SCRIPT_DIR / "xianyu_conversations.sql"
DEFAULT_ENV  = SCRIPT_DIR.parent / ".env"   # ai_kefu/.env
DEFAULT_HOST = "192.168.50.132"
DEFAULT_PORT = 33601
DEFAULT_USER = "root"
DEFAULT_PASS = "Xs527215!!!"
DEFAULT_DB   = "xianyu_conversations"


def load_env(path: Path) -> dict:
    """读取 .env 文件，返回 key→value 字典（忽略注释和空行）。"""
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 去掉行内注释，再 strip
        line = re.sub(r"\s*#.*$", "", line).strip()
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


def parse_args():
    p = argparse.ArgumentParser(description="XianyuAutoAgent DB restore (Python)")
    p.add_argument("--sql",      default=str(DEFAULT_SQL))
    p.add_argument("--env",      default=str(DEFAULT_ENV))
    p.add_argument("--host",     default=None)
    p.add_argument("--port",     type=int, default=None)
    p.add_argument("--user",     default=None)
    p.add_argument("--password", default=None)
    p.add_argument("--db",       default=None)
    return p.parse_args()


def get_connection(host, port, user, password, db=None):
    kwargs = dict(
        host=host, port=port, user=user, password=password,
        charset="utf8mb4",
        connect_timeout=10,
    )
    if db:
        kwargs["db"] = db
    return pymysql.connect(**kwargs)


def run_sql_file(conn, sql_path: Path, db_name: str):
    """逐条执行 SQL 文件中的语句，并显示进度。"""
    total_size = sql_path.stat().st_size
    processed  = 0
    stmt_count = 0
    last_pct   = -1

    with conn.cursor() as cur:
        cur.execute(f"USE `{db_name}`;")

        buf = ""
        with sql_path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                processed += len(line.encode("utf-8", errors="replace"))
                # 跳过注释行
                stripped = line.strip()
                if stripped.startswith("--") or stripped.startswith("#") or not stripped:
                    continue

                buf += line

                # 以分号结尾表示语句完整
                if stripped.endswith(";"):
                    try:
                        cur.execute(buf)
                        stmt_count += 1
                        # 每执行 500 条提交一次，避免超大事务
                        if stmt_count % 500 == 0:
                            conn.commit()
                    except pymysql.err.OperationalError as e:
                        # 忽略"已存在"类错误，其余抛出
                        if e.args[0] not in (1007, 1050):
                            raise
                    buf = ""

                    # 进度显示
                    pct = int(processed / total_size * 100)
                    if pct != last_pct and pct % 5 == 0:
                        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                        print(f"\r   [{bar}] {pct:3d}%  ({stmt_count} stmts)", end="", flush=True)
                        last_pct = pct

        conn.commit()
    print()  # 换行
    return stmt_count


def main():
    args = parse_args()

    # ── 加载 .env ───────────────────────────────────────────────
    env = load_env(Path(args.env))

    host     = args.host     or env.get("MYSQL_HOST",     DEFAULT_HOST)
    port     = args.port     or int(env.get("MYSQL_PORT", DEFAULT_PORT))
    user     = args.user     or env.get("MYSQL_USER",     DEFAULT_USER)
    password = args.password or env.get("MYSQL_PASSWORD", DEFAULT_PASS)
    db_name  = args.db       or env.get("MYSQL_DATABASE", DEFAULT_DB)
    sql_file = Path(args.sql)

    # ── 打印摘要 ────────────────────────────────────────────────
    size_mb = sql_file.stat().st_size / 1024 / 1024 if sql_file.exists() else 0
    print("=" * 50)
    print(" XianyuAutoAgent Database Restore (Python)")
    print("=" * 50)
    print(f" SQL file : {sql_file} ({size_mb:.1f}M)")
    print(f" Database : {db_name}")
    print(f" Host     : {host}:{port}")
    print("-" * 50)

    # ── 检查 SQL 文件 ───────────────────────────────────────────
    if not sql_file.exists():
        sys.exit(f"❌  SQL dump 不存在：{sql_file}")

    # ── Step 1: 连接测试 ────────────────────────────────────────
    print("🔍  测试数据库连接...")
    try:
        conn = get_connection(host, port, user, password)
    except pymysql.err.OperationalError as e:
        print(f"❌  连接失败：{e}")
        sys.exit(1)
    print("✅  连接成功")

    # ── Step 2: 建库 ────────────────────────────────────────────
    print(f"🗄️   确认数据库 '{db_name}' 存在...")
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
        )
    conn.commit()
    conn.close()
    print("✅  数据库就绪")

    # ── Step 3: 导入 ────────────────────────────────────────────
    print("📥  导入 SQL dump（可能需要一点时间）...")
    conn = get_connection(host, port, user, password, db=db_name)
    t0 = time.time()
    try:
        stmt_count = run_sql_file(conn, sql_file, db_name)
    finally:
        conn.close()
    elapsed = time.time() - t0
    print(f"✅  导入完成：{stmt_count} 条语句，耗时 {elapsed:.1f}s")

    # ── Step 4: 验证 ────────────────────────────────────────────
    print("📊  各表行数统计：")
    conn = get_connection(host, port, user, password, db=db_name)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, table_rows "
            "FROM information_schema.tables "
            f"WHERE table_schema = '{db_name}' "
            "ORDER BY table_name;"
        )
        rows = cur.fetchall()
    conn.close()

    if rows:
        col_w = max(len(r[0]) for r in rows) + 2
        print(f"   {'TABLE':<{col_w}} ROWS")
        print(f"   {'-'*col_w} --------")
        for table, cnt in rows:
            print(f"   {table:<{col_w}} {cnt}")
    else:
        print("   （无表数据）")

    print("=" * 50)
    print("🎉  恢复成功！")
    print()
    print("后续步骤：")
    print("  1. 确认 ai_kefu/.env 中 MYSQL_HOST/PORT/USER/PASSWORD 正确")
    print("  3. 启动应用：make run")
    print("=" * 50)


if __name__ == "__main__":
    main()

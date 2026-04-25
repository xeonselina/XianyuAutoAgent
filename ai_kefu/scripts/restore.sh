#!/usr/bin/env bash
# =============================================================
# XianyuAutoAgent — One-click database restore script
# Usage:
#   ./restore.sh                        # use defaults from .env
#   ./restore.sh --container my-mysql   # custom Docker container name
#   ./restore.sh --host 127.0.0.1 --port 3306 --user root --password 123456
#   ./restore.sh --no-docker            # target machine has local mysql client
# =============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SQL_FILE="$SCRIPT_DIR/xianyu_conversations.sql"
ENV_FILE="$SCRIPT_DIR/.env"

# ── Defaults (overridable via flags) ────────────────────────
CONTAINER="xianyu-mysql"
DB_HOST="192.168.50.132"
DB_PORT="33601"
DB_USER="root"
DB_PASSWORD="Xs527215!!!"
DB_NAME="xianyu_conversations"
USE_DOCKER=false   # set to false with --no-docker

# ── Load defaults from bundled .env ─────────────────────────
if [[ -f "$ENV_FILE" ]]; then
  while IFS='=' read -r key value; do
    # Strip comments and blanks
    [[ "$key" =~ ^[[:space:]]*# ]] && continue
    [[ -z "$key" ]] && continue
    key="${key// /}"
    value="${value%%#*}"          # strip inline comments
    value="${value%"${value##*[![:space:]]}"}"  # rtrim
    case "$key" in
      MYSQL_HOST)     DB_HOST="$value" ;;
      MYSQL_PORT)     DB_PORT="$value" ;;
      MYSQL_USER)     DB_USER="$value" ;;
      MYSQL_PASSWORD) DB_PASSWORD="$value" ;;
      MYSQL_DATABASE) DB_NAME="$value" ;;
    esac
  done < "$ENV_FILE"
fi

# ── Parse CLI flags ──────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --container) CONTAINER="$2"; shift 2 ;;
    --host)      DB_HOST="$2";   shift 2 ;;
    --port)      DB_PORT="$2";   shift 2 ;;
    --user)      DB_USER="$2";   shift 2 ;;
    --password)  DB_PASSWORD="$2"; shift 2 ;;
    --db)        DB_NAME="$2";   shift 2 ;;
    --no-docker) USE_DOCKER=false; shift ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

# ── Sanity checks ────────────────────────────────────────────
if [[ ! -f "$SQL_FILE" ]]; then
  echo "❌  SQL dump not found: $SQL_FILE"
  exit 1
fi

echo "=================================================="
echo " XianyuAutoAgent Database Restore"
echo "=================================================="
echo " SQL file : $SQL_FILE ($(du -sh "$SQL_FILE" | cut -f1))"
echo " Database : $DB_NAME"
if $USE_DOCKER; then
  echo " Method   : docker exec → container '$CONTAINER'"
else
  echo " Method   : local mysql client"
  echo " Host     : $DB_HOST:$DB_PORT"
fi
echo "--------------------------------------------------"

# ── Helper: run a mysql command ──────────────────────────────
run_mysql() {
  local sql="$1"
  if $USE_DOCKER; then
    docker exec -i "$CONTAINER" \
      mysql -u"$DB_USER" -p"$DB_PASSWORD" \
      -e "$sql" 2>/dev/null
  else
    mysql -h"$DB_HOST" -P"$DB_PORT" -u"$DB_USER" -p"$DB_PASSWORD" \
      -e "$sql" 2>/dev/null
  fi
}

# ── Step 1: Check connectivity ───────────────────────────────
echo "🔍  Testing database connection..."
if ! run_mysql "SELECT 1;" > /dev/null 2>&1; then
  if $USE_DOCKER; then
    echo "❌  Cannot connect to MySQL in container '$CONTAINER'."
    echo "    Make sure the container is running: docker ps | grep $CONTAINER"
  else
    echo "❌  Cannot connect to MySQL at $DB_HOST:$DB_PORT."
  fi
  exit 1
fi
echo "✅  Connection OK"

# ── Step 2: Create database if missing ──────────────────────
echo "🗄️   Ensuring database '$DB_NAME' exists..."
run_mysql "CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" > /dev/null
echo "✅  Database ready"

# ── Step 3: Restore dump ─────────────────────────────────────
echo "📥  Importing SQL dump (this may take a moment)..."
if $USE_DOCKER; then
  docker exec -i "$CONTAINER" \
    mysql -u"$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" \
    < "$SQL_FILE"
else
  mysql -h"$DB_HOST" -P"$DB_PORT" -u"$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" \
    < "$SQL_FILE"
fi
echo "✅  Import complete"

# ── Step 4: Quick verification ───────────────────────────────
echo "📊  Table row counts:"
if $USE_DOCKER; then
  docker exec -i "$CONTAINER" \
    mysql -u"$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" \
    -e "
      SELECT table_name, table_rows
      FROM information_schema.tables
      WHERE table_schema = '$DB_NAME'
      ORDER BY table_name;
    " 2>/dev/null
else
  mysql -h"$DB_HOST" -P"$DB_PORT" -u"$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" \
    -e "
      SELECT table_name, table_rows
      FROM information_schema.tables
      WHERE table_schema = '$DB_NAME'
      ORDER BY table_name;
    " 2>/dev/null
fi

echo "=================================================="
echo "🎉  Restore finished successfully!"
echo ""
echo "Next steps:"
echo "  1. Copy .env to your project's ai_kefu/ directory"
echo "  2. Update .env MYSQL_HOST/PORT/USER/PASSWORD if different"
echo "  3. Start the application: make run"
echo "=================================================="

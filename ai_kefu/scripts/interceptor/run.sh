#!/usr/bin/env bash
# =============================================================
#  闲鱼拦截器启动脚本
#  自动激活虚拟环境后运行 run_xianyu.py
#
#  压缩包解压后目录结构：
#    xianyu-interceptor-*/
#    ├── install.sh        ← 本脚本和 install.sh 都在根目录
#    ├── run.sh
#    └── ai_kefu/
#        ├── run_xianyu.py
#        ├── xianyu_interceptor/
#        └── ...
# =============================================================
set -euo pipefail

ARCHIVE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ARCHIVE_ROOT/.venv-interceptor"
VENV_PY="$VENV_DIR/bin/python"
MAIN_SCRIPT="$ARCHIVE_ROOT/ai_kefu/run_xianyu.py"

if [[ ! -f "$VENV_PY" ]]; then
    echo "[ERROR] 虚拟环境未找到: $VENV_DIR"
    echo "        请先运行: ./install.sh"
    exit 1
fi

if [[ ! -f "$ARCHIVE_ROOT/ai_kefu/.env" ]]; then
    echo "[WARN]  ai_kefu/.env 文件不存在，将使用默认配置"
fi

echo "[INFO]  启动闲鱼消息拦截器..."
echo "[INFO]  Python: $VENV_PY"
echo ""

# ARCHIVE_ROOT 作为 PYTHONPATH：
#   使 'import ai_kefu' 和 'import xianyu_interceptor' 均可正常解析
export PYTHONPATH="$ARCHIVE_ROOT:${PYTHONPATH:-}"

exec "$VENV_PY" "$MAIN_SCRIPT" "$@"

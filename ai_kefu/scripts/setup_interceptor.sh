#!/usr/bin/env bash
# =============================================================
#  闲鱼拦截器一键安装脚本
#  用法：bash setup_interceptor.sh
# =============================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[ OK]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERR ]${NC}  $*" >&2; }
step()    { echo -e "\n${GREEN}━━━ $* ━━━${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# 脚本放在 scripts/ 子目录时，项目根目录是上一级；
# 直接放在项目根目录时，项目根目录就是当前目录
if [[ -f "$SCRIPT_DIR/../run_xianyu.py" ]]; then
    PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
elif [[ -f "$SCRIPT_DIR/run_xianyu.py" ]]; then
    PROJECT_DIR="$SCRIPT_DIR"
else
    error "找不到 run_xianyu.py，请确认脚本与项目文件在同一目录或 scripts/ 子目录"
    exit 1
fi

cd "$PROJECT_DIR"
info "项目目录: $PROJECT_DIR"

# ── 检查 Python3 ──────────────────────────────────────────────
step "1/4  检查 Python 环境"
if ! command -v python3 &>/dev/null; then
    error "未找到 python3，请先安装 Python 3.10+"
    error "  brew install python  或从 https://www.python.org/downloads/ 下载"
    exit 1
fi
PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Python 版本: $PYTHON_VER"
success "Python 检查通过"

# ── 创建虚拟环境 ──────────────────────────────────────────────
step "2/4  创建虚拟环境"
if [[ ! -d ".venv" ]]; then
    info "创建 .venv ..."
    python3 -m venv .venv
    success "虚拟环境已创建"
else
    warn ".venv 已存在，跳过创建"
fi

source .venv/bin/activate
info "已激活虚拟环境: $(which python3)"

# ── 安装 Python 依赖 ──────────────────────────────────────────
step "3/4  安装 Python 依赖"
REQUIREMENTS="scripts/interceptor/requirements.interceptor.txt"
if [[ ! -f "$REQUIREMENTS" ]]; then
    # 兜底：用完整 requirements.txt
    REQUIREMENTS="requirements.txt"
    warn "未找到拦截器专用依赖文件，使用 $REQUIREMENTS"
fi
info "安装依赖: $REQUIREMENTS"
pip install --upgrade pip -q
pip install -r "$REQUIREMENTS"
success "Python 依赖安装完成"

# ── 安装 Playwright Chromium ──────────────────────────────────
step "4/4  安装 Playwright 浏览器"
info "下载 Chromium（约 200MB，首次安装需要几分钟）..."
python3 -m playwright install chromium
success "Chromium 安装完成"

# ── 检查 .env ─────────────────────────────────────────────────
echo ""
if [[ ! -f ".env" ]]; then
    if [[ -f ".env.example" ]]; then
        cp .env.example .env
        warn ".env 不存在，已从 .env.example 生成"
        warn "请编辑 .env，填入 COOKIES_STR 和其他必要配置后再启动"
    else
        warn ".env 和 .env.example 均不存在，请手动创建 .env"
    fi
else
    success ".env 已存在"
fi

# ── 完成 ──────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  安装完成！                                       ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  启动拦截器："
echo -e "    ${BLUE}source .venv/bin/activate${NC}"
echo -e "    ${BLUE}python3 run_xianyu.py${NC}"
echo ""
echo -e "  或直接一行："
echo -e "    ${BLUE}.venv/bin/python3 run_xianyu.py${NC}"
echo ""

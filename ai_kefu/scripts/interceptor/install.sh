#!/usr/bin/env bash
# =============================================================
#  闲鱼拦截器 — macOS 一键安装脚本
#  适用：全新 Mac，不保证已有 Python / Node.js / Playwright
#
#  用法：
#    chmod +x install.sh && ./install.sh
#
#  安装内容：
#    1. Homebrew（如未安装）
#    2. Python 3.11（通过 pyenv，不污染系统 Python）
#    3. Node.js 20 LTS（Playwright 签名算法依赖）
#    4. Python 虚拟环境 + 依赖包
#    5. Playwright Chromium 浏览器
#    6. .env 配置文件（从模板复制）
# =============================================================
set -euo pipefail

# ── 颜色输出 ──────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[ OK]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERR ]${NC}  $*" >&2; }
step()    { echo -e "\n${GREEN}━━━ $* ━━━${NC}"; }

# 脚本所在目录（即压缩包解压后的根目录）
ARCHIVE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ARCHIVE_ROOT/.venv-interceptor"
PYTHON_MIN_MINOR=10      # 最低要求 Python 3.10
PYTHON_PREFERRED="3.11"  # 优先安装版本
NODE_MIN=18

# =============================================================
# 步骤 0：系统检查
# =============================================================
step "0/5  系统检查"
if [[ "$(uname)" != "Darwin" ]]; then
    error "此脚本仅适用于 macOS（当前: $(uname)）"
    exit 1
fi
ARCH="$(uname -m)"
info "macOS $(sw_vers -productVersion)  架构: $ARCH"

# =============================================================
# 步骤 1：Homebrew
# =============================================================
step "1/5  Homebrew"
if command -v brew &>/dev/null; then
    success "已安装: $(brew --version | head -1)"
else
    warn "未检测到 Homebrew，开始安装..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if [[ "$ARCH" == "arm64" ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
        grep -q 'homebrew/bin/brew shellenv' "$HOME/.zprofile" 2>/dev/null \
            || echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> "$HOME/.zprofile"
    fi
    success "Homebrew 安装完成"
fi

# =============================================================
# 步骤 2：Python 3.10+
# =============================================================
step "2/5  Python $PYTHON_PREFERRED"

PYTHON_BIN=""
# 优先找 brew / 系统已有的满足版本
for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        _minor=$("$candidate" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo 0)
        _major=$("$candidate" -c "import sys; print(sys.version_info.major)" 2>/dev/null || echo 0)
        if [[ "$_major" == "3" && "$_minor" -ge "$PYTHON_MIN_MINOR" ]]; then
            PYTHON_BIN="$(command -v "$candidate")"
            success "检测到可用 Python: $PYTHON_BIN ($("$PYTHON_BIN" --version))"
            break
        fi
    fi
done

if [[ -z "$PYTHON_BIN" ]]; then
    info "未找到 Python 3.$PYTHON_MIN_MINOR+，通过 pyenv 安装 Python $PYTHON_PREFERRED"
    if ! command -v pyenv &>/dev/null; then
        brew install pyenv
        SHELL_RC="${ZDOTDIR:-$HOME}/.zshrc"
        grep -q 'pyenv init' "$SHELL_RC" 2>/dev/null || {
            printf '\nexport PYENV_ROOT="$HOME/.pyenv"\nexport PATH="$PYENV_ROOT/bin:$PATH"\neval "$(pyenv init -)"\n' >> "$SHELL_RC"
        }
        export PYENV_ROOT="$HOME/.pyenv"
        export PATH="$PYENV_ROOT/bin:$PATH"
        eval "$(pyenv init -)"
    fi
    pyenv install -s "$PYTHON_PREFERRED"
    # 找到刚装好的 Python
    PYTHON_BIN="$(pyenv root)/versions/$(pyenv versions --bare | grep "^${PYTHON_PREFERRED}" | tail -1)/bin/python3"
    [[ -x "$PYTHON_BIN" ]] || { error "pyenv 安装后未找到 Python 可执行文件"; exit 1; }
    success "Python 安装完成: $PYTHON_BIN"
fi

# =============================================================
# 步骤 3：Node.js 18+ (PyExecJS 运行时)
# =============================================================
step "3/5  Node.js $NODE_MIN+ (PyExecJS 运行时)"

NODE_OK=false
if command -v node &>/dev/null; then
    _nv=$(node --version | sed 's/v//' | cut -d. -f1)
    if [[ "$_nv" -ge "$NODE_MIN" ]]; then
        success "已安装: $(node --version)"; NODE_OK=true
    else
        warn "版本过旧 ($(node --version))，需要 >= $NODE_MIN"
    fi
fi
if ! $NODE_OK; then
    info "通过 Homebrew 安装 node@20..."
    brew install node@20
    NODE_BIN_DIR="$(brew --prefix node@20)/bin"
    export PATH="$NODE_BIN_DIR:$PATH"
    SHELL_RC="${ZDOTDIR:-$HOME}/.zshrc"
    grep -q "node@20" "$SHELL_RC" 2>/dev/null \
        || echo "export PATH=\"$NODE_BIN_DIR:\$PATH\"" >> "$SHELL_RC"
    success "Node.js 安装完成: $(node --version)"
fi

# =============================================================
# 步骤 4：Python 虚拟环境 + 依赖
# =============================================================
step "4/5  Python 虚拟环境 + 依赖"

REQ_FILE="$ARCHIVE_ROOT/requirements.interceptor.txt"
[[ -f "$REQ_FILE" ]] || { error "依赖文件不存在: $REQ_FILE"; exit 1; }

if [[ -d "$VENV_DIR" ]]; then
    warn "虚拟环境已存在: $VENV_DIR"
    read -rp "  重新创建？[y/N] " _rb
    [[ "$_rb" =~ ^[Yy]$ ]] && rm -rf "$VENV_DIR" && info "已删除旧环境"
fi
if [[ ! -d "$VENV_DIR" ]]; then
    info "创建虚拟环境..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    success "虚拟环境: $VENV_DIR"
fi

"$VENV_DIR/bin/pip" install -q --upgrade pip
info "安装 Python 依赖（requirements.interceptor.txt）..."
"$VENV_DIR/bin/pip" install -q -r "$REQ_FILE"
success "Python 依赖安装完成"

# =============================================================
# 步骤 5：Playwright Chromium
# =============================================================
step "5/5  Playwright Chromium"

PW_BIN="$VENV_DIR/bin/playwright"
[[ -f "$PW_BIN" ]] || { error "playwright 未找到，步骤 4 可能失败"; exit 1; }
info "安装 Chromium（首次约 200MB）..."
"$PW_BIN" install chromium --with-deps 2>&1 | grep -E 'Downloading|Error|chromium' || true
success "Playwright Chromium 安装完成"

# =============================================================
# 配置 .env
# =============================================================
ENV_FILE="$ARCHIVE_ROOT/ai_kefu/.env"
ENV_EXAMPLE="$ARCHIVE_ROOT/ai_kefu/.env.example"
if [[ -f "$ENV_FILE" ]]; then
    success ".env 已存在，跳过"
else
    if [[ -f "$ENV_EXAMPLE" ]]; then
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        success ".env 已从模板创建: $ENV_FILE"
    else
        cat > "$ENV_FILE" <<'ENVEOF'
# ============================================================
# 闲鱼拦截器最小配置
# ============================================================

# 【可选】闲鱼 Cookie（首次可留空，启动后手动扫码登录）
COOKIES_STR=

# 【必填】AI API 后台地址（运行 API 后台的机器地址）
AGENT_SERVICE_URL=http://localhost:8000

# 是否启用 AI 自动回复
ENABLE_AI_REPLY=false

# 浏览器是否无头（Mac 建议 false，保持显示窗口便于扫码）
BROWSER_HEADLESS=false

# ── 以下为 API 后台字段，拦截器本身不使用，但配置加载时需要非空值 ──
API_KEY=not-used-by-interceptor
RENTAL_API_BASE_URL=http://localhost:8000
RENTAL_FIND_SLOT_ENDPOINT=/find-slot
ENVEOF
        warn "请编辑 $ENV_FILE，确认 AGENT_SERVICE_URL 指向正确的 API 后台"
    fi
fi

# 创建运行时目录
mkdir -p "$ARCHIVE_ROOT/ai_kefu/xianyu_images" "$ARCHIVE_ROOT/ai_kefu/logs"

# =============================================================
# 完成
# =============================================================
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  安装完成！                               ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${YELLOW}启动拦截器：${NC}"
echo -e "    ${BLUE}./run.sh${NC}"
echo ""
echo -e "  ${YELLOW}首次使用：${NC}"
echo -e "    1. 编辑 ${BLUE}ai_kefu/.env${NC}，确认 AGENT_SERVICE_URL"
echo -e "    2. 运行 ./run.sh，浏览器自动打开"
echo -e "    3. 在浏览器中扫码登录闲鱼"
echo -e "    4. 登录后拦截器自动开始监听消息"
echo ""

#!/usr/bin/env bash
# =============================================================
#  闲鱼拦截器 — 远端一键 Bootstrap 脚本
#
#  另一台 Mac 只需执行一行：
#    curl -fsSL https://raw.githubusercontent.com/xeonselina/XianyuAutoAgent/main/ai_kefu/scripts/interceptor/bootstrap.sh | bash
#
#  或者指定安装目录：
#    INSTALL_DIR=~/mydir bash <(curl -fsSL ...)
#
#  功能：
#    1. 拉取/更新 GitHub 代码（git clone 或 git pull）
#    2. 检查并安装 Homebrew（如未安装）
#    3. 检查并安装 Python 3.10+（如未满足）
#    4. 检查并安装 Node.js 18+（如未安装）
#    5. 创建/复用虚拟环境（已存在则跳过）
#    6. 安装 Python 依赖（已安装则跳过，仅 --upgrade 缺失包）
#    7. 安装 Playwright Chromium（已安装则跳过）
#    8. 初始化 .env（已有则跳过）
# =============================================================
set -euo pipefail

# ── 颜色输出 ──────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[ OK ]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERR ]${NC}  $*" >&2; }
step()    { echo -e "\n${GREEN}━━━ $* ━━━${NC}"; }
skip()    { echo -e "${YELLOW}[SKIP]${NC}  $*"; }

# ── 配置 ──────────────────────────────────────────────────────
REPO_URL="https://github.com/xeonselina/XianyuAutoAgent.git"
REPO_BRANCH="main"
INSTALL_DIR="${INSTALL_DIR:-$HOME/xianyu-interceptor}"
AI_KEFU_DIR="$INSTALL_DIR/ai_kefu"
VENV_DIR="$INSTALL_DIR/.venv-interceptor"
REQ_FILE="$AI_KEFU_DIR/scripts/interceptor/requirements.interceptor.txt"

PYTHON_MIN_MINOR=10
PYTHON_PREFERRED="3.11"
NODE_MIN=18

# ── 系统检查 ──────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║      闲鱼消息拦截器  Bootstrap                  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""

if [[ "$(uname)" != "Darwin" ]]; then
    error "此脚本仅适用于 macOS（当前: $(uname)）"
    exit 1
fi
ARCH="$(uname -m)"
info "macOS $(sw_vers -productVersion)  架构: $ARCH"
info "安装目录: $INSTALL_DIR"

# =============================================================
# 步骤 1：Homebrew
# =============================================================
step "1/6  Homebrew"
if command -v brew &>/dev/null; then
    skip "已安装: $(brew --version | head -1)"
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
step "2/6  Python $PYTHON_PREFERRED"
PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        _minor=$("$candidate" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo 0)
        _major=$("$candidate" -c "import sys; print(sys.version_info.major)" 2>/dev/null || echo 0)
        if [[ "$_major" == "3" && "$_minor" -ge "$PYTHON_MIN_MINOR" ]]; then
            PYTHON_BIN="$(command -v "$candidate")"
            skip "已安装: $PYTHON_BIN ($("$PYTHON_BIN" --version))"
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
    PYTHON_BIN="$(pyenv root)/versions/$(pyenv versions --bare | grep "^${PYTHON_PREFERRED}" | tail -1)/bin/python3"
    [[ -x "$PYTHON_BIN" ]] || { error "pyenv 安装后未找到 Python 可执行文件"; exit 1; }
    success "Python 安装完成: $PYTHON_BIN"
fi

# =============================================================
# 步骤 3：Node.js 18+
# =============================================================
step "3/6  Node.js $NODE_MIN+ (PyExecJS 运行时)"
NODE_OK=false
if command -v node &>/dev/null; then
    _nv=$(node --version | sed 's/v//' | cut -d. -f1)
    if [[ "$_nv" -ge "$NODE_MIN" ]]; then
        skip "已安装: $(node --version)"; NODE_OK=true
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
# 步骤 4：拉取 / 更新代码
# =============================================================
step "4/6  代码同步 (GitHub)"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "检测到已有仓库，执行 git pull..."
    git -C "$INSTALL_DIR" fetch origin "$REPO_BRANCH"
    git -C "$INSTALL_DIR" reset --hard "origin/$REPO_BRANCH"
    success "代码已更新到最新版本"
else
    info "首次克隆 $REPO_URL ..."
    git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" "$INSTALL_DIR"
    success "代码已克隆到 $INSTALL_DIR"
fi

[[ -f "$REQ_FILE" ]] || { error "依赖文件不存在: $REQ_FILE"; exit 1; }

# =============================================================
# 步骤 5：Python 虚拟环境 + 依赖（有则跳过）
# =============================================================
step "5/6  Python 虚拟环境 + 依赖"

# 虚拟环境：没有才创建
if [[ -d "$VENV_DIR" && -f "$VENV_DIR/bin/python" ]]; then
    skip "虚拟环境已存在: $VENV_DIR"
else
    info "创建虚拟环境: $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    success "虚拟环境创建完成"
fi

# pip 升级
"$VENV_DIR/bin/pip" install -q --upgrade pip

# 依赖安装：用 --upgrade 补全缺失，已安装的包自动跳过（pip 不会重装已满足版本）
info "同步 Python 依赖（已满足的包自动跳过）..."
"$VENV_DIR/bin/pip" install -q --upgrade -r "$REQ_FILE"
success "Python 依赖同步完成"

# =============================================================
# 步骤 6：Playwright Chromium（已安装则跳过）
# =============================================================
step "6/6  Playwright Chromium"

PW_BIN="$VENV_DIR/bin/playwright"
[[ -f "$PW_BIN" ]] || { error "playwright 未找到，步骤 5 可能失败"; exit 1; }

# 检测 Chromium 是否已经装好（读取 playwright 内部路径）
CHROMIUM_INSTALLED=false
if "$PW_BIN" show-browsers 2>/dev/null | grep -q 'chromium'; then
    skip "Playwright Chromium 已安装"
    CHROMIUM_INSTALLED=true
fi

if ! $CHROMIUM_INSTALLED; then
    info "安装 Chromium（首次约 200MB，请耐心等待）..."
    "$PW_BIN" install chromium --with-deps 2>&1 | grep -E 'Downloading|Error|chromium' || true
    success "Playwright Chromium 安装完成"
fi

# =============================================================
# 初始化 .env
# =============================================================
ENV_FILE="$AI_KEFU_DIR/.env"
ENV_EXAMPLE="$AI_KEFU_DIR/.env.example"

if [[ -f "$ENV_FILE" ]]; then
    skip ".env 已存在，保留原有配置: $ENV_FILE"
else
    if [[ -f "$ENV_EXAMPLE" ]]; then
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        success ".env 已从模板创建"
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
        success ".env 已生成"
    fi
    warn "请编辑 $ENV_FILE，确认 AGENT_SERVICE_URL 指向正确的 API 后台"
fi

# 创建运行时目录
mkdir -p "$AI_KEFU_DIR/xianyu_images" "$AI_KEFU_DIR/logs"

# =============================================================
# 生成启动快捷脚本（放在安装目录根）
# =============================================================
RUN_SCRIPT="$INSTALL_DIR/run.sh"
cat > "$RUN_SCRIPT" <<RUNEOF
#!/usr/bin/env bash
# 启动闲鱼消息拦截器
set -euo pipefail
INSTALL_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="\$INSTALL_DIR/.venv-interceptor/bin/python"
MAIN_SCRIPT="\$INSTALL_DIR/ai_kefu/run_xianyu.py"

if [[ ! -f "\$VENV_PY" ]]; then
    echo "[ERROR] 虚拟环境未找到，请先运行 bootstrap.sh"
    exit 1
fi

export PYTHONPATH="\$INSTALL_DIR:\${PYTHONPATH:-}"
echo "[INFO]  启动闲鱼消息拦截器..."
exec "\$VENV_PY" "\$MAIN_SCRIPT" "\$@"
RUNEOF
chmod +x "$RUN_SCRIPT"

# =============================================================
# 完成
# =============================================================
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Bootstrap 完成！                                ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${YELLOW}安装目录：${NC} $INSTALL_DIR"
echo ""
echo -e "  ${YELLOW}下次更新代码 + 同步依赖，直接重新运行：${NC}"
echo -e "    ${BLUE}curl -fsSL https://raw.githubusercontent.com/xeonselina/XianyuAutoAgent/main/ai_kefu/scripts/interceptor/bootstrap.sh | bash${NC}"
echo ""
echo -e "  ${YELLOW}启动拦截器：${NC}"
echo -e "    ${BLUE}$RUN_SCRIPT${NC}"
echo ""
echo -e "  ${YELLOW}首次使用：${NC}"
echo -e "    1. 编辑 ${BLUE}$ENV_FILE${NC}，确认 AGENT_SERVICE_URL"
echo -e "    2. 运行 run.sh，浏览器自动打开"
echo -e "    3. 在浏览器中扫码登录闲鱼"
echo ""

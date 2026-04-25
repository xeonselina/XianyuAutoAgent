#!/usr/bin/env bash
# =============================================================
#  一键部署脚本 — 更新群晖 NAS 上的 Docker 容器
#
#  功能：
#    1. SSH 到群晖 NAS
#    2. sudo docker pull 最新镜像（API + 控制台）
#    3. 停止并删除旧容器
#    4. 用新镜像重新启动容器
#
#  用法：
#    ./scripts/deploy_nas.sh [IMAGE_TAG]
#
#  示例：
#    ./scripts/deploy_nas.sh 20260424-0903
#    IMAGE_TAG=20260424-0903 make deploy-nas
#
#  依赖：
#    - sshpass（brew install sshpass）
# =============================================================
set -euo pipefail

# ── 颜色输出 ─────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[ OK]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERR ]${NC}  $*" >&2; }
step()    { echo -e "\n${GREEN}━━━ $* ━━━${NC}"; }

# ── 配置 ──────────────────────────────────────────────────────
NAS_HOST="192.168.50.132"
NAS_USER="xeon_pan"
NAS_PASS="oLwQpzUgXKae8Dae8UJC"
SUDO_PASS="$NAS_PASS"           # sudo 与 SSH 同一密码

REGISTRY="docker.cnb.cool/tdcc-demo/jimmy"
IMAGE_TAG="${1:-${IMAGE_TAG:-}}"

API_IMAGE="$REGISTRY/aikefu-api"
CONSOLE_IMAGE="$REGISTRY/aikefu-console"

API_CONTAINER="aikefu-api"
CONSOLE_CONTAINER="aikefu-console"

API_PORT="8000"
CONSOLE_PORT="8080"

# ChromaDB 持久化 volume（向量索引数据，重启/重新部署后不丢失）
CHROMA_VOLUME="aikefu-chroma-data"

# .env 文件：本地路径 → NAS 上的存放位置（放在用户 home，无需 sudo 即可 scp）
LOCAL_ENV_FILE="$(dirname "$0")/../.env"
NAS_ENV_FILE_REMOTE="~/aikefu.env"            # scp 目标（~ 由 NAS shell 展开）
NAS_ENV_FILE_ABS="/var/services/homes/$NAS_USER/aikefu.env"  # docker run 用绝对路径

# ── 检查 IMAGE_TAG ────────────────────────────────────────────
if [[ -z "$IMAGE_TAG" ]]; then
    error "请指定 IMAGE_TAG。用法: $0 <tag>  或  IMAGE_TAG=<tag> make deploy-nas"
    error "示例: $0 20260424-0903"
    exit 1
fi

# ── 检查 sshpass ──────────────────────────────────────────────
if ! command -v sshpass &>/dev/null; then
    error "未找到 sshpass，请先安装: brew install sshpass"
    exit 1
fi

info "目标 NAS : $NAS_USER@$NAS_HOST"
info "API 镜像 : $API_IMAGE:$IMAGE_TAG"
info "控制台   : $CONSOLE_IMAGE:$IMAGE_TAG"
echo ""

# ── SSH ControlMaster：整个脚本复用同一条连接，只握手一次 ─────
SSH_CTRL_DIR="$(mktemp -d)"
SSH_CTRL_SOCK="$SSH_CTRL_DIR/ctrl.sock"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10 -o ControlMaster=auto -o ControlPath=$SSH_CTRL_SOCK -o ControlPersist=300"

# 预先建立 master 连接（后续所有 ssh 复用它，无需重复认证）
sshpass -p "$NAS_PASS" ssh $SSH_OPTS "$NAS_USER@$NAS_HOST" true

# 脚本退出时自动关闭 master 连接并清理临时目录
cleanup() { ssh -O exit -o ControlPath="$SSH_CTRL_SOCK" "$NAS_USER@$NAS_HOST" 2>/dev/null; rm -rf "$SSH_CTRL_DIR"; }
trap cleanup EXIT

# ── 辅助：在 NAS 上执行命令 ───────────────────────────────────
nas_run() {
    ssh $SSH_OPTS "$NAS_USER@$NAS_HOST" "$@"
}

# 带 sudo 执行（通过 echo 传密码给 sudo -S）
# 群晖 sudo 会清空 PATH，显式传入 /usr/local/bin 使 docker 可被找到
nas_sudo() {
    nas_run "echo '$SUDO_PASS' | sudo -S env PATH=/usr/local/bin:/usr/bin:/bin $*"
}

# ── 步骤 1：连通性测试 ────────────────────────────────────────
step "1/4  测试 SSH 连接"
nas_run "echo 'SSH OK'"
success "SSH 连通"

# ── 步骤 1.5：上传 .env 到 NAS ────────────────────────────────
step "2/4  同步 .env 配置"

if [[ ! -f "$LOCAL_ENV_FILE" ]]; then
    error "本地 .env 不存在：$LOCAL_ENV_FILE"
    exit 1
fi

# scp 上传（群晖禁用 sftp，改用 ssh stdin 重定向；复用 ControlMaster 连接）
nas_run "cat > $NAS_ENV_FILE_REMOTE" < "$LOCAL_ENV_FILE"
success ".env 已同步到 NAS → $NAS_ENV_FILE_ABS"

# ── 步骤 2：拉取新镜像 ────────────────────────────────────────
step "3/4  拉取 Docker 镜像"

info "拉取 API 镜像..."
nas_sudo "docker pull $API_IMAGE:$IMAGE_TAG"
success "API 镜像已拉取"

info "拉取控制台镜像..."
nas_sudo "docker pull $CONSOLE_IMAGE:$IMAGE_TAG"
success "控制台镜像已拉取"

# ── 步骤 3：停止并删除旧容器 ─────────────────────────────────
step "4/4  重启容器"

# 确保 ChromaDB volume 存在（首次创建，后续重用）
# 注意：不能在 nas_sudo 内部用 ||，否则 || 后面的命令会在没有 sudo/PATH 的情况下执行
nas_sudo "docker volume inspect $CHROMA_VOLUME" >/dev/null 2>&1 \
    || nas_sudo "docker volume create $CHROMA_VOLUME"
success "ChromaDB volume: $CHROMA_VOLUME"

# 停止容器（不存在时忽略错误）
nas_sudo "docker stop $API_CONTAINER 2>/dev/null || true"
nas_sudo "docker rm   $API_CONTAINER 2>/dev/null || true"
success "旧 API 容器已清除"

nas_sudo "docker stop $CONSOLE_CONTAINER 2>/dev/null || true"
nas_sudo "docker rm   $CONSOLE_CONTAINER 2>/dev/null || true"
success "旧控制台容器已清除"

# ── 步骤 4：启动新容器 ────────────────────────────────────────

info "启动 API 容器 ($API_CONTAINER)..."
nas_sudo "docker run -d \
    --name $API_CONTAINER \
    --restart unless-stopped \
    --network bridge \
    --env-file $NAS_ENV_FILE_ABS \
    -v $CHROMA_VOLUME:/workspace/ai_kefu/chroma_data \
    -p $API_PORT:8000 \
    $API_IMAGE:$IMAGE_TAG"
success "API 容器已启动 → http://$NAS_HOST:$API_PORT"

info "启动控制台容器 ($CONSOLE_CONTAINER)..."
nas_sudo "docker run -d \
    --name $CONSOLE_CONTAINER \
    --restart unless-stopped \
    --network bridge \
    --env-file $NAS_ENV_FILE_ABS \
    -p $CONSOLE_PORT:80 \
    $CONSOLE_IMAGE:$IMAGE_TAG"
success "控制台容器已启动 → http://$NAS_HOST:$CONSOLE_PORT"

# ── 收尾：显示容器状态 ────────────────────────────────────────
echo ""
nas_sudo "docker ps --filter name=$API_CONTAINER --filter name=$CONSOLE_CONTAINER --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  部署完成！                                       ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  API 后台  : ${BLUE}http://$NAS_HOST:$API_PORT${NC}"
echo -e "  管理控制台: ${BLUE}http://$NAS_HOST:$CONSOLE_PORT${NC}"
echo -e "  镜像版本  : ${YELLOW}$IMAGE_TAG${NC}"
echo ""

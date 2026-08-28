#!/usr/bin/env bash
set +x
set -euo pipefail

die() {
    printf 'nas transport: %s\n' "$1" >&2
    exit 1
}

usage() {
    printf 'usage: %s check|deploy|status|logs\n' "$0" >&2
    exit 2
}

file_mode() {
    local path="$1"
    local mode

    if mode=$(stat -c '%a' "$path" 2>/dev/null); then
        :
    elif mode=$(stat -f '%Lp' "$path" 2>/dev/null); then
        :
    else
        die "cannot read permissions for $path"
    fi
    printf '%s\n' "$mode"
}

require_mode_0600() {
    local path="$1"
    local mode

    [ -f "$path" ] || die "configuration file does not exist: $path"
    mode=$(file_mode "$path")
    [ "$mode" = "600" ] || die "$path must have mode 0600 (found $mode)"
}

load_config() {
    local path="$1"
    local line key value

    require_mode_0600 "$path"
    while IFS= read -r line || [ -n "$line" ]; do
        line=${line%$'\r'}
        case "$line" in
            ''|'#'*) continue ;;
            *=*) ;;
            *) die "invalid configuration line in $path" ;;
        esac

        key=${line%%=*}
        value=${line#*=}
        case "$key" in
            NAS_HOST)
                [ -n "$EXPLICIT_NAS_HOST" ] || printf -v NAS_HOST '%s' "$value"
                ;;
            NAS_USER)
                [ -n "$EXPLICIT_NAS_USER" ] || printf -v NAS_USER '%s' "$value"
                ;;
            NAS_PORT)
                [ -n "$EXPLICIT_NAS_PORT" ] || printf -v NAS_PORT '%s' "$value"
                ;;
            NAS_DEPLOY_DIR)
                [ -n "$EXPLICIT_NAS_DEPLOY_DIR" ] || printf -v NAS_DEPLOY_DIR '%s' "$value"
                ;;
            APP_ENV_FILE)
                [ -n "$EXPLICIT_APP_ENV_FILE" ] || printf -v APP_ENV_FILE '%s' "$value"
                ;;
            FRPC_CONTAINER)
                [ -n "$EXPLICIT_FRPC_CONTAINER" ] || printf -v FRPC_CONTAINER '%s' "$value"
                ;;
            FRPC_NETWORK)
                [ -n "$EXPLICIT_FRPC_NETWORK" ] || printf -v FRPC_NETWORK '%s' "$value"
                ;;
            NAS_PASS)
                [ -n "$PASSWORD_AUTH_WAS_SET" ] || printf -v NAS_PASS '%s' "$value"
                ;;
            SUDO_PASS)
                [ -n "$SUDO_SECRET_WAS_SET" ] || printf -v SUDO_PASS '%s' "$value"
                ;;
            SSH_KEY)
                [ -n "$EXPLICIT_SSH_KEY" ] || printf -v SSH_KEY '%s' "$value"
                ;;
            LOG_TAIL)
                [ -n "$EXPLICIT_LOG_TAIL" ] || printf -v LOG_TAIL '%s' "$value"
                ;;
            *) die "unsupported configuration key: $key" ;;
        esac
    done <"$path"
}

require_value() {
    local name="$1"
    local value="${!name:-}"

    [ -n "$value" ] || die "$name is required"
}

is_safe_absolute_path() {
    local path="$1"

    [[ "$path" =~ ^/[A-Za-z0-9._/-]+$ ]] || return 1
    case "$path/" in
        *'//'*) return 1 ;;
        *'/../'*|*'/./'*) return 1 ;;
    esac
    return 0
}

validate_config() {
    require_value NAS_HOST
    require_value NAS_USER
    require_value NAS_PORT
    require_value NAS_DEPLOY_DIR
    require_value APP_ENV_FILE
    require_value FRPC_CONTAINER
    require_value FRPC_NETWORK

    [[ "$NAS_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]] || die "NAS_HOST is invalid"
    [[ "$NAS_USER" =~ ^[A-Za-z_][A-Za-z0-9._-]*$ ]] || die "NAS_USER is invalid"
    [[ "$NAS_PORT" =~ ^[0-9]+$ ]] || die "NAS_PORT must contain only digits"
    [ "${#NAS_PORT}" -le 5 ] || die "NAS_PORT must be between 1 and 65535"
    [ "$NAS_PORT" -ge 1 ] && [ "$NAS_PORT" -le 65535 ] || \
        die "NAS_PORT must be between 1 and 65535"
    is_safe_absolute_path "$NAS_DEPLOY_DIR" || die "NAS_DEPLOY_DIR is invalid"
    is_safe_absolute_path "$APP_ENV_FILE" || die "APP_ENV_FILE is invalid"
    [[ "$FRPC_CONTAINER" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || \
        die "FRPC_CONTAINER is invalid"
    [[ "$FRPC_NETWORK" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || \
        die "FRPC_NETWORK is invalid"
    [[ "$LOG_TAIL" =~ ^[0-9]+$ ]] || die "LOG_TAIL must contain only digits"

    if [ -n "$SSH_KEY" ]; then
        [ -f "$SSH_KEY" ] || die "SSH_KEY is not a regular file"
    fi

    if [ "$ACTION" = "deploy" ]; then
        [ "$BACKUP_VERIFIED" = "backup-verified" ] || \
            die "BACKUP_VERIFIED must be exactly backup-verified"
        require_value IMAGE_REPOSITORY
        require_value IMAGE_TAG
        [[ "$IMAGE_REPOSITORY" =~ ^[A-Za-z0-9][A-Za-z0-9._:/-]*$ ]] || \
            die "IMAGE_REPOSITORY is invalid"
        [[ "$IMAGE_TAG" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]*$ ]] || \
            die "IMAGE_TAG is invalid"
        [ "${#IMAGE_TAG}" -le 128 ] || die "IMAGE_TAG is invalid"
        case "$IMAGE_REPOSITORY/" in
            *'//'*) die "IMAGE_REPOSITORY is invalid" ;;
            *'/../'*|*'/./'*) die "IMAGE_REPOSITORY is invalid" ;;
        esac
        IMAGE_REF="$IMAGE_REPOSITORY:$IMAGE_TAG"
        [[ "$IMAGE_REF" =~ ^[A-Za-z0-9][A-Za-z0-9._:/-]*$ ]] || \
            die "IMAGE_REF is invalid"
    else
        IMAGE_REF=""
    fi
}

ssh_command() {
    local remote_command="$1"

    if [ "${#SSH_PREFIX[@]}" -gt 0 ]; then
        "${SSH_PREFIX[@]}" ssh "${SSH_ARGS[@]}" "$SSH_TARGET" "$remote_command"
    else
        ssh "${SSH_ARGS[@]}" "$SSH_TARGET" "$remote_command"
    fi
}

upload() {
    local source="$1"
    local remote="$2"

    is_safe_absolute_path "$remote" || die "remote temporary path is invalid"
    ssh_command "umask 077; cat > '$remote'" <"$source"
}

sudo_remote() {
    local command="$1"

    if [ -n "$SUDO_PASSWORD" ]; then
        printf '%s\n' "$SUDO_PASSWORD" | ssh_command "sudo -S -p '' $command"
    else
        ssh_command "sudo -n $command" </dev/null
    fi
}

cleanup() {
    local status="$?"
    local cleanup_status=0

    trap - EXIT
    if [ -n "${REMOTE_COMPOSE_TMP:-}" ] && [ -n "${REMOTE_SCRIPT_TMP:-}" ]; then
        set +e
        ssh_command "rm -f -- '$REMOTE_COMPOSE_TMP' '$REMOTE_SCRIPT_TMP'" </dev/null
        cleanup_status="$?"
        set -e
    fi
    if [ "$status" -eq 0 ] && [ "$cleanup_status" -ne 0 ]; then
        status="$cleanup_status"
    fi
    exit "$status"
}

[ "$#" -eq 1 ] || usage
ACTION="$1"
case "$ACTION" in
    check|deploy|status|logs) ;;
    *) usage ;;
esac

# Record which values were supplied by the process environment before reading
# the repository-external configuration file. Explicit values, including empty
# ones, take precedence over file values.
EXPLICIT_NAS_HOST="${NAS_HOST+x}"
EXPLICIT_NAS_USER="${NAS_USER+x}"
EXPLICIT_NAS_PORT="${NAS_PORT+x}"
EXPLICIT_NAS_DEPLOY_DIR="${NAS_DEPLOY_DIR+x}"
EXPLICIT_APP_ENV_FILE="${APP_ENV_FILE+x}"
EXPLICIT_FRPC_CONTAINER="${FRPC_CONTAINER+x}"
EXPLICIT_FRPC_NETWORK="${FRPC_NETWORK+x}"
PASSWORD_AUTH_WAS_SET="${NAS_PASS+x}"
SUDO_SECRET_WAS_SET="${SUDO_PASS+x}"
EXPLICIT_SSH_KEY="${SSH_KEY+x}"
EXPLICIT_LOG_TAIL="${LOG_TAIL+x}"

CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME:?HOME is required}/.config}"
CONFIG_FILE="$CONFIG_HOME/xianyu-agent/nas.env"
load_config "$CONFIG_FILE"

[ "${NAS_PORT+x}" = x ] || NAS_PORT=22
[ "${LOG_TAIL+x}" = x ] || LOG_TAIL=200
NAS_HOST="${NAS_HOST-}"
NAS_USER="${NAS_USER-}"
NAS_DEPLOY_DIR="${NAS_DEPLOY_DIR-}"
APP_ENV_FILE="${APP_ENV_FILE-}"
FRPC_CONTAINER="${FRPC_CONTAINER-}"
FRPC_NETWORK="${FRPC_NETWORK-}"
SSH_KEY="${SSH_KEY-}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY-}"
IMAGE_TAG="${IMAGE_TAG-}"
BACKUP_VERIFIED="${BACKUP_VERIFIED-}"

# Imported secret names must not remain in the environment inherited by ssh.
NAS_PASSWORD="${NAS_PASS-}"
SUDO_PASSWORD="${SUDO_PASS-}"
unset NAS_PASS SUDO_PASS SSHPASS

validate_config

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
LOCAL_COMPOSE="$PROJECT_DIR/deploy/nas/docker-compose.yml"
LOCAL_RELEASE_SCRIPT="$PROJECT_DIR/deploy/nas/remote_release.sh"
[ -f "$LOCAL_COMPOSE" ] || die "local Compose asset is missing"
[ -f "$LOCAL_RELEASE_SCRIPT" ] || die "local release script is missing"

command -v ssh >/dev/null 2>&1 || die "ssh is unavailable"
SSH_ARGS=(-p "$NAS_PORT" -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)
if [ -n "$SSH_KEY" ]; then
    SSH_ARGS+=(-i "$SSH_KEY")
fi
if [ -n "$NAS_PASSWORD" ]; then
    command -v sshpass >/dev/null 2>&1 || die "NAS_PASS requires sshpass"
    export SSHPASS="$NAS_PASSWORD"
    NAS_PASSWORD=""
    SSH_PREFIX=(sshpass -e)
else
    SSH_PREFIX=()
fi
SSH_TARGET="$NAS_USER@$NAS_HOST"

REMOTE_HOME=$(ssh_command "printf '%s\\n' \"\$HOME\"" </dev/null)
is_safe_absolute_path "$REMOTE_HOME" || die "remote home path is invalid"
TEMP_ID="$$-$RANDOM"
REMOTE_COMPOSE_TMP="$REMOTE_HOME/.xianyu-agent-compose-$TEMP_ID.yml"
REMOTE_SCRIPT_TMP="$REMOTE_HOME/.xianyu-agent-remote_release-$TEMP_ID.sh"
is_safe_absolute_path "$REMOTE_COMPOSE_TMP" || die "remote Compose temp path is invalid"
is_safe_absolute_path "$REMOTE_SCRIPT_TMP" || die "remote script temp path is invalid"
trap cleanup EXIT

upload "$LOCAL_COMPOSE" "$REMOTE_COMPOSE_TMP"
upload "$LOCAL_RELEASE_SCRIPT" "$REMOTE_SCRIPT_TMP"

if [ "$ACTION" = "deploy" ]; then
    INSTALL_COMMAND="sh -c \"install -d -m 0755 '$NAS_DEPLOY_DIR' && install -m 0644 '$REMOTE_COMPOSE_TMP' '$NAS_DEPLOY_DIR/docker-compose.yml' && install -m 0755 '$REMOTE_SCRIPT_TMP' '$NAS_DEPLOY_DIR/remote_release.sh'\""
    sudo_remote "$INSTALL_COMMAND"
    RELEASE_PROGRAM="'$NAS_DEPLOY_DIR/remote_release.sh' '$ACTION'"
else
    RELEASE_PROGRAM="bash '$REMOTE_SCRIPT_TMP' '$ACTION'"
fi

RELEASE_COMMAND="env DEPLOY_DIR='$NAS_DEPLOY_DIR' APP_ENV_FILE='$APP_ENV_FILE' FRPC_CONTAINER='$FRPC_CONTAINER' FRPC_NETWORK='$FRPC_NETWORK' LOG_TAIL='$LOG_TAIL'"
if [ "$ACTION" = "deploy" ]; then
    RELEASE_COMMAND="$RELEASE_COMMAND IMAGE_REF='$IMAGE_REF' BACKUP_VERIFIED='$BACKUP_VERIFIED'"
fi
sudo_remote "$RELEASE_COMMAND $RELEASE_PROGRAM"

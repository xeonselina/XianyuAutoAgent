#!/usr/bin/env bash
set +x
set -euo pipefail

# Capture only the supported public credential inputs with shell builtins, then
# remove every credential name that could otherwise be inherited by the first
# external process (currently the configuration permission check).  In
# particular, unset the private aliases before assigning them so an exported
# alias supplied by a parent cannot retain its export attribute.
PASSWORD_AUTH_WAS_SET="${NAS_PASS+x}"
SUDO_SECRET_WAS_SET="${SUDO_PASS+x}"
unset NAS_PASSWORD SUDO_PASSWORD
NAS_PASSWORD="${NAS_PASS-}"
SUDO_PASSWORD="${SUDO_PASS-}"
unset NAS_PASS SUDO_PASS SSHPASS

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
            MIN_FREE_SPACE_MB)
                [ -n "$EXPLICIT_MIN_FREE_SPACE_MB" ] || printf -v MIN_FREE_SPACE_MB '%s' "$value"
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
    [[ "$MIN_FREE_SPACE_MB" =~ ^[1-9][0-9]*$ ]] && \
        [ "${#MIN_FREE_SPACE_MB}" -le 9 ] || \
        die "MIN_FREE_SPACE_MB must be a positive base-10 integer"

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
        # Keep SSHPASS scoped to the password helper and the ssh process it
        # launches.  It must not be exported by this shell or inherited by
        # checksum/configuration/cleanup children.
        SSHPASS="$NAS_PASSWORD" "${SSH_PREFIX[@]}" ssh "${SSH_ARGS[@]}" "$SSH_TARGET" "$remote_command"
    else
        ssh "${SSH_ARGS[@]}" "$SSH_TARGET" "$remote_command"
    fi
}

upload() {
    local source="$1"
    local remote="$2"

    is_safe_absolute_path "$remote" || die "remote temporary path is invalid"
    # noclobber makes the open used by the redirection fail if an attacker has
    # pre-created the predictable user-home pathname (including as a symlink).
    ssh_command "umask 077; set -C; cat > '$remote'" <"$source"
}

sudo_remote() {
    local command="$1"
    local root_command="sudo -n env -i PATH='/usr/local/bin:/usr/bin:/bin' HOME='/root' $command"

    if [ -n "$SUDO_PASSWORD" ]; then
        # Keep authentication and the action in the same remote shell so sudo
        # timestamp policies remain effective, but replace that shell's stdin
        # with /dev/null after validation. If sudo -v uses a cached timestamp or
        # NOPASSWD and leaves the here-string unread, exec closes that input
        # before the privileged command can start.
        ssh_command "sudo -S -p '' -v && exec </dev/null && $root_command" \
            <<<"$SUDO_PASSWORD"
        return
    fi

    # Passwordless actions also receive immediate EOF and the same minimal
    # DSM-compatible root environment.
    ssh_command "$root_command" </dev/null
}

cleanup() {
    local status="$?"
    local cleanup_status=0
    local current_cleanup_status

    trap - EXIT
    if [ -n "${ROOT_COMPOSE_STAGE:-}" ] && [ -n "${ROOT_RELEASE_STAGE:-}" ]; then
        set +e
        sudo_remote "rm -f -- '$ROOT_COMPOSE_STAGE' '$ROOT_RELEASE_STAGE'"
        current_cleanup_status="$?"
        set -e
        if [ "$cleanup_status" -eq 0 ]; then
            cleanup_status="$current_cleanup_status"
        fi
    fi
    if [ -n "${REMOTE_COMPOSE_TMP:-}" ] && [ -n "${REMOTE_SCRIPT_TMP:-}" ]; then
        set +e
        ssh_command "rm -f -- '$REMOTE_COMPOSE_TMP' '$REMOTE_SCRIPT_TMP'" </dev/null
        current_cleanup_status="$?"
        set -e
        if [ "$cleanup_status" -eq 0 ]; then
            cleanup_status="$current_cleanup_status"
        fi
    fi
    if [ "$status" -eq 0 ] && [ "$cleanup_status" -ne 0 ]; then
        status="$cleanup_status"
    fi
    exit "$status"
}

sha256_file() {
    local path="$1"
    local output digest

    if command -v sha256sum >/dev/null 2>&1; then
        output=$(sha256sum "$path") || die "cannot hash $path"
    elif command -v shasum >/dev/null 2>&1; then
        output=$(shasum -a 256 "$path") || die "cannot hash $path"
    else
        die "SHA-256 utility is unavailable"
    fi
    digest=${output%% *}
    [[ "$digest" =~ ^[A-Fa-f0-9]{64}$ ]] || die "cannot hash $path"
    printf '%s\n' "$digest"
}

[ "$#" -eq 1 ] || usage
ACTION="$1"
case "$ACTION" in
    check|deploy|status|logs) ;;
    *) usage ;;
esac

# Record which non-secret values were supplied by the process environment
# before reading the repository-external configuration file. Explicit values,
# including empty ones, take precedence over file values. Credential inputs
# were recorded and cleared before any external command at script start.
EXPLICIT_NAS_HOST="${NAS_HOST+x}"
EXPLICIT_NAS_USER="${NAS_USER+x}"
EXPLICIT_NAS_PORT="${NAS_PORT+x}"
EXPLICIT_NAS_DEPLOY_DIR="${NAS_DEPLOY_DIR+x}"
EXPLICIT_APP_ENV_FILE="${APP_ENV_FILE+x}"
EXPLICIT_FRPC_CONTAINER="${FRPC_CONTAINER+x}"
EXPLICIT_FRPC_NETWORK="${FRPC_NETWORK+x}"
EXPLICIT_SSH_KEY="${SSH_KEY+x}"
EXPLICIT_LOG_TAIL="${LOG_TAIL+x}"
EXPLICIT_MIN_FREE_SPACE_MB="${MIN_FREE_SPACE_MB+x}"

CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME:?HOME is required}/.config}"
CONFIG_FILE="$CONFIG_HOME/xianyu-agent/nas.env"
load_config "$CONFIG_FILE"

[ "${NAS_PORT+x}" = x ] || NAS_PORT=22
[ "${LOG_TAIL+x}" = x ] || LOG_TAIL=200
[ "${MIN_FREE_SPACE_MB+x}" = x ] || MIN_FREE_SPACE_MB=1024
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

# Values loaded from the local configuration are initially unexported because
# the public names were cleared above. Move them to aliases that are known to
# be unexported before another external command can run, then clear the public
# names again. Explicit environment credentials captured at startup win.
if [ -z "$PASSWORD_AUTH_WAS_SET" ]; then
    unset NAS_PASSWORD
    NAS_PASSWORD="${NAS_PASS-}"
fi
if [ -z "$SUDO_SECRET_WAS_SET" ]; then
    unset SUDO_PASSWORD
    SUDO_PASSWORD="${SUDO_PASS-}"
fi
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
ROOT_ASSET_DIR="$NAS_DEPLOY_DIR/.xianyu-agent-release"
ROOT_COMPOSE="$NAS_DEPLOY_DIR/docker-compose.yml"
ROOT_RELEASE_SCRIPT="$ROOT_ASSET_DIR/remote_release.sh"
ROOT_COMPOSE_STAGE="$ROOT_ASSET_DIR/.incoming-compose-$TEMP_ID.yml"
ROOT_RELEASE_STAGE="$ROOT_ASSET_DIR/.incoming-remote_release-$TEMP_ID.sh"
is_safe_absolute_path "$ROOT_ASSET_DIR" || die "root asset directory is invalid"
is_safe_absolute_path "$ROOT_COMPOSE" || die "root Compose path is invalid"
is_safe_absolute_path "$ROOT_RELEASE_SCRIPT" || die "root release script path is invalid"
is_safe_absolute_path "$ROOT_COMPOSE_STAGE" || die "root Compose staging path is invalid"
is_safe_absolute_path "$ROOT_RELEASE_STAGE" || die "root release staging path is invalid"
trap cleanup EXIT

COMPOSE_SHA256=$(sha256_file "$LOCAL_COMPOSE")
RELEASE_SCRIPT_SHA256=$(sha256_file "$LOCAL_RELEASE_SCRIPT")

upload "$LOCAL_COMPOSE" "$REMOTE_COMPOSE_TMP"
upload "$LOCAL_RELEASE_SCRIPT" "$REMOTE_SCRIPT_TMP"

# The temporary paths are untrusted user-home paths. Reject symlinks while
# uploading, then move each file under sudo into the root-only asset directory
# on the same filesystem as its final path. After ownership, mode, and digest
# checks, rename the prepared files into place atomically. The deploy directory
# is made root-owned and non-writable to the login user before either rename.
# The outer single quotes ensure that the remote login shell cannot expand the
# checksum variables before sudo starts the root-owned shell.
REMOTE_HASH_FUNCTION='hash_file() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1"; else return 127; fi; }'
INSTALL_COMMAND="sh -c 'set -eu; $REMOTE_HASH_FUNCTION; \
[ ! -L $REMOTE_COMPOSE_TMP ] && [ -f $REMOTE_COMPOSE_TMP ]; \
[ ! -L $REMOTE_SCRIPT_TMP ] && [ -f $REMOTE_SCRIPT_TMP ]; \
[ ! -L $NAS_DEPLOY_DIR ]; \
install -d -o root -g root -m 0755 $NAS_DEPLOY_DIR; \
[ -d $NAS_DEPLOY_DIR ] && [ ! -L $NAS_DEPLOY_DIR ]; \
chown root:root $NAS_DEPLOY_DIR; chmod 0755 $NAS_DEPLOY_DIR; \
install -d -o root -g root -m 0700 $ROOT_ASSET_DIR; \
[ -d $ROOT_ASSET_DIR ] && [ ! -L $ROOT_ASSET_DIR ]; \
chown root:root $ROOT_ASSET_DIR; chmod 0700 $ROOT_ASSET_DIR; \
[ ! -e $ROOT_COMPOSE_STAGE ] && [ ! -L $ROOT_COMPOSE_STAGE ]; \
[ ! -e $ROOT_RELEASE_STAGE ] && [ ! -L $ROOT_RELEASE_STAGE ]; \
mv $REMOTE_COMPOSE_TMP $ROOT_COMPOSE_STAGE; \
mv $REMOTE_SCRIPT_TMP $ROOT_RELEASE_STAGE; \
[ ! -L $ROOT_COMPOSE_STAGE ] && [ -f $ROOT_COMPOSE_STAGE ]; \
[ ! -L $ROOT_RELEASE_STAGE ] && [ -f $ROOT_RELEASE_STAGE ]; \
chown root:root $ROOT_COMPOSE_STAGE $ROOT_RELEASE_STAGE; \
chmod 0644 $ROOT_COMPOSE_STAGE; chmod 0755 $ROOT_RELEASE_STAGE; \
compose_hash=\$(hash_file $ROOT_COMPOSE_STAGE); compose_hash=\${compose_hash%% *}; [ \"\$compose_hash\" = $COMPOSE_SHA256 ]; \
script_hash=\$(hash_file $ROOT_RELEASE_STAGE); script_hash=\${script_hash%% *}; [ \"\$script_hash\" = $RELEASE_SCRIPT_SHA256 ]; \
[ ! -L $ROOT_COMPOSE ] && [ ! -d $ROOT_COMPOSE ]; \
[ ! -L $ROOT_RELEASE_SCRIPT ] && [ ! -d $ROOT_RELEASE_SCRIPT ]; \
mv -f -- $ROOT_COMPOSE_STAGE $ROOT_COMPOSE; \
mv -f -- $ROOT_RELEASE_STAGE $ROOT_RELEASE_SCRIPT; \
[ ! -L $ROOT_COMPOSE ] && [ -f $ROOT_COMPOSE ]; \
[ ! -L $ROOT_RELEASE_SCRIPT ] && [ -f $ROOT_RELEASE_SCRIPT ]; \
compose_hash=\$(hash_file $ROOT_COMPOSE); compose_hash=\${compose_hash%% *}; [ \"\$compose_hash\" = $COMPOSE_SHA256 ]; \
script_hash=\$(hash_file $ROOT_RELEASE_SCRIPT); script_hash=\${script_hash%% *}; [ \"\$script_hash\" = $RELEASE_SCRIPT_SHA256 ]; \
rm -f -- $ROOT_COMPOSE_STAGE $ROOT_RELEASE_STAGE'"
sudo_remote "$INSTALL_COMMAND"
RELEASE_PROGRAM="'$ROOT_RELEASE_SCRIPT' '$ACTION'"

RELEASE_COMMAND="DEPLOY_DIR='$NAS_DEPLOY_DIR' APP_ENV_FILE='$APP_ENV_FILE' FRPC_CONTAINER='$FRPC_CONTAINER' FRPC_NETWORK='$FRPC_NETWORK' LOG_TAIL='$LOG_TAIL' MIN_FREE_SPACE_MB='$MIN_FREE_SPACE_MB'"
if [ "$ACTION" = "deploy" ]; then
    RELEASE_COMMAND="$RELEASE_COMMAND IMAGE_REF='$IMAGE_REF' BACKUP_VERIFIED='$BACKUP_VERIFIED'"
fi
sudo_remote "$RELEASE_COMMAND $RELEASE_PROGRAM"

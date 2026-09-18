#!/usr/bin/env bash
set +x
set -euo pipefail

die() {
    printf 'nas release: %s\n' "$1" >&2
    exit 1
}

warn() {
    printf 'nas release: warning: %s\n' "$1" >&2
}

require_value() {
    local name="$1"
    [ -n "${!name:-}" ] || die "$name is required"
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

file_owner() {
    local path="$1"
    local owner

    if owner=$(stat -c '%u' "$path" 2>/dev/null); then
        :
    elif owner=$(stat -f '%u' "$path" 2>/dev/null); then
        :
    else
        die "cannot read ownership for $path"
    fi
    [[ "$owner" =~ ^[0-9]+$ ]] || die "cannot read ownership for $path"
    printf '%s\n' "$owner"
}

require_mode_0600() {
    local path="$1"
    local mode

    [ -f "$path" ] || die "$path is not a regular file"
    mode=$(file_mode "$path")
    [ "$mode" = "600" ] || die "$path must have mode 0600 (found $mode)"
}

require_root_owned_regular_file_0600() {
    local path="$1"
    local owner

    [ ! -L "$path" ] || die "$path must not be a symlink"
    [ -f "$path" ] || die "$path is not a regular file"
    owner=$(file_owner "$path")
    [ "$owner" = "0" ] || die "$path must be owned by UID 0 (found $owner)"
    require_mode_0600 "$path"
}

detect_compose() {
    if docker compose version >/dev/null 2>&1; then
        COMPOSE=(docker compose)
    elif command -v docker-compose >/dev/null 2>&1; then
        COMPOSE=(docker-compose)
    else
        die "Docker Compose is unavailable"
    fi
}

compose_with() {
    local env_file="$1"
    local selected_image_ref selected_app_env_file selected_frpc_network
    shift

    selected_image_ref=$(release_value "$env_file" IMAGE_REF) || \
        die "$env_file is missing IMAGE_REF"
    selected_app_env_file=$(release_value "$env_file" APP_ENV_FILE) || \
        die "$env_file is missing APP_ENV_FILE"
    selected_frpc_network=$(release_value "$env_file" FRPC_NETWORK) || \
        die "$env_file is missing FRPC_NETWORK"

    IMAGE_REF="$selected_image_ref" \
    APP_ENV_FILE="$selected_app_env_file" \
    FRPC_NETWORK="$selected_frpc_network" \
    "${COMPOSE[@]}" --project-name inventory-manager \
        --project-directory "$DEPLOY_DIR" --env-file "$env_file" \
        --file "$DEPLOY_DIR/docker-compose.yml" "$@"
}

release_value() {
    local env_file="$1"
    local key="$2"
    awk -v wanted="$key" '
        index($0, wanted "=") == 1 {
            print substr($0, length(wanted) + 2)
            found = 1
            exit
        }
        END { if (!found) exit 1 }
    ' "$env_file"
}

validate_release_env() {
    local env_file="$1"
    local key value

    require_mode_0600 "$env_file"
    for key in IMAGE_REF APP_ENV_FILE FRPC_NETWORK; do
        value=$(release_value "$env_file" "$key") || die "$env_file is missing $key"
        [ -n "$value" ] || die "$env_file has an empty $key"
    done
}

validate_deploy_layout() {
    require_value DEPLOY_DIR
    [ -d "$DEPLOY_DIR" ] || die "deployment directory does not exist: $DEPLOY_DIR"
    [ -f "$DEPLOY_DIR/docker-compose.yml" ] || \
        die "Compose file does not exist: $DEPLOY_DIR/docker-compose.yml"

    require_value APP_ENV_FILE
    require_root_owned_regular_file_0600 "$APP_ENV_FILE"
}

require_running_frpc() {
    local running

    require_value FRPC_CONTAINER
    running=$(docker inspect --format '{{.State.Running}}' "$FRPC_CONTAINER" 2>/dev/null) || \
        die "cannot inspect frpc container: $FRPC_CONTAINER"
    [ "$running" = "true" ] || die "frpc container is not running: $FRPC_CONTAINER"
}

ensure_frpc_network() {
    local action="$1"
    local connected network_created=0

    require_value FRPC_CONTAINER
    require_value FRPC_NETWORK
    require_running_frpc

    if ! docker network inspect "$FRPC_NETWORK" >/dev/null 2>&1; then
        [ "$action" = "deploy" ] || die "external network does not exist: $FRPC_NETWORK"
        docker network create "$FRPC_NETWORK" >/dev/null
        network_created=1
    fi

    if [ "$network_created" -eq 0 ]; then
        connected=$(docker inspect --format \
            "{{if index .NetworkSettings.Networks \"$FRPC_NETWORK\"}}connected{{end}}" \
            "$FRPC_CONTAINER" 2>/dev/null) || \
            die "cannot inspect frpc network attachment"
    else
        connected=""
    fi

    if [ "$connected" != "connected" ]; then
        [ "$action" = "deploy" ] || \
            die "frpc container is not connected to $FRPC_NETWORK"
        docker network connect "$FRPC_NETWORK" "$FRPC_CONTAINER"
    fi
}

preflight() {
    local action="$1"

    validate_deploy_layout
    command -v docker >/dev/null 2>&1 || die "Docker is unavailable"
    detect_compose
    validate_disk_controls
    check_disk_space
    ensure_frpc_network "$action"
}

validate_disk_controls() {
    MIN_FREE_SPACE_MB_VALUE="${MIN_FREE_SPACE_MB:-1024}"
    [[ "$MIN_FREE_SPACE_MB_VALUE" =~ ^[1-9][0-9]*$ ]] && \
        [ "${#MIN_FREE_SPACE_MB_VALUE}" -le 9 ] || \
        die "MIN_FREE_SPACE_MB must be a positive base-10 integer"
}

available_kb() {
    local path="$1"

    df -Pk "$path" 2>/dev/null | awk '
        NR > 1 { available = $4 }
        END {
            if (available ~ /^[0-9]+$/) print available
            else exit 1
        }
    '
}

require_free_space() {
    local label="$1"
    local path="$2"
    local available

    available=$(available_kb "$path") || \
        die "cannot determine free space for $label filesystem: $path"
    awk -v available="$available" -v minimum_mb="$MIN_FREE_SPACE_MB_VALUE" \
        'BEGIN { exit !(available >= minimum_mb * 1024) }' || \
        die "$label filesystem has less than ${MIN_FREE_SPACE_MB_VALUE} MiB free: $path"
}

check_disk_space() {
    local docker_root

    require_free_space "deployment" "$DEPLOY_DIR"
    docker_root=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || true)
    if [ -z "$docker_root" ]; then
        warn "Docker storage path could not be discovered; deployment filesystem check passed"
        return 0
    fi
    if [ ! -d "$docker_root" ]; then
        warn "Docker storage path is unavailable; skipping its space check: $docker_root"
        return 0
    fi
    require_free_space "Docker storage" "$docker_root"
}

write_candidate_env() {
    CANDIDATE_ENV=$(mktemp "$DEPLOY_DIR/.candidate.env.XXXXXX")
    chmod 600 "$CANDIDATE_ENV"
    printf 'IMAGE_REF=%s\nAPP_ENV_FILE=%s\nFRPC_NETWORK=%s\n' \
        "$IMAGE_REF" "$APP_ENV_FILE" "$FRPC_NETWORK" >"$CANDIDATE_ENV"
}

cleanup_candidate() {
    if [ -n "${CANDIDATE_ENV:-}" ] && [ -f "$CANDIDATE_ENV" ]; then
        rm -f -- "$CANDIDATE_ENV"
    fi
    if [ -n "${PROMOTION_NEXT_PREVIOUS:-}" ] && [ -f "$PROMOTION_NEXT_PREVIOUS" ]; then
        rm -f -- "$PROMOTION_NEXT_PREVIOUS"
    fi
    if [ "${KEEP_PROMOTION_BACKUP:-0}" -eq 0 ] && \
        [ -n "${PROMOTION_PREVIOUS_BACKUP:-}" ] && \
        [ -f "$PROMOTION_PREVIOUS_BACKUP" ]; then
        rm -f -- "$PROMOTION_PREVIOUS_BACKUP"
    fi
}

promote_candidate() {
    local had_current=0 had_previous=0
    local candidate_image_ref current_image_ref

    if [ -f "$CURRENT_ENV" ]; then
        candidate_image_ref=$(release_value "$CANDIDATE_ENV" IMAGE_REF) || \
            die "$CANDIDATE_ENV is missing IMAGE_REF"
        current_image_ref=$(release_value "$CURRENT_ENV" IMAGE_REF) || \
            die "$CURRENT_ENV is missing IMAGE_REF"
        if [ "$candidate_image_ref" = "$current_image_ref" ]; then
            if ! mv -f -- "$CANDIDATE_ENV" "$CURRENT_ENV"; then
                die "same-release metadata refresh failed; current/previous metadata retained"
            fi
            CANDIDATE_ENV=""
            return 0
        fi

        had_current=1
        PROMOTION_NEXT_PREVIOUS=$(mktemp "$DEPLOY_DIR/.next-previous.env.XXXXXX")
        chmod 600 "$PROMOTION_NEXT_PREVIOUS"
        if ! cp "$CURRENT_ENV" "$PROMOTION_NEXT_PREVIOUS"; then
            die "could not stage previous release metadata"
        fi

        if [ -f "$PREVIOUS_ENV" ]; then
            had_previous=1
            PROMOTION_PREVIOUS_BACKUP=$(mktemp "$DEPLOY_DIR/.previous-backup.env.XXXXXX")
            chmod 600 "$PROMOTION_PREVIOUS_BACKUP"
            if ! cp "$PREVIOUS_ENV" "$PROMOTION_PREVIOUS_BACKUP"; then
                die "could not journal existing previous release metadata"
            fi
        fi

        if ! mv -f -- "$PROMOTION_NEXT_PREVIOUS" "$PREVIOUS_ENV"; then
            die "could not install previous release metadata"
        fi
        PROMOTION_NEXT_PREVIOUS=""
    fi

    if ! mv -f -- "$CANDIDATE_ENV" "$CURRENT_ENV"; then
        if [ "$had_current" -eq 1 ]; then
            if [ "$had_previous" -eq 1 ]; then
                if mv -f -- "$PROMOTION_PREVIOUS_BACKUP" "$PREVIOUS_ENV"; then
                    PROMOTION_PREVIOUS_BACKUP=""
                else
                    KEEP_PROMOTION_BACKUP=1
                    die "candidate promotion failed and previous metadata recovery failed; journal retained at $PROMOTION_PREVIOUS_BACKUP"
                fi
            elif ! rm -f -- "$PREVIOUS_ENV"; then
                die "candidate promotion failed and initial previous metadata could not be removed"
            fi
        fi
        die "candidate promotion failed; current/previous metadata restored"
    fi
    CANDIDATE_ENV=""

    if [ -n "$PROMOTION_PREVIOUS_BACKUP" ]; then
        if ! rm -f -- "$PROMOTION_PREVIOUS_BACKUP"; then
            warn "could not remove promotion journal; deployment will continue: $PROMOTION_PREVIOUS_BACKUP"
        fi
        PROMOTION_PREVIOUS_BACKUP=""
    fi
}

stop_current_services() {
    local stop_status recovery_status

    [ -f "$CURRENT_ENV" ] || return 0
    validate_release_env "$CURRENT_ENV"
    if compose_with "$CURRENT_ENV" stop worker app; then
        return 0
    else
        stop_status="$?"
    fi

    warn "stopping current app/worker failed with status $stop_status; attempting recovery"
    if compose_with "$CURRENT_ENV" up --detach --remove-orphans app worker; then
        warn "current app/worker recovery succeeded; deployment aborted"
    else
        recovery_status="$?"
        warn "current app/worker recovery failed with status $recovery_status; deployment aborted with original stop status $stop_status"
    fi
    return "$stop_status"
}

migration_failed() {
    local migration="$1"
    printf 'nas release: %s failed; app and worker remain stopped; current/previous metadata retained. Fix the migration and redeploy.\n' \
        "$migration" >&2
    exit 1
}

validate_health_controls() {
    HEALTH_ATTEMPTS_VALUE="${HEALTH_ATTEMPTS:-30}"
    HEALTH_INTERVAL_VALUE="${HEALTH_INTERVAL_SECONDS:-2}"

    [[ "$HEALTH_ATTEMPTS_VALUE" =~ ^[1-9][0-9]*$ ]] || \
        die "HEALTH_ATTEMPTS must be a positive base-10 integer without leading zeros"
    [[ "$HEALTH_INTERVAL_VALUE" =~ ^[0-9]+$ ]] || \
        die "HEALTH_INTERVAL_SECONDS must contain only digits"
}

wait_for_app_health() {
    local container_id status attempt

    container_id=$(compose_with "$CURRENT_ENV" ps --quiet app)
    [ -n "$container_id" ] || die "app container is not running"

    for ((attempt = 1; attempt <= HEALTH_ATTEMPTS_VALUE; attempt++)); do
        status=$(docker inspect --format '{{.State.Health.Status}}' "$container_id" 2>/dev/null || true)
        if [ "$status" = "healthy" ]; then
            return 0
        fi
        if [ "$status" = "unhealthy" ]; then
            die "app container is unhealthy"
        fi
        if [ "$attempt" -lt "$HEALTH_ATTEMPTS_VALUE" ]; then
            sleep "$HEALTH_INTERVAL_VALUE"
        fi
    done

    die "app container did not become healthy"
}

probe_from_frp_network() {
    docker run --rm --network "$FRPC_NETWORK" --entrypoint python "$IMAGE_REF" \
        -c "import urllib.request; urllib.request.urlopen('http://inventory-manager-app:5002/health', timeout=5)"
}

print_success_summary() {
    local container_state new_image_ref previous_image_ref

    new_image_ref=$(release_value "$CURRENT_ENV" IMAGE_REF) || \
        die "$CURRENT_ENV is missing IMAGE_REF"
    previous_image_ref="<none>"
    if [ -f "$PREVIOUS_ENV" ]; then
        previous_image_ref=$(release_value "$PREVIOUS_ENV" IMAGE_REF) || \
            previous_image_ref="<unavailable>"
    fi
    container_state=$(compose_with "$CURRENT_ENV" ps app worker) || \
        die "could not read app/worker container state after deployment"

    printf 'nas release: deployment succeeded\n'
    printf 'new IMAGE_REF=%s\n' "$new_image_ref"
    printf 'previous IMAGE_REF=%s\n' "$previous_image_ref"
    printf 'container state:\n'
    printf '%s\n' "$container_state"
    printf 'follow-up logs: make nas-logs LOG_TAIL=200\n'
}

run_check() {
    preflight check
    [ -f "$CURRENT_ENV" ] || die "current release metadata does not exist: $CURRENT_ENV"
    validate_release_env "$CURRENT_ENV"
    compose_with "$CURRENT_ENV" config >/dev/null
    printf 'nas release: check passed\n'
}

run_deploy() {
    require_value IMAGE_REF
    [ "${BACKUP_VERIFIED:-}" = "backup-verified" ] || \
        die "BACKUP_VERIFIED must be exactly backup-verified"
    validate_health_controls

    preflight deploy
    trap cleanup_candidate EXIT
    write_candidate_env

    compose_with "$CANDIDATE_ENV" config >/dev/null
    compose_with "$CANDIDATE_ENV" pull app worker migrate-control migrate-tenants
    stop_current_services

    if ! compose_with "$CANDIDATE_ENV" run --rm migrate-control; then
        migration_failed "control migration"
    fi
    if ! compose_with "$CANDIDATE_ENV" run --rm migrate-tenants; then
        migration_failed "tenant migrations"
    fi

    promote_candidate
    compose_with "$CURRENT_ENV" up --detach --remove-orphans app worker
    wait_for_app_health
    probe_from_frp_network
    require_running_frpc
    print_success_summary
}

prepare_current_compose() {
    require_value DEPLOY_DIR
    [ -d "$DEPLOY_DIR" ] || die "deployment directory does not exist: $DEPLOY_DIR"
    [ -f "$DEPLOY_DIR/docker-compose.yml" ] || \
        die "Compose file does not exist: $DEPLOY_DIR/docker-compose.yml"
    [ -f "$CURRENT_ENV" ] || die "current release metadata does not exist: $CURRENT_ENV"
    validate_release_env "$CURRENT_ENV"
    command -v docker >/dev/null 2>&1 || die "Docker is unavailable"
    detect_compose
}

run_status() {
    local image_ref

    prepare_current_compose
    image_ref=$(release_value "$CURRENT_ENV" IMAGE_REF)
    printf 'current IMAGE_REF=%s\n' "$image_ref"
    if [ -f "$PREVIOUS_ENV" ]; then
        validate_release_env "$PREVIOUS_ENV"
        image_ref=$(release_value "$PREVIOUS_ENV" IMAGE_REF)
        printf 'previous IMAGE_REF=%s\n' "$image_ref"
    fi
    compose_with "$CURRENT_ENV" ps
}

run_logs() {
    local tail="${LOG_TAIL:-200}"

    [[ "$tail" =~ ^[0-9]+$ ]] || die "LOG_TAIL must contain only digits"
    prepare_current_compose
    compose_with "$CURRENT_ENV" logs --tail "$tail" app worker
}

ACTION="${1:-}"
case "$ACTION" in
    check|deploy|status|logs)
        ;;
    *)
        die "usage: $0 check|deploy|status|logs"
        ;;
esac

if [ "$#" -ne 1 ]; then
    die "usage: $0 check|deploy|status|logs"
fi

if [ "$ACTION" = "logs" ]; then
    LOG_TAIL="${LOG_TAIL:-200}"
    [[ "$LOG_TAIL" =~ ^[0-9]+$ ]] || die "LOG_TAIL must contain only digits"
fi

require_value DEPLOY_DIR
CURRENT_ENV="$DEPLOY_DIR/current.env"
PREVIOUS_ENV="$DEPLOY_DIR/previous.env"
CANDIDATE_ENV=""
PROMOTION_NEXT_PREVIOUS=""
PROMOTION_PREVIOUS_BACKUP=""
KEEP_PROMOTION_BACKUP=0
HEALTH_ATTEMPTS_VALUE=""
HEALTH_INTERVAL_VALUE=""
MIN_FREE_SPACE_MB_VALUE=""
COMPOSE=()

case "$ACTION" in
    check) run_check ;;
    deploy) run_deploy ;;
    status) run_status ;;
    logs) run_logs ;;
esac

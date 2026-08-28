#!/usr/bin/env bash
set +x
set -euo pipefail

die() {
    printf 'nas release: %s\n' "$1" >&2
    exit 1
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

require_mode_0600() {
    local path="$1"
    local mode

    [ -f "$path" ] || die "$path is not a regular file"
    mode=$(file_mode "$path")
    [ "$mode" = "600" ] || die "$path must have mode 0600 (found $mode)"
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
    shift
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
    require_mode_0600 "$APP_ENV_FILE"
}

ensure_frpc_network() {
    local action="$1"
    local running connected network_created=0

    require_value FRPC_CONTAINER
    require_value FRPC_NETWORK

    running=$(docker inspect --format '{{.State.Running}}' "$FRPC_CONTAINER" 2>/dev/null) || \
        die "cannot inspect frpc container: $FRPC_CONTAINER"
    [ "$running" = "true" ] || die "frpc container is not running: $FRPC_CONTAINER"

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
    ensure_frpc_network "$action"
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
}

compose_with_current_if_present() {
    if [ -f "$CURRENT_ENV" ]; then
        validate_release_env "$CURRENT_ENV"
        compose_with "$CURRENT_ENV" "$@"
    fi
}

promote_candidate() {
    local previous_temp=""

    if [ -f "$CURRENT_ENV" ]; then
        previous_temp=$(mktemp "$DEPLOY_DIR/.previous.env.XXXXXX")
        chmod 600 "$previous_temp"
        if ! cp "$CURRENT_ENV" "$previous_temp"; then
            rm -f -- "$previous_temp"
            die "could not stage previous release metadata"
        fi
        mv -f -- "$previous_temp" "$PREVIOUS_ENV"
    fi

    mv -f -- "$CANDIDATE_ENV" "$CURRENT_ENV"
    CANDIDATE_ENV=""
}

migration_failed() {
    local migration="$1"
    printf 'nas release: %s failed; app and worker remain stopped; current/previous metadata retained. Fix the migration and redeploy.\n' \
        "$migration" >&2
    exit 1
}

wait_for_app_health() {
    local container_id status attempt
    local attempts="${HEALTH_ATTEMPTS:-30}"
    local interval="${HEALTH_INTERVAL_SECONDS:-2}"

    [[ "$attempts" =~ ^[0-9]+$ ]] && [ "$attempts" -gt 0 ] || \
        die "HEALTH_ATTEMPTS must be a positive integer"
    [[ "$interval" =~ ^[0-9]+$ ]] || \
        die "HEALTH_INTERVAL_SECONDS must contain only digits"

    container_id=$(compose_with "$CURRENT_ENV" ps --quiet app)
    [ -n "$container_id" ] || die "app container is not running"

    for ((attempt = 1; attempt <= attempts; attempt++)); do
        status=$(docker inspect --format '{{.State.Health.Status}}' "$container_id" 2>/dev/null || true)
        if [ "$status" = "healthy" ]; then
            return 0
        fi
        if [ "$status" = "unhealthy" ]; then
            die "app container is unhealthy"
        fi
        if [ "$attempt" -lt "$attempts" ]; then
            sleep "$interval"
        fi
    done

    die "app container did not become healthy"
}

probe_from_frp_network() {
    docker run --rm --network "$FRPC_NETWORK" --entrypoint python "$IMAGE_REF" \
        -c "import urllib.request; urllib.request.urlopen('http://inventory-manager-app:5002/health', timeout=5)"
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

    preflight deploy
    trap cleanup_candidate EXIT
    write_candidate_env

    compose_with "$CANDIDATE_ENV" config >/dev/null
    compose_with "$CANDIDATE_ENV" pull app worker migrate-control migrate-tenants
    compose_with_current_if_present stop worker app

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
    printf 'nas release: deployed %s\n' "$IMAGE_REF"
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
COMPOSE=()

case "$ACTION" in
    check) run_check ;;
    deploy) run_deploy ;;
    status) run_status ;;
    logs) run_logs ;;
esac

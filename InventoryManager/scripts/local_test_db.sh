#!/usr/bin/env bash
set +x
set -euo pipefail

readonly CONTAINER="xianyu-saas-lite-mariadb-test"
readonly VOLUME="xianyu-saas-lite-mariadb-test-data"
readonly IMAGE="mariadb:10.11"
readonly PORT="127.0.0.1:33316:3306"
die() { printf 'local test database: %s\n' "$1" >&2; exit 1; }
container_exists() { docker container inspect "$CONTAINER" >/dev/null 2>&1; }

validate_container() {
    local image ports volume
    image=$(docker inspect --format '{{.Config.Image}}' "$CONTAINER")
    ports=$(docker inspect --format '{{json .HostConfig.PortBindings}}' "$CONTAINER")
    volume=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/mysql"}}{{.Name}}{{end}}{{end}}' "$CONTAINER")
    [[ "$image" == "$IMAGE" && "$ports" == '{"3306/tcp":[{"HostIp":"127.0.0.1","HostPort":"33316"}]}' && "$volume" == "$VOLUME" ]] ||
        die "existing container does not match the required image, port, and volume"
}

wait_ready() {
    local attempt
    for attempt in {1..60}; do
        if docker exec "$CONTAINER" sh -c 'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb-admin ping -uroot --silent' >/dev/null 2>&1; then
            printf 'ready: %s on 127.0.0.1:33316\n' "$CONTAINER"
            return
        fi
        sleep 1
    done
    die "MariaDB did not become ready"
}

up() {
    if container_exists; then
        validate_container
        docker start "$CONTAINER" >/dev/null
    else
        local root_password="${TEST_MARIADB_ROOT_PASSWORD:-}"
        [[ -n "$root_password" ]] || die "creating container requires TEST_MARIADB_ROOT_PASSWORD"
        docker volume inspect "$VOLUME" >/dev/null 2>&1 || docker volume create "$VOLUME" >/dev/null
        MARIADB_ROOT_PASSWORD="$root_password" docker run --detach --name "$CONTAINER" \
            --publish "$PORT" --mount "source=$VOLUME,target=/var/lib/mysql" \
            --env MARIADB_ROOT_PASSWORD "$IMAGE" >/dev/null
    fi
    wait_ready
}

status() {
    container_exists || { printf 'absent: %s\n' "$CONTAINER"; return 1; }
    validate_container
    local state
    state=$(docker inspect --format '{{.State.Status}}' "$CONTAINER")
    if [[ "$state" == "running" ]] && docker exec "$CONTAINER" sh -c 'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb-admin ping -uroot --silent' >/dev/null 2>&1; then
        printf 'ready: %s on 127.0.0.1:33316\n' "$CONTAINER"
    else
        printf 'not ready: %s (%s)\n' "$CONTAINER" "$state"
        return 1
    fi
}

down() {
    container_exists && docker rm --force "$CONTAINER" >/dev/null
    printf 'removed container; preserved volume: %s\n' "$VOLUME"
}

reset() {
    [[ -n "${TEST_MARIADB_ROOT_PASSWORD:-}" ]] || die "reset requires TEST_MARIADB_ROOT_PASSWORD"
    if container_exists; then
        [[ "$CONTAINER" == "xianyu-saas-lite-mariadb-test" ]] || die "unsafe container target"
        docker rm --force "$CONTAINER" >/dev/null
    fi
    if docker volume inspect "$VOLUME" >/dev/null 2>&1; then
        [[ "$VOLUME" == "xianyu-saas-lite-mariadb-test-data" ]] || die "unsafe volume target"
        docker volume rm "$VOLUME" >/dev/null
    fi
    up
}

case "${1:-}" in
    up|status|down|reset) "$1" ;;
    *) printf 'Usage: %s {up|status|reset|down}\n' "$0" >&2; exit 2 ;;
esac

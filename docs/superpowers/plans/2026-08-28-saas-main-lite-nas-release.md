# SaaS Main Lite NAS Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供 `make release-nas`，从开发机将一个 `linux/amd64` 镜像构建并推送后，安全更新 NAS 上共享 FRP Docker 网络的 app 与 worker。

**Architecture:** Makefile 只提供稳定的用户接口和版本计算；本地脚本负责无泄密 SSH 传输；NAS 远端脚本负责 Docker Compose、FRP 网络、迁移顺序和健康验收。远端生命周期脚本与 SSH 传输分离，使关键失败路径可以分别用 fake Docker 和 fake SSH 做单元测试。

**Tech Stack:** GNU Make、Bash 3.2+、Docker Buildx、Docker Compose v2/`docker-compose` fallback、pytest、OpenSpec。

**Spec:** `docs/superpowers/specs/2026-08-28-saas-main-lite-nas-release-design.md`

## Global Constraints

- app 与 worker MUST 使用同一完整镜像引用；不得生成第二个 worker 镜像。
- 生产镜像平台固定为 `linux/amd64`，默认 repository 为 `docker.cnb.cool/tdcc-demo/jimmy/inventory-manager`。
- frpc 与 app MUST 共享用户自定义 external network；app 的稳定别名为 `inventory-manager-app`，端口为 5002。
- 生产 `.env` 只驻留 NAS，发布不得上传本地 `.env`，不得打印容器完整环境。
- worker MUST 清空 `PROVISIONER_DATABASE_URL` 和全部腾讯短信 app-only 环境变量。
- 数据库迁移失败 MUST 保持 app/worker 停止，不得自动降级 schema。
- 预检或镜像拉取失败 MUST 发生在停止旧服务之前。
- 不自动修改 frpc 配置内容；首次真实部署时只核对其本地目标为 `inventory-manager-app:5002`。
- 保留现有 `ai_kefu/xianyu_provider/upstream` 工作区状态，不加入任何提交。

---

### Task 1: Make 发布接口与契约测试

**Files:**
- Modify: `InventoryManager/tests/unit/test_production_config.py`
- Create: `InventoryManager/tests/unit/test_nas_release_assets.py`
- Modify: `InventoryManager/Makefile`

**Interfaces:**
- Consumes: 现有 `build`、`push`、`run-app`、`run-worker`、`worker-once` 目标。
- Produces: `build-push`、`check-nas`、`deploy-nas`、`release-nas`、`nas-status`、`nas-logs`；变量 `IMAGE_REPOSITORY`、`RELEASE_TAG`、`IMAGE_TAG`、`PLATFORM`。

- [ ] **Step 1: 更新旧 Make 契约并写新失败测试**

将 `test_one_image_and_parameterized_make_contract` 的精确 target 集合更新为：

```python
assert targets == {
    "help", "build", "push", "run-app", "run-worker", "worker-once",
    "build-push", "check-nas", "deploy-nas", "release-nas",
    "nas-status", "nas-logs",
}
assert "include .env" not in makefile
assert "NAS_PASS :=" not in makefile and "SUDO_PASS :=" not in makefile
```

在 `test_nas_release_assets.py` 增加 Make 行为检查：

```python
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_make(*args):
    return subprocess.run(
        ["make", "--no-print-directory", *args], cwd=ROOT,
        env={**os.environ, "GIT_SHA": "abc123def456", "RELEASE_TIME": "20260828-120000"},
        text=True, capture_output=True, check=False,
    )


def test_release_tag_and_single_image_are_visible_in_dry_run():
    result = run_make("-n", "release-nas", "BACKUP_VERIFIED=backup-verified")
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "docker buildx build" in output
    assert "--platform \"linux/amd64\"" in output
    assert "docker.cnb.cool/tdcc-demo/jimmy/inventory-manager:20260828-120000-abc123def456" in output
    assert output.count("20260828-120000-abc123def456") >= 2


def test_deploy_existing_tag_requires_an_explicit_tag():
    result = run_make("deploy-nas", "IMAGE_TAG=")
    assert result.returncode != 0
    assert "IMAGE_TAG" in result.stdout + result.stderr
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python3 -m pytest tests/unit/test_production_config.py::test_one_image_and_parameterized_make_contract tests/unit/test_nas_release_assets.py -q
```

Expected: FAIL，因为新 targets 和发布变量尚不存在。

- [ ] **Step 3: 实现最小 Make 目标**

在 Makefile 中引入递归 Make 共享的稳定变量：

```make
IMAGE_REPOSITORY ?= docker.cnb.cool/tdcc-demo/jimmy/inventory-manager
GIT_SHA ?= $(shell git rev-parse --short=12 HEAD)
RELEASE_TIME ?= $(shell date +%Y%m%d-%H%M%S)
RELEASE_TAG ?= $(RELEASE_TIME)-$(GIT_SHA)
BACKUP_VERIFIED ?=
IMAGE_TAG ?=

build-push:
	docker buildx build --platform "$(PLATFORM)" \
		--tag "$(IMAGE_REPOSITORY):$(RELEASE_TAG)" --push .

deploy-nas:
	@test -n "$(IMAGE_TAG)" || { echo "IMAGE_TAG is required" >&2; exit 2; }
	@IMAGE_REPOSITORY="$(IMAGE_REPOSITORY)" IMAGE_TAG="$(IMAGE_TAG)" \
		BACKUP_VERIFIED="$(BACKUP_VERIFIED)" bash scripts/deploy_nas.sh deploy

release-nas:
	@test "$(BACKUP_VERIFIED)" = "backup-verified" || { echo "BACKUP_VERIFIED=backup-verified is required" >&2; exit 2; }
	@test -z "$$(git status --porcelain -- .)" || { echo "InventoryManager working tree must be clean" >&2; exit 2; }
	@$(MAKE) --no-print-directory build-push RELEASE_TAG="$(RELEASE_TAG)"
	@$(MAKE) --no-print-directory deploy-nas IMAGE_TAG="$(RELEASE_TAG)" BACKUP_VERIFIED="$(BACKUP_VERIFIED)"
```

`check-nas`、`nas-status`、`nas-logs` 分别调用本地脚本的 `check`、`status`、`logs` action。`help` 显示首次配置位置和指定 tag 用法。

- [ ] **Step 4: 运行 Make 契约测试并确认 GREEN**

Run:

```bash
cd InventoryManager
python3 -m pytest tests/unit/test_production_config.py::test_one_image_and_parameterized_make_contract tests/unit/test_nas_release_assets.py -q
make -n release-nas RELEASE_TIME=20260828-120000 GIT_SHA=abc123def456 BACKUP_VERIFIED=backup-verified
```

Expected: tests PASS；dry-run 只出现一个 repository/tag，并调用 build-push 后调用 deploy-nas。

- [ ] **Step 5: 提交 Make 接口**

```bash
git add InventoryManager/Makefile InventoryManager/tests/unit/test_production_config.py InventoryManager/tests/unit/test_nas_release_assets.py
git commit -m "build: add NAS release make targets"
```

---

### Task 2: NAS Compose 拓扑与静态验证

**Files:**
- Create: `InventoryManager/deploy/nas/docker-compose.yml`
- Create: `InventoryManager/deploy/nas/release.env.example`
- Modify: `InventoryManager/tests/unit/test_nas_release_assets.py`

**Interfaces:**
- Consumes: `IMAGE_REPOSITORY` 与 `IMAGE_TAG` 组成的 `IMAGE_REF`；NAS 上已有的 `APP_ENV_FILE`。
- Produces: Compose services `app`、`worker`、`migrate-control`、`migrate-tenants`；external network `frp`；alias `inventory-manager-app`。

- [ ] **Step 1: 写 Compose 失败测试**

在 `test_nas_release_assets.py` 增加：

```python
COMPOSE = ROOT / "deploy/nas/docker-compose.yml"


def test_nas_compose_uses_one_image_and_external_frp_network():
    text = COMPOSE.read_text()
    assert text.count('image: "${IMAGE_REF:?IMAGE_REF is required}"') == 4
    assert "migrate-control:" in text and "migrate-tenants:" in text
    assert 'name: "${FRPC_NETWORK:?FRPC_NETWORK is required}"' in text
    assert "external: true" in text
    assert "inventory-manager-app" in text
    assert "ports:" not in text


def test_worker_clears_every_app_only_secret():
    text = COMPOSE.read_text()
    for key in (
        "PROVISIONER_DATABASE_URL", "TENCENTCLOUD_SECRET_ID",
        "TENCENTCLOUD_SECRET_KEY", "TENCENT_SMS_SDK_APP_ID",
        "TENCENT_SMS_SIGN_NAME", "TENCENT_SMS_TEMPLATE_ID",
    ):
        assert f'{key}: ""' in text


def test_app_healthcheck_uses_python_stdlib():
    text = COMPOSE.read_text()
    assert "urllib.request.urlopen" in text
    assert "http://127.0.0.1:5002/health" in text
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python3 -m pytest tests/unit/test_nas_release_assets.py -q
```

Expected: FAIL，因为 Compose 文件不存在。

- [ ] **Step 3: 创建 Compose 和非敏感示例**

Compose 的核心结构为：

```yaml
services:
  app:
    image: "${IMAGE_REF:?IMAGE_REF is required}"
    restart: unless-stopped
    env_file:
      - "${APP_ENV_FILE:?APP_ENV_FILE is required}"
    networks:
      frp:
        aliases:
          - inventory-manager-app
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - import urllib.request; urllib.request.urlopen('http://127.0.0.1:5002/health', timeout=3)
      interval: 10s
      timeout: 5s
      retries: 12
      start_period: 30s

  worker:
    image: "${IMAGE_REF:?IMAGE_REF is required}"
    restart: unless-stopped
    command: ["python", "worker.py"]
    env_file:
      - "${APP_ENV_FILE:?APP_ENV_FILE is required}"
    environment:
      PROVISIONER_DATABASE_URL: ""
      TENCENTCLOUD_SECRET_ID: ""
      TENCENTCLOUD_SECRET_KEY: ""
      TENCENT_SMS_SDK_APP_ID: ""
      TENCENT_SMS_SIGN_NAME: ""
      TENCENT_SMS_TEMPLATE_ID: ""
    networks: [frp]

  migrate-control:
    image: "${IMAGE_REF:?IMAGE_REF is required}"
    profiles: ["migration"]
    command: ["alembic", "-c", "control_alembic.ini", "upgrade", "head"]
    env_file:
      - "${APP_ENV_FILE:?APP_ENV_FILE is required}"
    networks: [frp]

  migrate-tenants:
    image: "${IMAGE_REF:?IMAGE_REF is required}"
    profiles: ["migration"]
    command: ["python", "-m", "flask", "--app", "run.py", "upgrade-tenant-databases"]
    env_file:
      - "${APP_ENV_FILE:?APP_ENV_FILE is required}"
    networks: [frp]

networks:
  frp:
    external: true
    name: "${FRPC_NETWORK:?FRPC_NETWORK is required}"
```

在 `release.env.example` 只提供：

```dotenv
IMAGE_REF=docker.cnb.cool/tdcc-demo/jimmy/inventory-manager:20260828-120000-abc123def456
APP_ENV_FILE=/volume1/docker/inventory-manager/app.env
FRPC_NETWORK=xianyu-frp
```

- [ ] **Step 4: 运行静态测试并用可用 Compose CLI 验证**

Run:

```bash
cd InventoryManager
python3 -m pytest tests/unit/test_nas_release_assets.py -q
bash -c 'if docker compose version >/dev/null 2>&1; then docker compose --env-file deploy/nas/release.env.example -f deploy/nas/docker-compose.yml config >/dev/null; elif command -v docker-compose >/dev/null 2>&1; then docker-compose --env-file deploy/nas/release.env.example -f deploy/nas/docker-compose.yml config >/dev/null; fi'
```

Expected: tests PASS；存在 Compose CLI 时 config PASS。

- [ ] **Step 5: 提交 Compose 拓扑**

```bash
git add InventoryManager/deploy/nas InventoryManager/tests/unit/test_nas_release_assets.py
git commit -m "build: define NAS app worker compose"
```

---

### Task 3: NAS 远端发布引擎

**Files:**
- Create: `InventoryManager/deploy/nas/remote_release.sh`
- Create: `InventoryManager/tests/unit/test_nas_remote_release.py`

**Interfaces:**
- Consumes: action `check|deploy|status|logs` 和环境变量 `DEPLOY_DIR`、`APP_ENV_FILE`、`IMAGE_REF`、`FRPC_CONTAINER`、`FRPC_NETWORK`、`BACKUP_VERIFIED`。
- Produces: 原子 release env、`previous.env`、Compose 生命周期、FRP 网络探针；所有 action 以 0/非 0 表达结果。

- [ ] **Step 1: 创建 fake Docker 测试夹具**

`test_nas_remote_release.py` 通过临时 `PATH` 注入一个 Python fake Docker。fake 必须把每次 argv 以 JSON line 写入 `FAKE_DOCKER_CALLS`，并支持以下分支：

```python
if args[:2] == ["compose", "version"]:
    raise SystemExit(0)
if "pull" in args:
    raise SystemExit(1 if mode == "pull-fail" else 0)
if args[:2] == ["network", "inspect"]:
    raise SystemExit(1 if mode == "network-absent" else 0)
if args[:2] == ["network", "create"]:
    raise SystemExit(0)
if args[:2] == ["network", "connect"]:
    raise SystemExit(0)
if args[0] == "inspect" and args[-1] == "frpc":
    print("true" if "State.Running" in " ".join(args) else ("" if mode == "frpc-disconnected" else "connected"))
    raise SystemExit(0)
if "migrate-control" in args:
    raise SystemExit(1 if mode == "migration-fail" else 0)
if args[0] == "inspect" and args[-1] == "app-id":
    print("healthy")
    raise SystemExit(0)
if "ps" in args and "app" in args:
    print("app-id")
    raise SystemExit(0)
if args[0] == "run":
    raise SystemExit(1 if mode == "probe-fail" else 0)
raise SystemExit(0)
```

测试辅助函数创建 mode `0600` 的 `app.env`、Compose 占位文件和临时部署目录，然后执行：

```python
result = subprocess.run(
    ["bash", SCRIPT, action], env=env, text=True,
    capture_output=True, timeout=10, check=False,
)
```

- [ ] **Step 2: 写关键失败路径测试并确认 RED**

至少增加：

```python
def test_pull_failure_never_stops_old_services(tmp_path):
    result, calls = invoke(tmp_path, "deploy", mode="pull-fail")
    assert result.returncode != 0
    assert not any("stop" in call for call in calls)


def test_migration_failure_stops_without_starting_new_services(tmp_path):
    result, calls = invoke(tmp_path, "deploy", mode="migration-fail")
    assert result.returncode != 0
    assert any("stop" in call for call in calls)
    assert not any("up" in call for call in calls)


def test_disconnected_frpc_is_connected_before_service_stop(tmp_path):
    result, calls = invoke(tmp_path, "deploy", mode="frpc-disconnected")
    assert result.returncode == 0
    connect = next(i for i, call in enumerate(calls) if call[:2] == ["network", "connect"])
    stop = next(i for i, call in enumerate(calls) if "stop" in call)
    assert connect < stop


def test_success_orders_migrations_start_health_and_network_probe(tmp_path):
    result, calls = invoke(tmp_path, "deploy")
    assert result.returncode == 0
    positions = {
        "stop": next(i for i, call in enumerate(calls) if "stop" in call),
        "control": next(i for i, call in enumerate(calls) if "migrate-control" in call),
        "tenants": next(i for i, call in enumerate(calls) if "migrate-tenants" in call),
        "up": next(i for i, call in enumerate(calls) if "up" in call),
        "probe": next(i for i, call in enumerate(calls) if call[0] == "run"),
    }
    assert list(positions.values()) == sorted(positions.values())
```

Run:

```bash
cd InventoryManager
python3 -m pytest tests/unit/test_nas_remote_release.py -q
```

Expected: FAIL，因为远端脚本不存在。

- [ ] **Step 3: 实现安全预检和 Compose 适配**

`remote_release.sh` 顶部和 compose 适配：

```bash
#!/usr/bin/env bash
set +x
set -euo pipefail

die() { printf 'nas release: %s\n' "$1" >&2; exit 1; }

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
```

预检 MUST 按顺序验证目录、Compose 文件、mode `0600` 的生产 env、frpc running、external network。网络不存在时 deploy action 执行 `docker network create "$FRPC_NETWORK"`；frpc 未连接时执行 `docker network connect "$FRPC_NETWORK" "$FRPC_CONTAINER"`。`check` action 只报告问题，不创建或连接网络。

- [ ] **Step 4: 实现候选版本、迁移和健康验收**

候选 env 使用 `mktemp` 和 `mv` 原子生成：

```bash
write_candidate_env() {
    CANDIDATE_ENV=$(mktemp "$DEPLOY_DIR/.candidate.env.XXXXXX")
    chmod 600 "$CANDIDATE_ENV"
    printf 'IMAGE_REF=%s\nAPP_ENV_FILE=%s\nFRPC_NETWORK=%s\n' \
        "$IMAGE_REF" "$APP_ENV_FILE" "$FRPC_NETWORK" >"$CANDIDATE_ENV"
}
```

部署顺序必须直接表达为：

```bash
compose_with "$CANDIDATE_ENV" config >/dev/null
compose_with "$CANDIDATE_ENV" pull app worker migrate-control migrate-tenants
compose_with_current_if_present stop worker app
compose_with "$CANDIDATE_ENV" run --rm migrate-control
compose_with "$CANDIDATE_ENV" run --rm migrate-tenants
promote_candidate
compose_with "$CURRENT_ENV" up --detach --remove-orphans app worker
wait_for_app_health
probe_from_frp_network
```

`probe_from_frp_network` 使用同一 `IMAGE_REF`，不引入额外 curl 镜像：

```bash
docker run --rm --network "$FRPC_NETWORK" --entrypoint python "$IMAGE_REF" \
    -c "import urllib.request; urllib.request.urlopen('http://inventory-manager-app:5002/health', timeout=5)"
```

只有 `BACKUP_VERIFIED=backup-verified` 才允许 deploy 进入停止服务步骤。迁移失败 trap 删除 candidate、保留 current/previous 元数据并输出恢复提示，但不得执行 schema downgrade 或启动新版本。

- [ ] **Step 5: 实现只读 check/status/logs**

- `check`：验证 Docker、Compose、生产 env、frpc running、网络存在且 frpc 已连接、current env 可解析；不调用 create/connect/stop/up。
- `status`：运行 Compose `ps`，只输出 current 与 previous 的 `IMAGE_REF` 行，不执行 `docker inspect` 环境输出。
- `logs`：运行 `compose logs --tail "${LOG_TAIL:-200}" app worker`，并验证 `LOG_TAIL` 只含数字。

- [ ] **Step 6: 运行远端引擎测试并确认 GREEN**

Run:

```bash
cd InventoryManager
bash -n deploy/nas/remote_release.sh
python3 -m pytest tests/unit/test_nas_remote_release.py -q
```

Expected: syntax PASS；所有 fake Docker 时序与失败保护测试 PASS。

- [ ] **Step 7: 提交远端发布引擎**

```bash
git add InventoryManager/deploy/nas/remote_release.sh InventoryManager/tests/unit/test_nas_remote_release.py
git commit -m "feat: orchestrate safe NAS container updates"
```

---

### Task 4: 本地 SSH 传输与凭据保护

**Files:**
- Create: `InventoryManager/scripts/deploy_nas.sh`
- Create: `InventoryManager/tests/unit/test_nas_deploy_transport.py`
- Modify: `InventoryManager/Makefile`

**Interfaces:**
- Consumes: Task 1 Make actions；Task 2 Compose；Task 3 `remote_release.sh` actions。
- Produces: SSH key-first transport、`sshpass -e` password fallback、stdin 文件上传、Synology sudo invocation。

- [ ] **Step 1: 写 fake SSH/sshpass 失败测试**

fake `ssh` 把 argv 写到 JSON lines，并根据最后一个远程命令返回预设状态；fake `sshpass` 只允许 `-e`，断言 argv 不包含密码后 `exec` 余下命令。

关键测试：

```python
def test_password_never_appears_in_xtrace_or_process_arguments(tmp_path):
    result, calls = invoke(tmp_path, "check", trace=True, password="transport-secret")
    serialized = result.stdout + result.stderr + json.dumps(calls)
    assert "transport-secret" not in serialized
    assert any(call[0] == "-e" for call in calls["sshpass"])


def test_upload_uses_ssh_stdin_instead_of_sftp_or_scp(tmp_path):
    result, calls = invoke(tmp_path, "check")
    assert result.returncode == 0
    assert not any("scp" in part or "sftp" in part for call in calls["ssh"] for part in call)
    assert any("cat >" in " ".join(call) for call in calls["ssh"])


def test_unknown_action_fails_before_ssh(tmp_path):
    result, calls = invoke(tmp_path, "destroy")
    assert result.returncode == 2
    assert calls["ssh"] == []
```

- [ ] **Step 2: 运行传输测试并确认 RED**

Run:

```bash
cd InventoryManager
python3 -m pytest tests/unit/test_nas_deploy_transport.py -q
```

Expected: FAIL，因为本地脚本不存在。

- [ ] **Step 3: 实现配置加载和 SSH 数组**

脚本 MUST 首先 `set +x`，再 `set -euo pipefail`。只接受以下配置键：

```bash
NAS_HOST NAS_USER NAS_PORT NAS_DEPLOY_DIR APP_ENV_FILE
FRPC_CONTAINER FRPC_NETWORK NAS_PASS SUDO_PASS SSH_KEY LOG_TAIL
```

默认部署配置文件为 `${XDG_CONFIG_HOME:-$HOME/.config}/xianyu-agent/nas.env`。解析器逐行处理 `KEY=VALUE`，只用 `printf -v` 设置白名单键，不 `source` 文件。显式环境变量优先于文件值。

SSH 数组规则：

```bash
SSH_ARGS=(-p "$NAS_PORT" -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)
[[ -n "$SSH_KEY" ]] && SSH_ARGS+=(-i "$SSH_KEY")
if [[ -n "$NAS_PASS" ]]; then
    command -v sshpass >/dev/null || die "NAS_PASS requires sshpass"
    export SSHPASS="$NAS_PASS"
    SSH_PREFIX=(sshpass -e)
else
    SSH_PREFIX=()
fi
```

密码只进入 `SSHPASS` 环境或远程 sudo stdin，不得成为 argv。`NAS_DEPLOY_DIR`、`APP_ENV_FILE` 和远程临时路径必须先通过绝对路径/安全字符白名单校验，再参与远程命令。

- [ ] **Step 4: 实现无 SFTP 文件传输和远程调用**

通过 SSH stdin 上传到用户 home 临时目录：

```bash
upload() {
    local source="$1" remote="$2"
    "${SSH_PREFIX[@]}" ssh "${SSH_ARGS[@]}" "$NAS_USER@$NAS_HOST" \
        "umask 077; cat > '$remote'" <"$source"
}
```

随后用 `sudo -n` 或受保护 stdin 把文件安装到 `NAS_DEPLOY_DIR`。远程 action 只传非敏感参数；`SUDO_PASS` 不拼进远程命令字符串。脚本退出时删除用户 home 下此次明确命名的临时文件，不递归删除部署目录。

- [ ] **Step 5: 接通 Make 目标并运行 GREEN 测试**

Run:

```bash
cd InventoryManager
bash -n scripts/deploy_nas.sh
python3 -m pytest tests/unit/test_nas_deploy_transport.py tests/unit/test_nas_release_assets.py -q
make -n check-nas
make -n deploy-nas IMAGE_TAG=20260828-120000-abc123def456 BACKUP_VERIFIED=backup-verified
```

Expected: syntax/tests PASS；Make dry-run 不含密码或本地 `.env` 上传。

- [ ] **Step 6: 提交本地传输**

```bash
git add InventoryManager/scripts/deploy_nas.sh InventoryManager/tests/unit/test_nas_deploy_transport.py InventoryManager/Makefile
git commit -m "feat: add secure NAS release transport"
```

---

### Task 5: 文档、完整测试与 OpenSpec 状态

**Files:**
- Modify: `docs/deployment/saas-main-lite.md`
- Modify: `InventoryManager/openspec/changes/add-nas-release-automation/tasks.md`

**Interfaces:**
- Consumes: Tasks 1-4 的最终 Make、Compose 和脚本接口。
- Produces: 首次配置、日常发布、FRP 配置、失败恢复与日志操作说明。

- [ ] **Step 1: 写文档契约失败测试**

在 `test_nas_release_assets.py` 增加：

```python
def test_deployment_guide_documents_release_network_and_recovery():
    text = (ROOT.parent / "docs/deployment/saas-main-lite.md").read_text()
    for token in (
        "make release-nas", "make deploy-nas IMAGE_TAG=", "inventory-manager-app",
        "FRPC_NETWORK", "backup-verified", "make nas-status", "make nas-logs",
        "迁移失败", "向前修复",
    ):
        assert token in text
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python3 -m pytest tests/unit/test_nas_release_assets.py::test_deployment_guide_documents_release_network_and_recovery -q
```

Expected: FAIL，因为当前手册仍写着等待 NAS 样例。

- [ ] **Step 3: 更新部署手册**

手册新增并给出精确命令：

```bash
mkdir -p ~/.config/xianyu-agent
chmod 700 ~/.config/xianyu-agent
${EDITOR:-vi} ~/.config/xianyu-agent/nas.env
chmod 600 ~/.config/xianyu-agent/nas.env

cd InventoryManager
make check-nas
make release-nas BACKUP_VERIFIED=backup-verified
make nas-status
make nas-logs LOG_TAIL=200
```

记录 NAS `app.env` 路径、registry 一次性登录、frpc `localIP = "inventory-manager-app"`、`localPort = 5002`、external network、指定 tag 和数据库迁移失败处理。删除“等待用户样例后再适配”的过时描述。

- [ ] **Step 4: 运行新功能和相关回归测试**

Run:

```bash
cd InventoryManager
python3 -m pytest \
  tests/unit/test_nas_release_assets.py \
  tests/unit/test_nas_remote_release.py \
  tests/unit/test_nas_deploy_transport.py \
  tests/unit/test_production_config.py \
  tests/unit/test_worker.py -q
bash -n scripts/deploy_nas.sh deploy/nas/remote_release.sh
git diff --check
git grep -n -I -E 'NAS_PASS[[:space:]]*:?=[[:space:]]*[^$[:space:]]|SUDO_PASS[[:space:]]*:?=[[:space:]]*[^$[:space:]]|BEGIN (RSA|EC|OPENSSH) PRIVATE KEY' -- InventoryManager docs/deployment
cd InventoryManager && openspec validate add-nas-release-automation --strict
```

Expected: pytest/syntax/diff/OpenSpec PASS；敏感信息扫描无输出。

- [ ] **Step 5: 更新 OpenSpec checklist 并提交**

在 `InventoryManager/openspec/changes/add-nas-release-automation/tasks.md` 中只勾选已经由本机测试完成的 1.1-4.2；真实 NAS 的 4.3-4.4 在完成下一任务前保持未勾选。

```bash
git add docs/deployment/saas-main-lite.md InventoryManager/tests/unit/test_nas_release_assets.py InventoryManager/openspec/changes/add-nas-release-automation/tasks.md
git commit -m "docs: document repeatable NAS releases"
```

---

### Task 6: 真实 NAS 只读预检与受控首次发布

**Files:**
- Modify after evidence: `InventoryManager/openspec/changes/add-nas-release-automation/tasks.md`

**Interfaces:**
- Consumes: 已测试并提交的 `make check-nas`、`make release-nas`、`make nas-status`；用户提供的 NAS 访问和发布前备份确认。
- Produces: NAS 实际 frpc/container/network 证据，以及经用户授权后的端到端部署结果。

- [ ] **Step 1: 执行只读 NAS 发现**

先只运行不会停止或重建容器的命令，确认：

```bash
make check-nas
```

若配置名未知，使用只读 SSH 查询 `docker ps`、frpc mount 和 `docker inspect --format '{{json .NetworkSettings.Networks}}' <frpc-container>`。不得输出完整容器环境或 frpc token。

- [ ] **Step 2: 核对 frpc 配置目标**

只读取 frpc 配置的 proxy name、type、localIP、localPort、remotePort；token 和认证字段必须遮蔽。Expected: 对应库存服务的本地目标为 `inventory-manager-app:5002`；否则在用户授权范围内修改该明确配置并只重启 frpc 容器。

- [ ] **Step 3: 请求并记录备份/维护窗口确认**

在任何停止 app/worker 或执行 Alembic 之前，要求用户确认控制库与租户库备份已完成且可恢复。没有确认则停止在此步骤，不运行 release。

- [ ] **Step 4: 执行首次发布**

Run:

```bash
make release-nas BACKUP_VERIFIED=backup-verified
```

Expected: 单镜像成功推送；远端迁移完成；app/worker healthy/running；FRP 网络探针通过。

- [ ] **Step 5: 端到端验收与状态记录**

Run:

```bash
make nas-status
make nas-logs LOG_TAIL=100
```

再通过现有 frps 公网端口请求 app `/health`。Expected: NAS 内部与公网入口均成功；日志无持续异常且不含凭据。

- [ ] **Step 6: 完成 OpenSpec checklist 与最终验证**

勾选 4.3-4.4 后运行：

```bash
cd InventoryManager
openspec validate add-nas-release-automation --strict
git diff --check
```

只有真实发布和所有检查通过后，才提交运行证据对应的 checklist 更新；不得提交 NAS env、registry token、数据库备份或运行日志。

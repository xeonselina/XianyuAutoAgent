# DEPLOY — 唯一权威部署文档

**本文件由 `Makefile` / `Dockerfile` / `.env.example` / `config.py` / `gunicorn_config.py` 反推写成。**

已废弃、不可信（会撒谎）：`makefile.example`（52 个 target 全部不存在）、`README-Docker.md`、
`README-多架构构建.md`、`INSTALL.md`、`README.md` 中的部署段落、
`DEPLOYMENT_CHECKLIST.md` / `DEPLOYMENT_READINESS_REPORT.md` / `READY_TO_DEPLOY.md`。

SaaS 化迁移的交接记录见仓库根 `docs/deployment/saas-main-lite.md`
（首次迁移、默认租户、回滚判定以它为准，本文件不复制其命令以免产生第二份会漂移的副本）。

---

## 1. 30 秒速查

| 项 | 值 |
|---|---|
| 默认镜像名 | `inventory-manager:saas-main-lite` |
| 目标平台 | `linux/amd64` |
| app 端口 | 容器内 5002，宿主默认映射 5002 |
| 进程 | **一个镜像，两个进程**：app（默认 CMD）+ worker（覆盖命令 `python worker.py`） |
| 基础镜像 | `python:3.10-slim-bookworm` |
| 环境变量 | `.env`（由 `.env.example` 复制，**不入 git**） |
| 健康检查 | `GET /health`（`app/routes/web.py`）与 `GET /external-api/health` |
| CI | `.github/workflows/docker-build.yml` **只构建 ai_kefu 三个镜像，不含本项目**；本项目镜像需手动 build+push |

## 2. 构建与发布

```bash
make build  IMAGE='<registry/image:tag>' PLATFORM=linux/amd64
make push   IMAGE='<registry/image:tag>'
make run-app    IMAGE='<registry/image:tag>' ENV_FILE=.env APP_PORT=5002
make run-worker IMAGE='<registry/image:tag>' ENV_FILE=.env
make worker-once IMAGE='<registry/image:tag>' ENV_FILE=.env   # 跑一轮即退出，等价于 python worker.py --once
```

`Makefile` 只有这 6 个 target（含 `help`）。**不允许新增 target**——
`tests/unit/test_production_config.py` 会断言 target 集合恰为
`{help, build, push, run-app, run-worker, worker-once}`，且 Makefile 中不得出现
`NAS_` / `sshpass` / `docker-compose` / `include .env` / `REGISTRY :=`。
需要主机特定的部署脚本时，写在 `scripts/` 下，不要塞进 Makefile。

多架构构建见 `build-multiarch.sh`（ARM64 + AMD64）。

## 3. 环境变量

### 3.1 app 与 worker 都需要

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | bootstrap 业务库 |
| `CONTROL_DATABASE_URL` | 控制库（tenants / platform_admins） |
| `TENANT_DB_HOST` / `TENANT_DB_PORT` | 租户库地址，端口默认 3306 |
| `TENANT_DB_NAME_PREFIX` / `TENANT_DB_USER_PREFIX` | 必须恰为 `inventory_tenant_` / `im_t` |
| `SAAS_MASTER_KEY` | 主密钥，不得为默认值 |
| `SECRET_KEY` | 不得为默认值 |
| `FLASK_ENV` | 生产设 `production` |
| `CORS_ORIGINS` | **必须精确 origin**（`http` 或 `https` 开头，多项逗号分隔） |
| `TRUSTED_PROXY_HOPS` | 按实际反向代理层数 |
| `XIANYU_API_DOMAIN` | 默认 `open.goofish.pro` |

### 3.2 仅 app —— 权限隔离（勿给 worker）

`PROVISIONER_DATABASE_URL`（建库高权账号）+ 腾讯云短信 6 项：
`TENCENTCLOUD_SECRET_ID` / `TENCENTCLOUD_SECRET_KEY` / `TENCENT_SMS_SDK_APP_ID` /
`TENCENT_SMS_SIGN_NAME` / `TENCENT_SMS_TEMPLATE_ID` / `TENCENT_SMS_REGION`。

`make run-worker` 与 `make worker-once` 会用 `--env "KEY="` 把这 7 个变量**强制清空**。
任何自建部署脚本都必须保持这项隔离：worker 不参与 provisioning，也不该拿到建库权限和短信凭据。

### 3.3 生产 fail-closed

生产配置下以下情形**直接拒绝启动**而非降级：`SAAS_MASTER_KEY` 或 `SECRET_KEY` 为默认值、
存在 `DEV_SMS_CODE`、前缀不等于 `inventory_tenant_` / `im_t`、`TENANT_DB_PORT` 越界、
`CORS_ORIGINS` 非精确 origin（抛 `RuntimeError`）、`TRUSTED_PROXY_HOPS` 为负。

## 4. 双 Alembic 迁移 —— 最易错

两套迁移互相独立，**顺序不可颠倒**：

| | 控制库 | 租户业务库 |
|---|---|---|
| 目录 | `control_migrations/` | `migrations/` |
| 配置 | `control_alembic.ini` | Flask-Migrate |
| 版本数 | 1 | 31 |
| 命令 | `alembic -c control_alembic.ini upgrade head` | **不要手跑 alembic** |

```bash
cd InventoryManager
# 1) 先控制库
alembic -c control_alembic.ini upgrade head
# 2) 再全部已激活租户的业务库
python -m flask --app run.py upgrade-tenant-databases
```

首次上线另有两条 CLI（同样用 `python -m flask --app run.py <cmd>`）：
`bootstrap-platform-admin` 与 `migrate-default-tenant`。完整参数与前置条件
（完整备份、维护窗口、两个 `--confirm-*` 确认值）见仓库根 `docs/deployment/saas-main-lite.md`。

新租户由超级管理员页面创建，app 用 `PROVISIONER_DATABASE_URL` 自动建库、授权并迁移。

**铁律**：控制库先、租户库后；worker 停机期间执行；执行前先备份并验证可还原。

## 5. 接流量前验收

- `GET /health` 正常；安全 Cookie、可信代理、精确 CORS 来源符合部署拓扑
- 控制租户、首个 Admin、到期时间、默认仓库可见
- 顺丰 / 快麦 / 闲鱼配置显示 complete 或 incomplete，**日志中不含凭据**
- worker 单实例取得锁（`LOCK_NAME = inventory-manager-worker-v1`）；
  `worker-once` 跑完两个周期后退出

worker 用 MySQL/MariaDB advisory lock 保证单实例：取锁 `GET_LOCK`、
每个租户周期前 `IS_USED_LOCK` 复核归属（丢失则抛 `lock ownership lost`）、结束 `RELEASE_LOCK`。
**第二个实例会直接退出，不会接管**——无双写风险，但 worker 挂掉也不会自动补位。

## 6. 回滚

| 阶段 | 做法 |
|---|---|
| 接流量前失败 | 保持维护窗口，停 app/worker，用迁移前**完整备份**恢复业务库与控制库。不要只回滚部分表 |
| 接流量后失败 | 停止受影响写操作、保留完整备份，**向前修复**；已有新数据时禁止直接降级迁移 |

## 7. NAS 部署（群晖）—— 【待补】

本项目的 NAS 部署**尚未落地文档**。仓库根 `docs/deployment/saas-main-lite.md` 明确写着
「NAS 专用配置等待用户样例后再适配」。

已知的相邻参考：`ai_kefu` 有一套独立的 NAS 部署（`ai_kefu/Makefile` 的 `deploy-nas`
+ `ai_kefu/scripts/deploy_nas.sh`，NAS 192.168.50.132 / 用户 xeon_pan /
日志 `/volume1/docker/aikefu/logs/`）。**那是 ai_kefu 的，不适用于本项目，不要照抄。**

**TODO(用户确认)** —— 补齐下列信息后才能写成本章：

| 待确认项 | 为什么必须问 |
|---|---|
| NAS 上 MySQL 的位置（NAS 容器 / 群晖套件 / 另一台机器） | 决定 `DATABASE_URL` / `TENANT_DB_HOST` 能否用 `host.docker.internal`；`config.py` 会按 `/.dockerenv` 分叉 |
| 建库权限账号 | `PROVISIONER_DATABASE_URL` 需 `CREATE DATABASE` + `GRANT` 权限 |
| 镜像仓库路径与凭据 | ai_kefu 用 `docker.cnb.cool/tdcc-demo/jimmy`，本项目是否复用 |
| 容器名、宿主端口、app/worker 是否都上 NAS | worker 是否与 app 同机 |
| `.env` 在 NAS 上的绝对路径 | ai_kefu 放在 `/var/services/homes/xeon_pan/aikefu.env` |
| 日志目录挂载点 | ai_kefu 用 `/volume1/docker/aikefu/logs` |
| 反向代理 / TLS / 公网入口 | 决定 `SESSION_COOKIE_SECURE` 与 `TRUSTED_PROXY_HOPS` 取值 |
| NAS CPU 架构 | Makefile 默认 `linux/amd64`；群晖若为 ARM 需改 `PLATFORM` |

## 8. 故障速查

| 现象 | 原因与处理 |
|---|---|
| `RecursionError: maximum recursion depth exceeded`（拉取闲鱼订单时） | gevent monkey patch 晚于 SSL 导入。检查 `run.py` 首行必须是 `gevent.monkey.patch_all()`，且 `gunicorn_config.py` 中 `preload_app = False`。**该问题只在 x86 服务器出现，本地 Mac 不复现**——不要因本地正常就放松约束 |
| 启动即抛 `Credentialed CORS requires exact HTTP origins` | `CORS_ORIGINS` 含非法值（必须精确 origin，不可带 path/query） |
| 租户数据串库 | `bind_request_tenant` / `TenantSession.get_bind` 链路；检查 ContextVar 绑定与 `teardown_request` 清理 |
| worker 起不来且无报错 | 可能未抢到锁（已有实例持有）。这是预期行为，非故障 |

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

`Makefile` 还提供 `build-push`、`check-nas`、`deploy-nas`、`release-nas`、
`nas-status`、`nas-logs`。NAS 的连接配置保存在仓库外，具体操作见第 7 节。

Docker 镜像构建会分别从 `frontend/` 和 `frontend-mobile/` 的锁文件生成 PC 与移动端静态资源，
不使用工作区中已有的前端构建产物。

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

2026-09 同单双设备预约新增业务迁移 `20260914_multi_device_booking`（两张关联/幂等表和 `rentals.booking_id`）。
更新应用前按上述流程升级所有租户库；旧租赁不自动合并，关联字段保持空。本变更未增加控制库迁移。
业务迁移当前统一到 `20260914_merge_booking_alerts`，合并双机预约与远程套餐/退款提醒两条迁移历史，不改写已发布的父版本。

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

## 7. NAS 部署（群晖）

现网部署目录为 `/volume1/docker_5/inventory-manager`，生产环境文件为该目录下的
`app.env`。开发机通过仓库外的 `~/.config/xianyu-agent/nas.env` 指定这两个绝对路径；
发布脚本不会上传或覆盖生产密钥。`app` 和 `worker` 使用同一个镜像，运行在
`xianyu-saas-lite` 网络，`xianyu-frpc` 提供入口。

日常发布先执行 `make check-nas`，完成控制库及所有租户库备份与恢复验证后执行
`make release-nas BACKUP_VERIFIED=backup-verified`，最后用 `make nas-status` 和
健康检查验收。完整发布、回滚与首次准备步骤见仓库根
`docs/deployment/saas-main-lite.md`。若容器曾通过其他方式更新，发布前应对照运行中的
app/worker 镜像核对 `current.env`，确保它记录的是实际运行版本。

## 8. 故障速查

| 现象 | 原因与处理 |
|---|---|
| `RecursionError: maximum recursion depth exceeded`（拉取闲鱼订单时） | gevent monkey patch 晚于 SSL 导入。检查 `run.py` 首行必须是 `gevent.monkey.patch_all()`，且 `gunicorn_config.py` 中 `preload_app = False`。**该问题只在 x86 服务器出现，本地 Mac 不复现**——不要因本地正常就放松约束 |
| 启动即抛 `Credentialed CORS requires exact HTTP origins` | `CORS_ORIGINS` 含非法值（必须精确 origin，不可带 path/query） |
| 租户数据串库 | `bind_request_tenant` / `TenantSession.get_bind` 链路；检查 ContextVar 绑定与 `teardown_request` 清理 |
| worker 起不来且无报错 | 可能未抢到锁（已有实例持有）。这是预期行为，非故障 |

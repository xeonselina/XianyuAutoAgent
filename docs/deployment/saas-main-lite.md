# SaaS Lite 部署与迁移

本交付只有 app 与 worker 两个进程，共用一个镜像。数据库、反向代理和公网入口由运行环境提供；NAS 专用配置等待用户样例后再适配。

## 环境准备

复制 `InventoryManager/.env.example` 为受保护的 `.env`。app 和 worker 都需要 bootstrap `DATABASE_URL`、`CONTROL_DATABASE_URL`、租户数据库地址、固定前缀及 `SAAS_MASTER_KEY`。`PROVISIONER_DATABASE_URL` 和腾讯云短信配置仅给 app；不要给 worker 数据库建库权限。

`CORS_ORIGINS` 只能填写明确的 `http` 或 `https` 来源，多项以逗号分隔。生产环境启用安全 Cookie，并按实际反向代理层数设置 `TRUSTED_PROXY_HOPS`。

## 首次迁移

1. 创建数据库完整备份，并验证可以还原。
2. 进入维护窗口，停止写流量和 worker。
3. 迁移控制库：

   ```bash
   cd InventoryManager
   alembic -c control_alembic.ini upgrade head
   ```

4. 创建首个超级管理员：

   ```bash
   python -m flask bootstrap-platform-admin --username '<admin>'
   ```

5. 把旧生产库迁移为默认租户。下列两个确认值必须在备份和维护窗口均已核实时使用：

   ```bash
   python -m flask migrate-default-tenant \
     --name '<tenant-name>' \
     --admin-phone '<admin-phone>' \
     --expires-at '<ISO-8601-expiry>' \
     --db-name inventory_management \
     --province '<province>' \
     --city '<city>' \
     --confirm-maintenance maintenance-enabled \
     --confirm-backup backup-verified
   ```

迁移时可临时提供 `.env.example` 末尾列出的旧集成键。成功后立即从运行环境删除；后续配置在仓库或闲鱼店铺页面维护。

## 发布与租户升级

每次发布先备份，再执行控制库迁移和全部已激活租户的业务迁移：

```bash
alembic -c control_alembic.ini upgrade head
python -m flask upgrade-tenant-databases
```

新租户由超级管理员页面创建，app 使用 `PROVISIONER_DATABASE_URL` 同步建库、授权并迁移；worker 不参与 provisioning。

## 同一镜像的两个进程

```bash
make build IMAGE='<registry/image:tag>' PLATFORM=linux/amd64
make push IMAGE='<registry/image:tag>'
make run-app IMAGE='<registry/image:tag>' ENV_FILE=.env APP_PORT=5002
make run-worker IMAGE='<registry/image:tag>' ENV_FILE=.env
```

镜像默认命令是 app。worker 的覆盖命令是 `python worker.py`。同一套控制库只能运行一个 worker；它使用 MariaDB advisory lock，第二个实例不会待机接管。
上述 make worker 目标会把 provisioner 和腾讯短信键覆盖为空；后续 NAS 配置也必须保持这项权限隔离。

受控检查可运行一次 shipping 与闲鱼周期后退出：

```bash
make worker-once IMAGE='<registry/image:tag>' ENV_FILE=.env
# 等价覆盖命令：python worker.py --once
```

## 接流量前验收

- app `/health` 正常，安全 Cookie、可信代理和精确 CORS 来源符合部署拓扑。
- 控制租户、首个 Admin、到期时间和默认仓库可见。
- 顺丰、快麦、闲鱼配置明确显示 complete 或 incomplete，日志不含凭据。
- worker 单实例取得锁；一次模式完成两个周期并退出。
- 抽查租赁、库存、发货、打印、验货和多店铺同步。
- 检查 app/worker 日志无持续异常，再恢复业务流量。

## 失败与回滚

接流量前失败：保持维护窗口，停止 app/worker，用迁移前完整备份恢复业务库和控制库，再复核 head 与关键计数。不要只回滚部分表。

接流量后失败：先停止受影响写操作并保留完整备份，采用向前修复；不要在已有新数据后直接降级迁移。

NAS 的进程定义、健康检查和日志路径，以及公网入口、TLS、稳定 IPv4/IPv6 方案，等待用户提供 NAS 配置样例和网络条件后决定。

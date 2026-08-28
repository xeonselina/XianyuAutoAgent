# SaaS Main Lite 群晖一键发布设计

## 1. 背景

`saas-main-lite` 只交付一个 `InventoryManager` 镜像，并以不同命令运行 app 与 worker。当前 `InventoryManager/Makefile` 只能在本机完成 build、push 和临时 `docker run`，尚不能像 `ai_kefu` 一样从开发机一条命令更新群晖 NAS。

NAS 上的公网入口由 Docker 容器中的 frpc 提供。app 必须与 frpc 位于同一个用户自定义 Docker 网络，并通过稳定的网络别名被 frpc 访问，不能依赖动态容器 IP。

## 2. 目标与非目标

### 2.1 目标

- 用 `make release-nas` 从本机完成构建、推送和 NAS 更新。
- app 与 worker 使用同一个不可变镜像 tag 和 digest。
- 用 NAS Docker Compose 管理 app、worker、迁移任务、健康检查和重启策略。
- 确保 frpc 与 app 共享外部 Docker 网络，并以 `inventory-manager-app:5002` 转发。
- 后续更新重复执行同一个命令，不覆盖 NAS 上的生产密钥。
- 保留 `make deploy-nas IMAGE_TAG=<tag>`，用于部署已经推送的指定版本。
- 在破坏旧运行实例前完成镜像、SSH、Compose、frpc 网络和配置文件预检。

### 2.2 非目标

- 不构建 app、worker 两个镜像。
- 不在仓库、镜像、Compose 或命令行输出中保存 NAS 密码、数据库密码、`SAAS_MASTER_KEY` 等密钥。
- 不由发布脚本安装或升级 frpc/frps，也不自动改写未知格式或未知挂载位置的 frpc 配置。
- 不使用 Watchtower 或可变的 `latest` tag 自动迁移生产数据库。
- 不自动执行首次默认租户迁移、创建首个管理员或恢复数据库；这些操作需要业务参数和人工确认。
- 不承诺数据库迁移后的自动降级回滚。

## 3. 方案选择

### 3.1 采用：NAS Docker Compose + 外部 FRP 网络

提交一份 NAS 专用 Compose 文件，由远程部署脚本更新版本文件并执行 `docker compose`。Compose 的 app、worker 引用同一镜像；app 使用默认 CMD，worker 覆盖为 `python worker.py`。

优点：服务拓扑、网络、环境隔离、健康检查和重启策略都可声明和重复执行；指定历史 tag 也能可靠重建。缺点：NAS 必须可用 Docker Compose，且首次需要准备生产环境文件和 frpc 本地目标。

### 3.2 不采用：逐条 `docker run`

该方式与现有 `ai_kefu/scripts/deploy_nas.sh` 接近，初始代码更少，但两个服务的参数、网络和升级顺序容易漂移，也不利于审计当前部署版本。

### 3.3 不采用：Watchtower 或 webhook 自动更新

它们适合无状态容器，但不能安全表达本项目的控制库迁移、租户库迁移、worker 单实例和失败停机要求。

## 4. 文件与职责

### 4.1 `InventoryManager/Makefile`

新增以下公开目标：

- `build-push`：使用 Buildx 构建并推送单个 `linux/amd64` 镜像。
- `check-nas`：执行 SSH、Docker、Compose、环境文件、frpc 容器及网络预检，不改变 app/worker。
- `deploy-nas`：部署已存在的 `IMAGE_TAG`，不在本机构建镜像。
- `release-nas`：生成不可变 tag，依次执行 `build-push` 和 `deploy-nas`。
- `nas-status`、`nas-logs`：查看版本、容器状态及有限日志，便于发布后检查。

默认镜像为 `docker.cnb.cool/tdcc-demo/jimmy/inventory-manager`，但 registry、image name、NAS 主机和部署路径都允许用环境变量覆盖。tag 由 UTC/本地时间戳和短 Git SHA 组成，不推送 `latest`。

### 4.2 `InventoryManager/deploy/nas/docker-compose.yml`

定义以下服务：

- `app`：使用镜像默认 CMD，读取 NAS 上的生产 env，加入 FRP 外部网络，网络别名固定为 `inventory-manager-app`，不必向 NAS 宿主机发布端口。
- `worker`：使用同一镜像，命令为 `python worker.py`；清空 provisioner 与腾讯短信变量，保持现有最小权限约束。
- `migrate-control`：一次性执行 `alembic -c control_alembic.ini upgrade head`。
- `migrate-tenants`：一次性执行 `python -m flask --app run.py upgrade-tenant-databases`。

app 的 Compose 健康检查使用镜像内 Python 标准库请求 `http://127.0.0.1:5002/health`，不要求在运行镜像中增加 curl。

Compose 通过外部变量接收完整镜像引用、FRP 网络名称和生产 env 的绝对路径。生产 env 不由 Compose 创建，也不提交 Git。

### 4.3 `InventoryManager/scripts/deploy_nas.sh`

脚本只负责编排发布：验证输入、复用 SSH 连接、同步非敏感 Compose 文件、运行远程 Docker 命令、保存当前与上一个镜像 tag，并输出可执行的诊断信息。脚本使用 `set -euo pipefail` 且关闭命令回显，不打印 env 或密码。

SSH 默认使用本机 SSH 配置和密钥。为兼容当前 NAS，也允许从仓库外、权限为 `0600` 的部署环境文件读取 `NAS_PASS`/`SUDO_PASS` 并使用 `sshpass`；仓库中不得设置默认密码。

## 5. FRP 网络设计

默认专用网络名为 `xianyu-frp`，可通过 `FRPC_NETWORK` 覆盖。部署预检执行以下检查：

1. `FRPC_CONTAINER` 指定的 frpc 容器存在且正在运行。
2. 网络不存在时创建用户自定义 bridge 网络；已存在时只复用，不删除或重建。
3. frpc 尚未加入该网络时，使用 `docker network connect` 增量接入，不断开其现有网络。
4. Compose app 加入同一 external network，并注册 `inventory-manager-app` 别名。
5. app 健康后，使用同一应用镜像启动一次性探针容器，在 `xianyu-frp` 内解析并请求 `http://inventory-manager-app:5002/health`。

frpc 的对应代理必须使用：

```toml
localIP = "inventory-manager-app"
localPort = 5002
```

远端端口和现有 frps 认证保持不变。部署脚本不会猜测或改写 frpc 配置；首次部署前由实际 NAS 配置确认上述目标，之后 app 更新不需要再修改 frpc。

## 6. 发布数据流

`make release-nas` 执行以下顺序：

1. 检查发布范围内的 Git 文件无未提交修改，计算 `<timestamp>-<short-sha>` tag。
2. 使用 `docker buildx build --platform linux/amd64 --push` 构建并推送唯一镜像。
3. SSH 到 NAS，检查 Docker、Compose、生产 env、磁盘空间、frpc 容器及 FRP 网络。
4. 将 NAS Compose 文件和只包含镜像版本、网络名等非敏感值的 release env 原子更新到部署目录。
5. 拉取新镜像，并记录当前 tag 为 `PREVIOUS_IMAGE_TAG`。
6. 停止 worker 和 app，进入短维护窗口。
7. 运行控制库迁移，再运行全部 active 租户业务库迁移；任一步失败立即停止，不启动新版本。
8. 使用新 tag 重建 app 与 worker；等待 app Compose healthcheck 成功。
9. 从 FRP 网络内请求 app 健康端点，并确认 frpc 仍处于 running 状态。
10. 输出新旧 tag、容器状态和后续日志命令。

`make deploy-nas IMAGE_TAG=<tag>` 从第 3 步开始，用于重复部署或选择已存在版本。它仍会执行迁移命令，因为 Alembic upgrade 必须保持幂等。

## 7. 失败处理与回滚

- 预检或拉取失败：不停止现有 app/worker。
- 停止服务后、迁移前失败：恢复旧 release env 并重新启动旧 tag。
- 数据库迁移失败：保持 app/worker 停止，输出迁移日志和恢复指引；必须从发布前已验证备份恢复或向前修复，脚本不自动猜测数据库回滚。
- 新 app 健康检查失败：保留失败容器日志和前一个 tag。只有确认新迁移向后兼容时，才能显式执行 `make deploy-nas IMAGE_TAG=<previous>`；否则向前修复。
- 发布成功后不自动删除旧镜像，至少保留当前和上一个 tag；镜像清理由独立运维操作完成。

生产发布必须在命令开始时明确确认已有可恢复备份。首次默认租户迁移继续遵循现有部署手册中的维护窗口和双确认参数，不塞入日常发布目标。

## 8. 配置与安全

- NAS 生产 env 固定存放在部署目录外或部署目录内权限为 `0600` 的明确路径，部署只检查存在与权限，不上传本地 `.env`。
- 远程 release env 只包含镜像、tag、Compose project、网络名和容器名等非敏感配置。
- NAS 地址、用户、SSH key、密码文件位置通过环境变量或用户目录配置传入，不硬编码密码。
- `sudo` 密码不得拼接进可见命令；优先使用受限 NOPASSWD Docker 运维命令或受保护的 stdin。
- 日志命令限制输出行数，且不打印 `docker inspect` 的完整环境变量。
- registry 登录在本机和 NAS 上一次性完成；部署日志不回显 token。

## 9. 验证与验收

实现阶段至少验证：

- Make 变量展开和 `make -n` 不泄漏凭据。
- `bash -n` 和可用时的 ShellCheck 通过。
- `docker compose config` 对示例 release env 解析成功，app/worker 镜像引用完全一致。
- worker 的敏感 app-only 环境变量仍被覆盖为空。
- 部署预检在 frpc 不存在、网络错误、生产 env 缺失和镜像拉取失败时安全退出，旧服务保持运行。
- NAS 上 app、worker、frpc 都连接到指定外部网络；`inventory-manager-app` 能在该网络解析。
- app `/health` 成功，FRP 网络内探针成功，worker 仅一个实例并取得 advisory lock。
- 重复部署同一 tag 幂等；指定另一个已推送 tag 能重建两个服务。
- Git 不追踪生产 env、部署凭据或 release 运行态文件。

## 10. 首次部署前置条件

首次执行真实发布前需要确认：

- NAS 的 frpc 容器名及配置挂载位置。
- 现有 FRP 代理已把本地目标改为 `inventory-manager-app:5002`。
- NAS 已配置 registry 登录、Docker Compose 和足够磁盘空间。
- NAS 生产 env 已就绪并为 app/worker 提供正确数据库 URL；worker 的 app-only 权限仍由 Compose 清空。
- 控制库和租户库已有可恢复备份，首次管理员与默认租户参数另行执行。

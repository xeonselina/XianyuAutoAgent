# SaaS Lite 部署、迁移与 NAS 发布

本交付只有 app 与 worker 两个进程，共用同一份不可变镜像引用。NAS 通过
Docker Compose 管理这两个进程和迁移任务；公网入口仍由既有的 frpc 容器提供。
日常发布使用 `make release-nas`，不要为 worker 构建第二个镜像，也不要使用
`latest` 这类可变 tag。

生产密钥只保存在 NAS 的 `app.env` 和开发机仓库外的连接配置中。仓库、镜像、
Compose 文件、release metadata 和命令输出都不得保存或打印密码、registry token、
数据库密码或 `SAAS_MASTER_KEY`。

## NAS 首次准备

以下内容由有 NAS 管理权限的操作员完成。首次发布前还没有执行过真实 NAS 验收；
请先用只读预检确认实际容器、网络和配置挂载，而不是猜测现网配置。

### 1. 准备 NAS 生产环境文件

在 NAS 上建立部署目录，并把完整的生产环境变量写入固定的
`/volume1/docker/inventory-manager/app.env`。该文件是 Compose 的
`APP_ENV_FILE`，必须只允许 root 读取；发布过程不会上传本机 `.env` 或覆盖它。

```bash
sudo install -d -o root -g root -m 0755 /volume1/docker/inventory-manager
sudo install -o root -g root -m 0600 /dev/null \
  /volume1/docker/inventory-manager/app.env
sudoedit /volume1/docker/inventory-manager/app.env
sudo chmod 600 /volume1/docker/inventory-manager/app.env
```

按 `InventoryManager/.env.example` 和当前生产拓扑填写 app 所需变量，例如数据库
连接、租户配置、`SAAS_MASTER_KEY`、安全 Cookie、CORS 与可信代理设置。app 和
迁移任务读取这个文件；worker 也读取它，但 Compose 会显式清空
`PROVISIONER_DATABASE_URL` 及所有 Tencent SMS app-only 配置，维持最小权限。

### 2. 为开发机创建仓库外的 NAS 连接配置

`scripts/deploy_nas.sh` 只从开发机用户目录读取连接配置，默认路径固定为
`~/.config/xianyu-agent/nas.env`（设置 `XDG_CONFIG_HOME` 时使用其下同名路径）。
它不会 `source` 这个文件，只接受白名单中的 `KEY=value`，并要求文件 mode 为
`0600`。不要把这个文件、其备份或任何密码提交到 Git。

```bash
mkdir -p ~/.config/xianyu-agent
chmod 700 ~/.config/xianyu-agent
${EDITOR:-vi} ~/.config/xianyu-agent/nas.env
chmod 600 ~/.config/xianyu-agent/nas.env
```

在该文件中填写实际值（等号两侧不要加空格）：

```dotenv
NAS_HOST=nas.example.internal
NAS_USER=deployer
NAS_PORT=22
NAS_DEPLOY_DIR=/volume1/docker/inventory-manager
APP_ENV_FILE=/volume1/docker/inventory-manager/app.env
FRPC_CONTAINER=frpc
FRPC_NETWORK=xianyu-frp
MIN_FREE_SPACE_MB=1024
# SSH_KEY=/absolute/path/to/private-key
```

`NAS_PORT` 默认为 `22`，`LOG_TAIL` 默认为 `200`，`MIN_FREE_SPACE_MB` 默认为
`1024`。空间阈值同时用于部署目录和可发现的 Docker storage filesystem；可以按镜像
规模提高，但必须填写不带前导零的正整数。若 `docker info` 无法发现 storage 路径，
脚本会给出警告并只使用已完成的部署目录检查，不会猜测群晖的存储路径。
`SSH_KEY` 可省略并优先使用本机 SSH 配置。若现有 NAS 必须使用密码认证，
`nas.env` 可以包含受保护的
`NAS_PASS` 与 `SUDO_PASS` 键，但只能保存实际凭据于这个 mode-`0600` 的仓库外
文件，绝不能复制到文档、shell history、CI 变量回显或 Git。优先使用 SSH key 和
受限的 passwordless sudo。密码 sudo 在同一个 SSH 远程 shell 内严格分为认证和执行
阶段：密码只进入专用的 `sudo -v` 标准输入；认证成功后 shell 先把自己的标准输入
替换为 `/dev/null`，安装、生命周期或清理才通过 `sudo -n` 执行。因此即使 sudo
timestamp 或 NOPASSWD 使认证阶段不读取密码，未读输入也会在 root 动作开始前关闭，
不会流入 root 脚本或 Docker/Compose。

### 3. 一次性登录镜像仓库

开发机需要登录才能推送；NAS 的 root Docker 上下文需要登录才能在远端以
`sudo docker compose pull` 拉取私有镜像。分别在可信终端交互式完成一次登录，
不要把 token 放进命令行或 `nas.env`：

```bash
# 开发机
docker login docker.cnb.cool

# NAS（SSH 或 NAS 终端；按提示交互输入凭据）
sudo docker login docker.cnb.cool
```

默认仓库是 `docker.cnb.cool/tdcc-demo/jimmy/inventory-manager`；如有必要可在
调用 Make 时用 `IMAGE_REPOSITORY` 覆盖。远端 release metadata 只记录完整
`IMAGE_REF`、`APP_ENV_FILE` 和 `FRPC_NETWORK`，不含任何登录信息。

### 4. 配置 FRP external Docker network

Compose 将名为 `frp` 的网络声明为 external，并从 `FRPC_NETWORK` 取得实际网络
名（默认示例为 `xianyu-frp`）。app 不发布 NAS 宿主机端口，而是在该网络中注册
稳定别名 `inventory-manager-app`，监听 5002；worker 和迁移容器也使用同一网络。
不要删除、重建或通过 Compose 管理现有的 frpc 网络。

在 NAS 的实际 frpc 配置中，为这个库存服务保留原有的 proxy 名、认证和远端端口，
仅确认本地目标为：

```toml
localIP = "inventory-manager-app"
localPort = 5002
```

发布脚本从不猜测或改写 frpc 配置。`deploy` 在拉镜像和停止旧 app/worker 之前，
会在网络不存在时创建用户自定义 bridge 网络，或在 frpc 尚未接入时增量连接它；
它不会断开 frpc 的其他网络。`check-nas` 是只读的：若外部网络或 frpc 接入尚未
就绪，它会失败并报告问题，不会替你修改运行态。

### 5. 理解根权限发布资产

每次 `check`、`deploy`、`status` 或 `logs` 都会从开发机传输当前的非敏感
Compose 文件和远端生命周期脚本。传输端先计算 SHA-256，再将它们安装为 NAS 上
已验证的 root-owned 文件：

- `$NAS_DEPLOY_DIR/docker-compose.yml`：root:root、`0644`；
- `$NAS_DEPLOY_DIR/.xianyu-agent-release/remote_release.sh`：root:root、`0755`。

临时文件只会出现在远端登录用户的 home 目录。root 会把文件移入部署目录同一文件
系统内的私有 staging 路径，设置 ownership/mode 并校验摘要，再用原子 rename 替换
最终文件并复核最终摘要；精确命名的残留 staging 文件会被清理。root 资产安装、
生命周期和 root staging 清理全部从空环境开始，只设置受控的
`PATH=/usr/local/bin:/usr/bin:/bin` 与 `HOME=/root`（生命周期另接收已验证的非敏感
配置）。`app.env`、本机 `.env` 和任何凭据均不会被上传。远端的
`current.env`/`previous.env` 也由 root 创建并要求 `0600`。

## 日常发布

先确认控制库和所有租户库已有可恢复备份，并已安排可接受的短维护窗口。备份确认
是破坏性动作的硬门：`BACKUP_VERIFIED` 必须精确等于 `backup-verified`。

在 `InventoryManager` 目录运行：

```bash
cd InventoryManager
make check-nas
make release-nas BACKUP_VERIFIED=backup-verified
make nas-status
make nas-logs LOG_TAIL=200
```

`make release-nas` 要求 `InventoryManager` 范围的 Git 工作区干净。它生成
`<YYYYMMDD-HHMMSS>-<short-git-sha>` 的唯一 tag，以 `linux/amd64` 构建并推送，
然后把同一个完整镜像引用部署给 app、worker 和两个迁移任务。将 tag 视为不可变：
不要重推同名 tag，也不要替换已发布 tag 的内容。

`make check-nas` 不会停止、拉取、创建网络或重建 app/worker；它验证已部署 release
的 Docker/Compose、root-owned Compose、`app.env` 存在且为 `0600`、frpc 正在运行、
部署目录和 Docker storage 可用空间、外部网络已存在且 frpc 已接入，以及 Compose
配置可解析。首次部署尚无
`current.env` 时，或网络尚未准备好时，该命令预期会以未就绪状态结束；修复明确的
前置条件后重试。首个 `release-nas` 的 deploy 预检仍会在停止服务前执行同样的
Docker、Compose、环境文件和 frpc 检查，并可创建/接入缺失的 external network。

`make nas-status` 输出 current 与（存在时）previous 的完整 `IMAGE_REF` 和 Compose
状态；`make nas-logs LOG_TAIL=200` 只输出 app/worker 的有限日志，不会 dump 容器
完整环境。

### 部署已推送的指定版本

要重试或选择已经推送的不可变 tag，不在本机构建镜像，改用：

```bash
cd InventoryManager
make deploy-nas IMAGE_TAG=20260828-120000-abc123def456 \
  BACKUP_VERIFIED=backup-verified
make nas-status
make nas-logs LOG_TAIL=200
```

`make deploy-nas IMAGE_TAG=` 后必须给出非空 tag，并且仍会运行幂等的控制库和所有
active 租户迁移。不要省略备份确认，即使只是重新部署相同版本。
相同 `IMAGE_REF` 的重复部署会刷新 `current.env`，但不会把它旋转到
`previous.env`；`previous.env` 始终指向最近一个不同版本。

## 发布顺序与验收

部署脚本按以下顺序工作：

1. 验证本地配置和 root-owned 发布资产；在 NAS 预检 Docker、Compose、`app.env`、
   部署目录/Docker storage 可用空间、frpc 容器与 `FRPC_NETWORK`。
2. 渲染候选 release metadata 并检查 Compose 配置，拉取 app、worker 和迁移所用的
   同一完整镜像引用。
3. 只有这些步骤成功后，才停止当前 worker 与 app，随后依次运行控制库迁移和全部
   active 租户数据库迁移。
4. 提升 release metadata，重建 app/worker，等待 app Compose healthcheck 成功。
5. 在 `FRPC_NETWORK` 内用同一镜像探测
   `http://inventory-manager-app:5002/health`，并确认 frpc 仍在运行。

因此预检、Compose 配置或镜像拉取失败时，旧 app/worker 不会被停止。发布成功后用
脚本直接输出新版本、前一个不同版本、app/worker 容器状态和后续
`make nas-logs LOG_TAIL=200` 命令。镜像清理是独立运维操作，至少保留 current 与
previous tag。

日常发布自动执行的数据库步骤与以下命令等价；只在排障或经维护窗口授权的人工操作
中单独运行它们：

```bash
alembic -c control_alembic.ini upgrade head
python -m flask --app run.py upgrade-tenant-databases
```

## 本地同一镜像的进程（非 NAS 发布）

本地或其他受控环境仍可使用同一个镜像启动两个进程：

```bash
make build IMAGE='<registry/image:tag>' PLATFORM=linux/amd64
make push IMAGE='<registry/image:tag>'
make run-app IMAGE='<registry/image:tag>' ENV_FILE=.env APP_PORT=5002
make run-worker IMAGE='<registry/image:tag>' ENV_FILE=.env
make worker-once IMAGE='<registry/image:tag>' ENV_FILE=.env
```

镜像默认命令是 app；worker 覆盖命令是 `python worker.py`。同一套控制库只应运行
一个 worker，它使用 MariaDB advisory lock；受控检查的等价覆盖命令是
`python worker.py --once`。这些本地 Make 目标同样会清空 worker 的 provisioner 与
Tencent SMS app-only 配置。

## 首次数据库初始化（非日常发布）

首次默认租户迁移需要业务参数和双确认，不会由 NAS 日常发布目标自动执行：

1. 创建数据库完整备份，并验证可以还原。
2. 进入维护窗口，停止写流量和 worker。
3. 迁移控制库：

   ```bash
   cd InventoryManager
   alembic -c control_alembic.ini upgrade head
   ```

4. 创建首个超级管理员：

   ```bash
   python -m flask --app run.py bootstrap-platform-admin --username '<admin>'
   ```

5. 将旧生产库迁移为默认租户。只有备份与维护窗口都已核实时才使用：

   ```bash
   python -m flask --app run.py migrate-default-tenant \
     --name '<tenant-name>' \
     --admin-phone '<admin-phone>' \
     --expires-at '<ISO-8601-expiry>' \
     --db-name inventory_management \
     --province '<province>' \
     --city '<city>' \
     --confirm-maintenance maintenance-enabled \
     --confirm-backup backup-verified
   ```

新租户由超级管理员页面创建。app 使用 `PROVISIONER_DATABASE_URL` 同步建库、授权并
迁移；worker 不参与 provisioning。

## 失败处理与恢复

- 预检、Compose 配置或镜像拉取失败：旧 app/worker 保持运行；修正可见错误后从
  `make check-nas` 或指定 tag 部署重新开始。
- 停止旧 app/worker 返回非零：脚本会立即用 `current.env` 对当前版本执行一次
  best-effort `up` 恢复，明确报告恢复成功或失败，并始终返回原始 stop 状态；不会进入
  迁移。若恢复失败，保持维护窗口并人工检查两个容器状态。
- 迁移失败：app 和 worker 会保持停止，`current.env` 与 `previous.env` 保留以供诊断。
  脚本绝不自动降级 schema 或猜测数据库回滚。保留迁移日志，依据已经验证的备份恢复
  或进行向前修复，然后重新部署；没有明确的人为恢复决策，不要恢复业务流量。
- 新 app 健康检查或 FRP 网络探针失败：保留失败容器日志和 previous tag，先运行
  `make nas-status`、`make nas-logs LOG_TAIL=200`。只有在确认新迁移向后兼容时，才
  能显式用 `make deploy-nas IMAGE_TAG=<previous-tag>` 重建旧镜像；否则进行向前修复。
  该命令仍会执行 upgrade，不会执行数据库 downgrade。

接流量前必须同时确认 app `/health`、FRP 网络内探针、frpc running 状态和单实例
worker advisory lock；随后再从既有公网入口验证 `/health`。真实 NAS 的只读预检、
frpc 配置挂载确认及首次端到端发布仍须由获授权的操作员执行并记录，不能用本地测试
替代。

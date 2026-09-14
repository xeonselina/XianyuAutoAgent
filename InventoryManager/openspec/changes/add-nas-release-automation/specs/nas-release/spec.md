## ADDED Requirements

### Requirement: 单镜像一键发布

系统 MUST 提供一条本机 Make 命令，将同一个不可变 `linux/amd64` 镜像构建并推送到 registry，再用该镜像更新 NAS 上的 app 与 worker。app MUST 使用镜像默认命令，worker MUST 覆盖为 `python worker.py`。

#### Scenario: 发布新版本

- **WHEN** 操作者执行 `make release-nas` 且本机、registry 与 NAS 预检均通过
- **THEN** 系统构建并推送一个新 tag，并用完全相同的镜像引用重建 app 与 worker

#### Scenario: 部署已有版本

- **WHEN** 操作者执行 `make deploy-nas IMAGE_TAG=<tag>`
- **THEN** 系统跳过本机构建并在 NAS 部署指定的已推送 tag

### Requirement: FRP 共享网络

系统 MUST 确保 frpc 容器与 app 位于同一个用户自定义 external Docker network。app MUST 在该网络提供稳定别名 `inventory-manager-app` 和端口 5002，部署不得依赖动态容器 IP。

#### Scenario: frpc 尚未加入目标网络

- **WHEN** frpc 正在运行但尚未加入已配置的 FRP 网络
- **THEN** 部署将 frpc 增量连接到该网络且不移除其现有网络连接

#### Scenario: 验证网络内访问

- **WHEN** 新 app 通过自身健康检查
- **THEN** 部署从同一 FRP 网络解析 `inventory-manager-app` 并成功请求其 `/health` 端点后才报告成功

#### Scenario: frpc 不可用

- **WHEN** 配置的 frpc 容器不存在或未运行
- **THEN** 部署在停止旧 app/worker 前失败并输出不含秘密的诊断信息

### Requirement: 受控数据库迁移

系统 MUST 在短维护窗口内先停止 worker 与 app，再依次升级控制库和所有 active 租户业务库，迁移成功后才启动新版本。

#### Scenario: 迁移成功

- **WHEN** 控制库和租户库迁移均成功
- **THEN** 系统使用新 tag 启动 app 与 worker，并继续健康验收

#### Scenario: 迁移失败

- **WHEN** 任一迁移命令失败
- **THEN** 系统保持 app 与 worker 停止，保留迁移日志与前一 tag，并要求恢复已验证备份或向前修复

### Requirement: 生产秘密隔离

系统 MUST 从 NAS 上权限受限的生产 env 文件向容器注入秘密。发布不得上传本地 `.env`，不得在仓库、镜像、Compose、release 元数据或日志中硬编码或回显秘密。

#### Scenario: 生产 env 缺失

- **WHEN** NAS 上配置的生产 env 文件不存在或权限不符合要求
- **THEN** 部署在改变旧服务前失败

#### Scenario: worker 权限隔离

- **WHEN** Compose 启动 worker
- **THEN** provisioner 数据库和腾讯短信相关环境变量被覆盖为空，即使生产 env 中存在这些值

### Requirement: 安全失败和版本留存

系统 MUST 在破坏性步骤前完成 SSH、Docker、Compose、镜像、生产 env 和 FRP 网络预检，并至少保留当前 tag 与前一个 tag 的发布元数据。

#### Scenario: 预检失败

- **WHEN** SSH、Docker、Compose、镜像拉取、生产 env 或 FRP 网络预检失败
- **THEN** 旧 app 与 worker 继续运行且发布返回非零状态

#### Scenario: 新 app 不健康

- **WHEN** 迁移成功但新 app 未在期限内通过自身健康检查或 FRP 网络探针
- **THEN** 发布返回非零状态、保留失败日志与前一 tag，并且不自动降级数据库

### Requirement: 可重复运维

系统 MUST 提供只读的 NAS 状态和有限日志入口，并使重复部署同一 tag 保持幂等。

#### Scenario: 重复部署

- **WHEN** 操作者再次部署当前 tag
- **THEN** 迁移命令安全重复执行且 app、worker、frpc 网络关系保持不变

#### Scenario: 查看状态

- **WHEN** 操作者运行 NAS 状态或日志 Make 目标
- **THEN** 系统显示当前 tag、容器健康状态和有限日志，但不显示完整容器环境或秘密

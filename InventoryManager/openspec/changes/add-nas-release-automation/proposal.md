# Change: 增加群晖 NAS 一键发布

## Why

`saas-main-lite` 已能构建一个同时运行 app 与 worker 的镜像，但缺少可重复、可验证的 NAS 发布流程。公网入口由 Docker frpc 提供，因此 app 更新还必须保持与 frpc 的共享网络和稳定服务名。

## What Changes

- 增加 `make release-nas`，从本机完成单镜像构建、推送和 NAS 更新。
- 增加指定 tag 的 `make deploy-nas` 以及 NAS 预检、状态和日志目标。
- 增加 NAS 专用 Compose，使用同一镜像运行 app、worker 和一次性迁移任务。
- 使用外部 Docker 网络连接 frpc 与 app，并验证 `inventory-manager-app:5002` 的网络内健康状态。
- 保护 NAS 生产 env 和部署凭据，不上传本地 `.env` 或硬编码密码。
- 在迁移和健康检查失败时停止发布并提供受控恢复路径。

## Impact

- Affected specs: `nas-release`（新增）
- Affected code: `InventoryManager/Makefile`、`InventoryManager/deploy/nas/`、`InventoryManager/scripts/`、部署测试与 `docs/deployment/saas-main-lite.md`
- External systems: 群晖 Docker/Compose、Docker registry、现有 frpc 容器和外部网络
- Canonical design: `docs/superpowers/specs/2026-08-28-saas-main-lite-nas-release-design.md`

## Context

app 与 worker 共用一个镜像。NAS 上的 frpc 运行在 Docker 容器内，需要通过用户自定义 Docker 网络和稳定别名访问 app。当前 Makefile 只有本地 build/push/run 目标，缺少远程编排、迁移顺序和健康验证。

完整设计见 `../../../../docs/superpowers/specs/2026-08-28-saas-main-lite-nas-release-design.md`。

## Goals / Non-Goals

- Goals: 单命令发布、不可变 tag、同镜像双进程、FRP 共享网络、迁移与健康检查、密钥隔离。
- Non-Goals: 第二个 worker 镜像、自动升级 frpc、自动首次租户迁移、数据库自动降级、Watchtower。

## Decisions

- Decision: 使用 NAS 专用 Docker Compose，而不是逐条 `docker run`。
- Decision: 使用可配置的 external bridge network；frpc 与 app 都加入该网络，app 别名固定为 `inventory-manager-app`。
- Decision: `release-nas` 负责 buildx push 后调用指定 tag 的 `deploy-nas`。
- Decision: 生产 env 只驻留 NAS；远程同步内容只包含 Compose 与非敏感 release 元数据。
- Decision: 迁移失败不自动回滚数据库；健康失败只在确认迁移向后兼容时允许显式选择旧 tag。

## Risks / Trade-offs

- MariaDB DDL 迁移可能无法事务性撤销；通过发布前备份、维护窗口和失败停机降低风险。
- frpc 可能已经连接多个网络；通过显式 `FRPC_NETWORK` 和网络成员检查避免猜测。
- 密码式 SSH 方便但有泄漏风险；默认 SSH key，密码兼容值只从仓库外权限受限文件读取。

## Migration Plan

1. 准备 NAS 生产 env 和 registry 登录。
2. 创建或复用 FRP 外部网络，并把 frpc 增量接入。
3. 将 frpc 本地目标设为 `inventory-manager-app:5002`。
4. 创建数据库备份并验证恢复能力。
5. 首次运行 `make release-nas`，核对 app、worker、frpc 网络和健康状态。
6. 后续使用同一命令发布；指定历史 tag 时使用 `make deploy-nas IMAGE_TAG=<tag>`。

## Open Questions

- 实现后首次真实部署时，从 NAS 实际状态确认 frpc 容器名、配置挂载位置和 external network 名；这些值保持可配置，不写死生产秘密。

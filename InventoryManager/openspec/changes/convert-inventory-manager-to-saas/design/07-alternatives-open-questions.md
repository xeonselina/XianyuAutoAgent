# 备选方案与待确认事项

> 返回：[总体设计索引](../design.md)

## 19. Alternatives Considered

### Shared tables with `tenant_id`

已在 D01 中否决。它的基础设施成本最低，但所有租户共享大表，任何遗漏过滤都可能直接泄露数据，单租户备份/恢复和数据迁出也更复杂，不符合项目负责人的风险偏好。

### Database per tenant on a shared MySQL instance

D01 已确认采用。MySQL 中 database/schema 基本同义；每个租户运行独立业务表集合并使用只能访问本 schema 的独立账号，但共享实例的 CPU、内存、IO 和故障域。通过 `database_instance_key` 预留未来跨实例迁移。

### Shared MySQL data account

D01 已否决。共享账号最省凭证管理成本，但路由或 SQL 错误时数据库权限无法阻止串库，且单个密码泄露会暴露全部租户 schema，不符合本项目选择独立数据库的隔离目的。

### Encrypted stored database passwords versus deterministic derivation

D08 经修订后采用确定性派生：控制库只保存非敏感上下文和版本，不保存数据库密码密文或每条 DEK。代价是根密钥轮换必须实际修改所有租户 MySQL 账号；项目负责人接受该运维代价以换取更简单的数据模型和恢复路径。纯 `hash(tenant_id + 固定字符串)` 因源码可反算全部密码而被否决。

### Per-record envelope encryption versus one-root direct encryption

D08 已确认外部 Secret 使用同一平台根密钥派生用途/记录/修订级 key，再以 AES-256-GCM 直接认证加密。未采用“每条随机 DEK + 根密钥包裹 DEK”的两层信封模型，也不在 Core 引入 KMS；这样控制库字段、备份和恢复路径更简单，正常运行只需离线备份一把逻辑根密钥。接受的代价是平台根密钥换代必须重加密全部外部 Secret，且根密钥泄露会影响所有租户，因此必须用最小挂载、异地副本和完整轮换 runbook 控制风险。

### MySQL instance per tenant

物理隔离与资源隔离更强，但首发基础设施和运维成本过高。未来可作为企业套餐或私有化部署选项，不是所有租户的默认形态。

### Managed MySQL for Core

托管 MySQL 能降低应用主机与数据库同时损坏的概率，并提供成熟备份/时间点恢复，但项目负责人决定 Core 阶段暂时继续使用同一云主机上的 Docker MySQL，以控制当前成本和复杂度。该选择是阶段性的，不否定未来迁移；D22 的异机备份、恢复演练和非公网访问属于补偿性上线门禁。

### Immediate microservices rewrite

不能自动解决认证和数据隔离，反而扩大分布式事务、调用鉴权和运维面。先完成模块化单体 SaaS 边界。

### JWT in localStorage

实现直观但扩大 XSS 后 token 被盗风险，且逐设备撤销更复杂。浏览器已按 D45 选择 MySQL server-side session：HttpOnly Cookie 只含不透明随机 token，每次请求核对 session、`auth_version`、membership 和 tenant 状态。D55 已进一步确认 Core 不提供 tenant API key；未来机器调用必须另行设计，不能复用浏览器 token 或第三方 integration/provider credential。

## 20. Open Questions Requiring Approval

具体决策 D01–D59 已逐项确认；当前只剩整体 Approval Gate，以及 Core 之后的在线支付方向：

1. 整体 Approval Gate：是否批准当前完整 SaaS Core 设计进入实现与 delta spec 拆分。
2. Core 之后是否需要在线支付；若需要，收款主体与目标地区决定 Stripe、微信/支付宝或合同转账 provider。

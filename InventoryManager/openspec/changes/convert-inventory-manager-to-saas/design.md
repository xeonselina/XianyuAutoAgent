# 多租户 SaaS 技术设计

> 状态：**讨论草案，尚未批准**。本文是模块化设计入口；具体规则以对应领域模块为准，不在入口重复维护第二份规范。

## 阅读方式

- 先读本索引，再按任务只打开相关模块。
- 查询某个已讨论决定时，先在[决策协议与记录](design/00-decisions.md)中搜索 D 编号。
- 修改跨模块规则时，只在下表指定的权威模块写完整规则，其他模块使用引用，避免同一规则出现多个版本。
- 尚未完成整体批准、delta specs、任务清单和严格校验前，不进入代码实现或生产迁移。

## 模块导航

| 模块 | 原章节 | 权威内容 |
|---|---:|---|
| [决策协议与记录](design/00-decisions.md) | 0 | D01–D59 决策表、确认记录、取代关系和决策流程 |
| [基础架构与数据模型](design/01-foundations-data-model.md) | 1–5 | 背景、目标、Docker 架构、租户解析、数据库隔离、控制库与租户库模型 |
| [身份、控制面与产品工作流](design/02-identity-product-workflows.md) | 6–7 | 登录、会话、RBAC、平台管理员、邀请、注册续期、仓库、附件和前端/API 工作流 |
| [集成、密钥、任务与文件](design/03-integrations-jobs-files.md) | 8–10 | 根密钥、Secret、顺丰/短信等 provider、后台任务、面单/PDF/导出边界 |
| [租户生命周期与性能](design/04-lifecycle-performance.md) | 11–12 | 套餐、席位、到期、暂停、删除、手机号释放、实时查询、API 聚合和连接预算 |
| [安全、迁移与测试](design/05-security-migration-testing.md) | 13–15 | 安全/隐私基线、阶段迁移、回滚边界、隔离与并发测试矩阵 |
| [运维、监控与灾备](design/06-operations-recovery.md) | 16–18 | 三层监控、NAS 备份、整机恢复、recovery hold、交付估算和风险 |
| [备选方案与审批门槛](design/07-alternatives-open-questions.md) | 19–20 | 被否决方案、Core 之外的未来决策边界与整体 Approval Gate |

## 常用定位

| 要处理的问题 | 优先读取 |
|---|---|
| 注册、登录、成员、验证码、平台管理员 | [02](design/02-identity-product-workflows.md)；数据字段同时看 [01](design/01-foundations-data-model.md) |
| 租户数据库、账号派生、根密钥、路由 | [01](design/01-foundations-data-model.md) 与 [03](design/03-integrations-jobs-files.md) |
| 仓库、设备、附件、rental、甘特、接力 | [02](design/02-identity-product-workflows.md)；查询性能同时看 [04](design/04-lifecycle-performance.md) |
| 顺丰月结账号、下单、打印、物流、闲鱼 | [03](design/03-integrations-jobs-files.md) 与 [02](design/02-identity-product-workflows.md) |
| 到期、暂停、删除、兑换码、席位 | [04](design/04-lifecycle-performance.md) |
| 备份、恢复、监控、RPO/RTO | [06](design/06-operations-recovery.md)；恢复数据模型同时看 [01](design/01-foundations-data-model.md) |
| 首次切换、兼容、测试和发布门禁 | [05](design/05-security-migration-testing.md) |

## 跨模块权威边界

- 决策是否已确认，只以 [00-decisions.md](design/00-decisions.md) 为准。
- tenant context、数据库身份和控制库数据结构，只以 [01-foundations-data-model.md](design/01-foundations-data-model.md) 为准。
- 认证授权、tenant-scoped 最终事务门禁和统一控制库锁序，只以 [02-identity-product-workflows.md](design/02-identity-product-workflows.md) 为准。
- provider credential、外部副作用与任务执行边界，只以 [03-integrations-jobs-files.md](design/03-integrations-jobs-files.md) 为准。
- subscription、suspension、deletion 的有效状态归约，只以 [04-lifecycle-performance.md](design/04-lifecycle-performance.md) 为准。
- 发布门禁和必须覆盖的测试，只以 [05-security-migration-testing.md](design/05-security-migration-testing.md) 为准。
- 备份、恢复 epoch、recovery hold 和运行监控，只以 [06-operations-recovery.md](design/06-operations-recovery.md) 为准。
- D01–D59 的 Core 方案决策均已确认；[07-alternatives-open-questions.md](design/07-alternatives-open-questions.md) 只保留被否决方案、Core 之外未来另立决策的能力和整体 Approval Gate，不再有阻塞本次审批的产品选择。

## 当前审批状态

- SaaS Core 总体方案仍未最终批准。
- D53 已全部确认：平台可增加或减少服务期，采用“增减整数天 + 独立立即到期”输入，由任一 active 平台管理员逐次完成 TOTP/恢复码验证后单人提交；允许目标为 `active`、`expired` 或已完成冻结的 `suspended` 租户，暂停中调整绝不解除暂停，过渡态、recovery hold 和删除流程均拒绝。退款场景只记录原因、受限备注和可选线下参考号，不保存金额/币种/支付状态，也不执行或核对资金退款。D54 已全部确认：开户失败只允许原用户重新完成同手机号 OTP 后自助重试同一 registration attempt；平台没有 retry、abandon 或 cleanup UI，唯一动作是以同一控制事务把旧 attempt/worker fence 为 `superseded_by_replacement`、旧码置为 `revoked(reason=replaced)` 并立即补发唯一新码，registration final commit 与 replacement 只能一方提交。新码精确继承 source code 的 entitlement snapshot、plan revision 和 service duration，只选择新的未来截止日，使用全新密码学上下文且作为不绑定手机号的普通 bearer 支持注册或续期；旧 provisional 资源由 system-only janitor 异步清理且不阻塞新码。D55 已确认 Core 完全不提供 tenant API key，现有 `/external-api` 与全局 `X-API-Key` 移除/禁用，未来外部 API 必须在 Core 之后另立决策。D56 已确认：expired 租户的所有有效成员登录后统一进入过期提示页，Operator 只能查看提示/注销，Admin 只可额外提交兑换码续期，不开放账号安全、顺丰解绑或其他业务/设置；suspended 租户同样没有顺丰解绑例外，必须由平台先恢复，历史 shipment 快照不变。D57 已确认 Core 不提供旧手机号不可接收时的平台人工恢复、代改号、代输 OTP 或 impersonation：若另有 active Admin，由其按既有权限移除旧成员并重新邀请新号，授予/移除 Admin 仍走 D48；最后一名 Admin 丢号只能先恢复旧手机号，其他找回方式留作 Core 之后另立决策。至此 D01–D59 均已确认，只剩 SaaS Core 整体 Approval Gate。
- 总体批准后再创建 delta specs 与 `tasks.md`，运行 `openspec validate convert-inventory-manager-to-saas --strict`，通过后才进入实现。

# 多租户 SaaS 技术设计

> 状态：**SaaS Core 总体方案已批准**（2026-08-21）。本文继续作为模块化设计入口；具体规则以对应领域模块、决策表及 superseding 记录为准，不在入口重复维护第二份规范。

## 阅读方式

- 先读本索引，再按任务只打开相关模块。
- 查询某个已讨论决定时，先在[决策协议与记录](design/00-decisions.md)中搜索 D 编号。
- 修改跨模块规则时，只在下表指定的权威模块写完整规则，其他模块使用引用，避免同一规则出现多个版本。
- delta specs、任务清单和严格校验仍用于普通开发核对；失败项修复后重跑，不再形成进入实现前的独立阶段审批门。生产规模演练按 D64 的 `project_complete_at + 168h` 顺序安排。

## 模块导航

| 模块 | 原章节 | 权威内容 |
|---|---:|---|
| [决策协议与记录](design/00-decisions.md) | 0 | D01–D73 决策表、确认记录、取代关系和决策流程 |
| [基础架构与数据模型](design/01-foundations-data-model.md) | 1–5 | 背景、目标、Docker 架构、租户解析、数据库隔离、控制库与租户库模型 |
| [身份、控制面与产品工作流](design/02-identity-product-workflows.md) | 6–7 | 登录、会话、RBAC、平台管理员、邀请、注册续期、仓库、附件和前端/API 工作流 |
| [集成、密钥、任务与文件](design/03-integrations-jobs-files.md) | 8–10 | 根密钥、Secret、顺丰/短信等 provider、后台任务、面单/PDF/导出边界 |
| [租户生命周期与性能](design/04-lifecycle-performance.md) | 11–12 | 套餐、席位、到期、暂停、删除、手机号释放、实时查询、API 聚合和连接预算 |
| [安全、迁移与测试](design/05-security-migration-testing.md) | 13–15 | 安全/隐私基线、阶段迁移、回滚边界、隔离与并发测试矩阵 |
| [运维、监控与灾备](design/06-operations-recovery.md) | 16–18 | 三层监控、NAS 备份、整机恢复、recovery hold、交付估算和风险 |
| [备选方案与剩余决策](design/07-alternatives-open-questions.md) | 19–20 | 被否决方案，以及 Core 之外仍需另立决策的未来能力 |

## 常用定位

| 要处理的问题 | 优先读取 |
|---|---|
| 注册、登录、成员、验证码、平台管理员 | [02](design/02-identity-product-workflows.md)；数据字段同时看 [01](design/01-foundations-data-model.md) |
| 租户数据库、账号派生、根密钥、路由 | [01](design/01-foundations-data-model.md) 与 [03](design/03-integrations-jobs-files.md) |
| 仓库、设备、附件、rental、甘特、接力 | [02](design/02-identity-product-workflows.md)；查询性能同时看 [04](design/04-lifecycle-performance.md) |
| 顺丰月结账号、下单、打印、物流、闲鱼 | [03](design/03-integrations-jobs-files.md) 与 [02](design/02-identity-product-workflows.md) |
| 到期、暂停、删除、兑换码、席位 | [04](design/04-lifecycle-performance.md) |
| 备份、恢复、监控、RPO/RTO | [06](design/06-operations-recovery.md)；恢复数据模型同时看 [01](design/01-foundations-data-model.md) |
| 首次切换、兼容和普通测试清单 | [05](design/05-security-migration-testing.md) |

## 跨模块权威边界

- 决策是否已确认，只以 [00-decisions.md](design/00-decisions.md) 为准。
- tenant context、数据库身份和控制库数据结构，只以 [01-foundations-data-model.md](design/01-foundations-data-model.md) 为准。
- 认证授权、tenant-scoped 最终事务门禁和统一控制库锁序，只以 [02-identity-product-workflows.md](design/02-identity-product-workflows.md) 为准。
- provider credential、外部副作用与任务执行边界，只以 [03-integrations-jobs-files.md](design/03-integrations-jobs-files.md) 为准。
- subscription、suspension、deletion 的有效状态归约，只以 [04-lifecycle-performance.md](design/04-lifecycle-performance.md) 为准。
- 迁移顺序和必须覆盖的普通测试清单，只以 [05-security-migration-testing.md](design/05-security-migration-testing.md) 为准。
- 备份、恢复 epoch、recovery hold 和运行监控，只以 [06-operations-recovery.md](design/06-operations-recovery.md) 为准。
- D01–D73 的 Core 方案决策均已确认；D64 已取消迁移项目的阶段 Approval Gate、候选签字/receipt/evidence digest 和 hard release gate，D71 明确 SQL-backed 只支持 MySQL 8/MariaDB，D72 采用深度行为等价收缩，D73 明确一个租户可关联多个闲管家账号/闲鱼店铺且订单保留 connection 归属。[07-alternatives-open-questions.md](design/07-alternatives-open-questions.md) 只保留被否决方案和 Core 之外未来另立决策的能力。

## 当前审批状态

- SaaS Core 总体方案已于 2026-08-21 获得项目负责人正式批准；本轮只修改规范文件。D63/D64 允许后续项目按普通开发流程继续，不再设置实现前的独立阶段审批门。
- D53–D57 的最新边界继续按各自 superseding 记录执行。D60 已确认默认租户 36,500 天的唯一 `migration_grant`；D61 只确认三类既有暴露凭证必须“有期限”接受，当前 policy v1 的 30×24 小时是保守默认值/单次上限而非项目负责人逐字指定，且最迟在首次演练开始失效。D63 取消 D12/D62 的代码、schema、核心模块冻结、例外与解冻流程；D64 取消阶段审批门、候选签字/receipt/evidence digest 和 hard release gate。全部项目实现、默认租户迁移工具及必要测试/核对任务完成后直接记录 `project_complete_at=T`，首次生产规模演练使用不早于 `T+168h` 的首个可用窗口；影响迁移结果的实现变更在重跑相关测试后更新 T 并重新计时。
- capability delta specs、`tasks.md` 和 `openspec validate convert-inventory-manager-to-saas --strict --no-interactive` 继续作为普通可勾选任务；发现问题即修复并重跑，不需要项目负责人签字、receipt 或单独 release approval。

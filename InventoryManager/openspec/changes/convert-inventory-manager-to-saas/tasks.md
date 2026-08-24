# SaaS Core 实施任务

## 执行规则

- 本清单按真实技术依赖顺序排列；可独立的盘点、开发和验证可以并行，只有直接依赖的实现或数据前置未完成时才等待。
- 只有实现、自动化测试、演练记录和文档均完成时才勾选任务；仅开始开发、仅完成代码或仅人工确认均不算完成。
- 各阶段末尾的验证项是普通可勾选任务，用来证明结果可复现，不构成额外流程或时间条件。
- D01–D68 以当前决策表和 superseding 记录为准；D63 取消迁移冻结，D64 将项目流程简化为实现、验证、记时、演练、切换和观察，D65–D67 将 SQL-backed 测试简化为串行复用现有 `inventory_management_test` 且不再使用 SQLite 正向 backend；D68 将默认租户旧运单/打印事实迁为独立 `legacy_unattributed` 只读历史；历史文字与当前规则冲突时不得恢复已被取代的流程。
- 实施期间保留用户已有改动，不处理、覆盖或提交与本 change 无关的文件。

## 0. 基线、D12 变更排序与实施准备规划

**依赖/前置条件：** 无。

**完成条件：** 当前 schema、关键数据、HTTP/SQL/连接基线、外部副作用入口和所有活跃 OpenSpec change 均已形成可复现清单；D12 的归档、暂停和保留适配顺序已执行；D61 的已知风险、期限、触发器和最终处置任务已登记；外部依赖的当前状态、责任人和后续实现任务均已形成 readiness 清单；D63/D64 的简化流程已登记。Phase 0 不要求尚未实现的 Core 路由、Secret 退休、监控、NAS、根密钥、外部 smoke 或生产演练产物已经存在，也不阻塞与未完成盘点项无直接依赖的开发。

**可验证结果：** 可用相同数据夹具重跑基线；OpenSpec 列表与 D12 分类一致；每个当前未知或未就绪外部项都有 owner、当前状态、后续任务和适用的 fail-closed 运行规则；清单不会把未来实现结果反向写成 Phase 0 前置。

- [ ] 0.1 盘点所有 HTTP 路由、数据库读写入口、Web 内定时器、独立脚本、第三方调用、文件生成和打印副作用，并为每项标注资源、权限、租户归属和重试风险。
- [ ] 0.2 保存当前 schema、Alembic 链、生产规模行数、关键金额与关联关系、孤儿数据、现有数据库账号/grants 和第三方配置来源的基线快照。
- [ ] 0.3 使用桌面端和移动端 network trace、SQL query counter 与连接 checkout 记录预约、编辑、甘特、搜索、批量发货、顺丰追踪、验货和闲鱼告警的 HTTP 数、SQL 数、p50/p95 及压缩前后字节数。
- [x] 0.4 先将 add-rental-damage-notes 按已完成归档，保留损坏备注产品能力，并登记后续租户路由、RBAC 和输出转义复验项。
- [x] 0.5 再收尾 select-sf-express-type：统一半日达代码和规格、补齐关键测试、确认运单创建后锁定产品类型，然后归档该 change。
- [x] 0.6 随后暂停 batch-print-shipping-orders，记录不建设旧 A4 独立发货单页面；在仓库级分页查询替代完成前不得删除被其他页面共用的待发货查询。
- [x] 0.7 随后暂停 enhance-batch-shipping-workflow，记录不恢复“扫发货单二维码再扫面单”流程，同时保留顺丰自动取号、两联面单和第二联教程二维码。
- [x] 0.8 最后为其余 13 项 active changes 建立“保留功能、随 SaaS 适配”的重基矩阵，逐项映射到可信租户路由、仓库绑定、持久任务、执行快照、聚合 API 和本清单对应阶段，禁止将保留能力降级为暂停、删除或推倒重写。
- [x] 0.9 为所有重基 change 记录 superseded 边界：旧文档与多租户、多仓、D33/D34/D39 或 provider job 冲突时，以本 change 的 delta spec 和当前决策记录为准。
- [ ] 0.10 建立 credential/data exposure containment 与处置台账：只记录 current tree、Git history、日志、镜像/缓存、部署 bundle 和运行环境的已知/未知范围，并为每类仍具权威的值指定 rotate/revoke/retire/D61 处置、owner、期限、触发器、受限记录位置和本清单后续任务。D61 仅允许现有旧数据库账号、默认租户顺丰和快麦三类 legacy 凭证在有效窗口内暂缓，不能把旧值迁移为 Core 身份或新 provider revision；本项只完成盘点、当前可行的操作性隔离和任务映射，不要求 4.9/8.10/10.7 的代码退休、12.9 的最终轮换或 13.1 的生产验证已经完成。
- [ ] 0.11 建立外部 readiness matrix：逐项记录腾讯云短信资质/签名/模板、真实顺丰 capability、CVM/云拨测与通知渠道、NAS 拉取/云盘/恢复、平台根密钥两故障域保管以及生产网络/数据库权限的当前状态、查询时间、owner、所需权限、可用测试窗口、受限记录位置和后续实现任务。未知或尚不存在的 Core 健康端点、NAS wrapper、根密钥副本和恢复结果明确标为 pending；本项只形成准备清单，不要求主动 provider 调用、Core 实现或恢复演练已经发生，相关开发可按自身技术依赖直接推进。
- [x] 0.12 按 D63/D64 记录简化的迁移时间规则：代码、schema、模块和项目可以继续正常修正；必要实现、D61 收口和普通验证任务完成后直接记录 `project_complete_at = T`，首次生产规模迁移演练使用不早于 `T + 168h` 的可用运维窗口；若演练前的实现、schema、迁移 bundle 或运行配置变化，则重跑受影响验证、更新 T 并重新计算 168 小时。
- [ ] 0.13 完成 Phase 0 清单核对：确认 0.1–0.12 的只读基线、D12 处置、D61 台账、外部 readiness matrix 和 D63/D64 时间规则均有 owner 与对应后续任务；未来代码、基础设施、凭证轮换、主动 provider 调用和生产演练结果保持在后续任务中，不作为独立开发开始的循环前置；确认未通过规划文字改变任何运行时产品规则。

## 1. 控制库、平台根密钥与安全基座

**依赖/前置条件：** 根密钥文件位置、宿主机权限、两故障域保管和恢复方式已有可执行方案与 owner；与此实现直接相关的 Phase 0 盘点项可同步补齐。实际文件、离线副本和恢复证明在本阶段及阶段 11 实现，不得反向成为阶段 1 的前置产物。

**完成条件：** 控制库可从空库迁移；密钥、加密上下文、安装标记、不可变事件和最小权限账号均可用；错误密钥或不一致恢复状态会 fail closed。

**可验证结果：** 新空库迁移、普通重启、密钥版本读取、密文防调换、错误根密钥和 marker 不匹配测试全部通过。

- [ ] 1.1 创建 inventory_control 的 expand migrations，覆盖 installation/baseline、tenant/database route、user/membership/session、短信 challenge、邀请、套餐/订阅、兑换码、registration、审计、任务/outbox、生命周期和 recovery run 所需控制面表。
- [ ] 1.2 实现仓库外版本化平台根密钥加载和 installation/baseline marker 校验，确保根密钥值不进入代码、Git、镜像、数据库、普通环境值或日志。
- [ ] 1.3 为租户 DML 密码和平台 SELECT-only 密码实现不同用途域的 HKDF-SHA256 确定性派生，并绑定不可变 tenant/database UUID 与 credential generation。
- [ ] 1.4 为顺丰、闲鱼、快麦凭证、可重复查看的兑换码和平台 TOTP 材料实现按用途、记录 UUID、修订号派生的 AES-256-GCM 认证加密及 AAD 校验。
- [ ] 1.5 建立控制库普通账号、平台 SELECT-only 账号、tenant DML 账号和 provisioning/migration 高权限账号的最小权限边界，禁止应用常规路径持有全库权限。
  - [x] D65 已把人工账号简化为一个可持有全局 `ALL PRIVILEGES WITH GRANT OPTION` 的 DBA 身份；Web、worker、备份与 tenant route 不使用它。本地人工显式启动的迁移/真实数据库测试可复用该账号，不再临时创建 schema-scoped 账号，但 DSN 必须预先固定为 `inventory_management_test` 并启用独立 global-DBA opt-in；生产业务 schema 仍只读，主项仍待生产 runtime 全面接线后关闭。
  - [x] D66 已把真实数据库测试目标统一为现有 `inventory_management_test`：测试串行持有 advisory lock，不再创建数据库、账号/grant 或一次性容器；global DBA 必须另行 opt-in，SQL guard 拒绝切库、实例/账号变更和显式跨 schema 写入。该简化不把 DBA 带入 Web/worker，也不改变生产逐租户权限边界。
  - [x] D67 已进一步要求所有 SQL-backed 正向测试使用同一个 `inventory_management_test`，纯函数/fake/前端不建立无意义连接，SQLite 只剩无连接负向 dialect stub。代码层迁移和 runner 当前收集的 55 个逐 revision MariaDB migration 用例均已完成；当前代码已用单次不中断的完整默认真实库命令验证 isolated、migration 和 shared 三组。
    - [x] Gantt HTTP、rental、registration publication、default expand verifier 和 tenant/control schema qualification 已改为共享或顺序复用同一个 MariaDB schema；纯 verifier 使用 fake receipt/connection，不为形式建立数据库。逐 revision fixture 使用模块级 advisory lock、每 case 空基线 reset、精确库名复核和脱敏 URL repr，不创建库、账号、grant 或第二 schema。
    - [x] 2026-08-24 当前共享真实库批次 `744 passed in 594.44s`；Gantt 单库模块 `10 passed` 后修正统一引擎下控制事务 commit 的观察口径，失败节点复跑 `1 passed`；default tenant identity 的首次/重放时间精度修复与原注册回归 `7 passed`；schema qualification 无数据库负向矩阵 `10 passed`。未连接生产业务 schema，未调用 provider 或打印。
    - [x] runner 当前精确收集的 55 个逐 revision MariaDB migration 用例已按模块用 `-x` 分批全部跑绿；control `base→head→base→head` 为 `1 passed in 564.50s`。分批过程同时验证并修正 MariaDB inspector 的 `BINARY(32)`/CHECK 表达式、默认 `RESTRICT` 省略、CHECK 错误类别、固定 `BINARY` 短输入补零、反射 JSON 文本、历史 revision 与 head 模型的预期类型差异、数据库生成时间窗口及真实 FK 父记录前置。最终只读核对为 `remaining_table_count=0`；未连接生产业务 schema、provider 或打印机。完整默认真实库命令仍由上级 D67 主项追踪。
    - [x] 逐 revision 修复后的当前 shared database group 已完整重跑：`761 passed, 1793 warnings in 633.03s`。warning 均为现有 dateutil/SQLAlchemy `utcnow` 弃用提示；未出现测试失败，未连接生产业务 schema、provider 或打印机。
    - [x] D67 最终连续验证于 2026-08-24 以 `make test-real-db` 一次完整退出 0：isolated `326 passed in 3362.79s`，migration `55 passed in 9872.00s`，shared `761 passed in 647.74s`，合计 `1142 passed`。测试串行复用名称精确为 `inventory_management_test` 的获准测试库；未写生产业务 schema，未调用真实 provider 或打印机。
    - [x] D67 后续将此前要求两个 MySQL 8 实例和三个 URL 的完整 default-backfill 组合用例迁入同一 `inventory_management_test` shared lifecycle，并加入默认 shared selector。MariaDB/MySQL 双兼容 schema preflight digest 取代该用例中的 MySQL 8 专属 observer，仍在 backfill 后重新观察 generation/revision/schema digest；六个已决 backfill steps、空历史 adapter、步骤提交后崩溃续跑、二次幂等重放及 12 类 reconciliation 聚焦运行 `1 passed in 182.19s`。MySQL 8 专属 observer 保留独立测试，不再为本组合用例创建第二实例。
    - [x] 同一连接能力矩阵已在 MariaDB 10.11 上证明 PyMySQL/`utf8mb4`/严格 SQL mode/UTC session、两条独立连接的 `FOR UPDATE SKIP LOCKED` 优先级跳锁语义，以及 connection-bound `GET_LOCK` 获取/拒绝/释放；聚焦运行 `1 passed in 177.37s`，只使用 `inventory_management_test`。
- [ ] 1.6 建立不可变事件、版本号、fencing generation、幂等键、审计 actor/request context 和统一 tenant-first 锁序基础设施。
- [ ] 1.7 实现普通重启语义：同一控制库持久卷、installation marker 和正确根密钥下保留平台 TOTP、恢复码使用状态和仍有效 session；旧快照导入不得走普通重启路径。
- [ ] 1.8 增加密码派生黄金向量、不同用途隔离、密文调换拒绝、nonce/tag 损坏、根密钥错误、版本轮换和日志脱敏自动化测试。
- [ ] 1.9 验证空控制库可重复迁移，最小权限和 crypto 测试通过，缺失/错误根密钥及恢复 marker 不一致时服务拒绝启动或拒绝敏感操作，并保存可复现结果。

## 2. 租户路由、数据库账号与 provisioning

**依赖/前置条件：** 阶段 1 的控制库、密钥派生和最小权限基础可供本阶段调用。

**完成条件：** 可信 session → membership → tenant 只能路由到对应业务库；租户开户、迁移、账号轮换和引擎淘汰均可重入并可从崩溃点恢复。

**可验证结果：** 至少两个租户的正向访问、跨 schema 拒绝、错误路由、账号轮换和崩溃注入测试通过。

- [ ] 2.1 实现服务端可信租户解析，拒绝客户端 database name、tenant id、header、query 或 body 直接选择业务库。
- [ ] 2.2 为每个租户创建不可变 database_identity、独立高熵 DML 账号及仅限本 tenant schema 的精确 grants，并为以后迁往其他 MySQL 实例保留路由字段。
- [ ] 2.3 实现按 database UUID、路由版本、凭证 generation 和用途区分的有界 engine cache，覆盖 LRU 淘汰、dispose、轮换、暂停、删除与恢复。
- [ ] 2.4 限制每 tenant engine 的 pool_size/max_overflow，并计算 Web、worker、control 与 provisioner 的总连接理论上限，使其低于批准的 MySQL 连接预算。
- [ ] 2.5 实现账号变更三阶段协议：短控制库事务获取 fencing lease、MySQL advisory lock、候选账号创建/验证及最终 tenant-first CAS 发布。
- [ ] 2.6 实现暂停/删除后的恢复账号规则：解锁只能发布新的未公开候选 generation，不重新启用已经发布、暴露或锁定的旧 generation。
- [ ] 2.7 实现可重入 provisioner：创建 provisional schema/account、运行 tenant migrations、写 database_identity、执行最小权限 smoke，并在 registration final commit 前保持 route 不公开。
- [ ] 2.8 建立 fleet migration 状态、兼容版本范围、逐 tenant drift 检测、失败重试和发布阻塞状态。
- [ ] 2.9 对 route publish、账号生成、迁移、smoke 和 final commit 各崩溃点执行注入测试，证明重试不会发布双路由、双账号或不完整 tenant。
- [ ] 2.10 验证双租户全资源隔离和数据库 grants；重跑 cache 淘汰、账号轮换及 provisioner 中断恢复测试并保存机器可复现结果。

## 3. 后台任务、幂等、outbox 与副作用隔离

**依赖/前置条件：** 阶段 2 的可信租户路由、数据库身份和 provisioning 基础可供本阶段调用。

**完成条件：** Web 进程不再运行定时调度器；所有外部副作用均有持久任务、幂等账本、提交边界和明确的恢复策略。

**可验证结果：** 双 worker、租约过期、响应丢失、进程崩溃、暂停/删除竞态不会重复提交 provider 副作用。

- [x] 3.1 实现 MySQL background_jobs 的状态、优先级、available_at、租约、heartbeat、attempt、退避、dead-letter、generation 和幂等唯一约束。
  - [x] control migration 与 ORM 已固定完整状态/lease fence、优先级 claim 索引、`DATETIME(6)` protocol timestamp、attempt/max-attempt、execution generation 与 tenant/job/resource/idempotency 唯一键；MySQL claim 使用 `FOR UPDATE SKIP LOCKED`，过期 lease 只按 recovery policy 回收，耗尽进入 dead-letter。唯一 worker 现在强制注入不可变、正值、非递减且末档封顶的共享 retry schedule；prepare/execute/确认可安全重试的 provider 异常都把下一次 `available_at` 持久推后，provider 明确给出的未来 `retry_at` 优先、已过期 deadline 回退共享退避，避免各 capability 复制算法或异常热循环。真实 MySQL 双 worker/lease stealing 压测仍由 3.9 与 12.11 验收，不再作为本实现项的未完成代码。
- [ ] 3.2 建立单个独立 worker 进程，同时负责基于 MySQL 持久任务的定时触发和任务执行，并删除 Web 进程内 APScheduler/scheduler 的启动路径。
  - [x] 已实现与部署方式解耦的单进程运行循环：每个 cycle 先用同一 UTC 快照执行全部持久 fan-out definition 和有界 capability producer，再领取任务直至队列空闲或达到预算；producer 只在当前显式 interval bucket 成功一次，失败不上绿且可由 supervisor 重启后重试。有积压时立即继续、空闲时可中断等待。Blocking APScheduler host 只注册一个 immediate、coalescing、`max_instances=1` 的 durable cycle，cycle 异常会停止整个 host 并以固定错误上抛给 supervisor，不会留下只有 scheduler 的半存活进程；真实 APScheduler fail-fast smoke 已通过。capability composer 把各能力的 handler、periodic definition、producer 和可选专用 current-authority 合并进唯一 worker/process，拒绝 job-type/trigger 重名并把 claim scope 限定为注册集合；订阅到期扫描与过期投影已作为第一项 system capability 接入同一进程，仍按 tenant-first 生命周期锁执行但不被已到期 projection 自己阻断。外层 signal host 在主进程安装 SIGINT/SIGTERM 的 nonblocking stop 并无条件恢复原 handler；即使信号落在 handler 已安装但 APScheduler 尚未 start 的窗口，host 也会锁存 stop 而不迟到启动。Web factory 已无 legacy scheduler 启动接线且有负向回归。循环/host 均不解析环境、不持有 provider/数据库资源；SF create-waybill、unknown query、direct relay projection 与两类 30 秒 reconciliation 已由显式 builder 合入同一 worker/process且构造无 I/O，仍需把打印等剩余 capability 与生产参数组装进唯一可执行 launcher并做真实启停/readiness smoke，故主项不关闭。
  - [x] superseding 进展：SF capability 现包含 create、tenant-intent enqueue、unknown query 三个 shipping handler，并与 direct relay projection/relay reconciliation 合并为五类 handler；intent、unknown query、relay 三个 30 秒周期 definition 均在同一 environment-free process builder 注册。仍缺打印等 capability 与生产 launcher，因此 3.2 保持开放。
- [ ] 3.3 实现 control outbox、tenant 执行账本、provider operation ledger 和 provider_submitting 持久提交边界。
  - [x] SF create-waybill worker 已把 exact shipment/attempt snapshot、一次性 credential request、tenant `provider_submitting` fence、provider 调用和 typed result 分隔为短事务；成功/明确失败/unknown 都先固化到 tenant execution ledger，unknown 固定进入 review且 `max_attempts=1`，不会由通用 worker 自动重提。成功结果在 tenant commit 后尝试 direct relay enqueue，跨库响应丢失由同一 committed ledger 的周期 reconciliation 补偿；unknown 或 crash-after-submit attempt 由独立 one-shot query claim 先持久推进为 `needs_review`，再使用同两条 exact revision 的无 PII query request 收敛为 confirmed success/no-effect/still-unknown，最后一种保持人工复核且不重复自动查询。真实 create/query adapter和其他 provider/print producer 完成前主项保持开放。
  - [x] tenant attempt 现原子固化预分配 control job UUID、tenant access version、requesting user 与 request/correlation identity；provider-free reconciliation 以同一 UUID 单独提交 control enqueue，随后回写 tenant ack，任一跨库响应丢失都只重放 exact job。该 producer 不调用 provider，stale access version 不入队；真实 create/query adapter 和其他 provider/print producer 完成前主项保持开放。
- [x] 3.4 为开户、短信、顺丰、打印、闲鱼/快麦同步、备份和清理分别定义“可安全重试、仅查询对账、必须人工确认”的恢复策略。
  - [x] 新增不可变、版本化 recovery policy registry：开户和顺丰的未知结果只能使用持久快照查询/对账；短信未知送达与物理打印未知结果必须等待显式确认且禁止自动重发；闲鱼/快麦同步、备份和 system cleanup 仅可在稳定幂等键、immutable snapshot 与原 fencing generation 下安全重试。未知类别无默认 safe-retry，策略对象也拒绝“无稳定幂等却允许自动重放”及“无快照却允许查询对账”的非法组合。
- [ ] 3.5 在任务入队、领取 lease 和 provider 提交前重新计算 effective tenant gate；暂停、删除、过期限制或 recovery hold 时拒绝不允许的新任务/副作用。
  - [x] 通用 worker/scheduler authority 除 tenant projection 外现已强制注入并按 tenant-first 顺序锁定 current recovery hold、blocking deletion aggregate 与未终结 suspension aggregate，再读取 subscription/route；即使 `tenants.status` 因漂移仍显示 active，已批准进入 cooling/committing 的 deletion 或 suspension 行仍分别固定拒绝 normal job。尚在平台 `pending_review` 的删除申请按 D26 不提前冻结业务，批准后才成为 blocking phase。相同 reader 继续用于 claim、after-claim、tenant-context、heartbeat、provider boundary 与每次 provider call；probe 缺失、返回非布尔或查询异常统一 authority-unavailable。SF create-waybill handler 已在 credential 前、provider 前和 provider 结果后执行相同 current-authority recheck，最终 gate 失效也会先保存已发生的 provider 结果而不丢失事实。仍需接入外部 deployment marker，并让打印等尚未注册 capability 的 enqueue 全部使用同一 gate，故主项保持开放。
- [ ] 3.6 为相同租户定时 fan-out、用户即时刷新和重复点击实现稳定幂等键及优先级合并，禁止只靠前端按钮禁用防重。
  - [x] 闲鱼纵向切片已在控制库锁定 tenant 与 active/current-bucket job 后复用同一持久任务；scheduled/manual 连接集合使用同一 180 秒 bucket 与 exact revision digest，重复点击不会新增任务。通用 queue service 新增只向前的 pending promotion：复用到尚未领取的低优先级 scheduled job 时原子提升为即时请求优先级并可提前 `available_at`，但不改 payload、idempotency、requester 或 attempt budget；leased/terminal job 不重排也不改写。相同 job 幂等身份的重放还会核对 access version、immutable payload、requester、attempt budget 与 deadline，任一语义漂移固定冲突而不是静默执行首次或最新 payload。顺丰批量、打印与其他即时任务仍需复用该 primitive 后才能关闭主项。
  - [x] 顺丰 tenant intent 复用通用 queue primitive 并允许调用方预分配 job UUID；相同幂等身份重放若换 UUID 固定冲突，控制库提交后的 producer 重跑只能返回原 job。该进展补充 3.6；顺丰批量、打印与其他即时任务仍未全部接入。
- [ ] 3.7 将 D54 残留 provisional 资源清理限制为 current recovery run 内允许的 system-only janitor；普通用户和平台页面不得直接删除 schema/account/route。
- [ ] 3.8 记录 request/job/provider correlation、safe outcome 和不可变审计引用，禁止在任务参数、错误或普通日志中保存 Secret 和不必要 PII。
  - [x] 通用 job runtime 已把 handler outcome 收紧为 typed `JobOutcome`：safe result 只能是持久化 mapping，reason code 必须为有界单行安全码，retry deadline 必须带时区，provider “明确未提交”证明必须是布尔值；handler 返回错误对象时，provider 前按共享退避重试，跨过 provider boundary 后进入 review，不会把任意对象、异常文本或第三方原始响应塞入任务结果。现有 job 仍持久化 request/correlation UUID，顺丰 attempt 绑定 background job UUID；其余 provider-specific allowlist 与不可变审计引用接线完成前主项保持开放。
  - [x] 顺丰 attempt 已把 background job UUID、tenant access version、requesting user 及 request/correlation identity 固化为全有或全无的不可变来源，且不保存 Secret/PII provider payload；该进展补充 3.8，其余 provider-specific allowlist 尚未全部接线。
- [ ] 3.9 运行重复调度、双 worker、lease stealing、provider 响应丢失、暂停屏障和 crash-after-submit 测试，验证不会产生重复外部副作用。
  - [x] SF 子矩阵已覆盖 create 返回 unknown、provider 调用后结果未落库、direct relay enqueue 响应丢失和双 query reconciler 竞争：query claim 在 provider 前把 `provider_submitting/unknown` 单调改为 `needs_review`，只有一个 MySQL 事务获得 exact snapshot，另一个稳定无候选；confirmed success 写回同一 attempt 后接力只交接一次，still-unknown 不自动再查或下单。一次性 MySQL 8 模块 `6 passed`，扩展 shipping/accessory/shared-job 回归 `209 passed`；lease stealing、暂停屏障和其他 provider/打印路径仍需统一矩阵，故主项不关闭。
  - [x] superseding 矩阵已加入 tenant intent 控制库提交后 ack 响应丢失：连续 producer 只产生同一预分配 UUID 的一条 control job；新增 intent ack 行锁竞争只有一个 winner。新增 scan index 首次使旧 unknown-query 竞争暴露 MySQL 1213，候选认领改为 `SKIP LOCKED` 后完整一次性 tmpfs MySQL 8 模块 `7 passed`，扩展 shipping/accessory/shared-job 回归 `256 passed`。lease stealing、暂停屏障和其他 provider/打印路径仍需统一矩阵，故主项不关闭。

## 4. 身份、会话、RBAC 与平台管理员

**依赖/前置条件：** 阶段 3 的持久任务、幂等和副作用隔离基础可供调用；可与阶段 5 并行。

**完成条件：** 租户身份和平台身份完全分离；所有业务入口统一使用服务端 session、membership、RBAC 和状态门禁；不存在 tenant API key 或人工账号接管旁路。

**可验证结果：** 多实例 session 撤销、CSRF、Admin/Operator 权限、平台第二因子、防重放和身份命名空间隔离测试通过。

- [ ] 4.1 实现仅 +86 手机号规范化、腾讯云 SmsProvider、短信 challenge 状态机、60 秒冷却、5 分钟有效期和同 challenge 第 5 次错误锁定。
  - [x] 共享手机号规范器、purpose-bound root-key HMAC challenge、6 位码、5 分钟有效期、60 秒冷却、第五次错误锁定、一次消费和 `committed → sent/send_unknown/failed` delivery 状态机已实现；HTTP 发码在首个控制事务提交后才调用注入的 provider，再用独立短事务记录结果，provider 未配置时固定 503。
  - [x] 可信来源 resolver 必须由部署显式提供受信代理 CIDR 和最大转发链长且无内置网段/跳数默认；非受信直连忽略转发头，受信链从右向左跳过明确受信代理，多头、非法、空段或超长输入统一落入保守 `unknown` bucket。
  - [x] 已实现腾讯云官方 API `v20210111` adapter 和官方 product SDK 依赖：部署显式提供 Secret、SmsSdkAppId、已审核签名/模板、地域、超时和模板参数顺序，adapter 只提交一个 E.164 号码并把 `Ok`/明确拒绝/模糊响应分别映射为 sent/failed/send_unknown；Secret、手机号和验证码不进入 repr/普通日志，SDK/配置缺失 fail closed。
  - [ ] 仍需把真实 Secret/非秘密模板元数据通过受控部署设置接入，并完成企业资质、统一签名、验证码模板、运营商报备、腾讯云控制台限流和受控真实号码发送/接收/失败 smoke；不能用测试 fake 关闭本项。
- [x] 4.2 实现手机号跨 purpose 共享 5 次/滚动小时与 10 次/上海自然日、可信来源 IP 30 次/滚动小时与 200 次/上海自然日的控制库原子限流。
  - [x] 发码事务按 phone/source 稳定顺序取得控制库限流 subject 与 challenge 锁，滚动小时和 Asia/Shanghai 自然日窗口跨 purpose 聚合；未知来源使用单一保守 bucket，HTTP 429 返回有界 `Retry-After`，provider 控制台第二层配置仍归 4.1 readiness。
- [x] 4.3 实现 MySQL 服务端不透明 session、安全/HttpOnly/SameSite Cookie、独立逐 session CSRF、设备信息、tenant access version 和集中撤销；禁止 Flask signed session/Cookie，并移除会话路径对通用 `SECRET_KEY` 的依赖。
  - [x] 控制库 session service 已持久化不透明 token digest、逐 session CSRF、idle/absolute expiry、设备摘要、user auth version 与 tenant access version，并提供单 session/全账号撤销；固定 `__Host-` Cookie 使用 Secure/HttpOnly/SameSite=Lax 且不依赖 Flask signed session 或通用 `SECRET_KEY`。
  - [x] 浏览器 `GET /api/auth/session` 和 CSRF 保护的 `POST /api/auth/logout` 已组合到同一 control-only runtime；状态读取基于数据库当前时间和实时 effective gate，退出在 active/expired/suspended 均可用并原子撤销当前 session，响应统一 no-store，缺失 runtime 固定 503。
  - [x] 本人设备列表、指定设备撤销和全部设备撤销已接入相同 runtime：列表只投影 session UUID、设备摘要、创建/最近活动时间和当前标记；伪造 UUID 与他人 UUID 返回相同拒绝，单设备撤销不递增 auth version，全部撤销原子递增 auth version 并撤销当前设备。桌面/移动账号安全页均使用该契约，CSRF 仅从登录签发的独立 tab-session 状态读取。
  - [x] 新增 control migration 为 session 补齐唯一 `created_from_challenge_id`、`rotated_from_session_id`、`replaced_by_session_id`；登录最终事务按 user → membership → tenant → challenge → session 锁序消费 OTP、激活默认迁移的未验证首位 Admin、签发全新 token 并撤销同用户旧 Cookie。同 challenge 重放不产生第二 session，其他用户 Cookie 不会被撤销。
  - [x] 会话具体 idle/absolute 时长没有已确认产品数值，因此部署必须显式提供无代码默认值的版本化 typed policy；token/CSRF digest 碰撞在嵌套 savepoint 内最多重试三次且不污染调用事务。登录创建/轮换、当前退出、指定设备撤销和全部撤销均在动作的同一控制事务追加最小化安全事件，事件不保存 token、digest、手机号、IP 或自由格式 payload，重放撤销不重复写事件。
- [x] 4.4 实现固定 Admin/Operator RBAC capability matrix、active membership 校验和最后一名 active Admin 保护。
  - [x] 固定角色能力矩阵继续由统一 tenant HTTP boundary 在实时 user/membership/tenant gate 下执行；新增成员 mutation service 使用 caller-owned 控制事务，按相关 user → pending invitation → tenant/seat guard → membership → sensitive intent/open challenge/session 的统一顺序锁定并 current-read 目标 revision、操作者 active Admin 权威、D51 实时席位和 active-user 谓词。
  - [x] Operator 启用、停用、移除无需 D48，已接入 control-only CSRF API 和桌面/移动成员页；停用/移除原子递增目标 user auth version、撤销其全部 session并写最小安全事件，移除还失效目标未终结 challenge。任何授予/移除 Admin 权限的路径都要求 exact D48 proof；普通 mutation HTTP 固定拒绝此类操作，只有 4.5 的 action-bound issue/confirm 路径可构造内部 proof。
  - [x] 有效 Admin 复计严格使用 `membership active + unreleased + user active`；tenant 协调锁串行化不同目标的并发降级/停用/移除，事务中确认至少仍有一名有效 Admin，pending Admin invitation 不计入。focused service/RBAC/HTTP suite 通过，真实 MySQL 双事务竞争继续由 6.11/12.11 记录。
- [ ] 4.5 实现 D48 action-bound 敏感操作 intent 与逐动作短信复验；换手机号必须分别验证旧号码和新号码，challenge 不得跨 action 重放。
  - [x] 已实现通用 primary-challenge intent 基础层：控制库迁移 `202608220027` 创建 payload-free intent 与唯一 challenge-role link，`202608220028` 扩展最小安全事件以关联 challenge/intent/action outcome；共享 canonical action payload 和根密钥派生 context MAC 绑定 tenant/actor/session/action/target/revision/idempotency。精确请求可幂等重放但不重复发送，错码计数与拒绝事件提交，成功消费、动作提交、verified/committed 事件和 intent succeeded 保持调用方同一控制事务，响应丢失可从最小 correlation 重放原结果。
  - [x] 已接通成员 Admin 启用/停用/移除及 Operator↔Admin 角色变更的首个 D48 纵向切片：challenge 只发当前 active Admin 操作者本人 canonical 手机号，确认前按相关 user → pending invitation → tenant/guard → membership → intent/challenge/session 的共享锁序重验 exact context，生成的内部 proof 不能由 HTTP 传入；桌面与移动端均使用同一 action UUID 完成发码与确认，Operator 普通启停/移除仍走无需短信的原路径，最后 Admin 保护不放宽。SF 账号 claim/解绑/转移和删除仍需继续接入后才能完成 4.5。
  - [x] Admin invitation 已迁移到持久 D48 intent：桌面/移动端在发码前生成同一 action UUID，challenge 绑定当前 Admin user/session、tenant access version、目标手机号、Admin 角色和 expected-absent invitation；最终 invitation persistence 在取得 user/invitation/tenant/seat/membership 锁后才调用内部 authorizer，HTTP 不能提交 proof。错码通过 savepoint 回滚目标协调 user 等业务暂存后只提交一次失败计数和拒绝事件；成功原子消费 OTP、创建 Admin invitation、完成 intent 与安全事件。action UUID 同时作为 invitation UUID，版本化根密钥 PRF 生成 256-bit replay-stable token，库中仍只保存 token hash；成功响应丢失后的精确重试返回相同有效 fragment，不再次消费 OTP、发短信或写审计，链接后来轮换/撤销/过期则拒绝旧动作重放。
  - [x] 换号已完成固定 `old_phone`/`new_phone` 双 challenge 和完整纵向接线：同一 payload-redacting intent 精确关联两个角色，精确发码重放不重复发送；任一码失败时回滚可能已消费的正确码和临时协调 user，只对实际失败码提交一次错误计数。最终事务按 canonical user → 新号 invitations → tenant/seat guard → membership → registration/intent/challenge/session 顺序协调；只允许删除无 membership/session/registration/security history 的 invitation-only unverified 占位 user，单调 supersede 新号全部 pending invitation、清空终态 user 引用、失效 acceptance challenge 并释放席位，拒绝任何已验证或保留历史的身份合并。两码正确后保持原 user UUID，更新 canonical E.164/验证时间和 normalization metadata、递增 auth version、撤销全部旧 session，并由桌面/移动账号安全页清除 CSRF 后要求新号重新登录。
  - [x] tenant integration credential 已接入通用 D48 intent：服务端从当前 integration 锁定态派生 CAS pointer，challenge 绑定 provider、row version、tenant access version 和 canonical credential semantics digest，只发送到当前 active Admin 本人；确认在 savepoint 内先写不可变加密 pending revision，再消费 exact OTP、完成 intent/安全事件并写一次 durable validation outbox。错码回滚 revision/outbox 后只提交失败计数，响应丢失精确重放不会重复发码、建 revision 或写 outbox；Web 不调用真实 provider，expired/suspended 在解析 credential 前由 D56 拒绝。
- [x] 4.6 按 D57 禁止平台人工修改 canonical 手机号、替用户输入 OTP、签发绕过旧号 challenge、impersonate 或为最后 Admin 建恢复旁路。
  - [x] 平台 RBAC 不授予手机号自助变更、成员管理或租户删除能力；平台 HTTP 的 tenant mutation surface 由负向契约锁定为已确认的服务期调整，未暴露 phone/member/recovery/impersonation 写入口。host CLI 仅接受平台账号 create/reset/disable，并对 tenant phone、代输 OTP、impersonate、phone override 和 last-Admin recovery 命令在打开动作事务前固定拒绝；覆盖测试同时证明拒绝后没有 tenant user 写入。
- [ ] 4.7 实现独立的平台 username/password/TOTP/recovery code/session 命名空间、CLI bootstrap、近期 step-up 和 TOTP 时间步全局防重放。
  - [x] 已组合独立平台登录事务：版本化 memory-hard 密码验证后，必须原子验证 current confirmed TOTP 或消费当代未使用恢复码，随后才签发全新平台 bearer/CSRF；同一 TOTP 时间步全局 CAS 防重放，恢复码单次消费，成功审计失败会回滚因子游标和 session，根密钥换代期间可用 legacy key 解密既有 TOTP、只用 active key 生成新限流 subject 摘要。
  - [x] 平台密码与 MFA 阶段分别按 username/可信 IP/设备执行部署显式提供、无代码阈值默认值的版本化原子失败桶；subject 只保存根密钥用途隔离摘要，未知账号、错误密码、错误/重放 factor 和已限流请求使用同一公开错误。成功登录可按当前参数安全 rehash，失败登录不改密码 hash。
  - [x] 已接入独立 `/platform/api/login|session|logout` runtime：平台 session 与设备 Cookie 均为 host-only、Secure/HttpOnly/SameSite=Lax、固定 `/platform` path，平台 CSRF header 与 tenant CSRF/Cookie 分离；登录/注销追加不含密码、TOTP、恢复码或 bearer 的不可变 `platform_audit_logs`，审计与因子/session 同事务提交。runtime 已纳入原子 SaaS composition，未提供 typed policy、可信来源 resolver 或根密钥 registry 时 fail closed。
  - [x] 已实现依赖注入式 `inventoryctl platform-admin create/reset` host adapter：命令只接受 username、setup TTL、OS 操作者安全引用和 command ID，拒绝任何 password/TOTP seed/recovery code/DSN 参数；create 只创建 pending Admin，reset 在同一控制事务撤销 setup/TOTP/recovery/session 权威并递增全部相关 generation，再输出一次性 setup token。CLI 审计不含凭证，生产 launcher/config 注入仍归部署接线而非此 adapter 自行发现环境。
  - [x] 已实现 setup-only HTTP 闭环：一次性 setup token 只在 consume 请求正文出现，后续阶段使用独立 setup header；密码、active-root 新 TOTP seed、确认码和当代恢复码均只在对应一次性响应/请求中出现，TOTP 确认按 credential 记录的根密钥版本解密，全部阶段在各自动作事务内追加不可变审计，激活后 setup authority 立即失效。
  - [x] 已实现平台本人 session 列表、指定撤销和全部撤销：列表仅返回固定的 session UUID、设备摘要和时间字段且不含 token/digest/IP；认证与 CSRF 先于 target UUID 解析，伪造或跨 Admin target 使用同一 404；全部撤销递增 auth version 并清除当前 Cookie，实际撤销与审计同事务提交。
  - [x] 桌面端已接入独立平台 setup、password+TOTP/recovery 登录和本人 session 管理页面；租户默认仓守卫不探测 `/platform`，平台 bearer 只由 `/platform` path 的 HttpOnly Cookie 承载，平台 CSRF 使用独立 tab key，setup token/password/TOTP seed/code/recovery codes 只留在当前组件内存并在阶段切换或卸载时清除。
  - [x] 已实现 D52/D58 共用的近期 MFA step-up：当前有效平台 bearer+CSRF 下重新验证尚未接受的 TOTP 时间步或消费一枚恢复码，成功后在同一控制事务写防重放、签发新 bearer/CSRF、撤销旧 session 并追加无凭证审计；新 session 保留旧 absolute-expiry 上限而不借 step-up 延长寿命，失败因子只写显式 MFA 失败桶并保留当前 session。桌面安全页提交后只保存轮换后的平台 CSRF。
  - [x] 已实现已登录平台 Admin 的因子自助管理：登录 session+CSRF 下以全局防重放的 current TOTP 或恢复码授权新 TOTP 暂存，确认前旧 TOTP 保持 current；新 seed 验证成功的同一事务先原子替换 current credential，再递增恢复码 generation、作废旧恢复码并生成只展示一次的新集合，最后递增 auth version、撤销全部旧平台 session。恢复码也可独立重新生成；失败确认不替换旧 TOTP、不撤销 session，因子失败共用既有 username/source/device 限流和固定错误。桌面安全页仅在组件内存展示 seed/新恢复码，成功替换后要求保存新码再返回登录。
  - [x] 已实现 host-only 平台 Admin 停用和最后 active Admin 保护：`inventoryctl platform-admin disable` 仅接受 username 与固定格式的 OS 操作者/command 引用，在同一控制事务按 UUID 锁定账号集合，要求另一账号已 active 且拥有密码、current confirmed TOTP 和当代 active 恢复码；获准后撤销目标 setup/TOTP/recovery/session authority、递增 auth version、置为 disabled 并写 CLI 审计。仅有 pending/recovery/不完整继任者或只剩一个 active Admin 时固定拒绝且无部分写入。
  - [x] 已接入 `python -m inventory_control` host launcher：只从部署注入的 `CONTROL_DATABASE_URL` 构造独立短生命周期 control engine，并把已验证的 `platform-admin create/reset/disable` argv 交给同一 CLI application；命令行不接受 DSN，缺失/无效配置与运行错误只返回固定信息，结束后释放 engine。真实生产环境变量注入和 CLI smoke 仍归发布 readiness，不在代码中内置 URL 或口令。
  - [x] D53 已接入逐动作新鲜因子，不复用 session 近期 MFA：预览签发绑定 actor/session/auth version、输入摘要和全套生命周期 fence 的五分钟确认，最终事务才消费尚未接受的 TOTP 时间步或当代未使用恢复码；桌面页面的确认与 factor 仅留在组件内存。
  - [ ] 仍需把近期证明接入 D52/D58 动作 API；这些未完成前本项不关闭。
- [ ] 4.8 实现平台 SELECT-only 查询和 PII 查看审计；平台请求不得借用 tenant DML 身份，也不得跨库聚合业务行到控制库。
  - [x] 已接入控制库租户目录 list/detail：先验证平台 bearer/capability，再解析唯一且有界的 page/page_size/status 或 tenant UUID；只返回 tenant/subscription/route 的固定非 PII 投影，不返回 settings、数据库名、账号或业务行，也不解析 tenant engine。每次成功 list/detail 在返回 DTO 前写 `pii_revealed=false` 平台审计，审计事务失败则不返回数据。
  - [x] 已接入按单个可信 tenant 选择的租赁只读排障：平台 capability 与 target 状态校验先于租户路由，独立 router scope 只派生 `platform_read` 账号，MySQL 事务显式 `READ ONLY` 且查询携带部署注入的执行时限；DTO 只含有界分页的主租赁、设备和默认脱敏客户摘要，不选择地址/备注/买家/运单字段。认证、target、query、执行和成功结果均写固定低敏审计，成功审计提交失败时不返回已读数据；`provisioning/deletion_committing/deleted`、重复/未知 query 和 runtime 缺失均在打开 tenant engine 前失败。
  - [x] 桌面租户目录已消费上述单租户脱敏租赁列表；A→B 切换和 drawer 关闭会同步清空旧详情/业务 DTO、取消在途请求并以 generation 阻止不遵守取消信号的迟到响应覆盖当前租户，不提供跨租户搜索、聚合或导出。
  - [x] 已在同一 SELECT-only router、read-only tenant transaction、超时、分页和成功前审计边界增加设备与仓库 DTO：设备只选择名称/型号/附件标记/当前仓/生命周期和时间，不选择序列号或自由文本原因；仓库只选择 UUID/名称/状态/setup/default 和时间，不选择联系人、电话、地址、打印机或 provider binding。三类列表共用一套 query 解析、tenant target 解析、路由、失败/成功审计与迟到响应 fence；桌面详情并发读取首个有界页并在 tenant 切换/关闭时一起清空。
  - [x] 已实现单条主租赁完整客户 PII detail：必须同时具备平台 tenant-business read 与独立 `customer.pii.read` capability，并提供唯一 canonical rental ID 和逐次小写 reason code；仍仅使用 `platform_read` 的只读事务和单条有时限 SELECT。成功结果在返回前写入目标资源、reason、`pii_revealed=true` 审计；资源不存在、输入拒绝和执行失败均记录 `pii_revealed=false`，成功审计不能提交时绝不返回 PII。桌面端只在组件内存临时展示，关闭弹窗、关闭租户详情、切换租户或卸载时取消请求并清空理由及完整姓名/电话/地址，不写浏览器持久存储。
  - [ ] 仍需实现其它经批准的只读业务 DTO；这些完成前父项保持开放。
- [x] 4.9 按 D55 移除 /external-api、全局 X-API-Key、`API_KEY` 配置及任何 tenant_api_keys 表、模型、配置、权限、页面、恢复项和潜伏认证路径。
  - [x] 应用工厂不注册 `/external-api`，旧 `X-API-Key` 即使随请求或环境/config 出现也没有权威；当前模型/migration/runtime 不存在 tenant API key。`.env.example`、Docker、Windows/Makefile 样例和启动配置文档均不再声明 `API_KEY`，负向回归保留旧值只用于证明不可达。
- [ ] 4.10 执行双租户身份、平台/租户 namespace、角色矩阵、最后 Admin、session 撤销、短信竞态、TOTP/恢复码防重放、API key 不可达及旧 `SECRET_KEY`/`API_KEY` 不能建立身份测试并记录结果。
  - [x] 平台 focused tests 已覆盖未知账号/错误因子统一错误、密码与 MFA 三 subject 限流、TOTP/recovery 单次消费、审计失败整体回滚、legacy TOTP key、平台/tenant Cookie 与 CSRF 互不可用、host-only `/platform` Cookie，以及 host create/reset/disable、最后 active Admin、完整 setup、两次登录、指定/当前/全部 session 撤销、近期 MFA 成功轮换和失败保留、TOTP 先确认后替换、恢复码 generation 轮换及替换后全 session 撤销。D53 另覆盖逐动作 TOTP/recovery 防重放、确认篡改/过期、fence 变化、失败限流回滚和响应丢失重放；完整双租户与 D52/D58 动作 API 矩阵仍待后续子项完成后汇总。

## 5. 租户业务库 expand 与领域基础模型

**依赖/前置条件：** 阶段 3 的持久任务和事务边界可供调用；可与阶段 4 并行。

**完成条件：** 新租户业务库可从空 schema 完整迁移；多仓、逻辑附件、物流与集成历史所需结构和约束已就绪；兼容窗口内旧读路径仍可工作。

**可验证结果：** 全新 tenant schema 正向迁移、约束、索引、最小 CRUD 和 fleet drift 测试通过。

- [x] 5.1 增加 warehouses、唯一默认仓、setup ready、结构化地址、device warehouse、用户最近工作仓和 warehouse printer binding 模型。
- [x] 5.2 增加可配置 accessory types、内部 accessory units、rental accessory requests、unit links、unit events、current holder 和 relay case 所需模型。
  - [x] tenant migration 与 ORM 已建立 accessory type/config、不可见 logical unit、request、每 rental/type 唯一 link、current holder、只追加幂等事件及现有 relay case/binding 关联所需事实；模型约束回归覆盖重复 link/event、状态非法和 request/link/event 分离。
- [x] 5.3 增加租赁结构化收货地址、人工/官方物流估算上下文、计划寄出/回仓、实际发出/归还和客户可见订单备注字段。
  - [x] tenant migration 与 Rental ORM 已包含四段结构化地址、客户备注、0–7 天物流、估算来源/规则/时间/摘要、计划日期及独立实际事件；部分/反向计划窗口和非法天数由数据库约束拒绝，物流事实、客户备注与内部接力备注保持分离。
- [x] 5.4 增加 shipment、shipment attempt、provider operation、print job 及 warehouse/account/binding/credential/printer snapshot 引用。
  - [x] tenant migration 与 ORM 已建立稳定 shipment UUID、逐操作 attempt ledger 和 waybill print job；三者保存 exact warehouse/account/integration/binding revision、两类 credential revision、寄件/收件或寄回资料与打印机 SN 快照，并以 provider order/idempotency/attempt 唯一约束和受限状态集合阻止模糊重放。
- [x] 5.5 增加 tenant integration、connection、provider account、warehouse binding、immutable credential revision 和 current pointer 模型。
  - [x] control schema 已包含稳定 tenant integration/connection 与 provider-account identity、各自只追加 secret revision、current pointer、envelope event 及全局 claim 引用；tenant schema 已包含每仓 SF binding 的 account UUID、单调 binding revision、验证/状态事实。控制 migration `202608220029`、tenant current head、ORM metadata parity、bind/replace/unbind CAS、历史 exact revision 解密和 envelope rewrap 回归均通过；模型不提供 Secret reveal 字段或全局环境变量 fallback。
- [x] 5.6 建立默认仓唯一性、打印机一对一绑定、附件逻辑单元重叠窗口、shipment 快照不可变和状态转换约束。
  - [x] tenant schema 的唯一 default slot、warehouse/printer SN 双唯一键及正值/合法状态 check constraint 已与 ORM 对齐；附件预留按 type/warehouse/unit 固定顺序锁 unit 与当前重叠窗口，普通预留排除已占窗口，只允许显式 agreed relay chain 共享同一逻辑单元，并以有效起止窗口约束阻止反向区间。shipment/attempt/两联 print job 仅通过 exact snapshot replay 与 expected-status CAS 推进，任一 warehouse/account/credential/binding/sender/receiver/printer 快照漂移均冲突而不覆盖历史。模型、附件并发边界与 shipping ledger focused regression 为 `86 passed`；附件、甘特和调仓的真实 MySQL 8 contention 合计 `5 passed`，完整迁移/CRUD 收口仍由 5.8 验收。
- [ ] 5.7 根据真实数据分布和 EXPLAIN ANALYZE 建立设备使用期、计划物流窗口、附件候选/link/event、shipment 与 tracking 查询索引。
- [ ] 5.8 验证空 tenant schema 迁移、重复迁移、约束冲突、索引计划和最小业务 CRUD，确认旧数据尚未被破坏性 contract。
  - [x] 两个一次性 MySQL 8.0.46 实例已完成 tenant SaaS segment baseline→head→baseline→head、独立 forward apply、ORM metadata 零差异及 DML/platform-read grant/跨 schema 拒绝；同批真实行锁 contention 为 `5 passed`，临时实例已删除。
  - [x] 生产实例已创建用途分离的 `inventory_saas_test_migrator`、`inventory_saas_test_dml`、`inventory_saas_test_platform_read` 账号；权限分别严格限定为测试 schema 上的 `ALL`、`SELECT/INSERT/UPDATE/DELETE`、`SELECT/SHOW VIEW`，均无 `GRANT OPTION`，并已用各自身份证明对生产业务 schema 的读取被拒绝。随机密码只保存于本机钥匙串，未写仓库。
  - [x] 已在生产实例的 `inventory_management_test` 通过专用 platform-read 账号运行版本锁定的实际 source baseline 并立即重放：9 张旧表、6,264 行的 source snapshot digest 稳定一致，且无 DML/DDL。
  - [ ] 仍需运行数据迁移重复执行、代表性 CRUD 与索引计划；测试库缺少 `database_identity` generation 且为非空历史，下一步必须绑定已记录 source digest 并使用获批的非空历史 adapter，或另行获准后才可重建测试库，不能把漂移结构当作 current head。

## 6. 注册、邀请、兑换码与订阅生命周期

**依赖/前置条件：** 阶段 4 的身份/RBAC 与阶段 5 的 tenant schema 已实现本阶段直接使用的接口和约束。

**完成条件：** 注册、邀请、兑换码、开户、续期和补发均由持久状态机驱动，可中断恢复且不会双开户、双兑换或突破席位上限。

**可验证结果：** 并发注册/邀请/续期、worker 崩溃、响应丢失和 D54 补发竞态测试通过。

- [x] 6.1 实现不可变 Core plan revision 和 entitlement snapshot；唯一套餐硬额度仅为 active members 与未过期 pending invitations 合计最多 10。
- [x] 6.2 实现兑换码随机生成、规范化、lookup hash、可解密密文、兑换截止时间、服务时长、一次成功兑换、重复查看审计、CSV 导出和撤销。
  - [x] 已接入平台 control-only 基础管理闭环：current recovery run completed 且唯一 active Core plan 可用时，按幂等 generation request 批量生成绑定 run/plan/entitlement/duration/deadline、channel 和内部备注的 26 位 CSPRNG bearer；成功事务同时写生成与首次导出审计，响应只提供一次 CSV，精确重放不再次返回整批明文。列表使用不选择 ciphertext 的固定分页投影，按 effective active/expired 或持久终态筛选并只显示掩码；单码 reveal 按记录的 active/legacy 根密钥版本认证解密且每次审计，active 未预留码撤销使用 row-version fence，过期、reserved、redeemed 和 recovery-revoked 均不能被普通撤销。已授权请求的输入拒绝、并发冲突和不可用资源使用共享动作定义追加无凭证拒绝审计，避免各路由复制审计元数据。单码 reveal 使用部署显式提供、无产品默认阈值的 username/IP/device 三维控制库限流；成功、拒绝均计数，限流拒绝与查看审计原子提交。
  - [x] 列表已按 source code 唯一 lineage 和未解决 registration integrity incident 投影唯一产品结果：只显示“已补发新兑换码”或“一致性异常，未补发”，不返回 janitor/outbox、资源清单、清理进度、手机号、schema 或凭证。D54 实际补发事务和开户/续期并发仍分别由 6.8/6.9 保持开放，不再阻塞本项基础兑换码管理闭环。
- [x] 6.3 实现 7 天邀请、重发 token 轮换、旧链接立即失效、撤销/过期释放席位及同手机号重发不重复预占。
  - [x] 邀请状态机和持久服务使用数据库时间执行 7 天期限、重发 generation/token 轮换、撤销/过期终态及 realtime 席位重算；新增后台 expiry sweep 只扫描当前已到期 pending 行，显式限制每批 1–1000 条并逐 invitation 使用独立短事务调用同一锁序服务。崩溃后重扫、终态重放与并发 revision 漂移均不会复活 token 或重复释放 cached quota（席位权威始终实时排除过期行）。
  - [x] 已接入 control-only 成员/邀请 HTTP、桌面与移动成员页及 fragment-only 邀请落地页：Admin 新邀请的 D48 验证码发送给当前操作者本人而非目标号码，Operator 邀请不复验；服务端只返回一次可复制链接且不调用邀请通知 provider，重发轮换 token、撤销释放席位。落地页立即清除 URL fragment，不持久化 token，只有绑定手机号的 `accept_invitation` challenge 可在最终事务建立 membership；错误 OTP 的限次事实使用独立短事务保留而邀请/user 写入回滚。真实 MySQL contention 与代理/APM 日志链路验证继续由 6.11、12.10/12.11 发布矩阵负责，不重新打开本实现项。
- [x] 6.4 实现 D47 跨租户多个 pending invitations 的 first-membership-wins 原子收口：首个 membership 提交后 supersede 其他邀请并释放其席位。
- [ ] 6.5 实现 registration attempt、验证码成功后兑换码永久绑定原 user/attempt、provisioning job、commit anchors 和 immutable registration commit。
- [ ] 6.6 provisioning 自动创建“默认仓库”待完善记录并预填注册手机号；首次登录完成仓库名称、联系人、电话、省市区和详细地址前禁止进入业务页面。
- [ ] 6.7 按 D54 仅允许原 user 重新完成同手机号 register OTP 后恢复原 attempt；平台不得重试、abandon 或直接清理该 attempt。
- [ ] 6.8 实现平台唯一 D54 动作“补发兑换码”：与 final commit 共用锁序和控制库事务，递增 execution generation、失效 lease、永久撤销旧码并建立 replacement lineage。
- [ ] 6.9 补发新码必须复制 source code 的 immutable entitlement snapshot、plan revision 和 service duration，仅允许选择晚于数据库当前时间的新 redeem deadline；只有确有 provisional 资源时创建 system cleanup outbox。
- [x] 6.10 实现续期 max(database now, current expires_at) + service duration、一次兑换、不可变 subscription event 和 active/expired 投影。
  - [x] caller-owned 最终控制事务按 tenant → current run → hold → deletion → suspension → code → membership → subscription 锁序重验当前 authority，固化 consumed code 的 plan/entitlement/duration 后原子消费兑换码、更新 subscription/tenant 投影并追加唯一事件；同幂等请求响应丢失后返回首次结果，暂停在前置检查后获胜则不消费兑换码。
  - [x] control-only `GET /api/subscription/status` 仅向 expired 成员返回过期页所需 expiry/revision/can-redeem 投影；CSRF 保护的 `POST /api/subscription/redeem` 仅允许 active/expired Admin，畸形与未知兑换码使用相同公开拒绝且所有响应 no-store。
- [ ] 6.11 验证第 11 席、邀请重发/过期、跨租户接受、重复兑换、注册响应丢失、迟到 worker、补发先提交和 final commit 先提交等竞态并记录结果。

## 7. 到期、暂停、服务期调整、删除与状态门禁

**依赖/前置条件：** 阶段 6 的 subscription、entitlement、注册与补发状态模型可供调用。

**完成条件：** effective gate 统一约束 route、session、DML、job 和 provider；到期、暂停、服务期调整、删除及 recovery hold 不会相互旁路。

**可验证结果：** 状态优先级、状态转换、锁序、第二因子消费和在途副作用竞态均 fail closed。

- [x] 7.1 实现 deleted/committing > cooling > recovery hold > suspension > expired > active 的统一 effective tenant gate reducer 和稳定错误契约。
  - [x] 纯 reducer 固定输出 `TENANT_DELETED`、`TENANT_DELETION_COOLING_OFF`、`TENANT_RECOVERY_IN_PROGRESS`、`TENANT_SUSPENDED`、`TENANT_EXPIRED` 或 active，并将 stale access 与 invalid state 作为独立 fail-closed fence。登录/session 共用的 current-read authority 现在按 tenant → current run/hold → active deletion → active suspension → subscription 顺序锁定持久 aggregate，不再只相信 `tenants.status` projection；drifted active projection 仍显露正确 higher gate，删除 committing/cooling 又优先于 recovery overlay。普通 job 共用相同 blocking phase 语义，`pending_review` 不在平台批准前错误冻结业务。reducer、登录/session、HTTP boundary、job 和 aggregate drift focused regression 最新分别覆盖在 `75 passed` 与 `59 passed` 组合中。
- [ ] 7.2 实现到期 evaluator 和过期登录闭环：所有有效成员可登录到同一到期页，Operator 仅查看/注销，Admin 仅额外提交兑换码续期；禁止账号安全和顺丰解绑。
  - [x] 到期投影 evaluator、expired OTP session、状态 capability allowlist、最小订阅状态和 Admin 续期提交已接入控制库；桌面端和移动端成功续期后必须重新读取权威 session gate 才恢复业务导航，模糊响应也先对账而不盲目换幂等键。
  - [x] 到期候选已按显式批量/优先级/重试策略进入控制库 `background_jobs`，每个租户使用独立短事务和 subscription revision 幂等键；专用 system authority 按 tenant → current run → hold → deletion → suspension/action → subscription → job 锁序复验，provider-free handler 在独立事务 current-read 重算。任务排队后续期、access version 变化或 higher lifecycle 获胜时均安全收敛，任务提交后丢响应可幂等重跑，且不使用普通 expired tenant business-job gate 自我阻断。
  - [ ] 随 10.7 最终证明所有遗留业务、账号安全和顺丰解绑直连入口在 expired 状态不可达后关闭本项。
- [ ] 7.3 实现 D52 suspend：近期平台第二因子、可信 tenant 选择、非敏感原因、二次确认、首个控制事务立即 deny-all、access version 递增和 session 撤销。
- [ ] 7.4 实现可重入 suspension barrier，收拢 DML 连接、阻止新 lease/provider 提交，并将越过持久提交边界的 operation 改为查询/对账而非盲重试。
  - [x] ordinary control-outbox 已具备可复用 worker runtime：claim、当前 authority、provider dispatch fence、provider-free prepare、外部执行和最终业务投影分别位于短事务边界；prepare 失败只能按“副作用前”确定性重试/终结，越过 dispatch fence 的异常或 unknown 结果固定 quarantine，不能自动重新提交。integration credential validator 复用该 runtime，并以 D56 current gate + exact revision generation authority 在 claim/dispatch/result 三处阻止 suspended/expired/stale work；通用 DML 收拢和其余 provider handler 仍待完成。
- [ ] 7.5 实现 D52 resume：再次近期第二因子、撤销暂停期间 session，并按实时 subscription 落到 active 或 expired；过时副作用进入人工确认。
- [x] 7.6 实现 D53 增加正整数天、减少正整数天和立即到期三个互斥动作；普通减少跨过当前时间时整笔拒绝，不静默转换或钳制。
  - [x] API 不接受目标时间戳；预览和最终提交共用同一输入规范化与服务期纯计算器。增加天数以 `max(当前到期, database_now)` 为基准，减少天数跨过当前时间和已到期的立即到期均整笔拒绝，事件保留动作、计算基准、调整前后状态和有符号天数。
- [x] 7.7 对每个 D53 动作要求全新 TOTP 或 current-generation 未使用恢复码；最终事务重新计算、执行 tenant-first 锁序和 subscription 行锁，并将因子消费、事件、变更和审计原子提交。
  - [x] 服务端预览生成 action UUID、请求/预览摘要和短效确认；最终事务按 tenant → recovery run/hold → deletion/suspension → subscription → platform authority/factor 锁序复验并重新计算。因子、防重放游标、subscription CAS、唯一 immutable event 和成功审计同事务提交；错误 factor 的业务事务回滚后仅在独立短事务记录固定限流桶和失败审计，响应丢失可按 action/event 精确重放而不重复消费因子或写审计。
- [x] 7.8 仅允许 active、expired 和冻结屏障完成且权威 suspension aggregate 为 active 的 suspended tenant 执行 D53；其他暂停过渡、recovery hold、删除状态一律拒绝且不消费因子。
  - [x] 预览确认绑定 tenant/access/subscription、当前 recovery run/hold、可选 deletion request 及 suspension aggregate/action 的 UUID、revision、row version 与 generation；提交锁定后要求完全相等。domain 与 HTTP focused tests 覆盖 active、expired、完整 suspended、暂停过渡、未释放 hold、未完成 recovery、删除状态、stale fence、因子失败回滚及 idempotent replay；真实 MySQL 锁竞争仍由 12.11 的隔离环境矩阵证明。
- [ ] 7.9 实现受控删除申请、平台审核、30 天 cooling、取消、committing、永久 tombstone 异地确认、schema/account 删除及全局 claim/普通成员手机号释放。
- [ ] 7.10 保证 subscription 续期/调整不解除 suspension、deletion 或 recovery hold，暂停期间不补时，expired/suspended 不提供顺丰解绑例外。
- [ ] 7.11 执行状态优先级、暂停/续期、暂停/D53、删除/D53、删除/恢复、因子失败回滚和在途 provider 竞态矩阵并记录结果。

## 8. 多仓、设备、附件逻辑单元、档期与接力

**依赖/前置条件：** 阶段 5 的 tenant schema 与阶段 7 的生命周期规则已实现本阶段直接使用的部分。

**完成条件：** 仓库、设备位置、附件持有事实、档期、接力和调仓使用同一实时业务事实与锁序；不存在固定深圳、附件跨仓或第二份库存计数。

**可验证结果：** 多仓并发建单、设备调仓、逻辑附件分配和整条接力链重算不会超卖或产生静默缺货。

- [x] 8.1 实现默认仓 setup gate、仓库新增/编辑/停用、设备 warehouse 归属和账号最近工作仓选择。
  - [x] 共享 tenant business runtime 在交出普通业务 Session 前固定读取唯一默认仓；非 `active+ready` 返回稳定 `tenant_setup_required`，只允许具备 Admin-only `WAREHOUSE_SETUP` 的 setup GET/PUT 跳过该预检。预检结束只回滚只读 AUTOBEGIN，不产生业务提交；由此甘特固定 SQL 预算从 7 条增至 8 条，仍满足 8.11 上限。
  - [x] 仓库 runtime/service 支持全量管理列表、新增、编辑、原子转移唯一默认位和历史保留式停用；默认仓不可直接停用，仍有 active serialized device 或非 retired logical unit 的仓库必须先迁空，停用不会删除历史引用。
  - [x] 新主设备必须使用租户内启用的 main-device model，并在创建事务中落到显式 active/ready 仓或唯一默认仓；重复序列号、无效型号、停用仓稳定拒绝。账号可分别保存 booking/shipping/inspection 最近工作仓且只能指向 active/ready 仓。
  - [x] 桌面端已有首次默认仓确认页与仓库管理页，可编辑、设默认、停用、新增主设备和维护三类最近工作仓；身份登录壳自动跳转以及旧全局 device CRUD 的最终关闭继续由 10.2/10.7 承担，不作为本业务服务完成度的隐含 fallback。
- [x] 8.2 实现设备“更改仓库”的受影响订单预览、二次确认、可选备注，以及设备位置、移动历史和附件预留同事务更新；验货复用相同服务并记录来源。
  - [x] 调仓后端已迁入显式 tenant runtime：预览按租户业务日期列出订单号、使用期、物流天数、计划寄出/回仓日期和附件类型，并生成覆盖设备、仓库、订单、request/link/unit 事实的 revision；确认必须提交原仓、revision、显式确认和可选备注，使用 device → rentals → warehouses → request/link/unit 固定锁序，同事务写设备位置、移动历史、附件改配及 shortage，且不修改 rental 物流字段。HTTP 入口使用 `WAREHOUSE_DEVICE_MOVE` + 仓库/租赁/库存能力并在 runtime 缺失时固定 503。
  - [x] 桌面端“仓库与调仓”页面已接入可信仓库/主设备列表、新增仓库、影响预览和 revision-bound 二次确认；预览明确展示物流字段保持不变，确认后按 affected rental 汇总附件不足。验货创建响应使用相同的非阻断受影响/不足 rental 汇总并记录 `source=inspection` 的移动历史。默认仓 setup、仓库编辑/停用属于 8.1，继续单独开放。
- [x] 8.3 实现统一 AvailabilityService 和 ScheduleOverlapPolicy：客户使用期首尾均包含的重叠为 409；物流窗口 overlap_days > 1 仅产生可提交警告和接力候选。
  - [x] 预约预览、最终创建/编辑、范围甘特、接力候选和旧 find-slot 兼容入口均复用同一纯策略；find-slot 已从逐设备查询与完整物流窗口硬阻断改为一次批量读取，使用期重叠排除设备，`overlap_days > 1` 仍返回可提交警告/接力候选。`0/1/2` 天边界、首尾包含冲突、编辑排除自身、终态排除及 100 台设备固定 SQL 预算均有回归覆盖。
- [ ] 8.4 以候选/最终主设备当前仓库结构化地址为物流起点；删除固定广东/深圳和静默 3 天，官方时效不可用时要求 Admin/Operator 明确填写 0–7 天并保存确认快照。
- [x] 8.5 实现 accessory request、内部 logical unit 自动关联、同仓过滤、实时 total/reserved/available 聚合和最终事务固定顺序锁。
  - [x] tenant rental 最终 create/update 与 availability 共用逻辑附件库存边界：按主设备当前 ready warehouse 筛选 active unit，先锁 type/warehouse，再按 unit UUID 锁候选和重叠 link，普通 request 只关联同仓且窗口可用的单元；实时聚合从 active capacity、current holder 与目标窗口 overlap 直接计算 `total/reserved/available`，不读取缓存或返回内部 unit/link ID。普通分配、改配、并发冲突、同仓过滤、聚合和整链组合 focused regression 为 `97 passed`；真实 MySQL 8 双事务 contention 已纳入 `5 passed` 的隔离数据库运行，生产实例测试库复跑继续由 5.8/12.11 验收。
- [x] 8.6 实现同一主设备接力链的 unit link、current holder、linked/unlinked/dispatched/relay_handoff/returned 事件和从变更点向后原子重算。
  - [x] 普通订单状态变更已迁入 tenant runtime：发货时在同一事务校验全部 request/link、设置 current holder 并追加幂等 `dispatched`；归还写入权威实际时间；仍有 holder 时禁止完成。
  - [x] 安全删除已迁入 tenant runtime：仅允许无在途物流、无接力 case、无 current holder 的普通订单删除，并在同一事务释放普通 link/request；复杂链路稳定拒绝。
  - [x] 已将验货实收/损坏/未收到事实接入 tenant runtime：首次创建验货记录、主设备实际入库仓、移动历史、账号最近验货仓、逻辑附件 holder/condition/实际仓和只追加事件同事务提交；跨仓未来 link 在同一事务按 D41 重算，响应和页面均不出现 unit ID。
  - [x] 已实现 agreed 接力链从指定 edge 向后的固定锁序原子求解：连续边传播同一 unit、无 request 的中间单建立中性 link、上游后同意会重算全部下游、撤销会删除不可达 link 并为 request 同仓改配或保留 shortage；每次替换追加幂等 `linked/unlinked`，结果和错误均不暴露 unit ID。
  - [x] 现有接力状态事务已组合整链求解和实际 handoff：进入 `agreed` 或发货前先重算，`shipped` 在同一事务验证 exact predecessor holder 后更新 successor holder 并追加幂等 `relay_handoff`；乱序 holder、已实际发出的另一个 unit、已交接后降级或任一审计失败均整体回滚，闲鱼同步只在本地提交后执行。
  - [x] tenant-session 接力写服务已增加仅供持久 execution/reconciliation 调用的 provider-free `shipped/completed` 投影边界：它不解析 provider、不打开 control connection、不拥有事务，只在 caller-owned tenant transaction 内重算、交接、写 tracking/状态/里程碑和审计；B→C 先于 A→B 同意会在上游同意时补全整链，B 未持有时提前发货拒绝，A→B→C 顺序 handoff 后重放早先 edge 以不可变事件返回成功且不把 holder 倒退。public HTTP 在 outbox orchestration 完成前仍固定 503。
  - [x] 已把 committed Core shipping ledger 接到上述 provider-free 投影边界：`shipped` job 必须精确匹配已提交 SF shipment、唯一成功的 create-waybill attempt、waybill、租赁、binding/credential revisions 及该 attempt 的 response digest；control job 的 payload/resource/idempotency identity 必须完全一致，tenant 审计再持久绑定 source digest 与短 operation key。稳定 `submitted` shipment 是 handoff 的窄授权，但任一 in-flight/unknown/review provider 或打印事实仍失败关闭；冲突进入 durable review，不调用 provider/打印，也不泄露 unit/link ID。
  - [x] `completed` 已从 caller-supplied digest 收紧到独立持久化的运踪结果权威：provider adapter 只能把结果规范化为闭集 `in_transit/delivered/exception`，provider-free ledger 在 caller-owned tenant transaction 内锁定 exact submitted shipment/waybill/time，向既有 tenant audit ledger 写 canonical result digest 并精确重放；完成态 projector 必须命中唯一、字段严格且 digest/time/waybill 全匹配的 `delivered` 记录，否则进入冲突/review。两个 MySQL 事务并发记录同一签收结果只产生一条审计。
  - [x] successful create-waybill result 已具备直接 durable-job 通知边界：caller 在记录 provider 结果的同一 tenant transaction 内锁定 exact attempt/shipment/agreed relay 并生成不含凭证/PII 的 immutable signal，tenant commit 成功后由独立 control transaction current-lock tenant，使用当前 access version/timezone 幂等写 direct projection job；普通非接力 shipment 不产生日志或 job。若 tenant commit 后、control enqueue 前崩溃，30 秒 reconciliation 从同一 committed ledger 派生相同 command 补偿，不会重提 provider。
  - [x] shared durable capability 已增加每租户 30 秒 bucket 的 provider-free reconciliation job：它只为通过共享 tenant gate 的 current access version 调度，严格绑定 scheduler/job/resource/timezone identity，在显式 routed tenant transaction 中按提交时间/UUID/attempt 顺序发现至多一个 `agreed + submitted SF shipment + succeeded create-waybill attempt`，并复用上述 signal 派生器和同一 projector；无候选稳定 no-op，冲突进入 review。MySQL repeatable-read 下最终 digest audit 改用 locking current-read，两个 reconciliation worker 在旧 snapshot 竞争时仍收敛到一个 handoff。
  - [x] SF create-waybill provider-fenced handler 已实际调用 direct producer：三次 current-authority recheck 包围 exact credential load、tenant `provider_submitting` fence、一次 typed provider dispatch和最终结果持久化；成功 tenant commit 后 direct enqueue，入队响应丢失不改变已知成功且由上述 30 秒 reconciliation 恢复。SF unknown query handler 复用相同三重 authority 和 exact historical credential loader，但请求只含 shipment/provider-order identity而不含客户快照；一次 claim 后只允许一次自动 query，confirmed success 同样生成 direct signal。显式 `build_sf_relay_job_process` 把 create、unknown query、direct projection 与 relay reconciliation 四类 handler 合入唯一 worker，只为后两类 reconciliation 注册 30 秒 schedule，构造阶段零连接/零 provider 调用。fake provider/query 从 prepared 或 crash-after-submit 到 submitted ledger、direct/recovered job和 provider-free handoff 的完整链已通过；public HTTP、真实 SF adapter 与生产 launcher尚未完成，所以外部阶段继续 fail closed。
  - [x] 跨仓验货会先按共享 device → rental → warehouse 锁序固定未来作用域：正常实收保留仍可达的同设备 agreed 链，其余未来 request 按各自主设备当前仓的可用 unit 确定性改配；无候选时删除旧 link、保留 request 和 shortage，损坏/未收到单元不会被复用。验货、实物仓/holder/condition、link 事件与重分配同事务提交，已开始履约的未来订单使整体稳定回滚；创建响应和桌面提示列出受影响/不足 rental ID，仍不暴露 unit ID。
- [x] 8.7 实现 D34/D39 例外：无可用 unit 时保留 request 与内部补寄备注并返回非阻断 shortage warning，不创建第二 shipment/waybill 或伪造已满足状态。
  - [x] 最终 rental 写入与整链求解均保留无 link 的 request 并返回类型级 shortage；桌面/移动接力状态面板可维护最长 500 字、仅内部可见的补寄备注，备注与 actor/time 及最小审计在同一 tenant 事务提交。该路径只表达线下安排，不调用顺丰、不创建第二 shipment/waybill/打印/跟踪事实。
- [x] 8.8 调仓时自动尝试迁移所有未发货订单的手机支架/三脚架预留；目标仓不足时仍更新真实设备位置、释放旧预留、标记冲突并阻止顺丰下单、批量发货和打印。
  - [x] 普通未来 request/link 已实现确定性目标仓改配：保留已经位于目标仓且仍可用的 link，释放旧仓 link 并写幂等 `unlinked/linked`，候选不足时保留 request + shortage 且仍提交真实设备位置；预览 revision 漂移或事件写入失败会整体回滚。
  - [x] 调仓已复用同一 `AccessoryRelayChainService` 组合 relay-sourced/requestless 中性 link 的整链重算：先按目标仓改配根 rental 的普通 request，再从每个相关 root edge 向后传播同一 unit；目标仓不足时移除不可达普通/中性 link、保留 request + shortage 并提交真实设备位置。预览摘要包含 relay edge 状态，跨设备伪链、分叉/循环、已执行 edge、holder 或整链事件失败均整体回滚；Core shipment/waybill 提交与 print-effect boundary 已按 request/link/unit/current warehouse 复验 shortage。
  - [x] 遗留顺丰直连蓝图不再由应用工厂注册，testing/debug/production-like 三类配置均没有 `/api/sf-test/*`；旧批量发货 status/express/printer/print/Xianyu handler 在非测试进程统一先返回 503，唯一可用 schedule 路由只委托显式 tenant Core runtime。负向路由/配置矩阵 `28 passed`，真实 `inventory_management_test` 上的两个 schedule intent 用例证明 exact shipment/attempt 持久化、请求重放和 Core job enqueue；旧打印入口在阶段 9 完成新的 print-effect runtime 前保持不可用，不能绕过 shortage fence。
- [x] 8.9 实现 booking bootstrap、稳定筛选变化一次 availability、单次 edit-context 和单次范围 gantt view；mutation 由页面唯一负责至多一次当前窗口刷新。
  - [x] 后端 bootstrap/availability/edit-context/gantt view、桌面与移动 edit-context、桌面与移动 gantt view 已接入，并对重叠读取做 generation fencing。
  - [x] 桌面与移动新建页均已改为一次 bootstrap、稳定筛选一次 availability、结构化地址、优先仓、逻辑附件类型和显式人工物流确认，并提交 tenant-runtime final-create 契约。
  - [x] 桌面与移动最终 update 已迁移到相同的 locked revalidation/D39 request-link 契约；普通逻辑附件在事务中安全释放/重分配，已有接力来源 link 在整链重算服务完成前返回稳定冲突并整体回滚，页面继续由唯一成功协调器刷新当前窗口。
- [ ] 8.10 将 add-due-today-returns、add-gantt-schedule-reordering、add-logistics-time-warning、add-relay-management、show-gantt-schedule-conflicts 的现有能力重基到 tenant route、tenant timezone、D19/D33/D39 和聚合 API；把甘特预览从通用 `SECRET_KEY` 签名迁移到平台根密钥按 `inventory-manager/tenant-gantt-reorder-preview/v1` 独立 domain 派生的短期 HMAC，并绑定 tenant、actor session、规范化 payload、snapshot、权威 revisions 和时效；迁移后删除通用 `SECRET_KEY` 的应用配置、启动校验、部署/恢复读取和全部剩余签名路径。
  - [x] 接力列表、人工配对选项、人工建立及 provider-free 的 `pending/notified/agreed` 状态流已迁入可信 tenant Session，并使用 control UTC 派生的 tenant business date/timezone 与认证 actor；查询/写入参数均在权限通过后解析，人工建立及状态进退按 device → rentals → cases/bindings → logical units 固定锁序组合整链重算，响应统一 `private, no-store`。`shipped/completed` 与物流刷新在非测试进程稳定返回 503，不回退 global Session 或真实 provider；持久 outbox/provider execution/reconciliation 完成后才能迁移这些外部副作用阶段。
  - [x] SaaS 甘特 preview/execute 只使用平台根密钥派生的 tenant/session/authority-bound proof；通用 `SECRET_KEY` 已从应用配置、Docker/环境样例、Windows/Makefile 样例和启动文档删除。旧单租户甘特签名只允许 literal testing flag + 独立进程临时测试键，非测试进程直接拒绝，不能成为 Core 身份或 preview authority。
- [x] 8.11 使用至少 100 台主设备、多个仓库、多个同类型 logical units 和 31 天订单夹具验证 availability SQL 建议不超过 6 条、gantt SQL 建议不超过 8 条，且查询数不随设备/日期线性增长。
- [x] 8.12 运行多仓创建/编辑、0 天物流、调仓竞态、附件超卖、接力链撤销/重算、HTTP 扇出和 SQL 预算测试并记录结果。
  - [x] 接力/附件子矩阵已运行 `115 passed`：覆盖普通分配、整链同意/撤销/重算、乱序 handoff、A→B→C 顺序交接、较早 edge 在下游交接后的幂等重放、完成态投影、审计失败全事务回滚、HTTP provider 阶段 fail closed 及旧兼容路由；全部使用隔离 SQLite 与 fake/缺失 provider，未调用真实 provider/打印。
  - [x] 一次性 MySQL 8 容器中的附件与接力行锁矩阵已运行 `6 passed`：最后一个逻辑附件的重叠竞争只允许一方提交、非重叠窗口均可提交；同一 A→B handoff 的并发精确重放只追加一个事件，A→B 与 B→C 乱序竞争允许稳定冲突并在使用同一 operation key 重试后收敛到 C 持有且恰好两个 handoff 事件；create-waybill 用例由 fake provider 经真实 tenant store 从 prepared 推进到 succeeded/submitted，模拟 tenant commit 后 direct enqueue 响应丢失，再由两个 reconciliation worker 并发自动发现同一 shipment/attempt/digest并只产生一次 handoff；新增 crash-after-submit 用例证明两个 query reconciler 竞争同一 attempt 时仅一方取得 one-shot claim，fake confirmed-success 写回后仍只产生一次 handoff；同一 `delivered` 运踪 observation 的两个并发写入也只生成一条 canonical audit。测试只使用库级 `inventory_management_test.*` 账号，容器已删除，未连接生产 schema、provider 或打印机。
  - [x] 已增加唯一 `saas-core-relay-matrix.v1` 入口并固定 control head `202608220029`、tenant head `20260823_shipping_contract` 与精确测试选择器；`make test-saas-core-relay-matrix` 依次运行多仓/100 设备/31 天/0 天物流 create+edit、booking/gantt SQL budget、调仓和整链撤销/重算/handoff，随后运行前端 bootstrap/availability/edit-context/mutation 单请求/单刷新 fanout，最后串行委托 D66 的现有测试库 launcher。当前 bundle digest `f0469fe1f34a9cdb9cff3b4a0eb6d239776e6350c17b7dc53bce0f5532fa1a1b` 下三段一次通过：backend `58 passed`、frontend `53 passed`、MariaDB `inventory_management_test` 调仓/附件/接力/Gantt 竞争 `10 passed`；未连接生产业务 schema，未调用真实 provider/打印。
  - [x] D67 superseding 矩阵已把所有 SQL-backed 正向选择器从 SQLite 移入同一个 `inventory_management_test`：模块级 metadata lifecycle 配合逐 case 清数据，control+tenant 组合测试也在同一 schema 使用无重名 metadata 和独立 Session。当前 bundle digest `0542dd882dffbec234a873c833f5fdc7e6800297735f96b746546f41743f4bf7` 下完整命令一次通过：无数据库后端 `17 passed`、前端 `53 passed`、MariaDB `69 passed in 567.32s`；后者覆盖 booking 5 SQL、Gantt 8 tenant SQL、完整调仓/附件整链、fake-SF handoff、10 个真实竞争和批量 intent，未调用真实 provider/打印。

## 9. 顺丰账号、凭证修订、运单、打印及租户集成

**依赖/前置条件：** 阶段 1–3、5、7、8 已提供本阶段所需的密钥、路由、任务、schema、生命周期和仓库/附件接口；顺丰/腾讯云契约、受控测试 fixture 和 readiness owner 已确定。真实 capability、资质和通知送达可在后续普通 smoke 中验证，不阻止使用 mock/fake 在非生产实现和测试。

**完成条件：** 当前集成解析到 current revision，历史操作固定到精确快照；所有 provider 提交均可幂等执行或安全对账；运单与两联打印保持同仓一致。

**可验证结果：** 双租户账号 claim、credential 轮换、调仓取消重建、历史 tracking、重复下单和打印响应丢失测试通过。

- [ ] 9.1 实现不可变 integration、connection、provider account、warehouse binding 和 credential revision，以及 current pointer、provider Secret write-only/no-reveal 约束和根密钥版本轮换。
  - [x] tenant integration metadata、不可变 encrypted secret revision 与 provider-validation 执行已实现首个控制面纵向切片：列表只返回 provider/name/status/configured/last-verified/row-version 安全投影，不返回 Secret、ciphertext、digest 或 current revision UUID；credential 确认只创建 `pending_validation` revision，并以稳定 source generation/idempotency key 写 outbox。worker 在提交 exact revision/attempt 的 `submitting` fence 后才把一次性解密请求交给注入 adapter；明确成功原子切换 current 并 supersede 旧 revision，明确失败保留工作中 current，unknown/异常只进入 reconciliation quarantine，均不盲重试。connection/provider-account/warehouse-binding、根密钥轮换及真实 provider adapter 仍保持未完成；provider Secret 依当前集成 write-only 定稿不提供 reveal，而非新增查看端点。
  - [x] control head `202608220029` 已增加稳定 `tenant_provider_accounts`、独立 domain 加密且只追加的 account-secret revisions 和 envelope-event ledger；pending revision 固化 exact integration revision、claim generation/row fence 及 tenant binding target/expected CAS，明确成功在同一控制事务激活 reservation、切换 account current、supersede 旧 revision，失败/unknown 不切 pointer。租户库 warehouse binding 采用独立单调 revision 状态机，bind/replace/unbind 均要求 expected account/revision 并可精确重放。生产 worker composition 和异常 reconciliation 仍未完成，因此主项保持开放。
  - [x] provider-account exact current/superseded revision 已支持 caller-transaction envelope rewrap：新 root version 重新认证加密同一 canonical account，CAS 推进 envelope generation/row version 并追加 before/after ciphertext digest ledger；业务 revision、claim、account current pointer 和 canonical semantics 不变，旧 root 随即无法解密，精确重试只返回同一 rotation event。Admin settings 查询只返回 account/integration/warehouse/binding/status/掩码/版本安全投影，并从 immutable release event 重建已解绑账号的原仓事实；不选择或返回 revision/claim UUID、fingerprint、ciphertext、digest 或 provider Secret。
- [ ] 9.2 实现顺丰月结账号规范化 fingerprint 的全局 claim reservation、验证、绑定、主动解绑、转移和异常 reconciliation。
  - [x] 已完成 provider-account canonical value → root-key HMAC fingerprint、永久全局 claim row、reservation/activation/admin-unbind/deletion-release/rebind 的纯状态机与 caller-transaction persistence；全局唯一竞争只产生一个 owner，loser 不获知 owner 身份，event history 保留且 plaintext account/fingerprint 不进入 DTO/repr。初次绑定/同账号复验已纵向接入 provider validation、warehouse binding outbox 与 D48 HTTP；跨 fingerprint 换绑、跨 tenant transfer 和异常 reconciliation 仍未完成，因此 9.2 保持开放。
  - [x] provider-account control service 已把 reserved claim、exact encrypted account revision、exact API-connection revision 和最终 account pointer CAS 串成无 provider I/O 的事务边界；D50 Admin unbind 在同一 control transaction 释放 claim 并清除 account current-claim pointer，expired/suspended proof 的测试证明 claim/account 整体不变。tenant binding 失败时 control resolver 因局部 binding 不一致继续 fail closed。真实 SF validation adapter/worker launcher、跨 fingerprint 换绑/跨租户 transfer saga 与异常 reconciler 仍保持开放。
  - [x] provider-account validation 已复用 ordinary outbox 的 claim/dispatch/result 三重 current authority：只解密 account revision 固化的 exact SF API revision 与月结账号 revision，provider unknown 固定 quarantine 且不切 current；VALID 最终事务从已消费 D48 intent/challenge 及当前 active Admin user/session/membership 重建内部 proof，原子激活 claim/account 后再写一次 tenant-binding apply outbox。revision 现固化 local binding target/expected CAS，tenant binding applier 只接受 immutable worker command 并调用同一单调 binding service；control 成功而 tenant 写入未知时继续 fail closed，留给 reconciliation，不自动重放可能已提交的跨库写。生产 SF validator/router composition 和 reconciler 仍开放。
  - [x] 主动解绑已形成 provider-free 纵向链：tenant local plan 固化 active binding revision，D48 context 绑定 account/claim/warehouse/tenant access 与两库 CAS，正确 OTP 在单一 control transaction 释放全局 claim、停用 account pointer 并写一次 binding-remove outbox，错码则整体回滚。worker 只依赖不可变 claim-release event 授权旧租户本地清理，即使同一 fingerprint 已被其他租户重新预占也不会阻塞；HTTP 与 tenant unbind 都支持精确终态重放，后续新占用不会被旧 HTTP 请求误释放。跨 tenant transfer 与异常 reconciliation 仍开放，故主项保持未完成。
  - [x] provider-account validation unknown 已具备显式、非重提交流程：同一 exact revision/attempt 可更新 `still_unknown` 安全结果或一次性收敛为 confirmed success/failure；正常验证与 reconciliation 复用同一 claim/account/current-pointer CAS，confirmed success 仍要求 current D48 owner/proof/binding authority，confirmed failure 不切 current，终态后重复 reconciliation fail closed。生产 read-only provider 查询编排与受限触发入口仍开放。
- [ ] 9.3 对顺丰绑定、解绑和转移执行 Admin 权限、D48 action-bound 短信复验及 D56 effective gate；expired/suspended tenant 不开放解绑例外。
  - [x] 通用 integration credential change 已执行 Admin capability、D48 exact-action 短信复验和 D56 gate；HTTP 在 credential 解析和短信之前拒绝 expired/suspended，validation outbox 又在 claim、provider fence 和最终结果三处 current-read tenant/recovery/subscription/route/access-version 与 exact revision generation，暂停或过期先于 provider 时不会调用 adapter。顺丰账号绑定与主动解绑已接入同一 authority 边界，跨租户转移仍未接入。
  - [x] 顺丰账号初次绑定、同账号 credential revalidation 及主动解绑已接入 control/tenant 双 current-read 的 D48 HTTP：绑定重算同一 warehouse binding plan、account/integration pointers、tenant access version 和 account semantics digest；解绑重算 local removal CAS 及 current claim/account facts。错码 savepoint 回滚 claim/account/revision/outbox 后只保留 OTP 失败事实，响应丢失可精确重放。当前 active binding 换成不同 account 仍以通用 `SF_ACCOUNT_UNAVAILABLE` fail closed，要求先主动解绑；跨租户转移 HTTP 仍开放，因此主项不关闭。
- [ ] 9.4 实现 resolver：官方时效和新运单按主设备执行时的实际仓库选择 binding/account/connection；历史 shipment 永远使用创建时精确 revision 和寄件资料快照。
  - [x] 已实现可复用的 SF control resolver：新操作 locking-read 并同时核对 trusted tenant/warehouse、local binding revision、provider account/current account revision、global claim owner/generation/fingerprint、integration/current integration revision；任一漂移统一失败。历史 resolver 只接受 shipment 固化的两条 exact revision UUID，不跟随 current claim/pointer，claim 后续解绑仍可解析旧 revision。尚需把主设备实际仓、寄件资料快照和该 resolver 组合进 official estimate/waybill/print HTTP 与执行 ledger 才能关闭主项。
  - [x] tenant shipment ledger 的新建入口已改为只接受上述 typed `SfProviderExecutionContext`，不再接收 caller-supplied origin、sender 或 tracking phone last4；新 shipment 在最终 tenant transaction 锁定 main rental/device/实际 ready warehouse，复验该仓 active local SF binding 的 account/revision，服务端从仓库结构化资料生成 sender snapshot，并从 receiver 业务电话推导查询后四位。只有 exact provider-order replay 可在设备调仓或 claim 后续变化后返回既有历史快照；新建拒绝 historical context。official estimate/HTTP、provider submission adapter 与完整跨库 coordinator 仍开放，因此主项保持未完成。
  - [x] 已抽取 SF 共用 exact-credential loader，tracking 与 create-waybill credential request 复用同一双 revision 认证解密路径：只选择各 revision 记录的 root-key version，同时核对 tenant/integration/account/claim generation/binding revision/masked semantics，绝不回退 current pointer 或可用的新 key。create request 从 shipment ledger 的 typed sender/receiver snapshot 与 express type 构造 request-local 深拷贝，凭证只可消费一次且 repr 不含凭证或 PII；binding fence 漂移在 provider 前拒绝。尚缺 scheduled-time/cargo 的完整 execution snapshot、SF payload allowlist adapter、HTTP/control-job coordinator 与实网验证，故主项不关闭。
  - Superseding 进展：tenant head `20260823_shipping_contract` 已把 UTC 预约时间和服务端从锁定主设备生成的单件 cargo snapshot 纳入 shipment、request hash、worker snapshot 与 consume-once credential request；同 shipment 重放逐字段复用，不能跟随设备显示名或 rental 资料漂移。可信批量 HTTP 也已组合实际仓 local binding 与 control resolver；9.4 现剩官方时效、SF payload allowlist/真实 adapter、打印/取消 parity 和实网验证。
- [x] 9.5 实现稳定 shipment UUID、非 PII provider order id、逐订单 execution ledger、批量选择去重和 provider response 丢失后的查询对账。
  - [x] 新 shipment 入口不再接受 caller/client 自定义 provider order id：调用方只提交稳定 shipment UUID，tenant service 从 typed control context 的非敏感 tenant UUID 与该 shipment UUID 唯一派生 `sf:<tenant_uuid>:<shipment_uuid>`，并把同一 shipment UUID 作为 ledger 主键。精确重放按 shipment UUID 锁行并比较完整不可变快照，tenant/context/receiver/warehouse/account/revision 任一变化均冲突；客户姓名、电话、地址不能进入 provider identity。既有逐 operation attempt 状态机继续为每次 create/cancel 保存独立 idempotency、exact revision 和 unknown/reconciliation 终态。尚需 trusted HTTP→control job 的跨库提交协调、批量去重 worker、真实 SF create/query adapter 和 response-loss 对账，故主项保持开放。
  - [x] 已增加 current-tenant-bound 的 create-waybill coordinator 和 provider-fenced worker：control job 使用稳定 shipment/attempt UUID、非 PII resource/idempotency identity并固定 `max_attempts=1`；handler 只从 tenant ledger 取 exact frozen warehouse/binding/two credential revisions/sender/receiver/express snapshot，Secret request 在所有路径销毁，公开结果仅含 shipment UUID、typed outcome和 direct-enqueue 布尔值。provider 返回或异常先分类为 success/definitive failure/unknown并持久化；unknown 绝不盲重提，crash-after-provider-before-result 依 SF recovery policy 进入 review/query reconciliation。one-shot query worker 已从同一 frozen shipment/revisions 构造不含 sender/receiver 的 provider-order request，在 query 前持久 claim，按 confirmed success/no-effect/still-unknown 写回同一 attempt；并发或仍未知不会自动重复 query/create。尚需 tenant intent→control job 跨库 provenance/producer、批量协调及真实 create/query adapter，故主项保持开放。
  - [x] superseding 进展：tenant create attempt 已固化 immutable actor/access/request provenance 与预分配 job UUID；30 秒 provider-free producer 在独立 control transaction enqueue exact UUID 后回写 tenant ack。控制提交、响应丢失或 ack 失败后的重复 producer 只复用一条 job，stale access version 不入队。9.5 现剩 trusted HTTP/batch 协调及真实 create/query adapter。
  - Superseding 完成证据：`/api/shipping-batch/schedule` 已迁入显式 SaaS runtime，只接受 exact request UUID、去重后的最多 100 个 rental 与带时区整秒预约时间；它先提交 tenant shipment/attempt intent，再逐项 enqueue exact control job 并 acknowledgement。同 request UUID 的 HTTP 响应丢失重放返回相同 shipment/attempt/job，改变预约时间、actor/access/provenance 或 snapshot 固定冲突；direct enqueue 失败仍由同一 committed intent 的 30 秒 producer 恢复。真实 SF adapter 属于 9.4/9.11 的 provider 接线，不再阻塞本项列出的 identity、ledger、dedupe 与 response-loss 语义。
- [ ] 9.6 运单创建后设备调仓时阻止打印/实发，显式取消旧运单；取消结果未知时进入人工复核，确认后才能按新仓、新账号和新地址重建。
  - [x] tenant execution ledger 已形成 provider-free D40 状态链：已提交运单与设备当前仓不一致时两联提交 fence 失败；新 provider order 创建会在锁定同一 main rental 后拒绝任一非 `cancelled` 旧 shipment，`cancel_unknown/needs_review` 返回显式 unknown 而非新建。旧运单显式 request-cancel 后以 exact historical credential/binding snapshot 提交；结果未知只进入 reconciliation，只有 confirmed cancellation 才允许使用新仓 local binding、typed control context、结构化 sender 和新 provider order 建立 replacement。尚需接入 trusted tenant HTTP/worker、真实 SF cancel/query adapter 与 legacy 发货状态，故主项保持开放。
- [ ] 9.7 实现顺丰第一联与本地第二联的同一 warehouse/printer/shipment context；第二联只含批准字段和两个教程二维码，订单客户备注不进入顺丰 payload 或第一联。
- [x] 9.8 实现每仓最多一台启用快麦打印机且一台打印机不能绑定多仓；历史 print job 保存打印机 SN 快照，未绑定或失效只阻止打印。
  - [x] tenant schema 已以 warehouse/printer SN 双唯一约束表达一对一当前绑定；独立 caller-transaction binding service 只应用已由 exact Kuaimai revision 验证的稳定 command，支持精确重放、同仓换绑、跨仓 SN 冲突和 active resolver。paired-print preparation 不再接收 caller/client printer SN，而是在最终 tenant transaction 锁定 shipment/device/warehouse/accessory facts后复用该 resolver，并为两联保存相同 SN。缺失、inactive、verification_failed 或准备后换绑会在 provider submission fence 前只阻止打印；exact idempotent replay 保留原两联 SN 快照且不被 current binding 改写。`50 passed` focused regression 覆盖 schema/model、binding 和完整 print ledger 状态边界。Admin provider printer discovery/validation 与换绑 HTTP/worker 属于 9.1/9.11 的接线范围，不再阻塞本项列出的绑定与历史快照约束。
- [ ] 9.9 实现顺丰 tracking 服务端游标分页、batch query、手机号后四位验证，并按历史 shipment revision 分组解析查询凭据。
  - [x] tenant tracking query 已改为 `(submitted_at, shipment UUID)` 稳定 keyset cursor，固定 1–100 页大小且公开摘要不 join/返回客户 PII、credential revision 或 provider context；内部选择最多 500 条并按 exact integration/account/revision、原仓 binding 与 shipment 固化手机号后四位分组，每个 provider batch 最多 100 条。控制库 factory 逐批调用 historical resolver，逐字段核对 account/integration/revision/context，从 root-key ring 只选择各 revision 记录的 active/legacy 精确版本并认证解密两类 Secret，生成一次性、redacted request；typed dispatcher 只接收 bounded route result，补齐 not-found 并在成功/异常后销毁请求内引用。`/api/sf-tracking` 已改为显式 trusted tenant runtime，只接受 shipment UUID，授权后规划并在 provider 前再次 current-read D56/auth，缺 runtime 固定 503 且不会回退固定手机号、环境变量或 raw waybill。显式配置 endpoint mode/provider timezone 的 SF SDK adapter 只把 exact partner/checkword 与固化后四位发送给 read-only batch API，月结 revision 仅作历史 ownership fence；桌面页已消费 server cursor、当前页 shipment batch 和 bounded event DTO，不再请求客户 PII 或 raw-waybill credential fallback。该 runtime 现可作为可选 typed adapter 加入 SaaS Core atomic shared graph，并强制复用同一 control DB/auth boundary/tenant router；真实 SF readiness/超时策略、查询缓存和实网资格验证仍开放，故主项保持未完成。
- [ ] 9.10 实现闲鱼 credential/cursor/sync state tenant-bound、每租户每 3 分钟同步、显式即时高优先级同步和 180 秒幂等合并。
  - [x] tenant head `20260823_xianyu_sync_state` 已增加 aggregate/per-connection sync state 与 alert 的 exact integration/revision ownership；caller-transaction result applier 按 connection 独立替换成功摘要、保留失败 connection 的上次成功告警，并以 job UUID 防止重复 revision。控制库 scheduler 复用通用 180 秒 deterministic stagger，冻结所有 active Xianyu connection 的 exact revision/version 并把 connection-set digest 纳入 time-bucket 幂等键；Admin/Operator 手动刷新在控制库锁 tenant 后优先复用 scheduled/manual 在途任务及同桶终态任务，否则创建 180 秒窗口的高优先级 `xianyu_alert_sync_now`。可信 tenant HTTP 先关闭租户 session 再入控制库 enqueue，返回 `202 + job_id/snapshot_revision`；GET/ignore 只读写租户本地摘要，缺显式 runtime 时即使存在 legacy env 也固定 503。桌面端仅页面可见时每 180 秒 GET 本地摘要，显式刷新消费 job receipt，并展示 syncing/stale。
  - [x] per-connection tenant state 已持久化最多 512 字符且不进入公开 DTO/repr 的 provider cursor；只有成功结果推进游标，失败/限流保留上次成功游标和告警，credential revision 改变时则先清空旧 revision 游标。控制库 one-shot factory 锁定并核对 job 固化的 tenant/integration/current revision/两级 row version/verification，按 revision 记录只选择 exact active/legacy root key，绝不回退新 key 或 current 新 revision，明文 `app_key/app_secret` 只能消费一次。typed provider dispatcher 要求部署显式提供 HTTPS endpoint、1–30 秒连接超时、1–60 秒读取超时、1–3600 秒限流重试窗口及 1–100 page size/max pages，并把异常、非法响应和限流投影为固定 safe result。通用 durable provider-call authorizer 在多调用 job 的每次第三方请求前用短控制事务重新锁定 current authority 并续租；闲鱼 handler 对每个 connection 先执行该检查，再独立取 exact credential/cursor、调用注入 adapter、最终用短 tenant transaction 一次应用完整结果，credential 漂移不影响其他连接，authority deny 立即停止剩余 provider 调用。handler 将 recovery category 固定为 registry 已确认的 read/current-snapshot safe-retry；worker 只在该 immutable-snapshot + stable-idempotency policy 显式允许时重排 provider 后异常，过期 `provider_submitting` lease 也仅在同 job payload/key、未过 `not_after`、attempt 未耗尽和 current authority 仍允许时以新 lease fence 接管，其他 provider 类仍进入 review。production-shaped HTTP adapter 已按现有 status-12/page-number API 执行 compact-body 签名、完整分页、`pay_amount > 5000` 过滤、重复/缺页拒绝和 PII typed projection；该已知 API 未发布 opaque incremental cursor，因此 adapter 明确不伪造或提交未文档化游标。全部 HTTP 测试使用注入 fake client；生产 worker launcher/composition、实网 readiness、测量后的参数以及 provider 将来如发布 cursor 后的契约接入仍开放，故主项保持未完成。
  - [x] 已增加无环境变量发现的显式 Xianyu durable-worker composition，本条 supersede 上一记录中“composition 仍开放”的部分：复用同一进程级 bounded tenant router，把 scheduled/manual 两类 job 映射到同一 handler，并把 claim scope 限定为这两类，避免专用 worker 领取并误处置其他任务；同一构造器也输出 handler + 180 秒 definition 的 capability registration，能与未来 SF/快麦能力合并进唯一 worker/process。统一注入 control DB、current authority、heartbeat、root-key directory、provider settings/adapter、lease 与 clock。构造阶段不连接 control/tenant DB、不调用 provider，错误对象图在返回 runtime 前失败。独立进程最终 launcher、部署配置解析、signal 接线和真实 readiness 仍开放。
- [ ] 9.11 将 add-scheduled-shipping-status、add-single-rental-ship-button、add-xianyu-missing-order-alerts、enable-selective-batch-shipping、integrate-xianyu-order-api、interleave-shipping-slips-with-waybills、simplify-batch-shipping-flow、view-sf-shipment-tracking 重基到 warehouse context、持久 job、执行快照和统一幂等状态机。
- [ ] 9.12 移除进程级顺丰/闲鱼/快麦全局凭证和固定寄件地址 fallback，完成现有配置到默认 tenant 加密 revision 的迁移适配和 Secret 日志扫描。
  - [x] Xianyu 生产 sync 已只从 job 固化的 exact encrypted revision 取得 one-shot credential；legacy alert handler 改为仅在显式 testing compatibility 分支延迟导入，旧 `XianyuOrderService` 构造器不再读取任何 `XIANYU_*` 环境变量且默认实例保持无凭证，示例环境文件也已移除 Xianyu APPKey/Secret。所有仍依赖 global Session/SF/Kuaimai/Xianyu legacy provider 的 shipping-batch 路由在非测试进程于 handler/ORM/provider 前统一返回 private no-store 503；TestingConfig 的兼容开关不能在非测试进程启用。仍需把发货详情/ship provider 业务接到 exact revision worker、移除 SF/快麦进程 fallback，并完成默认租户 metadata→新 revision 的显式录入/验证，所以主项保持开放。
  - [x] legacy `/api/tracking/*` 与 Web scheduler 控制面已改为显式 testing-only compatibility；非测试请求在参数解析、global Session、scheduler 和 SF client 前返回 private no-store 503，模块顶层也不再导入会初始化 legacy SF client 的 `scheduler_tasks`。通用 `SECRET_KEY`/`API_KEY` 已从受版本控制的 Docker/production 环境模板和 Makefile 配置检查中移除；本机未跟踪 `.env` 未被读取、改写或作为验证输入。真实 SF tracking 继续只走 tenant-routed exact historical revision runtime；旧 scheduler/SDK 实现留作隔离兼容测试，待 9.11/9.12 contract 删除。
  - [x] 进程级 provider credential discovery 已从应用 Python 路径移除：legacy SF order/tracking/scheduler、Kuaimai print 和 Xianyu order adapter 均只接受显式构造参数或显式注入测试 client，默认 compatibility 单例保持无凭证，`app/` 下已无 `os.getenv(SF_*|KUAIMAI_*|XIANYU_*)`；受版本控制的环境模板、Makefile 检查和 Docker README 也不再要求这些值。Core 真实调用仍只允许 exact encrypted tenant revision；本项不等于已把现网旧值迁成新 revision，也不完成仍开放的 Xianyu ship/SF create/Kuaimai print worker。
- [ ] 9.13 运行账号 claim/转移、D48/D56、credential revision、重复运单、调仓取消重建、两联一致性、历史 tracking 和 provider 未知结果测试并记录结果。

## 10. API、桌面/移动端与旧能力移除

**依赖/前置条件：** 阶段 4、6–9 已提供界面所需的身份、订阅、生命周期、多仓和 provider API 契约。

**完成条件：** 桌面端、移动端和平台后台只使用新鉴权、状态门禁和聚合契约；已裁剪能力与不安全旧入口不可达。

**可验证结果：** API 绕过、前端 E2E、production build、旧路由/品牌/Secret 扫描全部通过。

- [ ] 10.1 为所有 tenant API 接入统一 AuthContext、membership、RBAC、CSRF、effective gate、可信 tenant session 和 no-store 安全错误响应。
  - [x] 已为当前迁移完成的 shared tenant/Identity/Invitation/Integration/SF provider-account/Subscription/Gantt/Rental/Inspection/Warehouse/Relay 与 platform HTTP runtime 建立单一显式 composition root：部署必须同时提供 typed database-instance registry、绝对 root-key 目录、pool/cache 设置和独立 control database；Identity、Invitation、Integration、SF provider-account、Subscription 与业务 runtime 强制共享同一 control database、TenantHttpBoundary 和 SessionService，完整对象图构建成功后才一次发布全部 extension，缺失/半配置保持固定 503 且不回退 global session。
  - [ ] 仍需迁移并组合 provider 转移、tenant lifecycle/delete 和其他尚未进入 trusted tenant runtime 的 API，再关闭本项。
- [x] 10.2 完成桌面端和移动端的手机号登录、tenant 状态、邀请接受、默认仓 setup、成员管理、集成设置、过期续期、暂停说明和账号安全页面。
  - [x] 桌面端和移动端默认仓 setup 页面均已接入 Admin-only tenant runtime，读取 provisioning 预填手机号并要求确认全部地址字段；普通业务后端在 pending 状态统一返回 `tenant_setup_required`。两个路由壳都会用经后端鉴权的 setup 状态把 pending tenant 自动送入 setup、把 ready tenant 送回业务首页；探测失败时不猜测身份或 tenant 状态。
  - [x] 桌面端和移动端账号安全页已接入本人设备列表、当前/指定/全部设备退出；pending 默认仓仍允许进入账号安全，页面不接收 token/hash/IP，所有撤销使用独立 CSRF，退出后统一回到 `tenant-login`。
  - [x] 桌面端和移动端已增加手机号 OTP 登录页：challenge/code 只保存在页面内存，成功后仅把独立 CSRF 放入 tab sessionStorage，opaque bearer 只由 HttpOnly Cookie 承载；active 登录交给默认仓守卫，expired/suspended 进入统一受限状态壳。expired Operator 只读取 expiry 并退出，Admin 可提交内存中的兑换码，成功或模糊响应后重新读取权威 gate 再决定是否回到业务页；suspended Admin 只额外开放本人账号安全。
  - [x] 桌面端和移动端均已完成邀请接受、成员/邀请管理和 integration settings 路由：集成页只读取安全 metadata，创建连接使用浏览器预分配稳定 UUID；provider 的 exact credential 字段、D48 action UUID、challenge 和 OTP 只停留在组件内存，字段或连接变化会失效旧 action，网络不确定重试保留 exact action，成功或卸载立即清空。pending 默认仓不把集成页加入例外，只有 ready/active 正常业务 tenant 可进入。
- [ ] 10.3 完成平台管理员登录、TOTP/恢复码、兑换码、租户只读查看、D52、D53、删除和 D58 单租户审核页面。
  - [x] 平台 setup、登录、session status、本人 session 列表、指定/全部撤销和 CSRF logout 后端契约已接入独立 `/platform/api` runtime；setup seed/recovery 明文只在一次性响应中出现，平台 bearer 只存在 HttpOnly Cookie。
  - [x] 桌面端平台 setup/login/security 页面已消费上述身份契约：setup token 不从 URL 读取且不进入 storage，密码和 factor 提交后清除，TOTP seed 与恢复码各只显示一次，确认离线保存后清除并进入登录；平台 CSRF 与 tenant CSRF 命名隔离，指定/当前/全部平台 session 可撤销，已登录 Admin 可先暂存并确认替换 TOTP 或重新生成恢复码，相关 seed/code 只保留在当前组件内存。单租户目录/只读租赁/逐条 PII 查看也已接入；D54 补发、D52、删除和 D58 页面仍待对应后端边界完成。
  - [x] 平台安全页可现场刷新 D52/D58 近期 MFA：成功响应轮换 HttpOnly bearer 和 tab CSRF 后重新读取权威 session，错误 factor 清空输入且不持久化；它不替代 D53 逐动作 factor。D52/D58 动作页面仍待对应后端 API 组合。
  - [x] 平台租户目录页面已接入分页/状态过滤、单租户控制面详情和独立 `platform_read` 脱敏租赁排障列表；控制详情只显示 tenant UUID、公开名称、状态、版本、订阅到期和非秘密 route 状态，业务列表只显示主租赁、设备、租期、状态和脱敏客户摘要。服务端先鉴权再解析查询，页面不接收 settings、数据库名、账号、完整手机号/地址、备注、买家或运单字段，并在切换 tenant 时清除旧状态。
  - [x] D53 单租户服务期调整页面已接入租户目录：仅提供增加天数、减少天数和立即到期，不接受目标时间；任一业务输入变化立即废弃预览确认并清空 factor，预览以 Asia/Shanghai 展示服务端数据库时钟计算结果，提交要求现场 TOTP 或恢复码。确认 token、factor 和结果只保留在组件内存，成功后重新读取租户详情，页面和响应均明确服务期记录不代表资金已退款。
  - [x] 平台兑换码基础页面已接入独立权限边界：状态筛选列表只消费掩码和非秘密结果投影，生成成功后用当前内存响应立即下载一次性 CSV 且不保留明文，幂等重放明确不重导；历史记录只能逐码查看并在弹窗关闭/卸载时清空，active 行按当前 row version 撤销。页面不提供历史批量导出、开户 retry/abandon、system cleanup 或恢复 active 入口；D54 唯一补发动作仍待 6.8/6.9 后端完成。
- [ ] 10.4 将批量发货、单单发货、验货和打印页面切换到 warehouse context、服务端分页、字段裁剪和统一持久任务状态。
- [ ] 10.5 删除身份证 OCR、租赁合同、独立单张/批量发货单及热敏发货单生成链路，但保留顺丰第一联和批准的本地寄回第二联。
- [ ] 10.6 将旧公司品牌、寄回地址和固定地理判断替换为 tenant branding 或 warehouse 数据，确保测试 fixture 不会成为生产 fallback。
- [ ] 10.7 删除 /external-api、X-API-Key、生产 test routes、已迁移兼容端点、旧 A4/扫码入口和普通 API 的无条件 WebSocket upgrade 头。
  - [x] `/external-api`、`X-API-Key` 与通用 `API_KEY` 已从运行时和配置面移除，并有“即使注入旧值仍不可达”的负向回归；本项其余生产 test route、兼容端点、A4/扫码入口和 WebSocket 头仍待逐项退休。
- [ ] 10.8 运行桌面/移动关键路径 E2E、生产静态构建、直接 API 绕过、无授权租户切换及旧路由/旧品牌/Secret 扫描并记录结果。

## 11. 监控、备份、NAS 拉取与灾难恢复

**依赖/前置条件：** 阶段 1–3、7、9 已提供监控、备份和恢复直接依赖的密钥、路由、任务、生命周期和 provider 接口；D58/D59 的完整演练还使用阶段 10 的最终入口。

**完成条件：** 三层监控和 NAS/云盘备份闭环可用；整机丢失后能够在新主机 fail closed 恢复，并按 D58/D59 逐 tenant 审核释放。

**可验证结果：** 备份完整性、保留、告警、tenant-only restore 和新主机 full restore 演练均有可审计证据；新 origin 外部探测成功。

- [ ] 11.1 实现无副作用、无敏感详情、no-store 的 /health/external 与 /health/monitor，以及容器/主机、故障域外云拨测、应用业务健康三层监控。
  - [x] 应用端两个固定 endpoint 已实现独立、非阻塞的并发 lease 与窗口限频预算，在借控制库连接前拒绝 query 参数/超载；external 只做最小 control read 与 host-restore completed/marker 核对，monitor 只检查 worker/evaluator freshness 和 notification-delivery latch，均固定 200/503 body 且不遍历 tenant、不调用 provider。
  - [ ] 仍需在真实腾讯云配置/校验 CVM Agent、至少两个不同 IDC 的故障域外拨测、origin 直连与 Nginx 专用限频，并保存受控故障验证；外部 smoke 继续由 12.13 覆盖。
- [ ] 11.2 实现 current operational signals、worker/evaluator heartbeat、provider/备份异常收敛和腾讯云自定义消息告警/恢复通知；版本化 MonitoringPolicy 与 runbook 存在故障主机之外。
  - [x] 到期 evaluator 每次完整 sweep 返回控制边界后，使用部署注入的版本化 operational policy 在独立控制事务写 `evaluator.heartbeat`；`DurableJobWorker` 同样要求显式心跳 recorder，并只在成功、阻断、review 或 idle 的 `run_once` 完整返回后以数据库时间写 `worker.heartbeat`。未处理的队列/数据库异常不会写绿色心跳，单租户 recovery authority 缺失则保留 skipped 计数但仍证明 evaluator 进程存活。固定 `/health/monitor` 已独立要求 evaluator 与 worker 两个新鲜心跳及 notification-delivery latch 清空。
  - [x] 轻量 freshness evaluator 接受部署显式列出的低基数 signal keys，对每个已初始化信号使用独立短事务和数据库时间推进版本化迟滞/repeat/recovery reducer；缺失信号进入稳定 missing 摘要且不阻断其他信号，重复同一时点不重复写生命周期事件。`notification.delivery` 是事件驱动 latch，配置层明确禁止把它交给周期 freshness 误判空闲健康期。
  - [x] durable queue adapter 使用数据库时间和部署显式的 oldest-wait、failure-lookback、terminal-failure-count 阈值，把已到期 pending 的最老等待与 failed/dead-letter/review 终态窗口分别原子写入两个固定低基数信号；空队列为健康，未来任务和窗口外旧失败不制造假告警，第二个信号失败会回滚同批第一个信号。
  - [ ] 仍需聚合 provider 的真实业务调用信号、把现有 backup/NAS adapter 接入独立进程，并配置腾讯云消息告警/恢复通知、调用周期及故障主机外 runbook。
- [ ] 11.3 建立不能交互登录的备份 SSH 用户、独立 key、root-owned 固定 wrapper、数据库最小备份账号和单实例备份 lease。
- [ ] 11.4 实现 NAS 每小时 pull、受限目录 .partial 临时文件、远端命令/传输/压缩/checksum 全部成功后的原子完成态，以及任务重叠拒绝。
- [x] 11.5 实现 48 个小时、30 个每日、12 个每月成功备份的保留策略；只有新备份验证成功后才能清理旧 artifact。
  - [x] 控制侧以显式时区按 recovery point 选择每小时/每日/每月最新成功代表并取三层并集；固定拒绝非 48/30/12 策略、损坏 catalog、未来时点、重复 identity，以及不是最新已验证成功点的清理 trigger。
  - [x] NAS 侧在与 pull 共享的排他锁内重新校验 trigger 和所有现存候选的 canonical manifest、identity、checksum、size 与普通文件属性，整批预检通过后才按 artifact 完成标记 → manifest 顺序删除并 fsync；中点崩溃留下的 manifest-only orphan 可由同一 plan 幂等收口，缺 manifest、symlink、篡改或竞态变化均 fail closed。真实定时 pull/云盘同步仍分别由 11.4/11.6 承担。
- [ ] 11.6 配置 NAS 仅把 completed artifact、manifest/checksum 和独立永久 tombstone ledger 同步到私有云盘目录；禁止同步 .partial、平台根密钥或其离线副本。
- [ ] 11.7 实现 full、control-only 和 tenant-only restore wrapper、staging 导入、checksum/manifest/ledger/marker 验证和禁止直接导入 production。
- [ ] 11.8 按 D58 为每次 host restore 创建 recovery run，在开放业务前对全部 survivor 安装正交 hold，并失效旧 tenant/platform session、短信 challenge、pending invitation、敏感 intent、未终结 registration attempt 和旧兑换码安全状态。
- [ ] 11.9 恢复新的平台密码、TOTP/恢复码后，仅允许平台逐 tenant 执行 release 或 keep-closed；release 不修改 subscription、D52 suspension 或 D26 deletion，也不复活旧任务、码或 provider operation。
- [ ] 11.10 按 D59 使用一个经审核可安全 release 的 active survivor 完成 route、库存/rental 和外部副作用隔离 smoke；若无此 tenant，则创建绑定 current run 的 DR-only scratch schema/account，验证后先销毁再记录摘要。
- [ ] 11.11 以故障域外 /health/external 首次成功命中新 origin 作为 host recovery completed 的唯一外部完成点；其余 tenant 保持 held 并单独记录 release/keep-closed 时间。
- [ ] 11.12 执行备份损坏、NAS 中断、云盘恢复、永久 tombstone 过滤、tenant-only restore 和全新主机 full restore 演练，并保存耗时、结果和告警通道记录。

## 12. 默认租户迁移工具、项目完成时间与生产规模演练

**依赖/前置条件：** 阶段 0–11 中被迁移工具直接调用的控制库、tenant schema、身份、任务、业务和运维实现已可用；D60 已确认默认租户使用固定 Core plan revision 的一次性 36,500 天 `migration_grant`；D61 的期限和处置任务以及 D63/D64 的简化流程已登记。未被本阶段直接调用的独立盘点或文档工作可以继续并行。

**完成条件：** 默认租户迁移工具及回滚工具已经实现并通过非生产验证；D61 三类旧权威已经轮换/撤销且新身份/修订可用；所有不依赖首次生产规模演练的自动化、隔离、安全、迁移、外部 smoke 和运维测试通过后直接记录 `project_complete_at = T`；不早于 `T + 168h` 的可用窗口完成至少一次生产规模演练及对账、回滚验证。

**可验证结果：** 同一迁移 bundle 可对合成和脱敏代表性快照幂等执行 expand → backfill/verify → application enforce → database/jobs enforce → contract 模拟；实现 commit、image digest、schema heads、migration bundle、D61 收口、D63/D64 的 T/最早时点/实际窗口、生产规模演练耗时、差异和回滚结果均有机器可读记录。

### 12A. 迁移工具实现与非生产验证

- [x] 12.1 D60 已正式确认并写入决策记录与 delta spec：默认租户使用固定 Core plan revision、`member_seats=10` 和一次性 36,500 天 `migration_grant`；不增加期限参数、perpetual 状态或运行时安全豁免。
- [ ] 12.2 实现版本锁定、可 dry-run、可中断续跑且具有稳定 migration idempotency key 的默认租户迁移命令与 manifest；命令明确区分 expand、backfill/verify、application enforce、database/jobs enforce、rollback-before-authoritative-write 和 contract，各阶段输出前置、完成证据、停止条件和不可逆边界，非生产验证不得连接生产写身份或调用真实 provider/打印机。
  - [x] 已实现严格、不可变且不回显受控身份值的 manifest/serde、固定阶段顺序、dry-run/rollback 计划和本地私有 journal 初始化。
  - [x] 已实现 `run-phase` 命令边界、manifest/phase 派生的稳定 execution key、显式 executor 注入、apply completion evidence、响应丢失 replay，以及 advisory lock + CAS + 原子替换的崩溃续跑；dry-run 和未注入 executor 的 apply 均不执行 mutation/provider/打印。
  - [x] 已实现按声明依赖顺序运行的 phase step composition，每个 step 获得 manifest/phase 派生的稳定 key；任一步骤崩溃不会追加 phase evidence，重跑保持相同 key。backfill composition 只在全部 mutation step 完成并通过 collector reconciliation 后返回可持久化结果。
  - [x] backfill/verify 只能用覆盖全部预定义 scope 且通过的 versioned reconciliation policy/report 完成，不能用普通 result digest 绕过；tenant-aware authoritative-write marker 是独立单向 CAS 边界。
  - [x] 已将已决 expand/backfill 切片接入真实 Session phase adapter：verified expand 按只读 source migration preflight → control schema → tenant schema → 原地登记排序，tenant identity 已提交而 control 登记崩溃时可重入；backfill 按默认仓、express type、计划物流、结构化地址、逻辑附件、control integration metadata 顺序使用独立 control/tenant transaction 并产生重放稳定 evidence。完整 builder 必须显式提供与 historical boundary 匹配的 `historical_snapshots` step，不能用同名占位 adapter 绕过。
  - [x] 已实现严格的零历史 `historical_snapshots` adapter：绑定 manifest/database identity/schema generation 后，只在 legacy 出入库运单字段、已发货/归还/完成事实、打印审计以及 Core shipment/attempt/print ledger 全部为零时生成重放稳定的通过证据；任一非零只返回固定 `HISTORICAL_SNAPSHOT_REQUIRES_APPROVED_NONEMPTY_ADAPTER`，不创建凭证 revision、shipment、print job 或 provider 调用。
  - [x] 已实现 application-enforce 实际 adapter：machine evidence 必须绑定 manifest/implementation/bundle 并证明可信 route、身份 namespace、effective gate、legacy surface negative matrix、零生产写身份和零 provider/打印副作用；最终控制事务重新锁定并核对 tenant/route/database identity、schema generation/revision/digest、用途分离账号与 active login state，随后原子写/重放 D60 grant 并把精确 `provisioning/provisional` 发布为 `active/ready`。漂移或证据冲突时 subscription 与发布一起回滚，崩溃重跑产生同一 phase result。
  - [x] 已实现 database/jobs-enforce 与 contract 的 machine-verifier adapters：前者强制绑定 grants 正反矩阵、fleet schema、Web scheduler 不可达、单 durable worker、outbox/provider fencing 与跨 schema 拒绝证据；后者强制绑定 observation window、legacy schema/route-config/recovery-path 负向扫描、历史 provider snapshot 保留，并要求 D61 legacy authority/global writer/生产写身份/provider/打印计数全部为零。两者不自行发现 DSN、改 grants、启动 worker 或触发副作用。
  - [x] 已建立精确五阶段 executor registry；expand/application/database-jobs/contract 必须分别绑定正确 phase 的 ordered executor，backfill 必须是运行完整 reconciliation 的专用 executor，错配或缺少任一阶段无法构造。该 registry 可直接作为现有 `run-phase` CLI 的 Mapping 注入。
  - [x] expand composition 已增加显式 control/tenant infrastructure verifier steps：分别绑定 control/tenant schema head、migration round-trip、metadata-model match、installation marker/database identity observer、control/DML/platform-read grants 和跨 schema 拒绝的 machine digests，并硬性拒绝生产写身份或 provider/打印副作用；只有两步均返回当前 manifest/implementation/bundle evidence 后才进入原地登记 step。
  - [x] 已实现不接受 DSN、环境变量或隐式 Flask database 的显式 Connection Alembic qualification/apply runner：DDL 前只接受位于显式 scratch root 的文件 SQLite，或由调用者显式授权且连接后再次证明当前库名精确为 `inventory_management_test` 的 MySQL 8.0.30+；script directory 必须只有 manifest 指定的唯一 head。qualification 库执行完整 upgrade → downgrade → upgrade，apply 库只允许 baseline/head → head 且绝不 downgrade，两者均要求 ORM metadata 零差异、独立 connection factory、无 caller transaction及不同匿名 target identity（SQLite canonical file；MySQL server UUID + schema）；同一物理库误绑定会拒绝，qualification head 不匹配则在打开 apply 连接前停止。控制库已在两个临时 SQLite 文件上用当前唯一 head `202608220029` 完成真实 round-trip、forward-only apply 与稳定重放，并把观察结果接入 control grants/installation marker 后生成 expand 结果。
  - [x] 已实现完整五阶段 registry 的边界感知命令编排：`run-to-authoritative-boundary` 从 journal 当前阶段连续执行 expand → backfill/verify → application enforce → database/jobs enforce 后必停在 contract 前；authority marker 是另一个显式、带 UTC 时间的单向 CAS，只有 marker 已落盘时 `run-contract` 才可执行。命令启动前强制验证五阶段 executor 齐全，完成态精确重放不重复执行任何 step，CLI 只输出脱敏 phase/result identity。
  - [x] authority marker 时间不变量已收紧：纯 journal reducer 要求 `enabled_at` 不早于 database/jobs-enforce completion evidence；runner 对首次写入另要求该 UTC 时间不晚于当前 migration clock。未来时间、回填到阶段完成之前、不同时间重放均拒绝，历史 exact replay 保持幂等。
  - [x] CLI 已区分离线文档失败与执行失败：manifest/serde/初始化输入错误固定返回 `MIGRATION_DOCUMENT_REJECTED`；apply、authority marker、contract 和 rollback 执行错误固定返回 `MIGRATION_EXECUTION_REJECTED`。缺少 executor 或 executor 抛出含连接信息的意外异常时不输出异常文本/traceback、不改写 journal，且 CLI 不从环境或应用配置发现 DSN。
  - [x] 已在四个一次性 MySQL 8.0.46 物理实例组合完整 expand：control 空库 qualification round-trip 与独立 forward apply、tenant SaaS segment qualification/forward apply、两侧 ORM metadata 零差异、installation marker、tenant identity 建立/精确重放、control tenant/Admin/membership/identity/provisional route 原地登记、tenant DML/platform-read 精确 grants 与跨 schema 拒绝、journal completion/replay 均真实通过；完成后只前进到 `backfill_verify`，不调用 provider/打印。该用例的 control-account grant digest 仍为 deterministic test evidence，不声称已验证真实 control runtime grant。
  - [x] 已实现版本锁定的只读 source baseline observer 和 mandatory verified-expand 首步：只接受 caller-bound MariaDB 10.11/MySQL 8.0.30+ connection、当前精确 schema、无 active role、无 `GRANT OPTION` 且只有目标 schema `SELECT/SHOW VIEW` 的账号；在一致性只读快照内只采集 schema metadata 与逐表 `COUNT(*)`，二次 schema inventory 漂移即拒绝，证据绑定 schema/baseline/server/schema digest/row-count digest/source snapshot digest，不读取或输出业务字段。manifest 不匹配会在任何 control/tenant expand verifier 前停止。
  - [x] source baseline/preflight evidence 已抽成控制层可复用的严格版本化文档，并接入离线 `create-manifest-from-source-baseline` 与 `create-manifest-from-source-preflight` CLI：manifest template 不再接受人工填写 `source_snapshot_digest`，而是从 exact-key evidence 注入后重新核对 schema/baseline/digest；相同 evidence、root-key identity 和受控输入稳定重放同一 manifest，额外字段、版本、schema/baseline 漂移均只返回固定文档拒绝。命令不接受或读取 DSN、应用配置、provider/打印配置。
  - [x] 已把固定迁移 bundle 变成 manifest-bound machine evidence：由仓库固定选择器覆盖 188 个 migration/runtime/model/harness/test 文件，逐文件绑定 canonical path、size 与 SHA-256，并从 Alembic script directory 自动要求唯一 control/tenant heads；source manifest 模板不再接受人工填写 heads 或 `migration_bundle_digest`，而是由 exact-key bundle evidence 注入。verified expand 在 source preflight 通过后、任何 control/tenant DDL verifier 之前核对当前 bundle；文件、head、字段或 digest 漂移均 fail closed。离线 CLI 可创建/验证 evidence 且不读取 DSN、provider 或打印配置。
  - [x] 同一只读一致性快照内已增加历史边界分类：在验证 schema/count baseline 的同时，按兼容的 legacy/current lifecycle 列固定统计历史生命周期、tracking、打印审计和 Core shipment/attempt/print 六类事实；缺列/未知 shape 拒绝。verified expand 第一阶段绑定 baseline 与 boundary 的组合 digest；backfill builder 对空历史只接受正式 zero-history verifier，对非空历史只接受 boundary digest 和正 approval revision 都匹配的获批 adapter。
  - [x] 已用 `inventory_saas_test_platform_read` 在生产实例的 `inventory_management_test` 真实观察并立即重放：MariaDB 10.11、9 张表、总计 6,264 行，两次得到相同 source snapshot digest `86a529d2f7825c5f26f11bf36916fd4de56489d7c9103fb26c82babb38b49824`；历史边界稳定判定为 `requires_approved_nonempty_adapter`，包含 1,828 条 lifecycle 历史和 1,807 条 tracking 历史，boundary digest 为 `7872e738642beba9f7f2e8c9ccdc2160204af5d46d02b9c25c55774cfdf0f575`。opt-in 集成测试 `1 passed`，无 DML/DDL、锁定读、provider 或打印。
  - [x] D68 非空历史 adapter 已实现：旧 lifecycle、出入库运单号和打印发生事实写入两张独立 `legacy_unattributed` 表，表与 DTO 均无 integration/account/binding/credential revision/provider order/printer/provider task 字段；adapter 绑定 manifest、database identity、schema generation、六类 boundary counts、稳定 source UUID/digest，完全一致重跑为 no-op，源内容漂移或既有 Core shipment/attempt/print ledger 非零即失败。真实 MariaDB 聚焦矩阵 `3 passed in 183.25s`，并证明 Core tracking、provider attempt、取消和打印规划均拒绝 legacy snapshot ID。
  - [ ] 仍需把获准代表性快照恢复到 `inventory_management_test`，重新观察并生成绑定新 source identity 的 manifest，再执行完整命令与统一 reconciliation。上述 9 表/6,264 行 baseline 与 digest 只保留为历史只读证据，不能靠旧 digest、空库或重建结构绕过；D68 已消除产品决策阻塞，但没有把旧 snapshot 绑定到任何后来新验证的凭证。
- [ ] 12.3 实现原地登记工具：新建或迁移 `inventory_control`，为现有公司生成不可变 tenant/database UUID，在原业务 schema 写入唯一 `database_identity` 并登记可信 route；不得复制整库、重编号主键、重命名 schema 或给每张业务表添加 `tenant_id`。默认租户显示名称和首位 Admin 手机号必须由受控输入显式提供，拒绝空值、占位值、非法/歧义手机号和同 idempotency key 下不一致的重跑输入，且日志不得回显敏感值。
  - [x] 已实现已路由 tenant transaction 内唯一 `database_identity` 的创建/精确重放，tenant/database UUID、schema generation 或既有单行身份不一致时 fail closed；服务不选择/复制/重命名数据库、不修改业务主键且不接收 DSN、密码或 provider secret。
  - [x] 已实现 control transaction 内 tenant、首位未验证 Admin、migration Admin membership、route 和 control-side identity record 的 manifest-bound 幂等登记；显示名称/手机号先经过受控输入 commitment 校验，冲突或半成品既有身份拒绝，不静默补齐或替换。route 只登记为 `provisional`，expand 不提前发布业务路由。
  - [x] 已实现原地登记 expand step：先在显式 tenant transaction 创建/重放 `database_identity`，再在独立 control transaction 登记控制面；跨库中点崩溃后以相同 manifest 重跑会复用 tenant identity 并完成 control 登记，phase evidence 仅在全部步骤完成后记录。
  - [x] 已把 application-enforce 后的发布接入实际控制事务：只有 backfill journal、隔离 runtime evidence、D60 grant、route/database identity 和 post-DDL schema facts全匹配时才原子 `provisional → ready`、`provisioning → active`；精确重放不重复加时或提升 row version。
  - [x] 已提供 source/control/tenant expand verifier steps 与组合 builder，固定顺序为 source migration preflight evidence → control schema evidence → tenant schema/database identity/grants evidence → 原地登记；baseline/history boundary mismatch 在任何 DDL verifier 前停止，后两类 evidence 都绑定 exact schema head 和 migration bundle，错 head、跨 bundle、生产写身份或真实副作用不能产生 step completion。
  - [x] control verifier 已接入显式连接的真实 Alembic qualification/apply runner，在独立临时控制库分别完成全 round-trip 与 forward-only apply，验证唯一 current head `202608220029` 和 ORM metadata 零差异后，再绑定 control grant/installation observer digest；旧 `202608220024` head 会在 DDL 前因不再是 script 唯一 head 而拒绝。
  - [x] 已实现 MySQL 8 用途分离账号的固定 SQL grant observer、只读跨 schema 拒绝探针及 tenant 双账号 matrix verifier：control app/tenant DML 只接受目标 schema 上精确 `SELECT/INSERT/UPDATE/DELETE`，platform-read 只接受精确 `SELECT/SHOW VIEW`；任一额外 global/table/column/routine grant、GRANT OPTION、额外/缺失 privilege、current 或 inactive applicable role、账号/当前 schema 漂移均拒绝。MySQL 8 不提供 `INFORMATION_SCHEMA.ROUTINE_PRIVILEGES`，因此 observer 组合四类 privilege inventory 与 exact `SHOW GRANTS` allowlist，同时只允许固有 global `USAGE`。matrix 强制 DML/platform-read 使用不同用户名和不同 bound connection factory，并要求两者都先证明本 schema `alembic_version` 可读，再执行限定 token 的 foreign-schema `SELECT ... LIMIT 0`；只接受 MySQL 1044/1142，查询成功、表不存在或连接异常均不能生成双账号 denial 结果。observer 只接受 caller-bound account connection，不接收密码/DSN，并已在一次性 MySQL 8.0.46 实例真实通过双账号正反矩阵。
  - [x] 已修正 tenant expand 的实际依赖顺序：qualified verifier 在 forward-only tenant DDL 后用现有 registration service 在独立事务写入/精确重放唯一 `database_identity`，将 manifest/tenant/database/schema generation/稳定 created-at 绑定为 observation digest，再运行 DML/platform-read 双账号 matrix；后续 in-place registration step 只重放同一 identity 后登记 control，不再尝试观察尚未创建的行。control installation observer 则只接受 expected fingerprint 对应的唯一未退休 installation、canonical UUID、正 row version 和稳定 created-at；零行、两个 live installation 或 fingerprint 漂移均无 expand evidence。
  - [x] tenant Alembic 环境已支持 caller-bound Connection + explicit target metadata，不再要求 Flask app context 或把连接还原为含凭证 URL；当前 ORM 的 devices/inspection/rentals 四个仓库外键补齐了 migration 已使用的显式名称。自动化在两个临时 SQLite 文件以 current ORM head 建库并 stamp 唯一 tenant head `20260823_xianyu_sync_state`，经受测 downgrade 生成 `20260807_damage_notes` baseline，随后实际完成 scratch baseline→head→baseline→head 与 apply baseline→head，两个目标均通过 metadata 零差异和外键名称核对。该结果只证明 SaaS segment；仓库最早 Alembic revision 依赖 pre-Alembic `devices` 等表，不能据此声称完整历史链可从空库重建。
  - [x] 已增加完整 expand 组合集成测试：四个独立临时 SQLite 文件分别承担 control/tenant qualification/apply；真实执行 control 空库 round-trip/head apply、唯一 installation marker 观察、tenant SaaS segment round-trip/forward apply、singleton database identity 建立/精确重放、首位 Admin/user/membership/control identity/provisional route 登记和 journal CAS。完成后 journal 只前进到 `backfill_verify`，tenant/control 状态分别保持唯一 identity 与 `provisioning/provisional`，响应重放返回原 phase evidence 且不重复执行；只有 MySQL account grants/cross-schema 使用 deterministic matrix。
  - [x] 四实例 MySQL 8.0.46 完整 expand 已把 control/tenant qualification、独立 forward apply、metadata 零差异、预置 control installation、tenant identity 建立/重放、control 原地登记、tenant 双账号 grant/跨 schema observer 和 journal replay 组合为同一自动化用例；`1 passed in 30.58s`，临时实例随后全部删除。
  - [ ] 实际 source baseline 已通过测试库专用只读账号装载并稳定重放，且已有无需手抄 digest 的 manifest CLI；仍需固定该次迁移的受控显示名称/首位 Admin/UUID/bundle identity 后生成实际 manifest 并运行完整命令。由 current head downgrade 得到的结构 fixture 仍不能被误称为完整历史空库重建；当前非空漂移 schema 必须选择获批的非空历史迁移路径，或在获得单独授权后才可重建测试库，不能自行写入。
- [ ] 12.4 实现按默认仓/设备位置、结构化地址、逻辑附件 unit/request/link/event、计划物流字段、integration/credential revision、shipment/print snapshot 的幂等 backfill 和反向核对；canonical express-type 的历史 NULL 只回填为 `2`，存量 `6`/其他非法值生成逐状态报告并保持 provider fail-closed，未经明确安全修正不得静默映射为 `263` 或提交顺丰。迁移 manifest 必须拒绝把 D61 暴露旧值仅加密成新 revision，只接受已轮换并重新验证的 provider revision 引用。
  - [x] 已实现默认仓/设备位置、计划物流字段和 canonical express-type 幂等 tenant transaction backfill；计划物流使用显式完整 main/child 计划并共享 D33 计算，任一部分既有值、源事实变化或 child 漏列/多列整批回滚；express-type manifest 固定只允许 `NULL → 2`，逐状态报告保留 `6`/unsupported 并阻止 provider-ready 结论，服务均不调用 provider。
  - [x] 已实现显式 legacy-device→logical-unit 计划：唯一 legacy source 创建隐藏 unit，所有未终结附件 child rental 必须完整 upsert request，可靠映射才创建带 planned window 的 link；shipped/returned 无可靠 link 失败，可靠在外单元设置 main-rental holder 并追加稳定 `created/linked/dispatched` migration events，不可靠单元保持 maintenance。重跑不重复 unit/request/link/event。
  - [x] 已实现 SF/快麦/闲鱼 metadata-only control backfill：稳定创建 `unconfigured` integration 且 config 必须严格为空，入口不接受 credential，整批原子，永不创建 secret revision/current pointer/claim 或 provider 调用；D61 legacy 值无法通过改键名包装迁入。
  - [x] 已实现显式逐行结构化收货地址回填：迁移计划只保存旧 `destination` 和目标地址的不可逆 commitment，不从自由文本猜测省/市/区；源值、父子关系、半回填或不一致目标发生变化时整批回滚，精确重跑不改写，兼容期保留旧展示字段。
  - [x] 已实现上述已决 backfill 的 phase adapter prefix：每个切片使用新建的已绑定 Session 与 caller-owned transaction，失败只回滚当前步骤且不产生 phase completion；步骤提交后进程崩溃会以相同稳定输入重放，warehouse/integration 的 evidence 排除 created/replayed 等瞬时差异，metadata adapter 发现任何 credential revision pointer 即拒绝。
  - [x] 对源快照确实不存在任何 shipping/print 历史的情况，已有独立零历史 verifier：它要求唯一 tenant database identity 与 manifest/schema generation 精确一致，并同时证明 legacy 跟踪字段、历史生命周期/打印审计和全部 Core shipment/attempt/print ledger 为零；该路径仅证明“无需创建历史行”，不会把旧值或后来的 current revision 绑定为历史凭证。
  - [x] 已实现非空历史前置分类与 adapter 选择约束：真实测试快照的 1,828 条 lifecycle/1,807 条 tracking 历史被稳定分类为必须使用获批非空 adapter；普通同名 step、zero-history verifier 或 boundary digest/approval revision 不匹配均在组合阶段拒绝，不会借此创建 credential revision、Core shipment 或 print job。
  - [x] D68 产品语义与非空 shipment/print snapshot 已落地：每个租赁/打印审计使用 database UUID 派生稳定 source UUID，保留租户内展示所需状态、运单号、时间与打印发生事实；独立只读查询 DTO 固定 `actionable=false`/空动作集，旧记录不引用新旧凭证且不能顺丰查询、PDF 获取、重打、取消或重试。Core 原生新业务仍只接受 `historical=false` 且已验证的 exact credential revisions。
  - [ ] 仍需在重新恢复的代表性快照上运行该非空 adapter、核对实际分类总量/孤儿/源漂移/重放，并完成统一反向 reconciliation；不得把后来新验证的 credential revision 回填给 `legacy_unattributed` 历史。
- [x] 12.5 实现 D60 默认租户初始 subscription：最终控制事务以数据库当前时间加精确 36,500×24 小时，写入固定 plan revision/entitlement 和唯一不可变 `migration_grant` event；唯一性绑定 tenant/database/initial-baseline/idempotency key，响应丢失或重跑只返回原结果，不得再次加时。实现由 manifest/journal 绑定 writer 在 backfill reconciliation 已记录后进入调用方拥有的最终控制事务，固定使用 manifest 的 Core plan revision 且不暴露期限参数；隔离控制库测试覆盖精确 `3,153,600,000` 秒、响应丢失重放、不一致 manifest/route/plan 拒绝和零重复 subscription/event。
- [ ] 12.6 实现控制库、默认 tenant schema 和迁移报告的自动对账，覆盖逐表行数、金额、设备/租赁/附件关联、孤儿数据、历史运单、凭证 revision、默认仓、legacy 双重计数、schema generation/digest 和预先定义阈值；任一未知、漂移或非零异常没有显式 disposition 时，迁移命令返回失败且不得继续写入。
  - [x] 已实现 versioned reconciliation policy/report、全部 12 类 scope 的精确覆盖要求、值类型/阈值/disposition 规则、unknown/undispositioned/schema/legacy fail-closed，以及与 manifest/source snapshot/policy/report digest 绑定的 backfill completion 边界。
  - [x] 已实现 exact-key collector orchestration 与 SQLAlchemy scalar read adapter；collector 按 policy 顺序运行，只接受非锁定结构化 SELECT，拒绝带 pending writes 的 Session，单值/类型/SQL 异常均固定失败且不回显观测值。
  - [x] 已把 fleet migration 的可信 schema inventory observer 接入 generation/digest collector set；两个 policy key 共享一次 post-DDL 观察，manifest/tenant/database/revision 不一致或 observer 失败均以固定错误 fail closed。
  - [x] 已实现 versioned 默认租户 policy fixture 和具体 SQL registry：固定采集设备行数/仓库关联、租赁金额/设备关联、逻辑附件 link、孤儿关系、历史 waybill、租户 credential revision 和默认仓；9 个 SQL collector 必须与 schema generation/digest 及独立 legacy-authority collector 精确组成全部 12 类 key，缺失/重复在查询前拒绝。
  - [x] `legacy.double_count` 已使用正式的 manifest/source/implementation/bundle-bound machine evidence collector：四个独立负向矩阵分别证明旧 quantity、child-rental、global-provider 和 shipment-writer 权威计数为零；任一非零计数、候选 identity 漂移、错误 reconciliation scope 或可豁免 policy 均固定拒绝，collector 不接收 DSN/provider/打印 adapter，也不把数据库行存在误当成旧 reader 已停用。
  - [x] 按 D64 保持普通检查流程：完整 backfill executor 直接运行同一 policy/collector runner，只有 12 类检查全部通过才由既有 migration journal 推进阶段；不再要求候选签字、独立 receipt/evidence artifact 或额外 hard gate，避免重复持久化和两套恢复语义。
  - [x] 已在两个物理隔离的一次性 MySQL 8.0.46 实例组合正式 resolved adapters：真实提交默认仓/设备归属、`NULL → 2`、计划物流、结构化地址和 legacy-device logical unit 后，在 integration metadata 前注入进程崩溃，确认已提交 tenant facts 存在且 control integration 仍为零；相同 phase key 从头续跑会幂等复用前五步、补齐三类 metadata-only integration 和 zero-history verifier，再由九个 SQL collector、真实 v3 schema inventory、四类旧权威负向 evidence 组成全部 12 类 reconciliation。随后再次完整重放，result/report digest 一致且 credential revision 保持零，`1 passed` 后实例删除。该合成空历史 run 不替代非空代表性快照。
  - [ ] 仍需在版本锁定的实际非空代表性隔离快照上组合相同 policy、SQL registry、schema observer 与 legacy-authority observer 并运行，记录普通测试输出；当前合成 MySQL 空历史 fixture 不能代替已绑定 MariaDB 源数据的迁移后验证。
- [ ] 12.7 在合成 fixture 和隔离的脱敏代表性快照上反复执行迁移、幂等重跑、每阶段崩溃续跑、预权威写回滚及 tenant-aware forward-fix 验证；针对 MariaDB 10.11/`utf8mb3` 源到 Core MySQL 8 目标验证 DDL、数据类型、SQL mode、timezone、collation/`utf8mb4` 转换、行锁/`SKIP LOCKED`、advisory lock、dump/restore 和 connector 行为，不把该验证称为首次生产规模演练。若使用本机可达的当前生产库，只允许经 grants 证明的目标 schema `SELECT/SHOW VIEW` 和单条非锁定只读观察；所有写入、迁移、fixture reset 与破坏性注入必须显式设置 `ALLOW_REAL_TEST_DATABASE=true`，且只允许名称精确为 `inventory_management_test` 的库，并先观察其可能漂移的实际 schema 后再按用例 fail closed、显式重建或迁移。
  - [x] MariaDB 10.11 只读源基线子矩阵已完成：精确只读 grants、无 active role、版本/profile、`utf8mb3` schema metadata、逐表行数、同快照历史边界、两次 digest 稳定重放和 broad-grant/schema-drift/未知 lifecycle shape fail-closed 均有自动化；真实 opt-in 用例只连接 `inventory_management_test` 并在 read-only consistent snapshot 后 rollback/close。
  - [x] resolved backfill 与完整 reconciliation 的合成 MySQL 8 子矩阵已完成前五步提交后崩溃、相同 phase key 续跑和第二次全量幂等重放；实跑修正 MySQL 8.0.46 `INFORMATION_SCHEMA.PARTITIONS` 已无 `ENGINE` 且未分区表 `NODEGROUP=''` 的 schema observer 兼容性，并把 schema inventory identity 升为 v3；金额 collector 对聚合结果最终 `CAST AS BIGINT`，避免 MySQL `SUM(BIGINT)` 返回 Decimal 破坏跨数据库类型契约。相关 observer/fleet 单元矩阵 `72 passed`。
  - [x] MariaDB→MySQL 合成可移植性子矩阵已在一次性 MariaDB 10.11 与 MySQL 8.0.46 实例真实运行：由源实例内同版本 `mariadb-dump` 使用精确只读账号和 single-transaction 导出固定三表 `utf8mb3` fixture，只移除 MariaDB 的精确 sandbox 兼容头并拒绝建库/切库/grant/文件 SQL、routine、trigger、definer 或其他 MariaDB 专用指令；目标库级账号恢复后逐库逐表转换为 `utf8mb4_0900_ai_ci`。中文、金额、微秒时间、外键、索引和行数均验证保持，`1 passed` 后两个容器及临时凭证删除；未连接生产实例。
  - [ ] 仍需完成实际非空数据 backfill、其阶段崩溃续跑、锁/connector 和代表性对账子矩阵；本次 source baseline 与三表合成 dump/restore 只证明输入身份绑定和基础跨版本可移植性，不证明生产形状的数据迁移完成。
- [ ] 12.8 验证迁移/回滚 bundle、manifest、固定输入 schema、对账器和非生产测试均版本锁定且可从空环境复现；确认测试 harness 对生产 URL、非精确测试库名、越权 grants、锁定/文件 SQL 和 schema 漂移均 fail closed，没有生产数据库 mutation、真实短信/SF/快麦/闲鱼提交或物理打印，所有已知数据异常均已修正或有 fail-closed disposition。
  - [x] superseding current-bundle evidence：固定选择器现覆盖 191 文件，唯一 heads 为 control `202608220029`、tenant `20260823_shipping_contract`；当前 tenant offline migration/bundle targeted `14 passed`。此前 `175 passed` default-migration 回归和四个 tmpfs MySQL 8 物理目标上的完整 expand `1 passed in 25.19s` 只保留为历史结果，head/bundle 改变后必须重跑才能形成当前完成证据。所有最近真实写测试只使用临时凭证和名称精确为 `inventory_management_test` 的一次性 schema，容器已删除，未连接生产实例、provider 或打印机。
  - [x] D66 superseding 测试基础设施：global-DBA 双 opt-in、精确库名复核和 SQL statement guard 为 `75 passed`；MariaDB 10.11 的现有 `inventory_management_test` 上完成 84 个不重复真实数据库用例（附件/运单并发 `7 passed`、仓库/甘特/接力/API `76 passed`、tenant baseline→head→baseline→head 与 ORM metadata 零差异 `1 passed`，清理修正后迁移用例又精确重跑 `1 passed`）。本地完整回归为 `2876 passed, 16 skipped`；没有连接生产业务 schema、provider 或打印机。后续真实数据库批次一律通过 `make test-real-db` 串行复用该现有测试库，不再建立临时实例或测试账号；旧多实例结果仅保留为历史证据。
  - [x] D66 统一入口现把 control 空基线→head→base→head 与 ORM metadata 零差异加入同一个 `inventory_management_test` migration 文件；五阶段默认迁移 adapter 也由唯一 registry builder 按 expand→backfill/verify→application enforce→database/jobs enforce→contract 组合，避免不同宿主重复拼装或漏阶段。相关本地 migration/registry 回归为 `136 passed`。2026-08-23 的首次新增真实库重跑在建立连接前因 `192.168.50.132:33601` 拒绝连接而停止，未执行 SQL；故新增 control round-trip 仍须待该实例恢复后通过 `make test-real-db` 验证，不能计入上条 84 个已通过用例。
  - [x] D66 的 metadata-rebuild 已按获准测试语义替换并在 teardown 清理 `inventory_management_test` 中与当前应用 metadata 同名的旧表；迁移用例另清理 `alembic_version`，最终只读核对 `remaining_table_count=0`。此前 9 表/6,264 行 source snapshot digest 只保留为历史只读证据，不再描述测试库当前内容。需要完成 12.4/12.6 的非空代表性迁移时，必须先把获准快照重新恢复到同一测试库并形成新的 source identity，不能复用旧 digest 或从生产业务 schema 写回。
  - [x] D67 superseding 当前真实库证据：连接恢复后，统一 `make test-real-db` 在现有 `inventory_management_test` 一次通过 `144 passed in 1359.74s`。其中 tenant `baseline→head→baseline→head`、control `base→head→base→head` 均通过 ORM metadata 零差异；booking/Gantt 固定 SQL、完整仓库/附件/fake-SF、10 个并发、73 个接力/API 和 2 个批量 intent 同批通过。共享模块 metadata lifecycle 将原本 38 分钟仍未完成的 73-case 子批缩短为 `211.01s`；MariaDB 外键还暴露并修正了测试中无效的 `source_relay_case_id=999`，现使用真实 case 并验证其阻止删除后再显式解除。未写生产业务 schema，未调用真实 provider/打印。
  - [ ] 仍需在固定实现 commit/image digest 和干净环境中复现完整 migration/rollback/代表性非空 fixture 链，并补齐实际非空历史 adapter、已知异常 disposition、回滚与全矩阵输出；当前 machine bundle 与 empty-history/expand 子矩阵不能代替这些完成条件。

### 12B. D61 收口、必要测试与项目完成时间

- [ ] 12.9 关闭 D61：轮换或撤销旧广域数据库账号、默认租户旧顺丰凭证和旧快麦凭证，建立并验证用途分离的最小权限数据库身份及新的加密 provider revisions；刷新远端/历史/镜像/缓存/日志扫描、数据库公网负向探测、grants、provider capability、异常/费用/额度和非复用记录。任一旧值仍具权威、仅被重新加密、补偿控制失败或风险接受过期时，本项不得勾选。
- [ ] 12.10 运行身份与隔离矩阵：双租户 route/grants/engine cache/任务/文件/日志/搜索/导出/provider/平台 SELECT-only 正反测试，以及平台/租户 namespace、session 撤销、CSRF、RBAC、短信限流、D48、D55、D57、TOTP/恢复码防重放和根密钥用途隔离；证明运行代码、生产配置和恢复 inventory 均不读取通用 `SECRET_KEY`/`API_KEY`，旧签名、Cookie 和 API header 无权威。
- [ ] 12.11 运行业务、状态机与性能矩阵：邀请/10 席/注册/兑换码/D53/D54/到期/暂停/删除/recovery hold 并发，默认仓/调仓/逻辑附件/接力/SF claim/运单/两联打印/闲鱼/快麦故障注入，以及 booking/gantt 的 HTTP、SQL、连接、响应体、10 倍数据量和 mutation 后至多一次刷新约束。
- [ ] 12.12 运行迁移与运维矩阵：fleet migration 幂等/schema drift、默认 tenant backfill、D60 grant 精确时长与唯一性、预权威写旧应用回滚、tenant-aware forward-fix、备份/tombstone/tenant-only 与 full restore；验证 Core 未引入 Redis、tenant API key、在线支付、业务对象存储、托管 MySQL、KMS、Managed Prometheus/Grafana 或其他未确认能力，并运行后端/前端/移动端全量测试与构建、OpenSpec target/all strict validation、Secret/route/config/bundle 扫描和 `git diff --check`。
- [ ] 12.13 运行外部 readiness smoke：验证真实腾讯云短信受控号码送达、顺丰 capability 与新 revision、三层监控及告警恢复、NAS 拉取/云盘、两故障域根密钥恢复和 off-host restore；所有调用使用受控测试对象并核对费用、额度、日志脱敏和零非预期业务副作用，失败项修正后重跑。
- [ ] 12.14 在 12.2–12.13 及其直接依赖实现和必要验证全部完成、D61 保持关闭且无未解决 P0/P1 后，直接记录 `project_complete_at = T`、实现 commit、image digest、control/tenant schema heads、migration bundle 和运行配置 identity，并计算 `earliest_rehearsal_at = T + 168h`；这只是可重算的时间记录。演练前任一实现、schema、migration bundle 或运行配置变化时，重跑受影响任务并以变化后的完成时点更新 T。

### 12C. 等待窗口与首次生产规模演练

- [ ] 12.15 选择不早于 `earliest_rehearsal_at` 的首个可用运维窗口；保存 UTC/Asia-Shanghai 时间、`lead_seconds >= 604800`、参与人、生产写/provider/打印隔离方案、脱敏快照 identity、回滚触发器和受限记录位置。错过最早时点只顺延到下一可用窗口，不延长 D61。
- [ ] 12.16 在 12.15 的窗口使用脱敏生产规模快照和生产等价 MySQL 8/Nginx/worker 配置执行完整 expand → backfill/verify → application enforce → database/jobs enforce → contract 模拟；保存每阶段输入版本、开始/结束、耗时、资源峰值、数据差异、失败点和 provider/打印零真实副作用证明，并执行预权威写旧应用回滚与权威写后 tenant-aware/forward-fix 演练。
- [ ] 12.17 对演练中的 MariaDB→MySQL、数据异常、隔离、性能、回滚或恢复失败执行 fail-closed 处置并重跑。若修正改变实现 commit、image、schema、migration bundle 或运行配置，则回到受影响的 12.2–12.14，重跑必要测试、更新 `project_complete_at = T` 并从新 T 重新等待完整 168 小时；仅重建相同 identity 的快照或重跑相同实现不更新 T。不得缩小 fixture、忽略差异或复用失效记录。
- [ ] 12.18 验证至少一次当前 T 对应的 12.16 run 对行数、金额、关系、schema、凭证 revision、D60 grant、性能、回滚和恢复全部达到预先定义阈值，D61 保持关闭，所有受限 artifacts checksum 可取；保存结果后直接进入通知和生产切换准备，不增加独立流程。

## 13. 通知、生产切换、48 小时观察与 contract

**依赖/前置条件：** 12.18 的生产规模演练验证完成；生产迁移使用与当前 T 和已记录演练相同的实现 identity、迁移 bundle 和配置边界。若这些输入变化，则先按 12.17 更新 T、重跑受影响验证并重新等待 168 小时。

**完成条件：** 切换前 readiness 复核和使用者通知完成；现有业务 schema 原地登记为默认 tenant database，唯一 D60 grant、全部 backfill 和对账通过；tenant-aware 写入切换后连续观察至少 48 小时并完成 contract，且没有恢复旧全局 writer、凭证或副作用路径。

**可验证结果：** 最终外部 readiness、通知、维护时间盒、生产迁移、权威写入边界、回滚判定、48 小时观察和 contract 删除均引用同一 release/run identity，并有机器可读记录。

### 13A. 切换前复核与通知

- [ ] 13.1 刷新并确认真实腾讯云短信资质/签名/模板/受控号码送达、顺丰 capability 与新 revision、三层监控所有 P1/P2/恢复渠道、NAS 拉取/云盘/恢复点、两故障域根密钥恢复、永久 tombstone 和 off-host full restore 结果；重新验证 D61 三类旧权威仍已撤销、Xianyu 条件式扫描仍成立、数据库公网探测失败且运行/备份/provisioning grants 最小化。
- [ ] 13.2 固定默认租户显示名称、首位 Admin 手机号、迁移 idempotency key、source/target inventory、实现 commit/image/schema/migration identity、维护窗口和操作者；至少提前 24 小时通知当前使用者并预留连续 2 小时，发布维护页、停写/停任务/停 provider、30/60 分钟判定和 tenant-aware write boundary 的逐步 runbook 与回滚负责人。
- [ ] 13.3 在任何生产 mutation 前核对 12.14 的 T、`lead_seconds >= 604800`、12.18 演练 identity、D60/D61 状态、值班联系人和 runbook，重跑快速自动化、隔离、迁移 dry-run、API contract、OpenSpec strict validation 和 artifact 扫描；发现实现或配置变化时按 12.17 返回、更新 T 并重新计时，未变化且检查通过则按已通知窗口直接切换。

### 13B. 生产切换

- [ ] 13.4 进入已通知的维护窗口后展示维护页并原子拒绝旧应用业务写入，停止旧 Web scheduler、新 worker 领取和顺丰/闲鱼/快麦 provider 提交，等待或隔离在途 operation；记录停写时点、源库只读边界和第三方副作用基线，未完成隔离时不得迁移。
- [ ] 13.5 使用 13.2 固定输入和已演练 bundle 原地创建/迁移 `inventory_control`、登记默认 tenant/database identity、执行 ordered backfill、创建 D60 唯一 `migration_grant` 并完成控制库/tenant schema/迁移报告对账；不得复制整库、重编号主键、重新引入旧 provider 值或把 legacy 广域账号登记为 Core route。
- [ ] 13.6 在 tenant-aware 写入开放前完成 schema/identity/route/grants、行数/金额/关系、登录/RBAC、默认仓、租赁/甘特、发货/打印、任务/outbox 和 provider 零意外提交 smoke。目标业务停写不超过 30 分钟；从维护开始满 60 分钟仍未全部通过且尚未开放 tenant-aware 写入时，必须执行已演练旧应用回滚并验证恢复，不能继续赌完成。
- [ ] 13.7 13.6 的检查全部通过后记录 `tenant_aware_writes_enabled_at`，只开放已验证的 tenant-aware Web/worker/provider route 并撤销旧 writer/scheduler 的运行资格；从该时点起旧单租户应用不再是合法回滚目标，只允许兼容的 tenant-aware 版本或 forward-fix。
- [ ] 13.8 验证首个 tenant-aware 登录及核心业务 smoke 成功，D60 plan/entitlement/数据库时间/36,500 天/唯一 event 与幂等查询一致，worker/provider 无重复提交，监控和备份 freshness 正常；任一失败按 13.6/13.7 的权威写边界选择旧应用回滚或 tenant-aware forward-fix，并记录处置结果。

### 13C. 48 小时观察与 contract

- [ ] 13.9 从 `tenant_aware_writes_enabled_at` 起连续观察至少 48 小时，持续核对租户隔离、数据库 grants/连接、session/RBAC、任务 lease/outbox、provider operation、行数/金额/关联差异、监控告警和备份；故障与修正均记录完整回归结果，不得缩短或重置观察口径掩盖故障。
- [ ] 13.10 对观察期内故障只使用兼容 tenant-aware rollback 或 forward-fix；暂停 provider、隔离任务或保持维护页时记录开始/结束、影响、数据/副作用对账和恢复判定。任何 schema 或迁移 invariant 改变均重跑相应迁移、隔离和 API contract 验证，不得重新启用旧全局 writer、D61 旧凭证或 `/external-api`。
- [ ] 13.11 连续 48 小时观察及核对完成后执行 contract：删除旧字段、全局 provider 配置与账号、旧数据库账号、兼容路由、旧 scheduler、迁移开关、OCR/合同/独立发货单和 legacy accessory 双重计数来源；证明旧 `SECRET_KEY`/`API_KEY`、旧认证 header、旧配置和恢复路径不可达。禁止删除审计、历史 credential/shipment/print 快照、migration/rollback/recovery evidence 或永久 tombstone。
- [ ] 13.12 汇总生产迁移报告、维护时间盒、权威写边界、D60 唯一 grant、D61 最终撤销、D63/D64 的 T/最早时点/实际演练窗口、回滚判定、48 小时观察和 contract 负向扫描；所有任务均真实完成后记录最终部署结果并进入 OpenSpec 归档流程。

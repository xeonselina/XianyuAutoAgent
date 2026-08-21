# SaaS 转型设计：生命周期与性能

> 返回：[总体设计索引](../design.md)

## 11. Plans, Subscriptions and Entitlements

### 11.1 Model

`plans.entitlements_json` 表达功能和已批准的额度：

- features: 闲鱼同步、批量发货、接力、优化排程、高级统计等。
- limits: Core 当前只支持一个明确版本的 entitlement schema；所有 active 或仍被 subscription、未终结兑换码/注册流程引用的 plan，必须恰好提供 JSON integer `member_seats = 10`，其用量定义为“满足 D51 谓词的有效 membership + 未过期 pending invitation”。缺少 schema version、`limits` 或 `member_seats`，version 不受支持，值为 boolean/string/null/非 10 整数，或出现 `active_devices`、`monthly_rentals`、`integration_accounts` 及其他未知 limit key 时，任何 plan 写入、启动/readiness、migration 与运行时解析均 fail closed；`active=false` 不能使仍被引用的 plan 绕过校验。三个候选键仅供未来 Commercial 讨论；它们在合法 Core plan 中缺失表示“不设套餐上限”，不能解释为 0。

SaaS Core 首发只有一个 Core 套餐，不接在线支付：兑换码决定服务时长，成员席位上限为 10。代码仍使用稳定 entitlement key，便于 Core 之后增加套餐而不重写业务权限，但未来候选键在再次确认前不能影响 Core 请求结果。

### 11.2 Enforcement

- `@require_entitlement("feature")` 控制已批准的功能；Core 的 `QuotaService.reserve/commit/release()` 只处理成员与 pending 邀请合计 10 席的并发占用。
- Core 不为设备、rental、普通 API 调用或集成账号建立套餐计数器，也不在这些写路径调用套餐额度服务。安全防刷、请求大小/分页、数据库连接预算、任务背压和 provider 固有限制属于独立的系统保护，必须返回对应的限流、过载或外部限制错误，不能返回套餐耗尽或升级提示。
- 创建邀请时严格沿用 6.4 的锁序：先插入/锁定 canonical `users` 协调行，再按 UUID 锁定并把本租户同手机号已到期 pending 邀请转为 `expired`、清空其 `user_id`，然后锁定本 tenant 行并复验 effective gate/access version，最后锁定本租户唯一 `member_seats` guard；取得 guard 后必须用 locking/current read 按 D51 谓词重新读取有效 membership 与未过期 pending invitation 并计数，不能使用等待 guard 前的事务快照，合计达到 10 时拒绝创建。重新生成本租户同一手机号 pending 邀请也按 user→invitation→tenant→guard 锁序，只轮换 token 并刷新到期时间，角色必须保持不变，不新增占用，也不调用腾讯云通知短信。要修改 pending 邀请角色必须先撤销再新建；新建 Admin 邀请必须使用新的 D48 challenge，禁止以 Operator 邀请重新生成绕过复验。其他租户对该手机号的 pending invitation 不计入本租户额度，也不形成全局占号。
- 接受邀请时把绑定 invitation UUID/token generation/手机号的 `accept_invitation` challenge 校验与消费放入同一个最终事务；按统一锁序锁定手机号身份、该手机号全部有效邀请、按 tenant UUID 排序的受影响 tenant 行和同序 `member_seats` guard；取得 tenant 行后只复验获胜/要加入租户的 join gate/access version，loser tenant 不越过自身 gate 新增任何资源，只执行邀请 supersede 和席位释放。取得 guard 后以 locking/current read 重数，再把当前邀请的一个预占席位原子转换为有效 membership，并把其余 pending invitation 置为 `superseded`、立即释放它们各自在所属租户的席位。撤销或过期同样进入终态并释放席位。注册和换号取得该手机号归属时也执行同一失效/释放规则。所有创建、重新生成、接受、注册、换号、撤销、membership 启用和 user 重新启用路径都必须持 tenant 锁；新增权限的目标租户复验 access gate，再持 guard 用 current read 实时重数，在并发下保证每租户合计不超过 10，且全平台同一 user 最多一个未释放 membership；启用后的角色为 Admin 时还必须按 D48 完成动作专用复验和最后 Admin 协调事务。
- 后台进程定期把到期 pending 邀请标为 `expired`；额度检查同时按 `expires_at` 实时排除过期记录，不能依赖清理任务及时运行才能释放席位。
- 成员页展示按 D51 谓词计算的当前有效成员、有效 pending 邀请及 `合计 / 10`；后端在所有席位变更路径重复校验。Core 不在设备、rental、普通 API 或集成设置页面展示套餐用量/升级提示。
- `active` 状态下 Admin、Operator 正常使用；服务期结束自动进入 `expired`。
- `expired` 状态下所有有效成员无论使用到期前旧 session 还是重新短信登录，都只能进入同一过期续费闭环：Admin 可提交兑换码续期并注销，Operator 只看到联系 Admin 的提示并可注销；两者都不能进入账号安全、成员、租户设置、仓库、集成、顺丰解绑或其他业务页面/API。兑换成功后租户立即恢复 `active`，随后才重新适用正常角色权限。
- D55 已确认 Core 不签发、不导入、不接受 tenant API key，也不提供创建、轮换、scope/expiry、撤销或恢复入口；浏览器业务请求只使用 D45 的服务端 session。第三方 integration/provider Secret 仍按各自专用模型、权限和加密规则运行，不能被当成 tenant bearer credential。未来若需要机器调用，须在 Core 之外另行设计认证、授权、迁移和恢复边界。
- `suspending/suspended/resuming` 服从 D52：三者均 deny 普通业务、续期兑换、新 job lease 和新 provider 提交；Operator 只可访问暂停说明/注销，Admin 仅额外访问本人账号安全。暂停不改变 subscription 到期时间、不释放 D51 席位、不消费兑换码，也不触发删除；D56 已确认不为顺丰解绑增加例外，必须先由平台完成 D52 恢复。Core 不增加未定义保留语义的 `closed` 状态。
- D56 的顺丰解绑状态门禁固定为：只有 current recovery hold released、没有 suspension/deletion gate、subscription 有效且 effective tenant state=`active` 时，原绑定仓所属租户的 Admin 才能按 D50 和 D48 的普通流程解绑。expired 必须先由 Admin 在上述统一页面续期；suspended 必须先由平台恢复，若恢复按实时期限落为 expired，还须再续期。任何 expired/suspending/suspended/resuming、D58 held 或 deletion 状态都不创建/消费解绑 challenge 或 intent、不释放全局 claim、不修改当前绑定；平台管理员也不能代替租户 Admin 解绑。解绑只影响当前 binding/claim，既有 shipment/waybill 继续使用创建时保存的 warehouse/account/integration/binding revision 和寄件资料快照。
- 顺丰 credential 的业务 revision 是不可变历史事实，不得把“当前 Secret 更新”实现成覆盖旧版本：每次更新 API connection 或 provider account Secret，都追加一个绑定原 integration/account UUID 与单调 revision 的认证加密版本，再以 CAS 切换 current pointer；旧 revision 的 crypto context、凭证语义/认证摘要、验证结果摘要和创建时间均不可改写。只有 current active revision 可用于新时效查询、绑定和新建运单；shipment/execution ledger 已保存的 integration/account/credential/binding revision 则继续精确引用并按外层租户门禁用于取消、查询、幂等重试和第一联获取/打印，更新、停用、解绑或 claim 转移都不得把历史操作切到新 revision。只要仍有未终结或按保留策略可操作的历史 shipment/execution 引用，旧 credential revision 就不能物理删除；若 provider 已撤销该旧凭证或解密/认证失败，历史动作进入明确失败或 `needs_review`，绝不能回退当前/default credential。根密钥换代可在保持同一业务 revision、crypto context 和明文语义的前提下可重入地更新其 ciphertext/nonce/tag 与 root/crypto/AAD 封装版本，但必须保留认证迁移 lineage，不得生成新的业务 revision 或改写 ledger 引用。
- D57 已确认：租户成员无法接收当前 canonical 旧手机号时，Core 不提供平台代恢复、直接改号、代收/代输 OTP、跳过 `phone_change_old` 或把平台 TOTP/恢复码转换为租户凭证的页面、API 或 CLI。自助换号仍必须由本人在同一事务完成旧号和新号两个专用 challenge；缺少旧号控制即 fail closed。若租户在 current recovery hold released、无 suspension/deletion 且 subscription 有效的 `active` 状态下另有 active Admin，该 Admin 只能走普通成员流程：先按旧成员角色适用 D48、最后 Admin 保护和 current-read 复计移除旧 membership并原子撤销目标全部 session/challenge/intent，提交后再以新号码创建全新邀请；邀请角色为 Admin 时另行完成该动作自己的 D48，新号持有人按普通邀请 OTP 接受并形成相对旧身份独立的 user/membership，不存在“原地恢复”或自动复制角色的特殊事务。若旧账号是最后一个 active Admin，则不能被移除、降级、停用，也不能在缺少旧号 challenge 时直接换号，平台管理员同样无旁路；只能先在系统外恢复旧手机号，再按正常登录/双码换号流程处理，否则 Core 接受租户继续不可访问，其他找回方式留待 Core 之后另行决策。历史订单、rental、shipment、审计 actor、创建/审批/业务归属等记录继续引用原 user/membership UUID及当时快照，不改写为新身份、不建立可改变历史语义的别名。
- D25 已确认服务期到期的数据永久保留：不得为 `expired` 租户创建按天数自动删除、drop schema 或丢弃历史记录的任务。其数据库路由保持已登记但业务访问门禁关闭，并继续纳入备份、恢复清单和 fleet schema migration；续期后复用原 tenant/database UUID、原关联和审计记录恢复访问。
- 永久保留会让已到期租户持续占用在线磁盘、备份容量和 migration 时间，也会长期保存租户录入的客户姓名、手机号和地址；这些是 D25 已接受的代价，必须持续做容量监控和隐私/合规复核，不能把“永久”误实现为无人盘点的孤儿 schema。
- D25 只处理服务期自然到期；租户 Admin 主动删除使用 D26/D27 的短信复验、人工审核、立即冻结、30 天冷静期和 tombstone 流程。平台强制关闭及其他特殊数据处理流程仍须单独授权，不能伪装成租户自助申请。
- 支付 webhook 先写入 `billing_events`，按 provider event id 幂等，再更新 subscription；不得直接相信前端支付结果。
- SaaS Core 正常注册或续期由兑换码创建或延长 subscription；D53 已确认后台可在异常处理、补偿或退费场景受审计地增加或减少服务期。自动支付后续接入同一 subscription event 接口。

#### D53 confirmed input contract

- D53 只有 `add_days`、`subtract_days`、`expire_now` 三个互斥动作。前两者只接受有版本化上限的正整数 `days`，拒绝 0、负数、浮点、字符串、溢出或混合动作；`expire_now` 不接受 days。客户端、API 和 action 均不得提交目标 `expires_at`，页面日期只用于展示服务端预览。
- 最终事务只取得一次数据库 UTC `effective_now`，一天固定为 24 小时；页面按 Asia/Shanghai 展示。`add_days` 使用 `max(before_expires_at, effective_now) + days × 24h`，因此 active 租户从原到期时间累加，expired 租户从实际提交时获得完整新增天数。`subtract_days` 使用 `before_expires_at - days × 24h`；若租户已自然到期或结果 `<= effective_now`，整笔拒绝且不写订阅事件，要求操作者显式选择 `expire_now`，不能静默钳制或转换动作。`expire_now` 仅在原期限仍晚于 `effective_now` 时把到期时间设为该事务时间；新请求命中已 expired 租户时不再生成事件，同一已成功幂等请求仍返回首次结果。
- `expire_now` 只触发普通 subscription 到期语义：数据按 D25 永久保留，Admin 仍可按 expired 规则续期；它不等于 D52 suspension、D26 deletion 或禁止未来续期。预览使用 `no-store`，返回 before/base/after、是否重新激活/立即到期及 expected tenant/subscription revision，但不写事实也不构成授权；提交事务 current-read 最新 revision 和数据库时间并重新计算。数据或门禁版本变化时要求重新预览，不能相信客户端 after 值。
- D53 与兑换续期、自然到期 evaluator 共用 subscription 行锁和唯一 effective-state reducer。兑换先提交会使旧 D53 preview/revision 失效；D53 先提交后，兑换按新的 `expires_at` 继续使用既有累加公式。成功调整恰好写一条不可变 subscription event 与同事务平台审计；同一幂等键和请求摘要重试返回首次保存的 before/after/effective-now，不能重新取时间或重复增减。
- D53 的每个新逻辑动作均要求当前 active 平台管理员现场提供 fresh TOTP 或一枚未使用恢复码；不复用 session 的近期 MFA，不做双人审批。提交事务在验证最新 gate/revision 与服务端确认摘要后，才把 factor 防重放状态、subscription/reducer、事件及平台审计一起提交；失败全部回滚。同一已成功 action 的幂等重取不是新动作，不再次消费因子。
- D53 每个成功事件必须有 reason code 和版本化长度上限的备注，可选一个采用受限字符集和长度的线下参考号；页面明确禁止在两者中填写 Secret 或不必要 PII，系统也不得从租户/客户资料自动复制这些内容。选择 refund 只解释减少服务期或立即到期的业务原因；系统不保存 amount/currency/payment channel/status/paid-at/proof/attachment，不从天数推导金额，不写 billing/refund 状态机，不调用支付 provider，也不提供退款金额汇总或对账结论。页面和导出均须明确“该记录不证明资金已退”，真实退款由平台人员在线下完成。
- D53 的状态矩阵固定为：current recovery run 必须 completed、目标 tenant 的 current hold 必须 released、没有任何未终结 deletion；tenant 为 `active` 或 `expired` 时可调整，tenant 为 `suspended` 时还必须有冻结屏障已成功收口且 `tenant_suspensions.state=active` 的唯一权威聚合。`suspending/resuming`、freezing/failed/resolving suspension、任一 recovery hold 非 released，以及 deletion cooling/committing/deleted 均拒绝。最终事务沿 `tenant → current run → hold → deletion → suspension/action → subscription → platform factor` 锁序 current-read 重验；preview 后 gate 获胜时不修改 subscription/event，也不消费 TOTP/恢复码。
- 对 fully suspended 租户，D53 只更新 subscription 与不可变事件；tenant/effective gate 继续保持 suspended，tenant `access_version`、suspension state/generation、DML desired/observed/route、session、job lease 和 provider submission 均保持原安全状态，不得解锁、恢复或重放，也不执行 D52 resume outbox。日后通过独立 D52 resume 时，reducer 才按调整后的实时 `expires_at` 落到 active/expired。D53 与 freeze/resume、自然到期 evaluator、兑换、deletion 或 recovery hold 并发时由相同 tenant/suspension/subscription 行锁确定唯一串行结果：D53 先提交可保留结果后再进入更高门禁；更高门禁或过渡态先提交则 D53 失败且 factor 不消费。

#### D54 confirmed failed-registration recovery

- Core 平台后台不提供“重试开户”“放弃开户”或“清理 provisional 资源”的按钮/API。普通失败保持原 redemption code、canonical user 与 registration attempt 的不可变绑定；原用户在注册会话过期后重新完成同一手机号的 `register` OTP，即可由用户侧恢复并重试同一 attempt。worker lease 接管和崩溃后的幂等续跑只是该用户动作的内部执行机制，不能被包装成平台人工 retry，也不得因失败次数、普通重启或原兑换截止时间经过而释放、转让或复制 reserved code。
- 平台若决定补偿，只能在现有兑换码后台执行一次“补发新码”。普通失败开户的 source 是仍绑定原 user/attempt 的 reserved code；D58 后也可在 current recovery run completed 后选择一枚已不可逆 recovery-revoked、尚无 successor 的 code 作为 source，后者可以没有 registration attempt。补发请求只接受 source code、可空的 source attempt、对应 source code/attempt expected revision、普通兑换码生成权限所需的审计字段、幂等键和平台选择的新截止时间；服务端在最终事务使用数据库 UTC 时间校验截止时间严格位于未来。immutable plan revision UUID、entitlements schema version、canonical entitlement snapshot/digest 与 exact duration 必须逐字段从旧码的 effective terms 继承，客户端不得提交、覆盖或按当前默认套餐重算这些字段。
- 补发事务与 registration final commit 使用同一控制库锁序和 locking current-read，锁定 source attempt（若有）/code、registration commit/source facts 与唯一 replacement guard，复核 current recovery run 已 completed。完整 registration commit 已先成立时拒绝补发；出现部分 commit、anchor 或 source-linked 事实时自动进入内部 integrity incident 并 fail closed，不生成新码，也没有普通平台或租户处置页面。只有全部成功事实不存在且 source 为上述 reserved 或 recovery-revoked 终态时，事务才在存在 attempt 时原子推进 `provisioning_execution_generation`、使旧 worker/lease/final commit 失效并把旧 attempt 置为 `superseded_by_replacement`；reserved 旧码永久转为 `revoked`，recovery-revoked 旧码保持该更严格终态。随后在同一事务创建恰好一个 successor code、不可变 replacement link 与平台审计。
- successor 使用新 UUID、全新 crypto context 和随机明文，是不预绑原 user/attempt 的普通 bearer code；取得明文者仍须按正常注册流程完成自己的手机号 OTP。`UNIQUE(source_code_id)` 或等价不可变 successor 指针保证同一旧码即使被两个管理员、不同幂等键或响应丢失并发补发也只产生一枚新码；同一幂等键与请求摘要重取返回首次结果，修改截止时间或其他摘要字段的重放拒绝。补发先线性化时迟到 final commit 必须在写 membership/subscription/code 前失败；final commit 先线性化时补发不得撤销已成功注册或另发权益。
- 新码可在上述控制事务提交后立即使用，不等待物理清理。安全前提是 provisional route 在权威 registration commit 前永不进入 Web/worker resolver，provisional credential 不向用户或 provider 暴露，旧 generation 的任何执行器都不能发布 route 或创建业务来源事实。只有 source 确实存在 provisional route、账号、schema 或关联任务时，补发事务才创建 system-only cleanup outbox，janitor 随后以同一 generation fence、backup/DDL lease 与 per-database advisory lock 幂等收口；无 attempt/database/resource 的 D58 source 不创建空 outbox或取得无意义的数据库锁。任一步失败只记录非敏感告警并继续重试，不阻塞新码、不复活旧 attempt/code，也不形成 Core UI 操作。D58 host restore 仍可运行自己的隔离与 system recovery cleanup，但 recovery run 完成前不得补发新码。

### 11.3 Platform suspension (D52 confirmed)

- D52 的 suspension 只用于平台安全、违规或应急止损，不替代 subscription 自然到期、删除冷静期或法务数据处置。有效门禁优先级为 `deleted/deletion_committing > deletion_cooling_off > non-resolved suspension intent > expired > active`；暂停的 freezing/active/failed/resolving 全部属于 non-resolved，只有 resolved 才不再占据该优先级。D58 recovery hold 是这个投影之外的最外层恢复 overlay，不抹掉底层状态：current hold 非 released 时，若去掉 D58 overlay 后的权威投影为 active/expired、没有未终结 deletion 或 suspension，平台仍可发起只会进一步收紧的 freeze；hold 全程保留，resume 则必须等 current hold released 后才能发起。tenant 已进入 deletion_cooling_off/committing/deleted 时，新的暂停和恢复请求均拒绝，不能借“恢复”清除或覆盖更高优先级状态。若 tenant 在 suspension 期间后来进入 deletion cooling，取消删除后仍回到 suspension，再由平台单独恢复。
- tenant `status` 是 deletion request、suspension intent 和 subscription 三类权威事实的有效投影，不是各 worker 可以独立覆盖的业务事实。D52 屏障收口、恢复收口、删除批准/撤销/提交和到期处理都在最终事务沿用 6.2 的 `tenant → current recovery run → current hold → 未终结 deletion request → suspension/action → subscription` 统一锁序，校验 recovery/hold、action generation、row/access version 后调用唯一 effective-state reducer。无 deletion 覆盖时，suspension phase 的唯一投影是 `freezing/failed → suspending`、`active → suspended`、`resolving → resuming`、`resolved → 按 subscription active/expired`。到期任务只更新 subscription 事实并重算投影，不得直接把 suspension/deletion 覆盖成 `expired`；任何陈旧 outbox 也不得把投影改回较低优先级。
- 发起暂停必须满足 6.3 的近期平台第二因子 step-up、可信 tenant UUID/current revision、非敏感原因和幂等键，且去掉 current D58 overlay 后的底层权威投影只能是 active/expired 并不存在未终结 deletion/suspension。首个短事务按统一 account-mutation 第一段复核，创建 `freeze` action 与 `freezing` suspension、把 tenant 投影切为 `suspending`、递增 `access_version`、撤销该 tenant 全部既有 session，并在同一提交中先把 DML authoritative `desired_login_state` 写为 locked、递增 `login_state_version`、写入绑定 freeze action/current recovery run 的 provenance，再原子提交平台审计和 control-plane outbox。该事务一旦提交，Web/scheduler/worker/provider gate 立即 deny 新业务；若 tenant 正被 D58 hold，hold 仍保持原状。只有同 action UUID/幂等键/请求摘要的丢响应重试返回原结果；`freezing/failed` 只允许同 freeze 屏障重试，`active` 才可进入恢复，`resolving` 只允许同 resolve 重试；中间态的反向新动作稳定返回 409，不自行决定谁覆盖谁。
- outbox 驱动的 suspension barrier 是平台控制任务，不作为 tenant 业务 job 领取。它按 5.1 取得控制库 fencing token 和目标 MySQL 实例的 per-tenant DML advisory lock，然后在每个外部账号动作前后重验 suspension/action generation、方向、状态、committed `access_version` 与 `login_state_version`。普通陈旧 freeze/resolve 任务 no-op/fail safe；若是 deletion/DR 使旧版本失效，只有由该高优先级事务新建并绑定当前 access version 的 `enforce_locked` compensation 可继续收紧，旧 action 本身仍不得执行。有效 freeze/enforce-locked 屏障停止新 scheduler fan-out/job lease，按持久 provider submission boundary 分类在途 operation，并复验首个事务已经提交 desired=locked 及正确 provenance；异步 barrier 只负责 dispose engine、执行物理锁定/连接排空并把 observed 状态收口，不能把“稍后写 desired”当作安全边界。provisioner 必须从可信控制库注册表、current route 和未终结 rotation 对账得到所有可归属该 tenant 的可登录 DML identity，包括 current/from/to/prepared/switched/draining/candidate 及遗留孤儿代数；在同一持锁特权连接上对全部执行/核验 `ACCOUNT LOCK`、终止/排空既有 DML 连接，释放 advisory lock 前再次按最新 desired state 收敛。任一未能解释或未能锁定的归属账号都使屏障保持失败锁态。独立平台只读账号、备份账号和 fleet migration 身份不被锁定。DML/root-key 轮换必须继承 desired locked，新代数从创建起即锁定并停在 `prepared_locked`，不得切换。
- suspension、D58、deletion、DML/platform-read rotation 及其 reconciler 共用唯一 account-mutation 三段锁序。第一段在短控制库事务中按 `tenant → current recovery run → current hold → deletion → suspension/action → subscription → tenant_databases → account kind(dml → platform_read) → rotation` 排序锁行，写 intent/desired state、分配单调 fencing token 和 expected revisions 后提交；不得持这些行锁等待 MySQL。第二段按数据库实例、tenant UUID、`dml → platform_read` 固定顺序取得所需 advisory lock，每个物理账号动作前后复验 fencing token 与 expected revisions。第三段在 advisory lock 仍存活时按第一段同序重取控制行并 CAS route/observed/action，随后再次读取最新 desired state并完成正向或重锁核验，最后才释放 advisory lock。只涉及一种 account kind 时可以省略另一把锁，但任何同时触碰两类账号的 DR、删除或根密钥轮换都禁止 `platform_read → dml` 反向取得；失去 lease、token 过期或连接断开后必须由新 owner 从第一段重来。
- freeze/enforce-locked 屏障完成后的收口事务再次执行统一锁序和 reducer：若同 generation 仍是有效收紧动作，将 suspension/action 置为 active/succeeded；仅当无更高 deletion gate 时才把 tenant 投影置为 `suspended`。如果高优先级 gate 已使原 action 失效，原收口 no-op，并且只由新 compensation generation 完成后把 suspension 置为 active；tenant 仍保持 deletion 投影，以便日后取消删除时安全回到 suspended。任一步失败都保持 deny-all、记录安全错误并可重入重试，不得恢复业务访问或谎报“已暂停完成”。
- 暂停前尚未越过持久 submission boundary 的 job/operation 一律阻断；已经越过边界、可能已到 provider 的 operation 进入只读查询/对账隔离，只能使用既有 immutable snapshot 和 idempotency ID 确认结果，不得自动重试、重新下单或打印。查询暂时无法完成可以保持 `needs_review` 到恢复后处理，不能为了写租户业务账本而解锁通用 DML 账号。
- 暂停期间允许用户完成短信登录，以便看到稳定说明而不是账号不存在。Operator allowlist 只有暂停说明与注销；Admin 另有本人账号安全页，可管理自己的 session、注销全部设备及按既定双验证码更换本人手机号。成员/邀请、兑换续期、删除申请、租户设置、仓库/设备/rental、集成管理、顺丰解绑和全部业务 API 均拒绝；D56 不增加例外入口。
- suspension 不修改 subscription `expires_at`，服务期按自然时间继续消耗，不生成补时或额度事件。暂停期间兑换接口必须在 reserve/consume 前拒绝，兑换码保持原状态；普通兑换码既不能解除 suspension，也不能在冻结中延长服务期。平台若误暂停，可在冻结屏障完全收口后通过独立、显式的 D53 动作增加、减少服务期或立即到期；该动作只记 subscription/账本，tenant 继续 suspended，D52 暂停/恢复本身仍不自动调账。
- 恢复也要求近期平台第二因子、独立原因、expected revision 和幂等键，且 current D58 hold 必须 released、只能从已完成冻结屏障的 `suspension.state=active` 发起；`freezing/failed` 必须先重试收敛冻结，不允许恢复抢跑。首个事务按 account-mutation 第一段确认没有 deletion gate，创建新 `resolve` action generation，把 suspension 置为 `resolving`、tenant 投影置为 `resuming`、递增 `access_version`，并登记一个绑定该 action、尚未发布且初始 `ACCOUNT LOCK` 的全新 DML candidate generation；authoritative desired 继续保持 locked，因此整个恢复屏障期间仍 deny 且不签发新 session。第二段取得 fencing token + DML advisory lock 后复核 resolve/candidate/access/login-state revisions，保持既有 current/from/to/prepared/draining/candidate/孤儿代数 locked 或撤销；只对本 action 新建、且不在任何应用 route/cache 中的 candidate 临时解锁，用独立正向连接验证 `database_identity`、所需读写权限和跨 schema 拒绝。验证成功也不能提前发布 candidate。
- 恢复收口事务在同一 advisory lock 尚未释放时执行 account-mutation 第三段，再按统一锁序重读 recovery hold、deletion、suspension/action 和 subscription，并 CAS 同一 resolve/candidate/access/login-state generation。只有仍有效、hold released 且无 deletion gate 时，才原子把 DML desired/observed 提交为 active、把可信 route 切到 candidate、将 suspension/action 置为 resolved/succeeded、撤销暂停期间 session，并由 reducer 按当前 subscription 落到 `active` 或 `expired`；`expired` 与普通自然到期使用同一底层路由状态，只由应用 tenant gate 限制到统一过期页，不能访问账号安全、顺丰解绑或其他业务 API。控制库提交后、释放 advisory lock 前，owner 再确认 route 只指向 candidate、candidate 可登录且所有旧代数 locked/已撤销。若在 final CAS 前进程或持锁连接崩溃，应用仍因 `resuming` 与未发布 route deny；物理层可能短暂留下一个未发布 candidate 可登录，这不是跨系统瞬时原子承诺，新 reconciler 必须先按三段锁序取得新 token、重锁并核验或撤销该 candidate、清退验证 engine，之后才能重试恢复。若 deletion/freeze 获胜、final commit 失败或目标不明，同样先收敛全部 candidate/旧代数为 locked；旧 fencing token 无权发布 route。任何失败都不得先开放再补验证，candidate generation 也不得跨 action 复用。
- 恢复收口一律撤销暂停期间 session 并要求用户重新短信登录。只有最终状态为 `active` 时，原绑定仓 Admin 才可重新发起普通顺丰解绑，周期性读/同步任务才从当前时点重新排程且不 catch up 每个错过周期；旧 user-triggered 发货、下单、打印和结果未知 operation 不自动恢复，只有当前事实、`not_after`、幂等和未提交条件都重新成立时才能生成新 access-version job。恢复为 `expired` 时重新登录仍只进入统一过期续费闭环，必须续期为 active 后才能解绑。
- suspended tenant 的 tenant schema、控制面记录、D51 席位、备份、恢复清单和 fleet migration 均继续保留；平台管理员仍可按 D44 用独立 SELECT-only 账号审计只读排障。暂停、恢复或失败重试都不触发 D26 删除、不释放手机号/顺丰全局 claim，也不删除第三方 integration/provider Secret；顺丰全局 claim 只有 tenant 恢复且必要时续期为 active 后，才能由原绑定仓 Admin 按 D50 普通解绑释放。

### 11.4 Controlled tenant deletion (D26 confirmed)

- 自然到期继续执行 D25 的永久保留；只有租户 Admin 主动发起的显式删除申请可以进入 D26。普通退出登录、删除某个成员、服务期到期、平台暂停或兑换码撤销都不得触发租户删除。
- 申请必须来自已认证 Admin，并向 AuthContext 当前 user 的 canonical `+86` E.164 发送用途固定为 `tenant_delete` 的新短信 challenge；请求体不能提供或覆盖接收号码。challenge 按 D48 绑定 tenant、actor/session 和删除申请摘要，验证码验证/消费与创建唯一 `requested` 申请在同一控制库事务提交。页面明确显示不可恢复后果、tenant 标识和 30 天冷静期，服务端拒绝复用登录、续期或其他高危操作验证码；本专用验证码已经满足 D48，不再叠加第三个通用验证码，也不直接执行任何删除。
- 平台管理员在独立后台人工核对 tenant、申请人权限和异常状态后批准或拒绝；批准时间是 30 天冷静期起点。批准事务按 account-mutation 第一段复核 tenant/recovery hold/deletion/suspension/subscription，立即把有效投影切为 `deletion_cooling_off`、递增 `access_version` 并撤销现有 tenant session：Operator 和业务 API 全部拒绝，scheduler/job 和第三方 provider 动作暂停；Admin 只可访问删除倒计时、短信复验撤销和账号安全。无论此前是否存在 suspension，该首个事务都必须把 DML authoritative desired 写为 locked、递增 `login_state_version`、写入绑定 deletion request/action generation/current recovery run 的 provenance，并创建 deletion 专用 `enforce_locked` action/control outbox；异步屏障只按第二、三段锁序完成全部 candidate/current/from/to/孤儿账号的物理锁定、连接排空与 observed 收口。已有 freezing/failed/resolving action 被 supersede，但 suspension intent 本身保留并按需归到 freezing；已 active 也不能省略新的 deletion generation。因而迟到旧 freeze/resolve/rotation outbox 无权解锁或改写投影，且无 suspension 的 tenant 也不存在“只靠应用 gate、没有物理收紧任务”的窗口。同一租户最多一个未终结申请，重复提交复用现有状态。
- 冷静期内 Admin 可用 purpose=`tenant_delete_cancel`、绑定当前 deletion request UUID/revision 的新短信 challenge 请求撤销；第一段控制事务单次消费 challenge、创建 immutable cancellation action 并保持 `deletion_cooling_off` 与 desired=locked，不能在等待外部账号验证前先把申请标为已撤销或开放 tenant。若存在 freezing/failed suspension，先等待 deletion 专用收紧屏障收敛，再按底层投影回到 `suspending`；若 suspension 已 active，最终只移除 deletion overlay 并回到 `suspended`，DML 保持 locked。只有 current recovery hold released、没有未 resolved suspension 且实时 subscription 底层为 active/expired 时，撤销才复用 D52 的全新未发布 DML candidate generation与 account-mutation 第二、三段：既有账号保持 locked，candidate 临时解锁完成 identity/正反权限验证，最终 CAS 才同时把 deletion request/action 置为 cancelled/succeeded、切换 route/desired/observed 并按 subscription 开放 active 或 expired。pre-CAS 崩溃时应用继续 deny，新 reconciler 必须先重锁/撤销 candidate；若 D58 hold、freeze、rotation 或 deletion commit 竞态获胜则不得发布 candidate。撤销不延长兑换码有效期，也不补偿被冻结天数；旧业务任务只在幂等性和时效仍成立时恢复，过期发货/打印/同步不得盲目重放。
- 冷静期届满时，worker 不得先锁 deletion request 再反向等待 tenant；必须按 6.2/D52 统一锁序执行 locking current-read/CAS，同事务重新确认未撤销且外部副作用已可安全隔离，然后经 reducer 把申请与 tenant 投影原子推进到不可取消的 `committing`、递增 `access_version`，回收/隔离剩余任务租约并 dispose 连接池。D58 recovery hold 不是删除门禁：删除提交是单调收紧动作，可在 hold 下继续并始终优先于 release；事务只保留/更新相应 recovery 处置事实，不能先清 hold 或开放 tenant。顺序必须保持“审批即冻结 → 冷静期 → 异机 tombstone → drop schema”，不能把冻结推迟到第 30 天或先 drop schema。
- 冻结完成后生成不含 PII/Secret/业务内容的永久 tombstone，并推进到 `awaiting_offsite_ack`。记录以全局单调 sequence 和 hash chain 排序，最新 head checkpoint 使用现有平台根密钥派生的独立用途 key 认证；根密钥换代时须用新版本为当前 head 写新 checkpoint，不能为此再要求用户管理第二把根密钥。tombstone 必须被 NAS 的独立只追加 restore-exclusion ledger 持久接收并回传已校验 ack；云主机或 worker 不能仅因“已发出流”就假定 NAS 已落盘。
- 只有 deletion request 已进入不可逆 `committing` 且取得上述匹配的站外 tombstone ack 后、删除任何 SF provider account、integration 或 warehouse binding 前，deletion executor 才必须执行 system-only current-claim release 阶段；这不是 D50 租户解绑，不创建/消费 Admin challenge，也不为 expired/suspended 租户开放普通解绑入口。执行器按规范化 account fingerprint/claim UUID 排序取得 deletion/claim fencing，逐项 current-read 复核 claim 的 current tenant/account/warehouse 与待删 account/binding 双向一致，先 fence 同租户仍为 `reserved` 的绑定验证 operation，再以 CAS 把仍归本删除 tenant 的 `active/reserved` claim 置为 `released`、清空 current owner，并写入 deletion request/generation 的 system provenance；已经由合法先行 D50 解绑释放的 claim 只做幂等核验。claim 已被新 owner 合法取得时删除执行器不得触碰；claim 指向待删 tenant 但 account/binding 缺失、binding 声称占用却 claim owner 不匹配，或无法证明 reservation 归属时一律视为 orphan/integrity failure，tenant 保持不可访问且不得继续删除 account/binding。新仓 bind/reservation、D50 解绑与 deletion commit/release 共用 claim 行和 fencing 线性化：删除 gate 先提交时旧租户的新绑定/普通解绑都失败，system release 提交后新仓才可重新竞争；任何崩溃重试只能收敛到“旧 owner 已清空”或“新 owner 已合法取得”，不能释放新 owner、双重绑定或永久假占用。
- 收到匹配 ledger sequence/head ack 后，删除执行器取得 tenant deletion/backup/migration lease，从可信注册表解析 schema 并再次核对 `database_identity`，且必须证明上述全部 system claim release 已完成、没有任何 current claim 仍指向本 tenant/account/warehouse，也没有 orphan claim/binding，再撤销租户 DML 与平台只读 MySQL 用户、终止残留连接。若当前 D58 run 已封存该 tenant，则在删除这些行前必须把 tenant、registration commit 与全部 source-linked normalization item 原子写为绑定同一 deletion UUID、ledger sequence/hash 的 `tombstoned` disposition；随后先删除 registration commit 权威行，再删除 tenant schema、数据库账号、第三方凭证、仓库/provider binding、租户设置及其他 tenant-owned source/control 记录。全局 claim 行永久保留为可重新竞争的 `released` 技术记录，不随 tenant-owned account/binding 级联删除；之后若新 owner 合法取得，它也不能被旧 deletion retry 改写。保留在 redeemed code、tombstoned hold 或其他必要审计行中的 commit/tenant UUID 只是无 FK 的技术历史标识，不得以 RESTRICT 阻塞删除，也不得 CASCADE 删除这些保留行。按 D28 同时删除全部 membership/invitation 和不再有租户引用的 tenant-only user/手机号记录；独立 `platform_admins` 及其平台审计不与 tenant user 建立级联关系，不能被租户删除流程影响。若是从删除前旧 dump 恢复但最新站外 ledger 已命中，则先从 survivor 集合排除该 tenant 及其 commit/source rows，并把旧 dump 中仍归该 tombstoned tenant 的 current claim owner 单调清为空/released 后再封存 inventory，不能让合法删除表现成部分 commit或复活月结账号占用。
- 删除是持久、可重入状态机：任一步失败都保持 tenant 不可重新开放并记录非敏感 failure code，平台管理员修复后从已完成边界继续。`completed` 只有在 schema/数据库账号/tenant-owned 控制面记录不存在、全部 SF claim 已释放或已证明由删除后新 owner 合法取得、没有 orphan claim/binding、tombstone ledger 已确认且跨租户负向检查通过后才能写入；禁止用一条跨库事务伪装原子删除。
- tombstone 永久保留并禁止 UUID/database identity 复用。NAS 中删除前产生的 `.sql.gz` 仍按 48 小时/30 日/12 月策略自然淘汰，不在压缩 dump 内做选择性改写；恢复任何时点的 dump 时，必须先加载 NAS 上最新永久 tombstone ledger，再创建数据库账号或业务路由。ledger 缺失、版本倒退、checksum 不符或选定 dump 比 ledger 新旧关系无法验证时，恢复流程 fail closed，不得开放任何可能命中的租户。
- 删除前不自动生成新的数据导出包；如果以后提供导出，导出物的权限、有效期和清理策略必须另行设计，不能成为绕开 D26 的永久副本。

### 11.5 Phone reuse after deletion (D28 confirmed)

- D26 `completed` 前，Admin、Operator 的有效 membership 仍占用其标准化手机号；注册、兑换码开户和接受其他租户邀请必须拒绝，不能因为 tenant 已冻结就提前释放。pending invitation 本身不建立手机号归属，按 D47 可以与其他租户邀请并存；但处于删除冻结状态的租户不得新建邀请，其既有邀请也不得再被接受，且删除清理只能移除本租户邀请，不能触碰其他租户对同一手机号的记录。
- 删除清理先撤销并移除该租户全部 `tenant_user_sessions`，再移除 membership/invitation。一个 `users` 记录按“一手机号只属于一个租户”已无其他合法引用时即删除，使 `phone_e164` 唯一值在 D26 完成事务后释放；`platform_admins` 是完全独立的表和身份域，不需要也不能通过 tenant `users` 保留。短信 challenge、日志和临时风控数据仍按各自短期保留规则清理，不进入永久 tombstone。
- 释放后的手机号可立即通过新的 `register` 短信 challenge 和未兑换兑换码创建租户，或接受另一个租户的新邀请；此前已兑换码不能复用。普通租户重新注册必须产生全新 user UUID、tenant UUID、database UUID、membership 和默认仓，禁止以手机号、公司名或历史 tombstone 关联旧业务数据。
- D26 tombstone 永不保存手机号，因此不能把手机号永久拉黑；它只阻止旧 tenant/database UUID 被恢复或复用。平台管理员是独立控制面身份，不创建 tenant membership，其身份和审计不会因某个租户删除而级联消失，也不能作为取回旧租户数据的通道。
- 注册/邀请与删除完成边界使用控制库事务、手机号唯一约束和 deletion row lock 协调：只有清理已提交且状态为 `completed` 后新身份才能成功，不能出现一个手机号同时属于冻结旧租户和新租户的窗口。

## 12. API Fan-out, Realtime Reads, Search and Rate Limiting

D16 已确认“减少连接/传输但不以陈旧库存缓存换速度”的目标与 Core 接口形态；经 D33 修订后的 D17 采用统一双窗口策略：客户使用期决定主设备硬冲突，计划物流窗口决定甘特/接力软警告。D34/D39 已确认手机支架和三脚架使用不可见逻辑单元：request、无状态 rental-unit link、单元当前持有事实、relay case 和事件是事实，单元随主设备接力且特殊提示不落库；后一单需要而设备未携带时允许内部备注的线下补寄例外，不阻断接力状态，也不建设第二正式运单流程。预约 bootstrap/availability、单次范围 gantt view、页面唯一写后刷新责任、无跨请求库存缓存以及统一策略服务均为约束性方向。

### 12.1 Realtime consistency boundary

- SaaS Core 不部署 Redis，也不对库存、设备仓位、附件数量/预留、档期冲突、待发货状态或甘特统计建立浏览器持久缓存、Service Worker API 缓存、服务端跨请求结果缓存或物化副本。对应接口返回 `Cache-Control: no-store`，每次有效刷新从当前租户数据库读取。
- Vue store 中“当前页面正在展示的这次响应”和按响应即时构建的 `rentals_by_device` 索引属于视图状态，不是跨页面/跨刷新事实来源；不得写入 localStorage/IndexedDB，不得在新请求失败时把旧可用性伪装成最新结果。
- 允许缓存版本化静态资源、教程二维码和不含业务状态的代码常量；SQLAlchemy engine/连接池缓存只复用连接，不缓存业务行。身份、路由和权限缓存仍受第 4/6 节的失效规则约束。
- 日期、型号或仓库筛选快速变化时，前端使用 250–400ms debounce、`AbortController`/Axios cancellation 和单调 request sequence 取消或丢弃旧请求；这是抑制无效在途请求，不是复用旧结果。
- 可用性响应只是 `evaluated_at` 时点的预览，不发放可绕过校验的“库存令牌”。创建/编辑订单、逻辑单元自动关联和调仓在最终数据库事务内按同一策略服务重新查询、锁行并校验；`USAGE_PERIOD_CONFLICT` 和普通订单无法建立逻辑单元 link 的 `ACCESSORY_UNIT_UNAVAILABLE` 是阻断写入的硬冲突，`LOGISTICS_OVERLAP_RELAY_WARNING` 是允许提交的非阻断警告。前单或连续 agreed 入站链可提供单元的候选后单可保存无 link request 并返回 `ACCESSORY_RELAY_CONFIRMATION_REQUIRED`；设备链不携带且仓库也无单元的接力补寄例外返回 `ACCESSORY_UNIT_SHORTAGE_WARNING`。两者都不能伪装成已备足，预览与提交之间事实变化时返回稳定结果并要求刷新。
- 可用性预览请求失败、超时或被取消时必须显示“无法确认”，禁止沿用上一次结果或按“可用”继续提交。即使客户端绕过该门禁，创建/编辑写接口仍必须在事务内复验；冲突响应使用稳定 reason code 和当前冲突摘要，不能只依赖前端预检查。
- 全文搜索、自动完成和统计聚合必须通过当前租户数据库 session 执行，不允许退回固定默认库或跨库搜索。搜索输入设最小字符数、debounce、取消旧请求和服务端 `limit`，但不保存跨请求结果缓存。

### 12.2 Confirmed current hotspots

- 桌面预约页当前把候选主设备和库存附件逐个送入 `/api/rentals/check-conflict`；一次检查会产生 `主设备数 + 附件数` 个并发 HTTP 请求。每个请求又按单一设备读取全部未取消租赁后在 Python 判断重叠，HTTP 和 SQL 都随设备数增长。
- 桌面甘特图当前对 16 天逐日调用 `/api/gantt/daily-stats`，移动端对 14 天逐日调用；该服务每天先取全部设备，再为每台设备查询冲突和最近租赁，并在附件统计中可能再次懒加载父单，形成“逐日 HTTP N+1 × 逐设备 SQL N+1”。
- 甘特主数据当前既在每个 device 下嵌套 rentals，又返回一份顶层 rentals；前端实际按顶层数组取数，重复结构增加传输。序列化中的 `device_model`、`child_rentals`、device 等懒加载也可能产生 ORM N+1。
- 桌面甘特初次进入还并行加载主数据、每日统计、型号、闲鱼告警和待归还，并在挂载后立即再次刷新闲鱼告警；当前前端 `statsCache` 可能在订单变化后继续返回陈旧统计。
- 桌面和移动端 gantt store 的 create/update/delete/ship/add mutation 成功后会隐式 `loadData()`，页面成功回调又再次 `loadData()`；一次写入常产生 1 次写 + 2 次完整甘特读取，部分桌面流程还额外读取 rental 详情和逐日统计。刷新责任分散也会让 watcher 再次触发统计请求。
- 桌面编辑弹窗同时监听 `rental` 和 `modelValue`，打开时两者均可触发 `initForm()`，最多重复两次 rental 详情和两次附件列表；移动端编辑页还串行读取完整甘特、附件和 rental 详情。
- 移动端新建页冷启动读取完整 `/api/gantt/data`，但后续并未使用该 store 数据；设备状态页也为只展示少数字段而加载整份甘特。搜索、验货、顺丰追踪、批量发货等列表普遍使用深层 `to_dict()` 或前端本地分页，存在重复 device/rental/child 数据和 ORM 懒加载风险。
- 预约冲突预检查目前存在错误路径 fail-open，而订单创建事务本身没有按相同规则最终复验。该问题会在并发预约或网络故障时造成档期/共享附件超卖，优先级高于纯性能优化。
- 当前 `/api/rentals/estimate-logistics` 只接收自由文本 destination，后端静态规则固定以“广东深圳”发出且未知地址静默默认 3 天；顺丰服务还从全局环境读取寄件地址，甘特接力判断直接检查 destination 是否包含“广东”。这些地理假设均不适用于多租户、多仓库，必须与旧硬编码寄回地址一起移除。
- 当前 Nginx 对全部 `/api/` 请求无条件发送 `Connection: upgrade`，而应用未使用 WebSocket；这会妨碍普通 upstream keep-alive。当前 Gunicorn 有 4 个 worker，每进程固定 engine 的 `pool_size=10` 且未覆盖 SQLAlchemy 默认 `max_overflow=10`，连接按需创建时的理论瞬时上限约 80；若把这套配置直接复制到每个租户/每个 worker，连接上限会随租户数继续放大。

### 12.3 Confirmed Core page contracts

#### Rental booking

1. `GET /api/rental-booking/bootstrap` 一次返回当前用户可选仓库及最近选择、设备型号、可配置附件类型和表单所需的最小非库存配置；不再分别请求 devices/accessories/device-models，也不依赖甘特 store 中可能较旧的设备快照。
2. `POST /api/rental-booking/availability` 接收 `start_date`, `end_date`, `model_id`, `preferred_warehouse_id`、客户结构化收货地址、可选的人工确认物流天数（必须绑定仓库与确认上下文）和 optional `exclude_rental_id`。后端一次返回按优先仓排序的候选主设备，并返回 `estimate_by_warehouse`；每台候选设备按自己所在仓的估算计算物流警告，不能拿一个全局 `logistics_days` 套用所有跨仓候选。`available` 只由客户使用期硬冲突和设备生命周期决定；另行返回 `warnings[{code, overlap_days, predecessor_rental_id, successor_rental_id}]` 与 `relay_candidate`，不能把软警告伪装为不可用。响应同时返回主设备所在仓手机支架/三脚架由逻辑单元聚合的 `total/reserved/available`，以及每种附件的实时事实 `requested/travels_with_device/fulfilled/relay_confirmation_required/shortage/display_hint`；这些是响应时推导值而非数据库状态，且绝不返回内部 unit ID。跨仓选择规则与 D14/D15/D19 一致。
3. 一次已稳定的日期/型号/优先仓变化只调用一次 availability，不再发送逐设备/逐附件请求。冲突详情若确需展示，通过用户显式展开时的一次批量详情请求获取，默认响应不传客户电话、地址或完整冲突订单。
4. 桌面与移动端共用上述契约，现有 `/api/rentals/check-conflict` 和 `/api/rentals/find-slot` 在迁移期由同一 `AvailabilityService` 实现，客户端全部切换后再删除兼容路由。
5. 编辑场景推荐 `GET /api/rentals/{id}/edit-context` 一次返回权威 rental 编辑 DTO、当前仓库/设备选择和表单所需附件配置；一个组合 watcher 仅在弹窗由关闭变为打开或 rental id 改变时调用。移动端复用该接口，不再先加载完整甘特。
6. 移动端新建页删除未使用的 `/api/gantt/data`；创建页所需静态表单选项并入 booking bootstrap。availability 的响应只包含下拉/冲突展示需要的设备字段，不返回完整 rental/device 深层对象。
7. 客户端不提交或覆盖 origin 地址。availability 根据候选设备的 `warehouse_id` 从当前租户库读取 ready/active 仓库结构化地址，并以 warehouse 去重估算；尚未选设备时优先仓结果只标记为 preview，最终选择跨仓设备后界面立即使用该设备仓库对应结果。
8. create/update 最终事务锁定并重新读取设备、仓库、附件 request、既有 link 和候选逻辑单元，使用同一 origin + destination 再校验物流天数、客户使用期硬冲突、逻辑单元可关联性和 D33 物流警告；`USAGE_PERIOD_CONFLICT`/普通 `ACCESSORY_UNIT_UNAVAILABLE` 返回 409，接力候选待确认返回允许提交的 `ACCESSORY_RELAY_CONFIRMATION_REQUIRED`，D34 补寄例外返回允许提交的 `ACCESSORY_UNIT_SHORTAGE_WARNING`，`LOGISTICS_OVERLAP_RELAY_WARNING` 也必须允许提交并随成功响应返回。若预览后、写入前设备已调仓，返回 409 `ORIGIN_WAREHOUSE_CHANGED` 及新的仓库/估算摘要，要求用户确认后重试，不能沿用旧深圳值或静默改变档期。订单一旦成功建立，后续调仓遵循 D21：只提醒检查，不自动修改既有 rental 字段。
9. 收货地址至少结构化保存省、市、区县和详细地址，并保留用户确认后的原始展示文本；从闲鱼导入的 `prov/city/area/town/address` 直接映射结构化字段。自由文本无法可靠解析时要求用户确认地区，不静默按默认 3 天计算；provider 不可用时由 Admin/Operator 明确填写并确认物流天数。

#### Logistics estimator provider (D19 confirmed)

| 方案 | 优点 | 代价/风险 | 建议 |
|---|---|---|---|
| 租户顺丰凭证调用官方时效查询 | 起终点、产品类型和发件时间均可传入，最接近真实承运能力 | 依赖租户账号接口权限、第三方延迟/限流；必须验证生产 entitlement | 主路径；仓库中已有 `EXP_RECE_QUERY_DELIVERTM` 报文样例，但当前业务 SDK 尚未接入，Phase 0 先做真实账号 capability test |
| 平台维护省市静态矩阵 | 无第三方依赖、响应快 | 双向路线、节假日和产品差异难维护；当前表只适用于深圳起点，不能直接扩为多仓事实 | 不作为权威主路径；最多以后作为明确标注的提示性 fallback |
| Operator/Admin 人工填写物流天数 | provider 故障时仍可建单，业务人员可结合实际经验 | 需要人工判断，过短会产生到货风险 | 推荐 fallback；必须显示 origin/destination、估算不可用原因，并记录操作者、填写值和确认时间 |

已确认采用“官方时效查询优先 + 人工确认 fallback”，不再静默返回固定 3 天。调用只针对当前优先仓或最终选中设备仓，不按设备逐台请求；同一 availability 请求内按 warehouse 去重。已落单记录保存当次估算快照作为订单事实和调仓提醒时的检查依据，不能被其他页面当作库存缓存，也不能在后续调仓时被系统自动覆盖。

#### Gantt view

1. 新增 `GET /api/gantt/view?start_date=&end_date=&device_model_id=&lifecycle_status=`，在一个只读数据库快照中返回扁平 `devices`、扁平 `rentals`、整个范围的 `daily_stats_by_date`、型号 facets，以及首页只需展示的待归还/闲鱼告警 count 与 revision；不在每个 device 中重复嵌套 rentals。
2. 默认窗口沿用桌面 16 天、移动端 14 天，服务端允许的最大窗口建议 62 天；必须按日期/型号/生命周期筛选和字段裁剪，超限返回 400，避免为了减少请求制造无上限巨型响应。
3. 移动窗口、改变服务端筛选或业务写入后的刷新各触发一次 view 请求；不再调用逐日 `daily-stats`，删除前端 `statsCache`。待归还/告警完整列表仅在用户打开抽屉时按需加载，外部闲鱼刷新由后台任务或用户显式操作触发，不在每次甘特挂载时同步调用第三方。
4. 迁移期可先提供单次范围接口 `GET /api/gantt/daily-stats?start_date=&end_date=`，但目标态应并入 view；旧单日参数保留一个发布窗口并返回 deprecation 指标，两个前端迁移完成后删除。
5. mutation 不再在 store 内隐式刷新。由页面成为唯一 refresh owner：写接口返回提交事务后的精简权威 DTO、`data_revision` 和 `refresh_scope`，页面随后最多发起一次当前窗口的 view 请求更新全部派生统计；不得同时由 store、页面回调和 watcher 各自刷新。
6. 同一页面使用无持久结果的 request coordinator：同一事件循环/短 debounce 窗口内多个刷新信号合并为一次，参数变化则取消旧请求并仅接受最新 sequence。它只合并在途工作，不复用已完成的库存响应，因此不构成本地缓存。

#### Lower-priority consolidation candidates

审计已发现以下候选项。P0 与 SaaS Core 同批处理；P1 是否进入 Core 由 Phase 0 实测请求数、SQL 数和压缩字节决定，不把低收益接口强行聚合。

| 优先级 | 页面/问题 | 推荐目标态 |
|---|---|---|
| P0 | mutation 后 store 与页面重复刷新 | mutation 无隐式 GET；页面最多一次范围 view 刷新，写响应可直接用于确认页 |
| P0 | 桌面/移动编辑页重复或串行初始化 | 单次 `edit-context` + 单一 watcher/in-flight cancellation |
| P0 | 甘特与设备状态使用重复、深层 DTO | 甘特规范化 DTO；设备状态改用分页、字段裁剪的 devices list |
| P0 | 移动新建页无用甘特读取 | 删除该请求，表单选项并入 booking bootstrap |
| P1 | 统计页 `/latest` 后再 `/recent` | `/api/statistics/overview` 一次返回 latest + series |
| P1 | 出租统计首屏 models/periodic/forecast 三请求 | `/api/rental-stats/view?include=`；不可见预测区可延迟到用户展开 |
| P1 | 待归还启动预取、打开再取、更新后双刷新 | view 只含 count；抽屉按需分页；写响应返回更新行和新 count |
| P1 | 闲鱼告警首屏 GET + POST 且每账号 60 秒轮询 | 按 D18 每租户 3 分钟后台同步；view 返回快照 count/revision，页面只轮询本地摘要，显式手动刷新才创建即时任务 |
| P1 | 搜索最多 50 条深层 rental 对象 | 2–3 字起查、取消旧请求、`search-summary` DTO、默认 20 条游标分页 |
| P1 | 接力物流刷新响应未使用又重读全列表 | 用刷新接口返回的权威 tracking DTO 就地替换对应行 |
| P1 | 顺丰追踪三年数据全量返回后前端分页 | 服务端游标分页、列表摘要 DTO、轨迹详情按需读取 |
| P1 | 批量发货最长 365 天深层全量对象、逐行 PATCH | 服务端分页/字段裁剪、一次 batch express-type patch；上一单状态批量查询 |
| P1 | 验货列表携带完整 rental/device/check items | 列表摘要 DTO；打开编辑时再取完整详情 |

检查列表、租赁列表、客户历史和搜索统一使用服务端分页、字段投影及关联预加载；任何列表组件不得为每一行再请求状态/详情。顺丰物流继续使用 batch-query，不退回逐单查询。其余页面在 Phase 0 通过浏览器网络 trace + SQL query counter 排名后，仅合并确有扇出的接口，避免做一个无边界“万能首页 API”。

### 12.4 Query and payload design

- 建立统一 `AvailabilityService` 与 `ScheduleOverlapPolicy`，供预约预览、find-slot、创建/编辑事务、范围甘特、接力候选和调仓附件重新关联共同调用，但按资源类型选择不同约束，不能再把一个 `occupancy_*` 区间同时当作主设备使用期和逻辑附件 link 窗口的冲突事实。
- 主设备硬冲突使用客户使用期且首尾日均包含，批量查询条件为 `device_id IN (...) AND start_date <= :candidate_end_date AND end_date >= :candidate_start_date`；一次取回/聚合全部冲突，禁止为每个 device 调用 `.query.all()`。同一设备存在有效客户使用期重叠时返回 `USAGE_PERIOD_CONFLICT` 和 HTTP 409。
- `ScheduleOverlapPolicy` 统一计算计划物流窗口：`planned_ship_out_date = start_date - (logistics_days + 1 day)`，`planned_return_date = end_date + (logistics_days + 1 day)`。在客户使用期无硬冲突时，只比较按 `start_date, id` 排序后的相邻有效主租赁，`overlap_days = (predecessor.planned_return_date - successor.planned_ship_out_date).days`；`> 1` 返回允许提交的 `LOGISTICS_OVERLAP_RELAY_WARNING` 并成为接力候选，`<= 1` 不提示。甘特和接力不得各自复制阈值或日期公式。
- 逻辑附件可用性由 `accessory_units` 的当前持有事实与 `rental_accessory_unit_links` 的重叠时间窗共同决定；不存在第二份总量表或 allocation status。普通 request 只能自动关联同仓、active、在目标时间窗可用的单元；同一单元出现重叠 link，仅在同一主设备且关联 relay case 已 `agreed`、表示单元连续随设备流转时允许。候选阶段可保存 request 但不建接力 link；任何 edge 进入 `agreed` 或在实际交接前撤销同意时都从该点向后重算整条链，原子写 `linked/unlinked` 事件。后单已有未发出的独立 link 时先解除再改用随行单元，已实际发出的第二单元进入人工核对。relay case 进入 `shipped` 前必须验证 holder=predecessor，之后才转为 successor 并写 `relay_handoff`；普通 rental 进入 `shipped` 前必须验证 holder 为空，之后写 `dispatched`。中间单未勾选不建 request，但为随行单元建立 link；在外单元可建立预计回仓后的不重叠未来 link，却不能计入当前可用或绕过实际发货复验。设备链未携带而接力后单需要附件时尝试关联另一同仓单元，无单元则保存无 link 的 request + 内部备注并返回非阻断接力的不足警告。
- `logistics_days` 为 0–7 的整数且 0 必须保留，不能被 `|| 1` 改写；前后额外 1 天是固定操作缓冲，不混入物流天数的字段语义。页面同时展示物流天数、缓冲天数、计划寄出日和计划回仓日，避免把“0 天物流”误解为完全没有缓冲。
- `not_shipped`、`scheduled_for_shipping`、`shipped`、`returned` 参与硬冲突、物流警告和未结束附件 link 窗口；`completed`、`cancelled` 不参与未来单元关联。计划寄出/回仓字段仅随租赁日期或物流参数的显式编辑而重算；实际发货和实际归还分别写 `actual_shipped_at/actual_returned_at`，不得覆盖计划字段。预览、find-slot、最终事务、甘特和接力共用同一状态集合与黄金测试。
- 最终 create/update 事务先按设备 ID，再按附件类型与逻辑单元 UUID 固定顺序锁定涉及的主设备、request、link、已关联单元和候选单元，再分别执行客户使用期硬冲突、单元可关联性与物流警告分析。普通硬冲突整体回滚并返回 409；D34 接力不足例外和物流警告允许写入并返回 warning，不能误当资源已满足。
- 范围甘特统计一次读取有效设备与范围内相关租赁，使用 SQL `GROUP BY` 或应用内 interval sweep/difference array 同时计算全部日期，并批量返回 D33 warning、`overlap_days` 和相邻订单技术 ID；不得为警告另发逐单请求。关联使用显式 join/selectinload 和专用 DTO，查询次数必须与展示天数、设备数无关。
- 建议验证并按 `EXPLAIN ANALYZE` 调整复合索引：主设备硬冲突使用 `rentals(device_id, status, start_date, end_date)`；物流警告/接力使用计划寄出/回仓日期索引；逻辑附件候选使用 `accessory_units(accessory_type_id, warehouse_id, condition_status, current_holder_rental_id)`，占用窗口使用 `rental_accessory_unit_links(accessory_unit_id, reservation_start_at, reservation_end_at)`，需求匹配使用 `rental_accessory_requests(rental_id, accessory_type_id)`，历史使用 `accessory_unit_events(unit_id, timestamp)`。索引顺序最终以真实数据分布与执行计划确认，不凭字段列表盲目上线。
- booking bootstrap 和 gantt view 使用显式 response schema，只传页面实际字段；日期使用 ISO 8601，枚举使用稳定 code，响应包含 `evaluated_at` 和 `request_id`。Nginx 保持 JSON gzip，TLS 边缘启用 HTTP/2；不通过重复 ORM 展开传输同一 rental/device。
- 列表与页面聚合 DTO 和编辑/详情 DTO 分离：列表不得调用通用深层 `to_dict()`，不得嵌套未在当前页面展示的 child rentals、完整 device、全部检查项或客户 PII。接口响应体设置基线和告警，但阈值以 Phase 0 的真实设备/订单量压测后确认。
- 每个聚合请求在认证控制库检查后，对目标租户业务库只建立一个 session/只读事务并复用同一连接；同一请求内不得为子服务各自创建 engine/session。非生产环境记录每路由 SQL 数、租户连接 checkout 数、未压缩/压缩响应字节和 `Server-Timing`，生产只输出聚合指标。

### 12.5 Connection and request budgets

- 发布门禁测试夹具至少包含 100 台主设备、多个仓库、多个同类型逻辑附件单元和 31 天重叠订单。booking bootstrap 最多 1 个 HTTP 请求；每次稳定筛选变化最多 1 个 availability 请求，availability 租户库 SQL 建议不超过 6 条且不随候选设备数或逻辑单元数增长。
- 甘特一次进入/窗口移动/筛选刷新最多 1 个核心 view 请求，不得再出现逐日请求；租户库 SQL 建议不超过 8 条且不随天数/设备数增长。抽屉详情和用户主动第三方刷新不计入核心 view，但只能由明确交互触发。
- 任一 create/update/delete/ship/device mutation 成功后，除写请求本身外最多触发 1 个当前窗口 view 请求；E2E 必须断言 store、页面回调和 watcher 不会产生第二次刷新。打开编辑页/弹窗最多 1 个 edit-context 请求。
- E2E 通过拦截网络请求断言 fan-out；SQL query-count 测试分别把设备数和日期窗口扩大 10 倍，查询条数不得线性增长；响应契约测试断言 rentals 不重复嵌套、无非必要 PII，压缩后字节数进入基线趋势。
- Nginx 删除普通 API 的无条件 WebSocket upgrade 头，使用 HTTP/1.1 upstream keep-alive；若未来确需 WebSocket，只在专用 location 使用 upgrade。浏览器到 TLS 边缘使用 HTTP/2，多请求迁移期也复用连接。
- 每租户 engine 使用小连接池和有界 LRU；不能沿用当前每 worker `pool_size=10`。总连接理论上限按 `Web 进程数 × engine cache 上限 × (pool_size + max_overflow) + worker/control/provisioner 预留` 计算，并低于 MySQL `max_connections` 的已批准预算；具体 pool/cache 数值在 Phase 0 压测后作为 D10 容量决策确认。

### 12.6 Rate limiting

- 短信 challenge 使用控制库原子计数：手机号在所有 purpose 间共享 5 次/滚动小时和 10 次/Asia/Shanghai 自然日额度；可信来源 IP 共享 30 次/滚动小时和 200 次/Asia/Shanghai 自然日额度。发送成功、provider 结果未知以及已提交腾讯云但业务响应丢失均消耗额度，明确在调用 provider 前失败的本地校验不消耗发送额度；不得通过换 purpose、并发请求或重复超时重试绕过。
- 60 秒冷却使用手机号最近一次 `sent/send_unknown` 时间，5 分钟有效期从验证码创建时计算；新验证码进入 `sent/send_unknown` 后立即锁定同手机号同 purpose 的旧 challenge。单 challenge 第 5 次错误在同一原子更新中转为 `locked`，成功消费与并发错误尝试只能有一个终态结果。
- 来源 IP 只接受 Nginx 来自已配置 trusted proxy/network 的转发值；应用入口先清除客户端自带的伪造 `X-Forwarded-For`，再由可信代理重建。无法取得可信 IP 时按更保守的 unknown bucket 计数，不能跳过 IP 限流。
- D37 阈值及 `policy_version` 由部署配置提供而非散落代码常量；修改须经发布记录并同步腾讯云控制台，已有 challenge 继续使用签发时版本。429 返回稳定 reason code 与 `retry_after_seconds`，但发送接口仍使用不泄露账号是否存在的统一响应形态。
- 登录和兑换码的非短信动作继续按手机号/IP/设备使用控制库滑动或固定窗口计数；业务 API 按 tenant + user/session 限流，高成本导出/排程另设并发限制。
- 对 availability、gantt view 和搜索限制日期跨度、ID 数量、分页大小和并发；429 响应包含可重试信息，但不泄露套餐内部规则。

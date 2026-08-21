# Identity and Product Workflows

> 返回：[总体设计索引](../design.md)

## 6. Identity and Access Control

### 6.1 Browser authentication

- SaaS Core 使用手机号 + 短信验证码无密码登录。D46 已确认所有 tenant identity 入口只接受中国大陆 `+86` 手机号，服务端通过一个版本化 `PhoneIdentityNormalizer` 统一解析/校验并保存 E.164 规范值，在控制库全局唯一；注册、登录、邀请/接受、换号、删除和其他短信复验不得各写一套格式规则。
- 页面固定显示不可切换的 `+86` 前缀，用户输入中国大陆手机号 national number。共享服务端规范器只接受 ASCII `1xxxxxxxxxx`，或带显式 `+86` 的等价形式；可以移除 ASCII 空格和短横线后再解析，但拒绝无 `+` 的 `86...`、`0086...`、全角/其他 Unicode 数字、字母、括号、分机和其他歧义格式。使用固定版本且可升级的号码元数据库确认 region=`CN` 且类型为有效 mobile，成功输出唯一 ASCII `+861xxxxxxxxxx`；不信任客户端规范化结果，也不在业务代码散落容易过期的运营商前缀正则。
- `+852` 香港、`+853` 澳门、`+886` 台湾及其他国家/地区号码在创建 challenge、占用邀请席位或写 user 前被明确拒绝，并且不能调用腾讯云发送；格式不同但代表同一 `+86` 号码的输入必须落到同一 `phone_e164`、唯一约束、验证码冷却和防刷计数桶。未来扩展国际号码时新增 provider routing/资质/合规并迁移允许范围，不改变已存 `+86` E.164 身份。
- 号码规范化必须发生在账号查找、HMAC、手机号/IP/用途限流和 provider adapter 之前；`SmsProvider` 内部只接受 canonical `+86` E.164，若调用者传入非规范值则 fail closed 且不产生 delivery attempt。格式/地区错误可明确提示“Core 仅支持中国大陆手机号”，但对已支持格式的登录/发送响应仍不得泄露账号是否存在。
- `phone_verified_at` 只表示当前 `phone_e164` 已完成对应 OTP：兑换码注册和接受邀请在验证码消费事务中设置；换号只在新号码 OTP 成功、唯一约束复验和提交时更新。首次默认租户迁移只创建未验证手机号身份，不能因为 CLI 操作者录入号码就标记已验证；首位 Admin 第一次成功短信登录后才设置。
- D46 只限制 tenant user 的身份手机号和对应安全短信。客户收货电话、仓库联系人/寄回电话、顺丰收寄/查询电话及其他业务字段不自动套用 `+86` 身份校验，而按各业务和 provider 的明确规则处理；平台管理员继续使用独立用户名，不受该手机号范围影响。
- 生产验证码由 D35 已确认的腾讯云平台账号发送；短信签名固定为平台运营主体的统一签名，不读取租户显示名称、公司全称或仓库资料，也不允许租户自带签名覆盖。登录/注册页面应明确这是平台账号验证，而不是某个租户以自己名义发送的通知。
- 验证码 challenge 保存在控制库，只保存平台根密钥按短信专用用途派生 key 后计算的 HMAC、用途、过期时间、错误次数和发送上下文，不保存可离线穷举的普通六位码哈希，也不把验证码明文写入数据库或日志；校验使用常量时间比较。
- 同一验证码只能成功使用一次，并使用明确的 register/login/accept-invitation/D48 action/phone-change/delete purpose；不保留可跨动作使用的通用 `sensitive_action` 或“近期已验证”标记，禁止跨用途、跨 context 或跨 session 复用。
- 登录成功后在控制库创建 `tenant_user_sessions` 并签发独立于平台后台、固定 tenant Cookie 名和 `/` path 的 host-only Cookie；Cookie 设置 `Secure`、`HttpOnly`、`SameSite=Lax`，生产环境强制 HTTPS。Cookie 只含高熵不透明随机 bearer token，不含 user/tenant/role/auth version、签名载荷或业务数据；数据库只存 token 摘要。token 不进入 URL、HTML、日志、审计、错误、指标、localStorage、IndexedDB 或 Service Worker cache。
- 短信 challenge 的单次消费、必要时把同一 canonical 号码的 NULL `phone_verified_at` 设置为当前服务端时间，以及会话创建必须在同一控制库事务完成；该补写只适用于已由迁移创建、且本次 `login` OTP 已成功的同一用户，不能借此改号或验证别的号码。同一 challenge 并发校验最多产生一个有效 session。服务端使用 CSPRNG 生成至少 256 bit token，若极低概率命中唯一摘要冲突则丢弃并安全重试；任何登录前 Cookie或本浏览器旧登录 token 都不能被升级复用，成功后生成全新 token 并撤销被替换行，防止 session fixation。没有 MySQL 当前有效行时一律未认证，不能解析 Cookie、使用进程缓存或回退旧无状态会话。
- 每次请求实时核对 session、`users.auth_version`、`tenant_access_version_at_issue`、唯一 membership、角色、tenant `status/access_version`、D52 suspension intent，以及外部部署 marker 对应的 current recovery run 和本 tenant hold。current run 下缺 hold、run/revision 不匹配或 hold 非 `released` 时，不签发正常 tenant session，也不进入 tenant 业务库；host restore 与 `tenant_restore_event` 重新安装的单租户 hold 使用同一规则，只能返回无 PII 的统一恢复中提示，平台 SELECT-only 与恢复控制面按独立 capability 运行。应用门禁是即时 deny 的权威：一旦 hold/suspension/deletion intent 事务提交并提升 access/login-state version，router 立即拒绝新 checkout、清退旧 engine；即使 MySQL `observed_login_state` 尚在异步收敛，物理延迟也不能重新开放应用访问。进入 `suspending/suspended` 时，暂停前的全部 session 已在服务端撤销；用户仍可重新短信登录受限页面，但 Operator 只允许暂停说明与注销，Admin 只额外允许本人账号安全，任何其他前端路由或直接 API 调用均 fail closed。进入 `resuming` 的首事务再次递增 access version，此后暂不签发新 session，只返回短暂维护/重试提示，直到未发布 candidate DML generation 验证并由最终 CAS 发布且状态回到 active/expired；因此暂停期间 session 不能跨恢复边界变成正常业务 session。`last_seen_at` 使用数据库条件更新合并短时间内重复写入，不依赖 Redis、浏览器缓存或跨请求业务数据缓存；空闲/绝对时长和活动时间写入间隔是版本化安全配置，并用服务端时间判定。
- D56 已确认采用统一的过期门禁：subscription 按数据库当前时间归约为 `expired` 后，任何具有有效 membership 的用户都可完成短信登录，但只能进入同一个过期/续费受限页面。Operator 只可读取该页所需的最小订阅状态并注销；Admin 另可按既有 `tenant.subscription.redeem` 权限提交兑换码续期，但同样不能进入账号安全、设备/会话管理、换号、成员、仓库、integration、顺丰月结账号查看/绑定/解绑/验证、审计或任何其他业务/设置页面和 API。过期门禁在 capability 与对象查询之前执行，不能因 Admin 角色或“只读配置”形成旁路；只有续期最终事务成功、按当前时间把租户归约回 `active` 后，后续请求才按原 membership/RBAC 恢复正常权限。D52 的 `suspending/suspended/resuming` 也没有顺丰解绑或 integration 例外，必须由平台先完成独立恢复；若恢复结果仍为 `expired`，立即适用本条过期门禁。
- 所有 tenant-scoped 控制面写入的最终事务（成员/邀请、续期、集成/顺丰绑定、换号、删除申请等）都必须锁定每个受影响的权威 tenant 行，并以 locking/current read 同时复核外部部署 marker、current recovery run、本 tenant hold/revision、effective gate 和 expected `access_version`，再消费兑换码/验证码或写入 mutation/outbox。单租户 intent/final transaction 的统一前缀固定为 `tenant → current recovery run → current tenant hold → 未终结 deletion request → suspension aggregate/相关 suspension、release、restore action（同类按 UUID）→ tenant_databases（涉及账号/路由时）→ tenant_database_account_rotations（涉及时）→ quota guard 与 code/subscription/job/intent/challenge/outbox 等业务行`；某路径没有的对象直接跳过，不能把 run/hold、deletion、action 或 route 反向插入。account-mutation lease 的 claim/renew 必须是只触碰 lease 行的独立短事务，多 account kind 固定 `dml → platform_read`；该事务结束后才按同序取得 MySQL advisory lock。持 advisory lock 后的 final control CAS 仍从 tenant 开始走相同前缀，最后才 current-read account lease 并校验 owner/fencing token/expiry，final tx 内不得续租；token、expected generation 或版本失败时先把未发布 candidate 与 published/from/to/orphan DML 账号收敛为 locked，再释放 MySQL lock。全局 recovery-run 状态推进不得在持有 run row 时再反向锁 tenant/hold，只能使用已提交 coverage/处置/smoke evidence 做 current read/CAS，不满足即退出。任何新增权限/资源的目标租户必须是 current run 的 `released`；hold 下只允许 D58 review、D52 freeze/enforce-locked、D26 删除提交、单租户恢复隔离、失效 invitation/challenge/code/job 等单调收紧操作，不能恢复暂停、撤销删除或发起业务/provider 动作。D58 release、D52 resolve 或 D26 合法取消删除需要恢复 DML 时，旧 published generation 始终保持 locked；只可在应用 deny 和双锁下临时解锁未发布 candidate 做正反测试，final CAS 成功才发布，CAS 前崩溃由 reconciler 先重锁/撤销 candidate。D47 这类会协调多个租户的身份事务仍以已定的 `canonical user → invitations → 按 UUID 排序的 tenants` 为前缀，再对每个 tenant 按上述 run/hold/gate/guard 后缀执行；只有获胜/要加入的 tenant 必须通过 join gate，losing tenant 即使已 held/suspended/expired/deletion 也不得阻断将本租户 pending invitation 单调置为 superseded 并释放席位。这个特例只允许减权/清理，不能向 losing tenant 新增 membership、邀请、席位、任务或其他业务写入。中间件预检仅用于快速拒绝，不是提交授权；已通过预检但在提交前被 recovery run/hold、suspension/deletion/access-version 变更超越的旧请求必须全部回滚，不得消耗 code/challenge、改变席位或留下可执行任务。
- D53 在上述 tenant-first 前缀和 subscription/action 业务行之后，统一按 `platform_admin → platform_admin_session → current TOTP credential 或 recovery-code row` 取得平台认证行；所有平台登录、会话撤销、因子替换和其他 step-up 事务也必须先锁 platform admin，再锁其 session/因子，且不得反向获取 tenant 行。这样登录、两个租户上的 D53 动作、session 撤销及恢复码并发消费都由同一个 admin/factor 权威行串行化，不形成 tenant↔factor 锁序环。
- 所有状态变更请求启用 CSRF token；CORS 使用明确 allowlist，不允许生产 `*`。
- CSRF token/generation 与 session bearer token 分离，不能把 session token 回显为 CSRF token；会话列出、指定撤销和全部撤销接口均使用非 GET 方法并通过 CSRF 校验。
- 发送和校验验证码按手机号 + IP + 设备/会话 + purpose 做数据库限流。D37 固定初始策略为：6 位随机数字、5 分钟有效、60 秒发送冷却、单 challenge 错误 5 次锁定；手机号跨用途 5 次/滚动小时和 10 次/Asia/Shanghai 自然日，可信来源 IP 30 次/滚动小时和 200 次/Asia/Shanghai 自然日。腾讯云控制台限频、日限额和防盗刷告警同步为相同上限并作为第二层保护，不能替代应用自身门禁。
- 发送接口使用不泄露账号存在性的统一响应；验证码发送、成功/失败校验和风控拦截写安全审计，普通日志中的手机号必须脱敏。
- 腾讯云调用在 challenge 初始短事务提交后执行且不占用数据库连接；返回后用短事务记录 delivery attempt。只有 `sent` 或 provider 超时后的 `send_unknown` challenge 可进入校验，`pending_send/send_failed` 均拒绝；超时必须复用同一 challenge 受控处理，禁止因无法确认结果就无限生成新验证码或在日志中打印请求正文。
- 账号安全页列出当前用户自己的设备摘要、创建时间、最近活动时间和“当前设备”标记；Core 中“设备”就是一次浏览器登录 session，同一物理设备的不同浏览器/配置可能显示为不同设备。注销当前设备或指定设备必须用不可猜测 session UUID 定位本人行，先在控制库原子写 `revoked_at/reason`，再清理本地 Cookie；只删除 Cookie 不算注销。必须防止用伪造 UUID、token/hash 或 tenant ID 撤销他人会话。用户不能查看或单独撤销其他成员的设备，但 Admin 移除/停用成员时须在同一控制库事务撤销该成员全部 session。
- “注销全部设备”在同一控制库事务递增 `users.auth_version` 并撤销该用户所有活动 session，包含发起操作的当前设备；手机号变更和账号安全事件也走相同全量失效流程。单设备撤销不递增全局 auth version，避免误伤其他设备。撤销提交后任何被复制的旧 Cookie 立即失败，失败响应不得泄露该 session 是否曾存在。
- 不限制同一账号同时登录的设备数量；10 人额度只计算有效 membership 和待接受邀请，不计算 session。过期/撤销 session 由控制库任务分批清理，清理延迟不能让其恢复有效。
- 更换手机号至少验证旧手机号和满足 D46 的新手机号；使用同一 change request ID 绑定 purpose=`phone_change_old` 与 `phone_change_new` 两个 challenge，不能把新旧号码验证码角色互换，且两码必须在同一最终事务一起消费。提交时若新号码尚无 user 先创建无权限协调行，再按 canonical 值排序锁当前 user 与新号码 user，复验新号码没有未释放 membership、活动注册/换号流程或可用 session。若新号码只有邀请创建的 unverified user，则把其 pending invitation 置为 `superseded`、清空这些终态邀请的 `user_id`、使 challenge 失效并释放席位，随后删除空占位行，再写当前 user 的新 canonical E.164/`phone_verified_at`；不得更换当前 immutable user UUID。新号码若已有已验证或保留历史的独立 user，则拒绝自动合并，不能静默把两个身份的审计历史合并。此自助换号可由 Admin 或 Operator 对本人执行：旧码只能发往 AuthContext 当前 canonical 号码，新码是“接收号码固定为当前用户”的唯一例外，只能发往同一 change request 中经 D46 验证的新号码。上述变化与 `auth_version` 递增、全部旧 session 撤销在同一事务提交，用户须用新手机号重新登录。
- D57 已确认无法接收旧手机号时 Core 一律 fail closed：不提供租户或平台“找回/改号”端点，不允许平台管理员、客服、宿主机 CLI 或 DBA 直接替换 tenant user 手机号、代输/跳过 OTP、把旧身份与新身份合并、签发 impersonation session，或用短信 provider 控制台状态、送达回执、其他收件号码及人工证明替代旧号 challenge。若租户已有另一名 active Admin，只能由该 Admin 从自己的正常 tenant session 执行既有成员流程：先按规则移除/释放旧号码的 membership，再向新号码创建普通邀请，由新号码持有人完成 invitation token + `accept_invitation` OTP 后建立全新的 membership；目标为 Admin 时，旧 Admin membership 的移除和新 Admin invitation 分别遵循 D48，不能用一个验证码或组合“恢复”接口打包绕过。新旧 user/membership UUID 不得重定向、复用或合并，历史业务记录、actor UUID、membership 来源和审计事件继续指向原身份，不因同一自然人重新加入而改写。若丢号者是最后一名 active Admin，Core 没有恢复入口；pending Admin invitation 不计作替代 Admin，也不能据此移除最后 Admin，只有一条此前合法创建的邀请被新手机号正常接受并实际形成另一名 active Admin 后，才可按上述普通流程处理旧 membership。
- 平台管理员使用 D43 已确认的独立全局账号、密码、TOTP 和一次性恢复码。首个账号由受控 CLI 创建短期单次 setup challenge；管理员在 setup-only 页面设置正式密码、绑定并确认 TOTP、一次性展示恢复码后才能获得平台能力，不创建可长期使用的临时密码。没有公开注册、租户手机号 OTP、邮件/短信 fallback 或代码默认账号；失去密码或全部第二因子时只允许宿主机 CLI 经审计重置。

#### Tenant Admin high-risk confirmation (D48 confirmed)

- 租户 Admin 没有登录密码、操作密码或长期 TOTP；高危操作只使用腾讯云短信验证码二次确认。需要复验的 Admin 动作固定包括：第三方 integration credential 创建/更新/删除及仓库顺丰月结账号绑定、解绑、换绑；邀请为 Admin、现有 Operator 提权为 Admin，以及任何让现有 membership 的 effective Admin 权限从无到有或从有到无的变更（包括启用、重新激活、降级、停用、移除）。兑换码注册创建首位 Admin 已由兑换码 + `register` OTP 授权；受邀者接受 Admin invitation 则由创建邀请时的 D48 + 受邀者 `accept_invitation` OTP 授权，这两条路径都不再叠加第三个验证码，但 invitation 角色必须不可变。租户删除申请及冷静期撤销也要求专用验证码。Admin/Operator 更换本人手机号使用既定 old/new 两码。已经确认纳入 Core 的 D53 平台服务期调整使用独立的平台 TOTP/恢复码规则，不属于租户短信复验。
- 仅邀请、启用、停用或移除 Operator，以及库存、设备、仓库资料、租赁、发货、打印、验货、接力和调仓等普通业务动作不触发 D48。最后一个有效 Admin 在任何情况下都不能被降级、停用或移除；验证码只证明当前操作者仍控制手机号，不提升角色、绕过 entitlement/tenant 状态、替代 CSRF 或放宽业务规则。pending Admin invitation 不算有效 Admin。
- 发码前服务端必须使用当前 `AuthContext` 的 user/session/tenant，实时复核该动作所需 capability：integration、Admin membership 和 tenant deletion purpose 只允许 active tenant 的 active Admin；active Admin 或 Operator 通常只能为自己发起 phone change，不能修改他人号码。D52 suspension 是唯一额外状态例外：受限页面中的 active Admin 仍可为本人申请/提交 phone change，Operator 不可；该例外不能扩大到成员、集成、续期、删除或业务动作。除 `phone_change_new` 外，接收号码固定为操作者当前 canonical `+86` E.164 且请求体不能指定；`phone_change_new` 只能取自同一 change request 中经 D46 规范化并绑定的新号码，并在最终事务与发往当前号码的 old challenge 一起消费。服务端使用版本化、无歧义的 canonical serialization（固定字段顺序、类型和长度边界），对 tenant、actor、session、purpose/action subtype、目标技术 ID、目标 current revision 和规范化请求正文计算带密钥的 context digest。包含凭证的请求只短暂参与 digest 计算，原文、普通可枚举 hash 和 Secret 都不写 challenge、日志或审计。
- 确认请求必须在同一浏览器 session 重新提交完全相同的规范化动作 payload 和该 intent 所需验证码（普通动作一枚，换号为 old/new 两枚）。服务端再次实时检查 user/session、动作所需 capability、tenant 状态、目标 revision、CSRF 和普通业务约束并重算 digest。能在控制库单事务完成的动作，在同一事务消费全部必需 challenge、提交变更、推进 intent 并写权威安全事件；跨库/provider 动作则在同一控制库事务消费 challenge，并持久化加密后的配置 revision 或 claim reservation、一次性 authorized intent、权威安全事件与 outbox，worker 只按 immutable 技术 ID/revision 幂等执行。job 不保存验证码、手机号、原始 Secret 或请求正文，验证结果也不形成可授权其他动作的时间窗口。
- 所有会改变 Admin 有效性的路径使用同一控制库事务和与 D47 相同的锁序：相关 `users` 行按 UUID 稳定排序 → 相关 invitation 行 → `tenants` 行按 UUID 排序 → 对应 `member_seats` guard 同序 → memberships 按 UUID 稳定排序 → challenge/intent/session/event。取得 tenant 行后先复验 effective gate/access version，取得 guard 后以 locking/current read 重数 D51 席位；然后按 user 与 membership 同时 active 重新计算变更后的 Admin 数，必须至少为 1。随后把 challenge 消费、membership CAS、被降级/停用/移除者全部 session 撤销和安全事件原子提交。两个 Admin 并发互相降级、停用或移除时只能一个事务成功；任何可重新启用为 Admin 的入口也必须执行相同 D48 门禁，不能以“恢复成员”绕过提权验证。
- 第三方 integration credential 的 action UUID/idempotency key 在重试时保持不变。若首次成功响应丢失，重试只返回已完成的非秘密配置元数据，不回显凭证，也不创建第二条 credential revision；用户若确实需要更换凭证，必须用新验证码发起更新。任何 target revision 或 payload 改变都需要新的 action/challenge。
- D37 的 6 位、5 分钟、60 秒冷却、5 次错误及手机号/IP/设备/purpose 防刷全部适用。手机号更换已经要求 old/new 两个绑定同一 change request 的验证码，删除申请/撤销分别使用 `tenant_delete`/`tenant_delete_cancel`，这些专用验证即满足 D48，不额外要求第三个验证码。短信 provider 不可用或结果未知且无法安全核实时，高危动作不得降级为仅登录态、人工勾选或平台代输。
- 每次发码、成功、失败、过期、重放和最终动作结果都写不含验证码、完整手机号、payload、context digest 或 Secret 的控制库权威安全审计；租户库中的展示性审计只能通过 outbox 投影。页面在真正提交前明确展示动作对象和影响；验证码框不得自动填入测试固定码，返回/刷新不能把已消费 challenge 当作仍有效。

### 6.2 Fixed role matrix for v1

首发保留两个身份域中的三个固定身份类别：平台身份域只有 `platform_admin`，租户身份域只有 Admin、Operator。平台管理员不是 tenant role，租户成员也不能通过角色变更提升为平台管理员。权限在后端以 capability 字符串判断，前端仅用于隐藏/禁用界面，不是安全边界。

D55 已确认 SaaS Core 完全不提供 tenant API key：不定义相关 capability、数据表、鉴权中间件、创建/轮换/撤销/查看端点、Secret 展示流程或前端入口。若未来需要机器访问凭证，必须作为 Core 之外的新能力另行设计，不能复用第三方 provider integration credential。

| 能力 | 平台管理员 | Admin | Operator |
|---|:---:|:---:|:---:|
| 生成/查看/撤销兑换码 | ✓ | － | － |
| 查看所有租户、任务和 schema 状态 | ✓ | 仅本租户摘要 | － |
| 只读查看设备、档期、租赁和统计 | ✓（跨租户） | ✓ | ✓ |
| 创建或修改设备、档期和租赁 | － | ✓ | ✓ |
| 只读查看仓库和设备所在仓 | ✓（跨租户） | ✓ | ✓ |
| 即时改变设备仓库 | － | ✓ | ✓ |
| 发货、打印、闲鱼同步、接力和验货 | － | ✓ | ✓ |
| 查看客户手机号和地址 | ✓（列表脱敏，完整查看审计） | ✓ | ✓ |
| 只读查看成员和集成状态 | ✓（跨租户，不显示 Secret） | ✓ | － |
| 管理租户成员和集成配置 | － | ✓ | － |
| 使用兑换码为租户续期 | － | ✓ | － |
| 增加/减少服务期或立即到期（每动作 fresh TOTP/恢复码） | ✓ | － | － |
| 暂停/恢复租户（近期平台第二因子 + 原因 + 审计） | ✓ | － | － |
| 灾备逐租户审核/放行（本次 DR 新会话 + 近期平台第二因子） | ✓ | － | － |

- 兑换码注册成功后的首位成员自动成为 Admin。
- Admin 可以邀请 Admin 或 Operator，也可以修改角色、启停或移除成员；邀请/提权/重新启用为 Admin，以及降级/停用/移除现有 Admin，均必须通过 D48 动作专用短信复验。不能降级、停用或移除租户最后一个有效 Admin，即使验证码正确也不例外。仅邀请、启停或移除 Operator 不要求二次验证码。
- D57 的丢号替换不增加 capability 或特殊成员状态：成员页只能调用上述正常移除与邀请动作，不能编辑现有 member 的手机号、把 invitation 直接绑定旧 membership、复制旧 role/source/actor UUID，或把 pending invitation 当成已建立的 Admin。旧成员为 Admin 时，执行移除的另一名 active Admin 必须用自己的 D48 验证；新号目标为 Admin 时，创建邀请再独立使用自己的 D48 验证，新号接受时仍使用自己的 `accept_invitation` OTP。
- 成员页分别显示“有效成员”“已停用成员”和“待接受邀请”，并在创建邀请前使用 D51 唯一谓词展示 `有效成员数 + 本租户未过期 pending 数 / 10`；邀请默认 7 天有效。重新生成本租户同一手机号 pending 邀请只轮换 token、令旧链接立即失效并从生成时重新计算 7 天，不新增一条席位占用；Admin 可复制新链接或随时撤销，系统不调用短信通知接口。同一手机号在其他租户是否存在邀请、最终加入了哪个租户都不能在本租户页面或错误中显示；因 D47 自动失效时只显示本邀请“已失效”。
- Operator 拥有现有日常业务的读写权限，不拥有成员、订阅和第三方凭证管理权限。
- 平台管理员是独立控制面身份，不创建 tenant membership；可经平台只读入口选择任一租户查看业务，但没有任何 `inventory.write`、`rental.write/ship`、`inspection.write`、`tenant.members.manage` 或集成写 capability，也不能生成租户会话。平台页面不得复用普通租户写组件或用“按钮隐藏”充当只读边界。
- D58 recovery 页面按 current run 显示不含 PII 的覆盖摘要、held/reviewing/released/kept-closed/tombstoned 数量、已接受 smoke evidence 的类型/版本状态、备份至故障的不确定时间窗及单个 tenant 审核入口；不提供 release-all、按筛选批量放行或“同时恢复全部码/job”。平台管理员可以用既有 SELECT-only 入口读取选中 tenant 的必要核对数据，但 release 本身仍须新 session、近期 TOTP/恢复码、单目标 expected revision、原因和不可变审计；平台只读能力不能直接改 hold/DML route。DR-only scratch evidence 只显示非敏感测试与销毁证明，不伪装成真实租户，也不能从页面进入普通 tenant route。
- Admin 与 Operator 中满足 D51 唯一有效成员谓词的 membership，加上本租户未过期 pending invitation，合计最多 10 个；注册创建的首位 active Admin 占用一个名额，平台管理员不占名额，同一用户的多设备会话不重复计数。disabled/released membership 和 disabled user 不占席，但任何重新启用都必须先取得 `member_seats` guard 并复验容量；tenant expired 或处于 suspending/suspended/resuming 本身不释放席位。

代码中不直接散落角色名判断，而判断 `inventory.write`、`rental.ship`、`inspection.write`、`customer.pii.read`、`tenant.members.manage`、`tenant.subscription.redeem`、`platform.redemption_codes.manage`、`platform.subscription.adjust` 等权限。Core 的 fixed platform-admin role 静态包含后者，不实现逐管理员 grant UI。
拥有 capability 只是 D48 高危动作的第一层授权；对应写接口还必须验证并消费动作专用 challenge。前端隐藏、普通登录 session、另一个 Admin 的验证码或平台管理员身份都不能替代该门禁。

### 6.3 Platform access

平台管理员身份与 tenant membership 分离，平台接口使用 `/platform/api/...` 独立蓝图、独立 host-only Cookie/CSRF、服务端 session 和独立审计。平台 Cookie 固定 `/platform` path 并设置 `Secure`、`HttpOnly`、`SameSite=Lax`；密码验证、TOTP/setup 阶段和 MFA 完成签发正式会话的每次权限提升都轮换 token，所有平台控制面写方法强制 CSRF。D43 的密码 + TOTP + 恢复码完成认证；D44 的全局业务读取只允许 `/platform/api/tenants/{tenant_uuid}/read/...` 一类显式只读路由，服务端从可信 registry 解析租户并强制使用 SELECT-only 数据库账号。禁止把平台 session 传入普通租户 API、生成 membership、调用租户写 service、接受任意数据库名或 impersonate。列表 PII 默认脱敏，显式查看完整值记录 actor、tenant、resource、reason 和 request ID；每个读取请求无论结果都记录平台审计，审计不可写时拒绝返回业务数据。Core 不提供跨租户业务数据批量导出、打印、文件生成、无审计全局搜索或 live provider 查询。

- 平台密码使用版本化 Argon2id 等抗暴力哈希和常量时间验证，登录按账号/IP/设备限流并使用不泄露账号存在性的错误；不把密码可恢复加密，也不允许管理员查看另一管理员密码。安全参数升级后在下一次成功验证时原子 rehash，失败或回滚不能把新 hash 降级为旧参数。
- 首位平台管理员通过 `inventoryctl platform-admin create` 一类宿主机 CLI 创建短期 setup challenge，而不是长期默认密码；首次成功设置密码并确认 TOTP 前账号保持 `setup_pending`。CLI 创建、解锁、密码重置、TOTP/恢复码重置都必须在生产审计中用 `os_operator/cli_break_glass` actor 留下操作者安全标识、目标管理员、command/correlation id、时间和结果；session 允许为空，且不能接受命令参数或环境变量中的明文密码、TOTP seed 或恢复码。
- TOTP 使用版本化的标准时间型一次性验证码参数，seed 只在绑定二维码阶段短暂显示并加密保存；校验有严格速率限制和很小的时钟容差，使用 `last_accepted_time_step` 原子拒绝同一时间步重放，不能记录验证码。active 管理员始终必须恰好有一个 current confirmed TOTP；只允许先确认新凭证再原子替换旧凭证，不能裸关闭。成功替换 TOTP 同事务递增 recovery-code generation、撤销旧平台 session 并生成一批只展示一次的新恢复码；CLI 重置或异常移除 TOTP 时立即递增 `auth_version`、撤销全部平台 session 和旧恢复码，并把账号置为 `setup_pending/recovery_pending`，完成新 TOTP 后才能恢复 `active`。
- 恢复码只在 TOTP 首次确认或主动重新生成后展示一次；每枚高熵、单次使用，只保存带 generation 的不可逆摘要。登录仍必须先验证正确密码，再以一枚未使用恢复码替代本次 TOTP；使用、失败尝试和重新生成均审计，重新生成递增 generation 并立即作废旧集合。密码和全部第二因子同时丢失时只能 CLI 重置，不能让恢复码成为单因子后门。
- 平台管理员停用、密码/TOTP 重置或安全事件递增 `auth_version` 并撤销全部平台 session。最后一名 active 管理员保护使用两阶段流程：CLI 先创建 `setup_pending` 继任者，继任者独立完成密码/TOTP/恢复码设置并变为 active；之后另一受控事务重新锁定账号集合、核对至少仍有一名其他 active 管理员，才允许停用旧管理员。数据库事务不能跨越人工网页登录，也不能用未完成 MFA 的 pending 账号满足最后管理员约束。
- D52 暂停与恢复租户属于高危平台控制面动作：必须从可信租户列表取得 tenant UUID/current row version，平台 session 的 `mfa_verified_at` 仍在近期 step-up 窗口内；超窗时重新验证 TOTP，或按 D43 消费一枚恢复码替代本次 TOTP。请求必须提供受限 reason code、长度受限且不得含 PII/Secret 的原因说明、幂等键和显式确认；目标 revision、原因或动作方向改变都必须重新 step-up。暂停/恢复状态、`access_version`、平台审计和必要 outbox 在同一控制库事务提交，审计/outbox 失败时动作不生效。
- D53 服务期调整采用更严格的逐动作复验，而不是 D52 的近期窗口：所有 active 平台管理员均可单人提交，每个新的 add/subtract/expire-now action 必须在当前有效密码会话和 CSRF 下现场验证一枚尚未接受的 TOTP 时间步，或原子消费 current generation 的一枚未使用恢复码；登录、D52/D58 或上一笔 D53 的 `mfa_verified_at` 都不能复用，也不更新为可供其他动作复用的 session step-up。preview 返回由平台根密钥按独立 `platform:d53-confirmation:v1` domain 派生 HMAC key 签名的短期、`no-store` confirmation token；token 绑定 canonicalization version、随机 action UUID、actor/session/auth version、current recovery run/hold、tenant/subscription、operation/days、reason/note/offline-reference 摘要、expected tenant/subscription、hold、未终结 deletion request、suspension aggregate/action revisions、preview 摘要、幂等键及签发/过期时间，但不含验证码、seed 或恢复码。最终提交携带原规范 payload、token 与 factor，服务端先重算摘要并验证 token/session/版本/时效，任何字段改变、跨 session/tenant 重放或篡改都要求重新预览；token 本身不是授权，也不形成可复用 step-up。factor 防重放写、subscription/reducer、唯一 subscription event 和平台审计在同一控制库事务提交；任一步失败全部回滚且不白白消费恢复码。错误 factor 的限流计数和无凭证拒绝审计使用独立短事务，不能因主事务回滚消失。相同 action/idempotency 的成功响应丢失重试先按 action UUID 命中已提交事件并返回首次结果，不再次验证 TOTP、消费恢复码或轮换平台 Cookie；同一 TOTP 时间步或恢复码并发授权两个动作最多一个成功。旧 confirmation token 因绑定 session/auth version/current run 与 gate revisions，在 D58 或任何相关变更后自动失效，无需持久 pending-action 表。Core 不设第二审批人，唯一 active 平台管理员也可按同一规则操作。
- 全局只读是“逐个选择租户后读取”，不是把所有 tenant schema 拼成共享大表。平台只读 API 使用分页、查询超时、租户范围和精简 DTO；任何写方法统一拒绝，客户 PII 在列表/搜索中脱敏，查看详情时才按专门 read capability 返回并写审计。平台 GET 使用独立的纯读 query service/DTO，不复用会刷新统计、同步 provider、创建 job 或写访问时间的租户 handler；读取只针对数据库中已持久化的事实。
- 平台业务响应统一设置 `Cache-Control: private, no-store`，页面不得把租户数据写入 localStorage、IndexedDB 或 Service Worker cache。切换 A→B→A 时取消旧请求并清空租户范围 view state，旧响应、engine 或组件状态不得覆盖新租户上下文。
- `active/expired/suspending/suspended/resuming/deletion_cooling_off` 且 schema/route 身份仍有效的租户可由平台只读排障；D52 只锁 DML 账号，不锁独立平台只读账号。进入 `deletion_committing/deleted` 后业务只读 fail closed，删除复核只读取控制面状态和永久 tombstone，不得重新创建业务 route。
- 平台只读查询执行完成后同步追加一条包含最终 outcome/result count 的不可变审计事件；只有该事件在控制库提交成功，响应才允许序列化并返回。查询失败或鉴权拒绝同样写一条最终事件。兑换码、暂停/恢复、服务期调整、删除复核等高风险控制面写操作必须与对应审计在同一控制库事务提交；若未来动作跨控制库或包含外部副作用，则先在同一事务写不可绕过的 outbox，审计/outbox 失败时不能执行后续动作。

### 6.4 Member invitation handoff (D36/D47 confirmed)

- Admin 创建邀请时只提交目标手机号和 `admin/operator` 角色。目标角色为 Admin 时，创建邀请本身必须先完成绑定 tenant、目标 canonical 手机号、角色与 expected-absent target 的 D48 challenge；Operator 邀请不要求二次验证码。服务端先用 D46 规范器取得 canonical `+86` E.164；若不存在 user，则插入一个没有权限的 `unverified` 协调行，否则复用该 canonical phone 的既有 user，并取得同一行锁。随后确认 user 仅为 `unverified/active`、尚无未释放 membership，再按 D47 统一锁序锁定本 tenant 行并复验 access gate，然后锁定本租户席位，并由数据库 pending generated-key 约束本租户/手机号最多一个有效邀请；`disabled` user 一律使用不泄露原因的稳定错误拒绝，不能借邀请恢复。Admin 邀请还须在该最终事务重验/消费对应 challenge。其他租户的 pending invitation 不阻断创建，也不得被返回、修改或计入本租户之外的席位；它们只通过同一内部 user 行参与并发协调。非法/国际号码不得创建 user/invitation、预占席位或生成 token。合法请求生成至少 192 bit 的 CSPRNG 随机 token，只保存 SHA-256 token hash；完整邀请 URL 仅在创建成功响应中返回一次。链接使用 `/invite#token=...`，浏览器 fragment 不进入普通 HTTP request target；前端从 fragment 读取后立即 POST token，随后清除地址栏和历史记录，不写入 localStorage、分析埋点、Referer 或日志。
- Core 不调用腾讯云发送邀请通知。Admin 通过微信等已有沟通渠道自行发送链接；页面明确提示链接绑定指定手机号、7 天有效且只能使用一次。链接遗失时使用“重新生成链接”，旧 token 立即失效并从新生成时间重新计算 7 天；该动作不新增席位占用并写审计。
- 打开链接只允许服务端返回最小邀请摘要，例如租户显示名称、角色和掩码手机号；token 不能直接创建 user 权限或 membership。接受者先针对该 invitation UUID 与当前 token generation 申请 purpose=`accept_invitation` 的腾讯云验证码，再把 token、challenge 和验证码提交给接受接口。该接口在一个最终事务中按稳定顺序锁定 invitation 引用的 `users` 协调行、该 user 全部未过期 pending invitation、按 UUID 排序的受影响 tenant 行、同序的 `member_seats` guard 和当前 challenge；取得 tenant 行后只复验获胜/要加入租户的 join gate/access version，losing tenant 仅允许对该手机号的 pending invitation 执行 supersede 与席位释放，不因其 suspended/expired/deletion 状态阻止获胜事务。然后才能验证并消费 challenge。若 user 仍为 `unverified/active` 且无未释放 membership，则设置当前号码的 `phone_verified_at`，仅在原状态为 unverified 时转为 active，建立目标 membership、把当前邀请置为 `accepted`，并把其他租户的 pending invitation 全部置为不可恢复的 `superseded`。若 user 已 disabled 则整个事务 fail closed，不能消费 challenge、改变状态或释放/转正邀请。当前及其他所有转入终态的邀请同时清空 `user_id`，只由新 membership 继续引用获胜 user。challenge 消费、这些状态变化、其他邀请对应未消费 challenge 的失效和各租户席位释放一次提交，不能靠异步清理收敛；事务失败时验证码也不能被单独吞掉。
- invitation、`accept_invitation` challenge 的 UUID/generation 与最终 user 的 canonical E.164 必须逐字节匹配；客户端不能替换手机号、token context 或用另一展示格式绕过规范化。token 过期、已消费、已撤销/失效、generation 过旧、手机号已有有效 membership、租户非可加入状态或席位条件变化时均拒绝，并使用不会泄露其他邀请、账号或租户详情的稳定错误。两个租户并发接受同一手机号时只有先提交 membership 的事务成功，失败方必须观察已提交归属且不能复活自己的邀请；成员以后被移除也不能恢复任何 `superseded` 邀请，只能由 Admin 新建。
- 被转发或泄露的链接在没有绑定手机号验证码时不能被接受。邀请落地页不加载第三方资源并设置 `Referrer-Policy: no-referrer`；邀请 token、完整 URL、验证码和未掩码手机号不得进入 Nginx/CDN/APM 访问日志、前端错误上报、指标、客服截图或平台审计明文。发布前须用真实代理和错误上报链路验证 fragment/POST body 均被正确排除或脱敏。
- 所有会改变同一手机号邀请或归属的路径统一锁序为：`users` 协调行 → invitation（按 UUID）→ 受影响 tenant 行（按 tenant UUID）→ 对应 `member_seats` guard（同序）→ challenge/membership；同一手机号的创建、重新生成、撤销、过期、接受、注册最终提交、换号、成员释放和删除清理都不能绕开协调行与 tenant 行。只有要新增 membership/权限的获胜 tenant 必须通过 join gate；loser 即使不可加入，仍必须允许本租户邀请 supersede/释放席位的单调清理。换号同时涉及两个手机号时按 canonical E.164 排序锁两条 user 行。challenge 消费必须联查 invitation 仍为当前 generation 的 pending 状态；accepted/superseded/revoked/expired 事务同步清空 invitation 的协调 `user_id`，并使其尚未消费的 `accept_invitation` challenge 失效，避免旧 OTP 在失效窗口重放。

## 7. API and Frontend Changes

### 7.1 API compatibility

- 新控制面 API 使用 `/api/v1/auth/*`、`/api/v1/tenant/*`、`/api/v1/members/*`、`/api/v1/integrations/*`、`/api/v1/subscription/*`。
- 现有 `/api/*` 与 `/web/*` 业务路由可先保留 URL，但统一挂认证、租户、权限和 entitlement decorator。
- 新代码返回统一错误结构：`code`, `message`, `request_id`, 可选 `details`；权限不足返回 403，跨租户对象统一按 404 处理。
- D52 门禁使用稳定 `TENANT_SUSPENDED` 错误码和 403，不把 suspension 伪装成登录失败、subscription 到期、资源不存在或 provider 故障；只有暂停说明/账号安全 allowlist 可在受限 session 下成功。
- D56 过期门禁使用稳定 `TENANT_EXPIRED` 错误码和 402；服务端 allowlist 仅包含过期页最小订阅状态、注销，以及仅 Admin 可调用的兑换码续期预览/提交。`/api/v1/integrations/*`、顺丰 connection/provider account/warehouse binding 的列表、详情、测试、创建、更新、停用、绑定和解绑，以及全部现有业务与设置 API，都必须在进入 resolver、读取租户库或返回配置元数据前拒绝 expired tenant；suspended tenant 对这些端点继续返回 `TENANT_SUSPENDED`，不存在解绑例外。
- D57 下自助换号最终接口缺少同一 request/session 的有效 `phone_change_old` challenge，统一返回 `PHONE_CHANGE_OLD_VERIFICATION_REQUIRED` 和 403，手机号、membership 与全部 session 均不变；错误不得暗示平台可恢复或接受证件、工单、provider 回执等替代材料。Core 不注册 tenant/platform 的 phone-recovery、member-phone-edit、identity-merge 或 impersonation 端点，也不提供对应 CLI 命令；平台只读 API 不能调用 tenant identity service。成员移除与新号邀请继续使用既有端点、各自幂等键、D48/席位/最后 Admin 校验和不可变审计，不增加组合式“换绑成员”API。
- D58 hold 使用稳定 `TENANT_RECOVERY_HOLD` 错误码和 503；登录/直接 API/worker/provider 对同一 held tenant 都返回一致的临时不可用语义，不泄露备份时点、审核原因、平台操作者或其他租户恢复进度。平台 release API 只接受单个可信 tenant UUID、current recovery run/hold revision、近期 MFA 和幂等键，不提供 release-all。
- 分页、导出和搜索同样必须限定租户；不得仅在详情接口做隔离。
- 对写接口增加幂等键支持，尤其是发货、打印和其他会产生外部副作用的用户操作；Core 没有支付回调或外部 API 创建租赁入口。
- API 文档只描述用户会话鉴权；Core 不发布 tenant API key 的 authentication scheme、请求头约定、数据 schema 或端点。

### 7.2 Desktop and mobile

- 新增登录、接受邀请、无权限、租户过期、租户暂停和灾备恢复中页面；登录后直接进入账号唯一租户，不显示租户选择器。recovery hold 页面只显示统一维护提示和联系指引，不创建正常 tenant session、不显示审核证据或进度。所有角色在 tenant expired 时都落到同一个过期/续费页：Operator 仅能看提示并注销，Admin 才显示兑换码续期表单；两者都不显示账号安全、成员、仓库、integration、顺丰月结账号查看/绑定/解绑、审计、其他设置或业务导航。暂停页显示平台提供的安全原因类别和联系指引，不展示平台内部备注，Operator 只有查看/注销，Admin 可进入本人设备、注销全部设备和本人换号等账号安全入口；成员、续期、integration、顺丰月结解绑和所有业务页面及其直接 API 均不可访问，只有平台完成恢复后才重新按目标状态路由。
- API client 默认携带 CSRF token，统一处理 401/403/402/409/429；401 清理本地状态并跳转登录。
- Pinia 增加 auth/tenant/entitlement store；路由 meta 标注所需权限，导航按权限和套餐展示。
- 桌面端新增成员、角色、集成、套餐/账单、审计入口；移动端首发只需登录和核心业务权限适配，复杂管理页可跳转桌面端。
- 注销、membership 失效、账号被迁移到其他租户、tenant 进入 expired 或 D52 暂停门禁时，清空所有业务/设置 store、查询缓存、选中对象和未提交草稿，只保留渲染对应受限页所需的最小状态。过期 Admin 续期成功后必须先重新读取 authoritative tenant/subscription 与 capability 再恢复业务导航；暂停恢复后不能复用暂停前或暂停期间的 session，必须重新登录并重新读取 tenant 状态。
- 换号页面只说明“必须同时验证当前手机号和新手机号”，不提供“无法接收旧号”恢复表单、客服工单、证件上传、平台代办或 provider 跳转。旧号验证无法完成时显示 `PHONE_CHANGE_OLD_VERIFICATION_REQUIRED` 的安全提示：有其他 active Admin 的成员联系该 Admin 走普通移除后重邀；最后 active Admin 明确提示 Core 无恢复入口。成员页处理丢号重建时分开展示“移除旧成员”和“邀请新号码”，在移除 Admin 或创建 Admin 邀请前分别展示 D48 确认，并提示新号将获得新的账号/membership 身份、旧记录与审计不会迁移；pending Admin invitation 未接受前仍禁止移除最后 Admin。

### 7.3 Redemption-code registration and renewal

#### Confirmed product boundary

- SaaS Core 提供兑换码注册，不提供无兑换码的公开租户创建。
- 兑换码由独立平台后台生成和管理，租户管理员不能自行生成。
- 一次兑换只作用于一个租户：未登录用户可用它创建账号/租户，已有租户可用它延长服务期。
- 兑换结果、操作者、来源兑换码、租户和有效期变化写入不可变 `subscription_events`。
- current host-restore run 未达到 `completed`（包括 installing/reviewing/failed_closed）时，平台可以查看恢复状态但不得生成、预览、预留或消费新旧兑换码，也不得开始新注册/续期；恢复出的 active/reserved 码已经不可逆 `recovery_revoked`。run 只有绑定安全 released-active-tenant smoke，或在没有可安全 release active survivor 时绑定已销毁的 DR-only scratch evidence，才能 completed；之后新生成的码绑定 current run，后续 host restore 会再次按新 run 处理。

#### Required registration state machine

以下流程是 D01/D03/D09/D54 的必要实现边界；具体 worker lease、单次任务超时和重试调度阈值作为版本化运行参数在 Phase 0 压测后确定。这些参数只控制执行器接管与告警，绝不释放、转让、恢复 active 或重新分配已 reserved 的兑换码：

1. 用户先提交兑换码，服务端只返回可公开的权益摘要，不返回内部 ID 或完整规则。
2. 用户填写租户名称并用 D46 的 canonical `+86` 手机号完成 `register` OTP；非 `+86` 或非法输入必须在创建 challenge、user 或预留兑换码前拒绝。若该手机号没有因邀请而存在的 unverified user，只在验证码成功消费后创建已验证用户；若已有 `unverified/active` 且无 membership 的协调行则锁定并复用，在同一事务设置 `phone_verified_at`。已有未释放 membership 或 status=`disabled` 的手机号不能创建第二个租户，disabled 不得因 OTP 成功而自助恢复。控制库同时锁定 current recovery run，要求 run 已 completed、兑换码为 `active` 且 `created_under_recovery_run_id` 与当前 run 一致（初始 baseline 同理），然后创建/复用 immutable registration attempt，并把兑换码原子预留为 `reserved`；只记录 `reserved_user_id` 与 `reserved_registration_attempt_id`，不在兑换码行重复保存 canonical phone。旧 run、`recovery_revoked` 或恢复审查期请求在创建 challenge/attempt 或消费码前 fail closed；此时不跨越 provisioning 长事务锁手机号或提前作废邀请。
3. provisioning worker 创建租户业务数据库、执行 migration、写入 `database_identity`，并创建唯一的“默认仓库”待完善记录；联系电话预填为注册手机号，但不视为用户已确认。用户输入的租户名称先只作为 attempt 快照保存，面向用户的名称/slug 唯一 claim 和首位 Admin 席位只允许在 registration final commit 建立；provisioning 路由使用 immutable tenant/database UUID，不依赖公开 slug。若存储层要求 provisional tenant 先有 slug，只能使用 UUID 派生且不进入公开命名空间的内部随机值，不能提前占用用户期望的 slug。
4. smoke test 成功后，最终控制库事务按 D47 锁定 canonical 手机号身份及其全部有效邀请，再按稳定顺序锁 provisional tenant/current recovery run、tenant database/route、registration attempt、唯一 replacement action/lineage 和 redemption code。租户库 `database_identity` 已在前置 provisioning 中写入，并在仍持有同一 backup/DDL lease 与 per-database advisory lock 时完成 smoke；最终事务不再写租户库，只 current-read 复核其 immutable schema-generation/digest 证明。它还必须复核外部 marker 与 run 仍 completed、user 仍 active 且尚无未释放 membership、attempt 为 ready/committing 并匹配本 worker 的 provisioning generation/lease、不存在 replacement action/lineage，而且 code 仍为 reserved 并不可变绑定同一 user/attempt；任一条件不符时在任何 membership/subscription/code 写入前失败。成功者分配 immutable registration commit UUID，在同一控制库事务写入 `tenant_registration_commits` 权威行及带该来源的 Admin membership、subscription/订阅事件、current-run state=`released` recovery-hold 基线和 tenant-database activation/初始 published route anchor；此时才占用公开 slug 和首位 Admin 席位，把该手机号所有 pending invitation 置为 `superseded`、清空其 `user_id` 并释放各自席位，同时将 attempt/code 写入同一 commit UUID、code 变为 redeemed、attempt/tenant 变为 active。如果 run 已变化、并发邀请接受已经先建立其他 tenant membership，或安全流程已把 user 置为 disabled，则注册不得覆盖归属、恢复账号或消费兑换码，进入 `identity_conflict/security_blocked` 阻断态；兑换码仍 reserved 给原 user/attempt，问题解除后只能由原用户重试同一 attempt，或由平台按第 6 步补发全新兑换码并永久终结旧 attempt/code。
5. provisioning 失败时，attempt 进入可重试的 `failed`，兑换码继续为 `reserved` 并不可变绑定原 user/attempt。worker 租约或注册页面会话过期、失败次数达到阈值、经过兑换截止时间都不释放或改绑；只有原用户重新完成同一 canonical 手机号的 `register` OTP 后才能恢复并自助重试同一 attempt，平台后台没有开户重试入口。用户已经提交的同一执行可以由 worker 按 immutable attempt/idempotency key、当前 provisioning generation 和 fencing lease 做技术性重试或安全接管；这不创建第二条 attempt，也不能改变 user、code、租户名称摘要、entitlement 或其他注册输入。
6. 平台不提供开户重试或独立的“放弃并清理”动作，只在兑换码后台提供“补发兑换码”。请求必须来自具备普通兑换码生成权限的有效平台会话，只提交 source code、可空 source attempt、source code/attempt expected revision、一个未来的新兑换截止时间、幂等键和审计字段；服务端拒绝客户端选择或修改套餐、服务时长、原 user/tenant 绑定。普通失败开户分支要求 source code 仍为 reserved 并绑定同一 user/attempt，attempt 精确处于 `failed/identity_conflict/security_blocked` 之一；D58 分支允许 current run completed 后从尚无 successor 的 recovery-revoked code 补发，source attempt 可以为空，存在时同样必须被 fence。补发与 registration final commit 使用第 4 步完全相同的控制库锁序和 locking current-read；只有 source 确实带 provisional database 时才取得同一 backup/DDL lease 与 per-database advisory lock，无 attempt、tenant、database 或其他 provisional 资源的 D58 source 不创建空 janitor/outbox。若 immutable registration commit 及全部 anchor/lineage 已完整，按历史成功对账为 active/redeemed 并拒绝补发；若 commit/source/anchor 只出现一部分或摘要不一致，创建或保留唯一内部 integrity incident 并 fail closed，旧码和 attempt 均不得被补发逻辑修补或清理，普通平台后台没有该事故的人工处置入口。只有确认全部 registration commit/source-linked 成功事实不存在时，单一控制库事务才在 attempt 存在时推进 provisioning generation、失效旧 worker lease并把 attempt 永久置为 `superseded_by_replacement`；普通 reserved source code 永久置为 `revoked(reason=replaced)`，recovery-revoked source 保持该更严格终态。旧 attempt 的 requested name 可按数据最小化规则清空，但 provisional tenant 从未发布公开 name/slug 或占用首位 Admin 席位；意外存在的 membership、subscription、首位 Admin 席位或公开 slug 都属于 integrity 异常，不能静默释放。该事务同时创建且只创建一枚 replacement code：使用新 code UUID、新单码 batch/crypto context 和 CSPRNG 随机明文，精确复制旧码 immutable entitlement snapshot、plan revision 与 duration，只采用平台本次选择且提交时仍在未来的新 deadline，并记录 source code/attempt/current run 的不可变 lineage。新码立即为绑定 current completed run 的普通 bearer code，可按既有规则用于注册或续期，不绑定原手机号或原 tenant；旧 attempt 的终态不阻止合法持码人用新码创建全新 attempt。分别对 source attempt UUID（非空时）与 source code UUID 建立 UNIQUE，保证一源最多一枚，响应丢失后的同幂等请求返回同一新码记录。旧码永远不能回到 active/reserved 或被第二次补发；旧 attempt UUID、terminal outcome 和 replacement lineage 同样不可改写或复用。

注册最终提交、用户自助重试和 replacement intent 必须使用第 4 步的同一锁序，并 current-read attempt provisioning generation、replacement lineage、code binding 和 current run。最终提交先线性化时，权威 registration commit 行与全部关联事实在同一事务成立，attempt/code 分别成为 active/redeemed，迟到补发稳定拒绝且不得生成新码；replacement intent 先线性化时，旧 worker与最终提交因 terminal attempt、generation 和 code CAS 不匹配而在任何 membership/subscription 写入前 fail closed，新码则已由同一补发事务唯一发行。任何死锁重试或响应丢失都不得产生第二条 replacement、第二个 tenant，或让旧 attempt/code 再次成功。

provisioning、replacement janitor 和 D58 system recovery cleanup 对实际存在的 provisional schema、账号或 route 的每一次外部变更，还必须先取得既有全局 backup/DDL lease，再使用同一个以 provisional database UUID 为键的 MySQL advisory lock；新 owner 不能越过仍持锁的旧 worker。补发事务与 provisioning final commit 在 source 带 provisional database 时须持有或重新取得该锁并复核 external marker/current run、attempt provisioning generation、replacement lineage 和 worker fencing token；没有 attempt/database/resource 的 D58 source 只生成 replacement，不创建 cleanup outbox。replacement 获胜且存在待清理资源时，与补发事务同事务写入的 system-only control outbox 驱动 janitor 异步撤销 provisional route/数据库账号、隔离任务/provider 副作用、核对 `database_identity` 并删除残留 schema。janitor 每一步前后都复核 replacement/source generation 与 outbox lease token，成功后保存可供 D58 识别的 immutable terminal cleanup disposition、资源清单摘要和认证 drop/negative proof；失败只由系统按同一 outbox 幂等重试并告警，普通 job 后台和平台页面都不能 cancel、replay 或另建 cleanup。新码已经发行不授权旧 provisional route，janitor 延迟或崩溃也不能恢复旧 attempt/code、旧 worker 或任何业务访问。D58 的 current-run system recovery cleanup 继续沿用其独立 normalization、`recovery_revoked` code 和 fencing 规则，不能借 replacement 流程改写或复活。

账号/控制面记录与租户业务数据库无法依赖一个跨库原子事务，因此注册必须是可重入状态机，不能用一条同步请求假装全部操作原子完成。

#### Confirmed renewal rule

只有租户 Admin 可以在已登录状态输入兑换码续期。最终兑换事务不能依赖早先的 middleware 检查；必须按 6.2 的统一顺序锁定 `tenant → current recovery run → tenant hold → deletion → suspension → redemption code → subscription`，以 locking/current read 重验 run 已 completed、tenant hold 已 released、Admin membership、tenant 仍为 `active/expired`、没有 suspension/deletion 门禁、`access_version` 匹配，并确认 code 为当前 run 生成的 `active` 而非旧 run/recovery-revoked，之后才消费码并更新 subscription。任一复验失败时码、权益和到期时间均不变；这使已通过前置检查的旧请求也不能越过 D52 暂停或 D58 recovery hold。复验通过后，事务从本次 consumed code 固化 immutable plan revision、entitlement snapshot/digest 与精确 duration 到 subscription/event，不得回查 source code 或后来 current plan；再以 `max(当前到期时间, 当前时间) + code.duration` 计算新到期时间：未到期续费累加剩余时长，已过期租户从兑换时重新计算。replacement code 与普通 bearer 完全走同一路径，同一新码并发注册和续期也只能一方消费成功。

#### Platform admin console scope

Core 最小平台安全控制台必须包括：

- current recovery run completed 后，单个或批量生成彼此独立、绑定该 run 的一次性兑换码，设置服务时长、兑换截止时间、套餐/权益、渠道和内部备注；reviewing 期间只能查看/处理恢复作废记录，不能提前发行可能绕过 hold 的新码。失败开户的 replacement 是单码特例：套餐版本、entitlement snapshot 与 duration 只能继承 source code，平台只选择新的未来 deadline。
- 列表默认显示兑换码掩码；具有 `redemption_code.reveal` 权限的平台管理员可重复查看完整码，每次查看都写平台审计。
- 列表明确显示 active/reserved/redeemed/revoked/expired/recovery-revoked 状态；已兑换码显示兑换用户、租户和兑换时间，reserved 行显示原 attempt 的非敏感状态，replacement 只显示“已补发”或“因一致性异常未补发”等产品结果，不展示 system janitor 的任务、清理步骤、资源清单或进度，也不泄露手机号、schema 名或凭证，并支持按状态筛选。
- 生成成功响应支持一次性 CSV 下载；Core 不支持对历史批次再次批量导出全部完整码。历史记录只允许按单码执行经审计的重复查看，避免一次操作暴露整批有效码。
- 撤销尚未预留的未兑换码；平台不能重试 provisioning，也没有“放弃并清理”入口。对符合第 6 步全部判据的失败 attempt，或 current run completed 后尚无 successor 的 recovery-revoked code，平台只能选择新的未来 deadline 并执行一次“补发兑换码”：普通分支立即永久 fence 旧 attempt/code，D58 分支在 attempt 存在时同样终结它，两者都生成唯一 replacement；页面对普通失败明确提示原用户随后不能再重试旧 attempt。残留 provisional 资源由 system-only janitor 异步收口，平台没有查看、取消、重放或重新创建 cleanup 的页面/API；已兑换或 `revoked(reason=replaced)` 记录不能删除、恢复 active 或再次使用，recovery-revoked source 本身也不能兑换，但允许按上述规则恰好补发一个 successor。
- 查看订阅事件账本并按 D53 由任一 active 平台管理员逐次完成 fresh TOTP/恢复码验证后，人工增加或减少服务期；表单只接受增加/减少正整数天或独立“立即到期”，不接受任意目标日期时间。目标选择器只允许 active、expired 或冻结已完成的 suspended 租户；suspended 页面必须同时展示“本次只调整服务期，不会恢复租户”，过渡态、current recovery hold 非 released 或 deletion 未终结时不提供可提交入口且后端仍独立拒绝。提交前展示服务端计算的原期限、计算基准、新期限和状态变化，最终事务仍按数据库当前时间及 expected revision 重算。人工调整必须填写 reason code 与受限备注，可选填短线下参考号；refund 页面明确提示“这里只记录服务期调整原因，不代表资金已退”，且不得出现退款金额、币种、渠道、状态、到账时间、凭证上传或支付调用入口。
- 所有生成、导出、查看、撤销、replacement intent/发行及 system janitor 的每次安全收口结果，以及人工服务期调整动作都写入平台审计日志；用户自助重试和 worker 技术重试记录其 immutable attempt/request correlation，但平台审计中不存在人工开户重试或放弃动作。

#### Security baseline

- 兑换码由 CSPRNG 均匀生成 26 个 Crockford Base32 字符（字母表固定为 `0123456789ABCDEFGHJKMNPQRSTVWXYZ`，130 bit entropy），展示时可插入 ASCII `-` 分组；不得把租户、套餐或时长编码为可篡改明文。
- 唯一 `normalized_code` 规则为：Unicode NFKC → 删除所有 Unicode whitespace 和 ASCII `-` → ASCII 大写 → `O` 映射为 `0`、`I/L` 映射为 `1` → 必须恰好 26 个上述字母表字符，否则拒绝。生成、兑换、导入和后台查看均调用同一个规范化函数；`lookup_hash` 对规范化后的 26-byte ASCII 计算 SHA-256。
- 同时保存 `SHA-256(normalized_code)` 查找摘要与应用层认证加密密文：前者只用于兑换查找和并发唯一性，后者仅供授权后台重复查看；130-bit 随机码使离线摘要穷举不可行，明文不得进入日志、缓存或 API 列表响应。
- `code_ciphertext` 使用平台根密钥派生的记录级 key + AES-256-GCM，并保存 nonce、root key/crypto version 和修订号；解密接口单独授权、限流并记录查看人、时间、IP 和 request ID。
- 校验接口按 IP、设备/会话和 code prefix 限流；错误响应不区分“不存在、已使用、已撤销”等内部状态。
- 兑换使用行锁/原子条件更新和 idempotency key，两个并发请求最多一个成功。
- 平台后台与租户后台使用独立权限；批量导出兑换码属于高风险操作。

#### Confirmed redemption-code rules

1. 每枚码严格只允许成功兑换一次；批量销售通过生成多枚独立码实现。
2. “兑换截止时间”和“兑换后授予的服务时长”是两个独立概念。
3. 兑换码绑定套餐/权益；SaaS Core 可以只有一个默认套餐，但模型必须支持后续套餐。
4. 续期采用 `max(当前到期时间, 当前时间) + 服务时长`。
5. 只有 Admin 可以为已有租户兑换续期。
6. 平台后台可多次查看完整兑换码；列表默认显示掩码和兑换状态，授权查看时解密并记录审计。

已确认 D04/D05：手机号 + 短信验证码无密码登录，一个手机号账号只归属一个租户。已有租户的 Admin 可兑换续期，但不能再创建第二个租户。

### 7.4 Confirmed document-feature removal

SaaS Core 删除以下完整功能链路，而不只是隐藏前端按钮：

- 身份证 OCR：删除 `/api/ocr/id-card`、OCR 路由注册、`ocr_functions.py`、前端上传/识别流程、阿里云 OCR SDK 与环境变量。
- 租赁合同：删除桌面端合同视图与路由、合同操作入口、服务端合同页面数据和 `rental_contract2.html`。
- 独立发货单/出货单业务页面：删除 `ShippingOrderView`、`BatchShippingOrderView`、对应页面路由、预览入口和把它作为独立文档下载/查看的能力。
- 重新构建桌面/移动静态产物，确保已删除功能和“光影租界”等旧文案不残留在 dist bundle。

明确保留并重构面单两联打印：

- 第一联由顺丰云打印接口生成，现有 PDF 转图片流程继续使用；第一联不需要也不接收本系统的“寄回地址”字段。
- 第二联由系统本地生成，用于向客户提供寄回信息；它是面单打印任务的一部分，不再称为独立“发货单”。
- 现有 `shipping_slip_image_service.py` 重命名/重构为 `waybill_second_sheet_service.py`，移除硬编码品牌和深圳地址；第二联从同次 print job 的可信仓库快照读取寄回联系人、电话和地址。没有既有运单时按主设备最新仓库创建快照；已有运单后设备调仓时，在旧运单确认取消并按新仓重建前禁止生成第二联。
- 批量打印按每个订单固定顺序提交“顺丰第一联 → 本地第二联”，任务结果分别记录两联成功/失败；不再用 `include_shipping_slips` 把第二联当成可夹带的另一种业务文档。
- 第二联字段固定为：订单号、应寄回日期、寄回联系人、联系电话、仓库寄回地址、客户可见订单备注，以及左右并排的“安装拍摄教程”“照片传输教程”二维码；不显示公司 Logo、客户信息或完整设备清单。
- 订单表单把该字段明确标为“客户可见备注”，提醒操作者内容会打印在第二联；后端顺丰请求模型不接收该字段，禁止把它映射为顺丰 `remark` 或第一联的任何字段。未来如需纯内部协作信息，另建权限和用途独立的内部备注，不复用本字段。
- 两个教程二维码作为平台固定打印资源随后端镜像/发布包提供，不再从 `frontend/src/assets` 运行时读取；Core 不为它们引入上传或对象存储。

其余明确保留：租赁发货状态、预约/批量发货、顺丰下单、快麦打印、闲鱼发货同步和物流轨迹查询。代码清理时必须区分“已删除的独立发货单页面”和“保留的本地面单第二联”。

### 7.5 Tenant branding

- 兑换码注册时填写的租户名称初始化 `tenant_branding.display_name`；新租户不继承“光影租界”或任何默认公司名称。
- 现有单租户迁移时，把当前品牌资料写入默认租户配置，随后可由 Admin 修改。
- Admin 可维护显示名称、公司全称、通用联系人和联系电话；Operator 只读。通用联系人用于新仓库默认值，仓库可以覆盖；Core 不提供公司 Logo 上传或展示能力。
- 页面标题、导航头部、租户设置和需要展示品牌的位置统一从品牌 API 读取，禁止在 Vue、模板、Python 服务或构建产物中硬编码公司名称。
- 顺丰 API connection 属于租户集成配置，月结账号作为可独立验证的 provider account 与仓库绑定；创建运单时的发件人、电话和地址来自主设备当时实际仓库并保存快照，不再存在一组全局顺丰月结号或寄件地址。历史运单继续使用创建快照；实际发货前设备调仓时必须显式取消旧运单并按新仓重建。
- `display_name` 只用于展示，不作为数据库路由、权限或唯一身份；可信身份始终使用不可变 `tenant_id`。

### 7.6 Multi-warehouse workflows

以下业务边界已确认：

- 一个租户可以维护多个仓库，并且始终至少有一个有效默认仓库。
- 新租户注册表单只收手机号验证码、兑换码和租户名称。provisioning 在租户业务库自动创建名称为“默认仓库”、`setup_state=pending` 的默认记录，联系电话预填注册手机号；用户可以在初始化时修改，预填不等于确认。
- 首位 Admin 首次登录后只能访问账号安全、订阅/续期、默认仓库初始化和退出登录。初始化表单必须确认仓库名称、联系人、联系电话、省/市/区和详细地址；后端校验后原子写入并把 `setup_state` 置为 `ready`，此后才开放业务导航与 API。
- 业务门禁以后端默认仓库是否为 `ready` 为唯一事实来源，前端路由守卫只负责引导。待完善期间伪造前端状态或直接请求设备、订单、发货等 API 必须返回明确的 `tenant_setup_required` 错误，不得创建业务数据。
- 每个序列化主设备增加所在仓库属性；新建设备默认进入默认仓库，也可以选择其他有效仓库。手机支架和三脚架在界面上仍按仓库级数量维护，但后台每份容量创建一个不可见逻辑单元，不建立用户可见、可选或可扫码的实物设备编号。
- 仓库保存名称、联系人、联系电话以及省/市/区/详细地址。租户通用联系人和联系电话可作为创建仓库时的默认值，但实际物流使用仓库记录中的有效资料。
- 预约档期时，若有多个有效仓库，用户必须先选择优先仓库；只有一个仓库时自动使用且不显示额外选择步骤。自动选货先返回优先仓的可用设备，再返回其他仓库的可用设备，并在每组内继续使用既有可用性/周转排序。
- 优先仓库只是主设备自动选货的排序条件，不是过滤条件。主设备下拉项展示所有仓库的可用设备并明确显示仓库名称，用户可以选择非优先仓的主设备。
- 主设备确定后，附件区域根据该设备的附件配置动态显示复选框。手机支架和三脚架的复选框读取主设备当时所在仓库在目标时间窗的聚合可用量，不出现具体附件编号下拉框。普通场景可用量为 0 时不可勾选；若同一主设备存在接力候选，且该类型单元由前单当前持有或经连续 `agreed` 入站 link 可达，则仍可勾选并明确显示“接力确认后可满足”，候选不能被伪装成已经备足。
- 一张主租赁只对应一个发货仓、一个包裹和一个顺丰运单，不支持按仓库拆成多个包裹。每个订单增加客户可见备注，用于打印给客户的随单使用或归还说明，不承载内部协调信息。
- 批量发货和面单打印在多仓时要求选择仓库，单仓时自动使用。该选择用于进入对应仓库的工作队列：只展示/处理主设备当前位于该仓的待发货订单；系统按账号保存该场景最近一次仓库，下一次进入时预选但允许修改。
- 每个仓库最多绑定一个当前 active 的顺丰月结账号；同一个规范化月结账号在全平台同一时刻也只能绑定一个仓库，无论是否同一租户。Admin 写入账号时，服务端只按 provider 明确允许的格式规则做规范化（保留前导零，拒绝歧义输入），以独立用途 HMAC-SHA-256 fingerprint 在控制库原子取得全局 claim，再用可重入 saga 写入租户库绑定；任一步失败或 claim/binding 不一致时 fail closed 并进入恢复任务，不能回退其他账号。重复账号只返回 `SF_ACCOUNT_UNAVAILABLE` 及“账号当前无法绑定，请确认原绑定仓已由 Admin 解绑并重新验证”的通用提示，不泄露冲突租户或仓库。只有原绑定仓所属租户的 Admin 可以主动解绑；Operator、其他租户 Admin 和平台管理员都不能替原仓执行。解绑后旧仓立即不能再以当前配置创建新顺丰动作，claim 进入 `released`；旧 account 和历史运单快照不删除。同租户或不同租户的新仓必须重新提交并验证账号，验证期间原子占用 `reserved` claim，成功后才建立新的 active 绑定。该流程不检查或等待旧仓未完成 operation，也不经过平台人工审批；旧运单继续按原快照执行历史操作。新增账号默认显式引用租户默认 SF connection；Admin 只在高级设置中为特殊账号选择独立 connection，运行时不得因默认值变化而改写既有引用。
- 顺丰月结账号不参与仓库 `ready` 判定。未绑定账号的仓库仍可维护设备、附件、客户和 rental；预约页在官方时效不可用时展示具体仓库和缺失原因，并进入 D19 已确认的人工填写/确认流程。只有需要产生顺丰副作用或第一联的动作被门禁，不能把配置缺失伪装成网络失败、空结果或成功。
- 预约优先仓和建单时记录的仓库都不决定新运单的发货仓。首次创建运单前重新读取主设备最新 `warehouse_id`；顺丰寄件/揽收资料、第二联寄回资料和打印机路由从同一仓库上下文解析，但第二联寄回资料不进入顺丰接口。若已有运单后设备再调仓，不得把第一联留在旧仓、第二联静默切到新仓；阻断打印/实发，待用户显式取消旧运单并按新仓重建。
- 顺丰下单解析结果必须同时满足：工作队列仓库 = 主设备当前仓库 = 月结账号绑定仓库 = 寄件资料仓库；任一不一致即拒绝执行。成功创建运单后保存账号及 binding revision 的非敏感快照，后续换绑不改变历史运单的原账号上下文。
- 主设备调仓时，在同一事务中按固定顺序锁定设备、受影响的附件需求、既有 link 和候选逻辑单元，并逐一重算所有尚未发货订单：删除不再适用的旧仓未来 link，再从目标仓自动建立同类型可用单元 link；目标仓不足时保留 request 但不建 link，由事实动态显示附件不足。不得让旧仓单元随数据库字段“瞬移”到新仓、自动借用其他仓、不拆包，也不生成第二运单。
- 附件不足不阻止设备位置更新：验货入库必须反映设备真实仓位；人工调仓先预览受影响订单并二次确认。存在未满足需求的订单在列表和详情中显著提示，并在解决前禁止普通顺丰下单、批量发货和打印面单；D34 已确认的接力线下补寄例外不阻止 relay case 状态流转。
- Core 每个仓库最多绑定一台启用的快麦面单打印机，一台打印机 SN 不能同时绑定多个仓库。操作者在批量发货/打印页面只选择仓库，不再选择打印机；系统按可信 print job 仓库显式发送，移除全局 `KUAIMAI_PRINTER_SN` 默认路由和任何跨仓回退。job 仓库在无既有运单时取主设备最新仓；已有运单后设备调仓时，旧运单确认取消并按新仓重建前不得创建或提交 print job。
- Admin 绑定或换绑前使用当前租户的快麦凭证验证打印机；换绑更新当前仓库绑定并写审计日志，既有 `waybill_print_jobs` 继续保存提交时的仓库、打印机 SN 和 provider task id 快照。仓库未绑定、绑定停用或验证失败时只禁止打印并给出可操作错误，不阻止订单编辑或已经独立完成的顺丰下单。
- 顺丰第一联仍按顺丰接口要求提交寄件/揽收资料，但不提交本系统的“寄回地址”。`waybill_print_jobs` 保存同次两联实际使用的仓库、寄回联系人、电话、地址和打印机快照。设备在下单后、实际发货前调仓时，旧运单和已打印标签明确作废；只有 provider 明确取消成功，或对未知结果完成后台人工核对后，才能按新仓重建。任何阶段都禁止“第一联旧仓、第二联新仓”的混合打印。
- 验货页面在多仓时先选择验货仓库，单仓时自动使用，并按账号记忆 `inspection` 场景的最近选择。每次新建验货记录时，把本次验到的设备更新到所选仓库，等同完成入库；无论验货结果正常或异常都更新仓库。
- 验货记录保存入库仓库和操作者。设备位置更新、移动历史和验货记录必须同一事务提交；编辑历史验货检查项只修改验货内容，不得再次触发设备调仓。
- Admin 和 Operator 均可执行显式“更改仓库”动作：必须选择有效目标仓，可填写调仓备注；若存在受影响的未来订单或逻辑附件单元关联，提交前必须展示清单并二次确认。通用设备更新接口不得直接接受 `warehouse_id` 静默覆盖。
- 调仓预览中的未发货 rental 清单至少展示订单号、客户使用期、当前物流天数和当前计划寄出/回仓日期，并明确写明“调仓不会自动修改这些订单”；每项提供查看/编辑 rental 的站内跳转。用户确认后只更新设备仓位、移动审计并重新分配 D15/D39 逻辑附件单元，不修改 rental 的 `logistics_days`、`planned_ship_out_date`、`planned_return_date` 或原估算快照，也不自动重算甘特警告/接力候选或创建 `logistics_review_required` 状态。验货导致设备进入另一仓且影响后续 rental 时，在验货结果页给出相同的非阻断汇总提醒。
- 调仓后的新顺丰下单、第一联、第二联和打印机路由仍按设备当时的新仓库及其绑定执行；这不会反向改写 rental 原物流字段。用户从提醒主动编辑 rental 时，才按普通编辑流程重新估算并执行完整可用性/附件冲突校验。物流提醒本身不阻断发货；D15 已确认的配件库存冲突门禁仍独立生效。
- Core 不建设调拨单以及待出库、运输中、待入库状态。确认后即时更新设备仓位，并把仓位、只追加移动历史、未来附件 link 的重分配或未满足 request 结果放在同一事务；任一步失败全部回滚。验货入库调用同一领域服务，但移动来源固定记录为 `inspection`，人工操作记录为 `manual_change`。
- 现有租户迁移时创建一个默认仓库，把所有设备归入该仓库；默认仓库的初始联系人、电话和地址从现有顺丰寄件配置迁移。
- 默认仓库不能直接删除或停用；必须先把另一个有效仓库设为默认。被设备、租赁或历史物流引用的仓库只允许停用，不做物理删除。

### 7.7 Configurable accessories and logical inventory units

附件不再按四个固定字段永久硬编码，而使用可配置附件类型和两种追踪模式：

- `device_bound`（设备配套）：手柄、镜头支架。管理员为每台主设备配置它实际具备哪些配套附件；租赁时只显示该设备已配置的附件复选框，勾选不占用仓库独立库存。
- `logical_unit`（逻辑库存单元）：手机支架、三脚架。每份容量在租户库中对应一个仅内部使用的逻辑单元；它不是现实序列号。管理员和普通用户只维护/查看仓库聚合数量，租赁表单仍然只勾选类型，系统自动建立单元关联。

具体业务规则：

- 设备设置页提供“可选附件”配置，不再假定每种机型或每台设备都固定拥有同一套附件。停用附件类型不能删除历史订单中的名称快照。
- 租赁表单把四种附件统一渲染为复选框；只显示当前设备已启用的类型。逻辑单元类型同时显示当前档期“可用/已用/总量”，这些数字由 `accessory_units` 与重叠 `rental_accessory_unit_links` 实时聚合，不维护另一张总量事实表。
- 逻辑单元 UUID 不出现在前端选项、API、导出、接力/验货清单、第一联、第二联、日志或二维码中。用户不选择具体单元；服务端只在固定排序和行锁下自动建立或替换 rental-unit link，link 本身也不形成用户可见概念。
- 新增仓库库存等于创建逻辑单元；减少库存只能 retire 当前在仓、无未来重叠需求且未处于维修/丢失处理的单元。在外、已预约或异常单元不能通过调低数量被删除或恢复可用。
- 普通建单时，服务端为 request 从主设备所在仓选择一个时间窗不冲突的逻辑单元并建立 link。两个并发订单争抢最后一个单元时最多一个成功；没有可用单元时按正常库存规则拒绝勾选/保存，返回 `ACCESSORY_UNIT_UNAVAILABLE`，但不写 `conflict` 状态行。
- 发现接力候选不会改变单元当前位置或写附件接力状态。如果所需类型由前单当前持有，或经连续 `agreed` 入站 link 可达，后单可保存 request 但候选阶段不建 link、不额外预留第二个单元，返回 `ACCESSORY_RELAY_CONFIRMATION_REQUIRED` 并动态显示“接力确认后随设备带来”。任何 relay edge 进入 `agreed` 时，都从该 edge 向后重算已同意链；为后单建立指向同一单元、带 `source_relay_case_id` 的 link 并追加 `linked` 事件。若后单已有另一个尚未实际发出的同类型普通 link，必须先在同一事务解除该 link、写 `unlinked` 事件，再关联随行单元；若另一个单元已经实际补寄或由后单持有，则不得静默替换，进入人工核对。这保证先同意 B→C、后同意 A→B 时也会重新求解 C。
- 实际交接的唯一触发器是 relay case 明确进入 `shipped`：事务必须验证每个随行单元的 `current_holder_rental_id` 正是 predecessor，才能将其改为 successor 并追加幂等 `relay_handoff` 事件；A 仍持有时不得乱序执行 B→C。Core 不给附件增加取消状态，也不新增 relay `rejected/cancelled` 枚举：动态候选未同意前消失不产生 link；`agreed` 后、`shipped` 前的“撤销同意”沿用现有 relay 状态降回 `pending/notified`，并从该节点向后重算整条链。候选若仍满足条件可再次出现；需要永久忽略功能时另行立项。
- 动态候选消失或接力在实际交接前撤销同意时，以固定顺序锁定并从该节点向后重算整条受影响接力链：删除不再可达的来源 link，为每个下游 request 尝试重新关联；失败时保留无 link request、显示附件不足并启用普通发货门禁，不能只删当前一条而让 B→C 继续错误引用 A 的单元。实际交接后不能降级或把单元假定退回仓库，只能通过验货或审计纠正事件处理。
- 后单未勾选某类型时不创建 request；接力 `agreed` 后仍为后单建立同一单元 link，表示它会随包裹经过该订单。由“本单有 link、同类型 request 不存在”动态显示“随设备带来，请继续保管/转寄”，不保存 `carryover_only`。这条中性关联使 A→B→C 在 B 未勾选时仍能可靠占用未来窗口和生成验货清单。
- 当前设备及其连续 `agreed` 入站链均未携带、但后单需要某附件时，系统从同仓自动关联另一个逻辑单元。无可用单元的接力后单允许保留无 link 的 request 和内部附件备注，返回 `ACCESSORY_UNIT_SHORTAGE_WARNING`，不阻止 relay case 进入 `agreed/shipped/completed`；这只是低频线下补寄例外，不保存 `supplemental_dispatch`，也不自动创建第二正式运单、面单或物流跟踪。若实际从仓库补寄，建立相应 link，并在人工确认发出时更新当前持有事实、追加幂等 `dispatched` 事件。
- 主设备接力断开、仓库/日期/附件选择变化时，在同一事务中锁定相关 relay case、request、既有 link 和候选单元，从最早受影响节点向后删除不再适用的未来关联并重新求解整条链；每次 link 插入、替换或删除都同步写幂等 `linked/unlinked` 事件，仍在客户手中的单元不能因计划变化而提前变为可用。
- 在外单元可以为预计真实回仓后的不重叠未来订单建立 link，但不能计入当前可用量。普通 rental 明确进入 `shipped` 时，事务必须复验其每个 link 的单元 `current_holder_rental_id IS NULL` 且可用，随后把 holder 更新为该 rental 并写 `dispatched`；如果仍由其他 rental 持有则阻断发货。唯一例外是同一主设备已 `agreed` 的接力，由 relay case `shipped` 执行前述 holder 转移，打印面单或只创建顺丰运单都不能改变 holder。
- 普通订单存在未满足附件需求时禁止顺丰下单、批量发货和两联打印；候选待确认和接力线下补寄例外只不阻断 rental 保存或 relay case 状态，本身不伪造“已备足”。补充库存、取消需求、重新关联或登记真实补寄后，界面根据事实自动消除不足提示。
- 验货清单取“当前 rental 的 request”与“当前 rental 的逻辑单元 link/持有事实”并集，因此本单未勾选但随设备带来的附件也必须验收。操作者只看附件类型和数量，不看内部单元 UUID。确认实收时清空 `current_holder_rental_id`，把单元自动归入实际验货仓，并追加幂等 `inspected/warehouse_moved` 事件；正常件恢复可用，损坏件进入验货仓 maintenance。未收到时不转仓、不清空 holder，进入 lost/异常核对且不得恢复可用；多出或无法对应时只记盘点差异，等待 Admin 显式调整。事务同时锁定未来 link，保留仍可达的同设备 agreed 接力链，其余 request 按各自主设备当前仓重新关联或转为不足并列出受影响订单，不自动修改任何 rental 物流字段。
- 现有手机支架/三脚架设备和未完成 child rentals 的迁移规则见 Phase 2：每份旧库存生成一个逻辑单元，未完成 child rental 转换成 request 并尽可能关联可核对单元，不再生成数量 allocation 或 custody chain/leg。

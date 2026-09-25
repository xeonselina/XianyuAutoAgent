# 租户认证、平台开店与管理设置

## Purpose

从控制库模型、认证服务、平台／设置路由和两端路由守卫反推的当前行为。此规格定义全系统的身份与入口，租赁、设备、发货等功能均依赖它。

## Requirements

### Requirement: 租户选择唯一登录方式

租户登录方式 MUST 由全局 `TENANT_AUTH_MODE` 明确选 `sms` 或 `password`；`GET /auth/config` 返回 `{success:true,data:{method}}`。未启用的登录入口 MUST 返回 409 `AUTH_METHOD_DISABLED`。登录成功创建控制库会话，并返回成员、租户、CSRF 数据；租户即使暂停／到期也可识别身份，但访问业务路径会被访问状态挡住。

#### Scenario: 密码模式请求短信
- **WHEN** 配置为 `password`，客户端请求 `/auth/sms/request`
- **THEN** 返回 409 `AUTH_METHOD_DISABLED`

### Requirement: 手机号与密码登录有统一验证和限流

手机号 MUST 规范化为 `+86` 加 11 位大陆手机号，允许输入空格、括号、连字符及 `+86`／`0086`／`86` 前缀。租户成员手机号在控制库全局唯一。密码长度为 8–128 字符；密码登录失败消息统一为“手机号或密码无效”，不得泄漏账号存在与否。连续 5 次失败锁定 15 分钟；成功清零。会话有效期 7 天，HttpOnly Cookie 名 `tenant_session`。

#### Scenario: 连续输错密码
- **WHEN** 某启用成员连续 5 次使用错误密码
- **THEN** 账号记录锁定至 15 分钟后，期间即使提交正确密码也不能登录

#### Scenario: 登录到暂停店铺
- **WHEN** 密码正确且租户已暂停
- **THEN** 登录结果包含 `tenant.access_status=suspended`，业务 API 后续返回 403 `TENANT_SUSPENDED`

### Requirement: 短信登录不能枚举成员

短信验证码 MUST 为 6 位、5 分钟有效、最多错误 5 次；只向已有的 active 成员发短信。`/auth/sms/request` 对未注册手机号仍返回相同成功文案。请求频率上限为同手机号每分钟 1 次、每小时 5 次、每天 10 次，同 IP 每小时 30 次；超出返回 429 `RATE_LIMITED`。验证以该手机号最新一条、已成功发送且未消耗的验证码为准；成功一次性消耗并创建会话。

#### Scenario: 未注册手机号请求短信
- **WHEN** 提交格式合法但不属于启用成员的手机号
- **THEN** 客户端仍得到通用成功文案，实际不发送短信

### Requirement: 租户业务请求受会话、CSRF 和访问状态保护

除健康检查与明确公开的认证入口外，`/api/*`、`/web/*`、`/external-api/*` MUST 先校验 `tenant_session`。写请求 MUST 带当前会话的 `X-CSRF-Token`。依次检查数据库开通为 active、租户状态 active、`expires_at` 晚于当前 UTC；对应返回 503 `PROVISIONING_FAILED`、403 `TENANT_SUSPENDED`、403 `TENANT_EXPIRED`。CSRF token 由会话 token 派生，一次登录期间稳定，多标签页刷新 `/auth/me` 不互相废弃。

#### Scenario: 写入缺少 CSRF
- **WHEN** 操作员已登录但 POST `/api/rentals` 未带有效 `X-CSRF-Token`
- **THEN** 返回 403 `CSRF_INVALID`，业务处理器不执行

#### Scenario: Cookie 过期后点击按钮
- **WHEN** PC 或移动端收到业务 API 的 401 `AUTH_REQUIRED`
- **THEN** 清理本地会话，重定向登录并保留当前内部路径为 `next`；重新登录后返回该页面

### Requirement: 密码修改与登出使会话可控

`POST /auth/password/change` MUST 要求有效会话、CSRF、当前密码和符合 8–128 字符策略的新密码。修改成功保留当前会话，撤销该成员其他租户会话；错误密码返回 401 `AUTH_INVALID`。`POST /auth/logout` 撤销服务端会话并删除 Cookie。

#### Scenario: 多设备登录后改密
- **WHEN** 成员在设备 A 更改密码
- **THEN** A 当前会话继续有效，设备 B 的旧会话变为 401

### Requirement: 平台管理员独立登录与租户开通

平台管理员 MUST 用用户名、密码和 TOTP 登录；TOTP 允许当前时间窗口前后各一格。平台会话 Cookie 名 `platform_session`、path `/platform`、有效 12 小时，与租户会话分开。首次管理员只能由 CLI 建立。平台租户列表、创建、重试和修改只接受平台会话及写请求 CSRF。

#### Scenario: 平台创建租户
- **WHEN** 提交店铺名、管理员手机号、到期时间和初始密码
- **THEN** 建控制库租户、分配专属数据库与用户、迁移并设置首个管理员和仓库；成功返回 201，建库失败返回 503 `PROVISIONING_FAILED` 且保留可重试状态

#### Scenario: 平台修改到期时间
- **WHEN** PATCH `/platform/api/tenants/<id>` 提交正整数 `extend_days`
- **THEN** 以当前到期时间与当前 UTC 中较晚者为基数延长；不能同时提交 `expires_at`

### Requirement: 管理员维护成员、仓库和集成配置

租户 `admin` MUST 可通过 `/api/settings/*` 创建成员、重置密码、更改角色／启用状态、创建或修改仓库、保存仓库顺丰及快麦配置、维护闲鱼店铺并触发同步。`operator` 请求这些接口返回 403 `FORBIDDEN`。成员手机号全控制库唯一；必须至少保留一个启用管理员。密钥字段加密落库，读取时只返回配置是否完整等非敏感值，不返回明文。

#### Scenario: 禁用最后一位管理员
- **WHEN** 管理员 PATCH 最后一位 active admin 为 disabled 或 operator
- **THEN** 返回 409，保持管理员仍 active

#### Scenario: 仓库集成配置
- **WHEN** 管理员保存顺丰或快麦凭据
- **THEN** 只关联目标仓库，其他仓库配置不改变；对外只展示完成状态和非密钥字段

### Requirement: 身份摘要和 CSRF 的响应字段稳定

登录及 `GET /auth/me` MUST 返回 `data.csrf_token`、`data.member={id,phone,role,status}` 和 `data.tenant={id,name,status,provisioning_status,expires_at,access_status}`；`expires_at` 为带 `Z` 的 UTC 字符串。平台登录及 `/platform/auth/me` 只返回 `data.csrf_token` 和 `data.admin={id,username}`。会话 Cookie 原文不写入数据库，仅保存摘要；刷新身份可返回相同会话的有效 CSRF。平台身份错误不能被当作租户登录错误。

#### Scenario: 登录后刷新浏览器
- **WHEN** 租户 Cookie 未过期时刷新并调用 `/auth/me`
- **THEN** 前端恢复成员、店铺、访问状态和可供写操作的 CSRF，免于重新登录

### Requirement: 管理员密码重置撤销目标成员所有租户会话

管理员创建成员 MUST 默认角色 `operator`、状态 `active`，要求全局唯一的规范化手机号和 8–128 字符初始密码。`PUT /api/settings/members/<id>/password` 必须清除该成员的错误密码次数／锁定时间、更新时间并撤销其在此租户所有会话；响应不得返回密码哈希。修改成员仅接受 `role=admin/operator` 与 `status=active/disabled`，需锁住本租户成员集合以保证至少一名 active admin。

#### Scenario: 管理员重置在线成员密码
- **WHEN** 被重置成员仍有 PC 与移动端会话
- **THEN** 两端后续业务请求均收到 401，使用新密码登录成功；另一个成员会话不受影响

### Requirement: 仓库名称和集成密钥更新遵循部分更新

创建仓库 MUST 要求非空 `province,city`，若未给有效名称，自动设为“省市仓库”；修改地区时，原名称恰是旧自动名才随之更新，手工名称保留。顺丰配置存 `partner_id,checkword,monthly_card,test_mode,sender_name,sender_phone,sender_address`；快麦配置存 `app_id,app_secret,printer_sn`。密钥输入省略／空字符串时保留旧密文，有效新值才加密覆盖；`test_mode` 必须为布尔。仓库列表中的 `sf_configured` 只在地区和顺丰必要字段完整时为真，`kuaimai_configured` 只在三个快麦字段完整时为真。

#### Scenario: 改仓库城市且已有手工名称
- **WHEN** 仓库叫“华南器材仓”，管理员只改 `city`
- **THEN** 名称保留“华南器材仓”；旧自动名的仓库则生成新省市名称

#### Scenario: 只改顺丰寄件电话
- **WHEN** 请求只提交 `sender_phone`，不提交 `checkword` 与 `monthly_card`
- **THEN** 两个密文继续有效，读取响应仅显示是否已配置而不泄漏密钥

### Requirement: 闲鱼店铺启用必须凭据完整

`POST/PATCH /api/settings/xianyu-shops` MUST 只接受 `name,app_key,app_secret,is_active`；新店铺默认 inactive，只有 app key 和加密 secret 均存在时才能设 active。空 secret 不删除旧密钥；列表按 ID 升序，返回 `app_secret_configured` 布尔、同步成功时间和错误，不返回 secret。停用店铺不参加 worker 定期同步。

#### Scenario: 启用未配置密钥的店铺
- **WHEN** 管理员新建只有名称的店铺并设 `is_active=true`
- **THEN** 返回 400，店铺不会成为 active 同步目标

### Requirement: 平台租户修改严格校验字段与到期时间

平台 `PATCH /platform/api/tenants/<id>` MUST 只接受 `name,admin_phone,status,expires_at,extend_days` 的非空子集；`status` 只允许 `active/suspended`，到期时间可用 ISO 时间并转 UTC 无时区值，必须位于 MariaDB DATETIME 有效范围。`extend_days` 必须是正整数且不能与直接到期时间并传；更新管理员手机号需在控制库全局查重并锁定。租户列表／修改结果显示 `id,name,status,expires_at,db_name,provisioning_status,provisioning_error,admin_phone`，不显示数据库密码。

#### Scenario: 延长已到期租户
- **WHEN** 当前到期日在过去，平台提交 `extend_days=30`
- **THEN** 从当前 UTC 往后延 30 天；同请求同时含 `expires_at` 则返回 400

### Requirement: 建库标识和重试保持同一租户身份

Provisioner MUST 以零填充的 8 位租户 ID 生成数据库名 `inventory_tenant_<id>`、用户名 `im_t<id>`，新业务库迁移到当前 head 并建立初始仓库。控制库先存 `provisioning` 与成员，失败转 `failed` 并保留原租户和密钥以供 `/retry` 幂等修复；重试不能再建第二个租户 ID。平台接口返回 503 时可把租户的 `provisioning_status/provisioning_error` 呈给管理员，而业务 API 对未 active 的租户保持封闭。

#### Scenario: 迁移失败后重试
- **WHEN** 建库已分配租户 ID 但业务迁移失败
- **THEN** 平台仍查到该 ID 与 failed 错误；修好数据库后 retry 同一 ID 成功，业务请求才开放

## 控制库数据字典

| 表 | 字段与关键约束 |
|---|---|
| `platform_admins` | 自增 `id`、唯一 `username`(64)、`password_hash`(255)、加密 `totp_secret_ciphertext`、时间戳 |
| `tenants` | 自增 `id`、`name`(128)、`status=active/suspended`、`expires_at`、唯一 `db_name`／`db_username`、加密 `db_password_ciphertext`、`provisioning_status=provisioning/active/failed`、`provisioning_error`、时间戳 |
| `tenant_members` | 自增 `id`、`tenant_id`、全局唯一 `phone`(+86 格式)、`role=admin/operator`、`status=active/disabled`、密码哈希、失败次数、锁定期限、改密时间、时间戳 |
| `auth_sessions` | 自增 `id`、`kind=platform/tenant`、`subject_id`、可空 `tenant_id`、唯一 token 哈希、CSRF 哈希、过期／创建／最近访问时间；原始 token 不落库 |
| `sms_login_codes` | 自增 `id`、手机号、验证码摘要、请求 IP、发送是否成功、错误次数、过期／消费／创建时间 |

租户库的 `warehouses` 是另一个表，含 `id,province,city,name,created_at,updated_at`；顺丰与快麦配置是按仓库 ID 一对一的表。闲鱼店铺 `xianyu_shops` 含 `id,name,app_key,app_secret_ciphertext,is_active,last_success_at,last_error,created_at,updated_at`。

## HTTP 契约

| 方法与路径 | 输入与结果 | 主要错误 |
|---|---|---|
| `GET /auth/config` | `data.method=sms/password` | — |
| `POST /auth/sms/request` | `{phone}` → 通用成功消息 | 400 无效电话、429 限流、409 模式关闭 |
| `POST /auth/sms/verify` | `{phone,code}` → 会话 Cookie 与登录数据 | 401 `AUTH_INVALID` |
| `POST /auth/password/login` | `{phone,password}` → 会话 Cookie 与登录数据 | 401 `AUTH_INVALID` |
| `POST /auth/password/change` | `{current_password,new_password}` | 400 `PASSWORD_POLICY`、401 `AUTH_INVALID` |
| `GET /auth/me` | `data={csrf_token,member,tenant}`，刷新稳定 CSRF | 401 `AUTH_REQUIRED` |
| `POST /auth/logout` | 撤销会话、清 Cookie | 401／403 |
| `POST /platform/auth/login` | `{username,password,totp}` → 平台 Cookie、CSRF、管理员摘要 | 401 `AUTH_INVALID` |
| `GET /platform/auth/me`、`POST /platform/auth/logout` | 平台身份读取／退出 | 401／403 |
| `GET /platform/api/tenants` | 按 ID 升序返回租户、首个管理员电话和开通错误 | 401 |
| `POST /platform/api/tenants` | `{name,admin_phone,expires_at,initial_password}` | 400、409 `PHONE_CONFLICT`、503 `PROVISIONING_FAILED` |
| `POST /platform/api/tenants/<id>/retry` | 重试 failed 开通 | 404、503 |
| `PATCH /platform/api/tenants/<id>` | `name,admin_phone,status,expires_at,extend_days` 子集；到期时间两种写法互斥 | 400、404、409 |
| `GET/POST /api/settings/members`、`PATCH /api/settings/members/<id>`、`PUT /api/settings/members/<id>/password` | 管理员成员维护 | 400／403／404／409 |
| `GET/POST /api/settings/warehouses`、`PATCH /api/settings/warehouses/<id>` | 仓库列表／建仓／改名和地区 | 400／403／404／409 |
| `PUT /api/settings/warehouses/<id>/sf`、`PUT .../kuaimai` | 仓库级凭据与发件人／打印机配置 | 400／403／404／409 |
| `GET/POST /api/settings/xianyu-shops`、`PATCH /api/settings/xianyu-shops/<id>`、`POST .../<id>/sync` | 闲鱼店铺维护与即时对账 | 400／403／404／409 |

## 页面与安全边界

PC `/login` 按 `/auth/config` 展示短信或密码表单；`/change-password` 仅密码模式有效。平台 `/platform/login` 与 `/platform/tenants` 分离。`/settings` 只对 tenant admin 开放，内容分成员、仓库及各仓库集成、闲鱼店铺。移动端没有完整的设置／平台管理页；移动业务功能仍遵从同一租户会话。

登录 `next` 仅允许内部绝对路径；禁用双斜杠、反斜杠、跨源、未完全解码的 `%` 和 `/platform` 路径。保留 query/hash，`/mobile/*` 重定向回移动端。认证失败的 API 信息与平台会话错误分开，租户 401 不应误清理平台会话。

## 代码依据与验收

依据：`app/control/models.py`、`app/auth.py`、`app/routes/{auth_api,platform_api,settings_api,web}.py`、`app/services/settings_service.py`、`app/provisioning.py`、`frontend/src/router/index.ts`、`frontend/src/stores/auth.ts`、`frontend/src/views/{LoginView,PlatformTenantsView,SettingsView}.vue`、`frontend-mobile/src/stores/auth.ts`。验收至少覆盖双模式登录、密码锁、短信枚举保护、CSRF、多标签页、登录过期返回原路由、平台／租户 Cookie 隔离、租户暂停／到期、最后管理员保护及跨租户读写隔离。

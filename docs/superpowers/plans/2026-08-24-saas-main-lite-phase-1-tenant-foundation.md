# SaaS Main Lite Phase 1 Tenant Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可安全演练的 MariaDB 测试环境、5 表控制库、请求级租户业务库路由、平台租户创建、腾讯短信登录、固定角色与最小登录/平台页面。

**Architecture:** 控制库使用独立 SQLAlchemy `Engine`/`Session` 和独立 Alembic 基线；现有 `db` 仅承载业务模型。自定义 Flask-SQLAlchemy Session 从 `ContextVar` 读取当前租户 Engine，避免全局切换连接。认证中间件只为业务路径设置上下文，平台与登录路由永不访问业务库。

**Tech Stack:** Flask、Flask-SQLAlchemy、SQLAlchemy、Alembic、MariaDB 10.11、PyMySQL、cryptography AES-GCM、Werkzeug、pyotp、Tencent Cloud SMS SDK、pytest、Vue 3、Pinia、Element Plus、Vant

**Spec:** `docs/superpowers/specs/2026-08-24-saas-main-lite-design.md` §§4–9、15–17、18.1、19

## Global Constraints

- 控制库只能有设计确认的 5 张表；不新增 invite、role、permission、subscription、audit、job 或 token 表。
- 平台 Cookie 名为 `platform_session`、Path 为 `/platform`、默认 12 小时；租户 Cookie 名为 `tenant_session`、Path 为 `/`、默认 7 天。两者均 HttpOnly、SameSite=Lax，生产环境 Secure。
- Cookie 保存 32 字节随机原始 token；数据库只保存 SHA-256 token hash。CSRF 原始 token 只返回浏览器内存，数据库只保存 hash。
- 平台请求、短信请求、静态页面和 `/health` 不得创建租户业务 Session。
- `/api/*`、`/web/*` 和 `/external-api/*` 是租户业务路径；现有 external API key 只能作为第二道校验，不能代替租户会话。`/external-api/health`、`/external-api/docs` 可公开；若未来需要无浏览器会话的机器调用，再单独申请租户级 API 凭证设计。
- 测试中的固定验证码只允许 `TESTING=true` 或非 production；production 检测到 `DEV_SMS_CODE` 必须启动失败。
- 新平台创建租户是同步、可重试流程；不引入 provisioning worker 或状态机框架。

---

### Task 1: 建立生产 SQL 安全提取器和 MariaDB 测试护栏

**Files:**
- Create: `InventoryManager/scripts/extract_inventory_dump.py`
- Create: `InventoryManager/tests/unit/test_inventory_dump_extractor.py`
- Modify: `InventoryManager/tests/support/test_database.py`

**Interfaces:**
- `extract_database(input_path: Path, output_path: Path, target_database: str) -> DumpSummary`
- `DumpSummary(source_database: str, target_database: str, statements: int, bytes_written: int)`
- 源数据库固定为 `inventory_management`；target_database 必须包含 `test` 且不能等于任何系统库。输入缺少源段或输出仍包含其他数据库时抛出 `UnsafeDatabaseError`。

- [ ] **Step 1: 写安全提取失败测试**

覆盖：只保留 `USE inventory_management` 段；拒绝 `mysql`；保留目标库内 delimiter/trigger 内容；临时文件原子替换；输出摘要不含 SQL 内容。

```python
def test_extracts_only_inventory_management(tmp_path):
    source = tmp_path / "backup.sql"
    source.write_text(
        "CREATE DATABASE `mysql`;\nUSE `mysql`;\nCREATE TABLE secret(id int);\n"
        "CREATE DATABASE `inventory_management`;\nUSE `inventory_management`;\n"
        "CREATE TABLE devices(id int);\n",
        encoding="utf-8",
    )
    target = tmp_path / "restore.sql"

    summary = extract_database(
        source,
        target,
        target_database="inventory_management_restore_test",
    )

    text = target.read_text(encoding="utf-8")
    assert "CREATE TABLE devices" in text
    assert "secret" not in text
    assert "USE `inventory_management_restore_test`" in text
    assert summary.source_database == "inventory_management"

def test_refuses_system_database(tmp_path):
    with pytest.raises(UnsafeDatabaseError):
        extract_database(
            tmp_path / "backup.sql",
            tmp_path / "mysql.sql",
            target_database="mysql",
        )
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_inventory_dump_extractor.py -q
```

Expected: 因模块不存在失败。

- [ ] **Step 3: 写最小流式提取实现**

逐行识别 mysqldump 的 `Current Database`/`USE` 边界，只在源 `inventory_management` 段写入；不得把 27MB 文件一次性读入内存。把该段的 `CREATE DATABASE`/`USE` 标识安全改写为已验证的 target_database，写入同目录临时文件，成功后 `os.replace`。CLI 固定参数为 `--source`、`--output`、`--target-database`，不开放源数据库选择。

- [ ] **Step 4: 扩展测试库护栏**

在 `tests/support/test_database.py` 增加：

```python
def assert_test_database_names(*names: str) -> None:
    if not names or any("test" not in name.lower() for name in names):
        raise RuntimeError("所有测试数据库名必须包含 test")
    if any(name.lower() in {"mysql", "inventory_management"} for name in names):
        raise RuntimeError("拒绝系统库或生产默认库")
```

MariaDB 集成测试约定使用显式环境变量 `TEST_CONTROL_DATABASE_URL`、`TEST_TENANT_DATABASE_URL_A`、`TEST_TENANT_DATABASE_URL_B`，三个库名都必须含 `test`，测试账号只能拥有这三个测试库权限。

- [ ] **Step 5: 运行测试并提交**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_inventory_dump_extractor.py tests/support/test_database.py -q
git diff --check
git add scripts/extract_inventory_dump.py tests/unit/test_inventory_dump_extractor.py tests/support/test_database.py
git commit -m "test: add safe inventory dump extraction harness"
```

Expected: 测试通过；没有读取、修改或提交原始备份文件。

---

### Task 2: 建立 5 表控制库、AES-GCM 和单基线迁移

**Files:**
- Create: `InventoryManager/app/control/__init__.py`
- Create: `InventoryManager/app/control/models.py`
- Create: `InventoryManager/app/control/store.py`
- Create: `InventoryManager/app/crypto.py`
- Create: `InventoryManager/control_alembic.ini`
- Create: `InventoryManager/control_migrations/env.py`
- Create: `InventoryManager/control_migrations/script.py.mako`
- Create: `InventoryManager/control_migrations/versions/20260824_control_baseline.py`
- Create: `InventoryManager/tests/unit/test_control_store.py`
- Create: `InventoryManager/tests/integration/test_control_migration.py`
- Modify: `InventoryManager/config.py`
- Modify: `InventoryManager/requirements.txt`

**Interfaces:**
- `SecretBox.from_base64(key: str)`, `encrypt(plaintext: str, purpose: str) -> str`, `decrypt(ciphertext: str, purpose: str) -> str`
- `ControlStore(url: str, secret_box: SecretBox)`, `session() -> ContextManager[Session]`
- `hash_token(raw: str) -> str` and `digest_sms_code(phone: str, code: str, key: bytes) -> str`
- 控制模型字段和约束严格对应设计 §5。

- [ ] **Step 1: 写模型与加密 RED 测试**

测试 AES-GCM round-trip、purpose AAD 不匹配失败、错误主密钥失败、token/code 只保存摘要、手机号唯一、状态/check constraint、控制迁移仅创建 5 表。

```python
def test_secret_box_binds_ciphertext_to_purpose(master_key):
    box = SecretBox.from_base64(master_key)
    encrypted = box.encrypt("secret", purpose="tenant-db-password")
    assert box.decrypt(encrypted, purpose="tenant-db-password") == "secret"
    with pytest.raises(InvalidTag):
        box.decrypt(encrypted, purpose="sf-checkword")

def test_control_baseline_has_exact_tables(control_connection):
    tables = set(inspect(control_connection).get_table_names())
    assert tables == {
        "platform_admins", "tenants", "tenant_members",
        "auth_sessions", "sms_login_codes",
    }
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_control_store.py tests/integration/test_control_migration.py -q
```

Expected: 新模块与迁移不存在而失败。

- [ ] **Step 3: 实现最小控制模型和 Store**

使用独立 `DeclarativeBase`，不导入 `app.db`。`ControlStore.session()` 每次创建短生命周期 Session，并保证异常 rollback、最终 close。枚举使用字符串列加 check constraint，避免引入复杂 enum 迁移。

`SecretBox` 只接受 base64 编码的 32 字节主密钥，密文为 `base64(nonce[12] + AESGCM ciphertext)`；不加版本字节。短信摘要派生键使用 HKDF-SHA256 的固定 info `sms-login-code-v1`。

- [ ] **Step 4: 写控制库唯一基线迁移**

`control_migrations/env.py` 从 `CONTROL_DATABASE_URL` 取连接，`target_metadata = ControlBase.metadata`。revision 创建且仅创建 5 张表及设计中的唯一/外键/索引；downgrade 只用于空控制库开发环境，按外键逆序删除。

- [ ] **Step 5: 增加配置启动校验**

`Config` 新增 `CONTROL_DATABASE_URL`、`SAAS_MASTER_KEY`、控制/业务连接池大小、tenant DB host/port；`ProductionConfig` 在 app 工厂启动时校验缺失主密钥、默认开发密钥和 `DEV_SMS_CODE`。不要把真实值写入 `.env.example`（环境文件在阶段 4 统一整理）。

- [ ] **Step 6: 运行测试并提交**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_control_store.py tests/integration/test_control_migration.py -q
git diff --check
git add app/control app/crypto.py control_alembic.ini control_migrations config.py requirements.txt tests/unit/test_control_store.py tests/integration/test_control_migration.py
git commit -m "feat: add minimal tenant control database"
```

---

### Task 3: 将现有业务 Session 安全绑定到当前租户

**Files:**
- Create: `InventoryManager/app/tenant_context.py`
- Create: `InventoryManager/tests/unit/test_tenant_context.py`
- Create: `InventoryManager/tests/integration/test_tenant_isolation.py`
- Modify: `InventoryManager/app/__init__.py`
- Modify: `InventoryManager/app/routes/web.py`
- Modify: `InventoryManager/app/utils/response.py`
- Modify: `InventoryManager/tests/conftest.py`

**Interfaces:**
- `TenantSession.get_bind(mapper=None, clause=None, bind=None, **kwargs) -> Engine`
- `TenantEngineRegistry.get(tenant: Tenant) -> Engine`, `dispose_all() -> None`
- Context API: `bind_tenant(tenant_id, engine) -> Token`, `reset_tenant(token)`, `current_tenant_id() -> int | None`
- 错误响应增加可空 `code`，保持现有 `success/message/data` 兼容。

- [ ] **Step 1: 写并发上下文与双租户 RED 测试**

构建两个 MariaDB 测试业务库，均创建 `devices` 且插入 `id=1` 的不同名称。分别建立租户会话后请求同一 `/api/devices/1`，断言各自只读到自己的名称；无会话返回 `AUTH_REQUIRED`；请求结束后 ContextVar 已清空。

```python
def test_same_primary_key_is_isolated(client, tenant_a_cookie, tenant_b_cookie):
    a = client.get("/api/devices/1", headers=tenant_a_cookie)
    b = client.get("/api/devices/1", headers=tenant_b_cookie)
    assert a.json["data"]["name"] == "tenant-a-device"
    assert b.json["data"]["name"] == "tenant-b-device"
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_tenant_context.py tests/integration/test_tenant_isolation.py -q
```

Expected: 当前全局数据库绑定造成失败。

- [ ] **Step 3: 实现 ContextVar Session 路由**

`TenantSession` 继承 `flask_sqlalchemy.session.Session`，优先使用显式 `bind`，其次使用当前 ContextVar Engine，否则回退现有测试/迁移默认 engine。`db` 初始化改为：

```python
db = SQLAlchemy(session_options={"class_": TenantSession})
```

Engine Registry 按 tenant id 缓存，URL 使用全局 host/port、租户 db_name/db_username 和解密密码组装；连接池默认 `pool_size=2`、`max_overflow=1`、`pool_pre_ping=True`。

- [ ] **Step 4: 实现请求边界**

app `before_request` 对 `/api/`、`/web/` 和 `/external-api/`（公开 health/docs 除外）：验证租户 session、成员 status、租户 provisioning/status/expires_at，设置 `g.tenant/g.member` 并绑定 engine。external API 继续校验已有 API key，但不能单独决定租户。`teardown_request` 先 `db.session.remove()` 再 reset ContextVar。静态路由、`/health`、`/auth/*`、`/platform/*` 不绑定。

测试配置可用显式 `AUTH_BYPASS_FOR_TESTS=True` 保持旧快速测试；安全相关测试必须设置 False。该开关仅在 `TESTING=True` 时生效，生产配置出现该值时启动失败。

- [ ] **Step 5: 删除 Web 进程内 scheduler 启动**

从 `create_app()` 删除 `init_scheduler(app)` 调用。不要在本任务删除旧 scheduler 文件，阶段 3 worker 替换完成后再删除，避免把无关行为和租户路由混在同一提交。

- [ ] **Step 6: 运行隔离与现有回归并提交**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_tenant_context.py tests/integration/test_tenant_isolation.py -q
python -m pytest tests/unit tests/integration/test_rental_api.py tests/integration/test_xianyu_order_alert_api.py -q
git diff --check
git add app/__init__.py app/tenant_context.py app/routes/web.py app/utils/response.py tests/conftest.py tests/unit/test_tenant_context.py tests/integration/test_tenant_isolation.py
git commit -m "feat: route business sessions by tenant database"
```

---

### Task 4: 实现平台会话、租户短信登录、CSRF 和固定角色

**Files:**
- Create: `InventoryManager/app/auth.py`
- Create: `InventoryManager/app/routes/auth_api.py`
- Create: `InventoryManager/tests/unit/test_sms_auth.py`
- Create: `InventoryManager/tests/integration/test_auth_api.py`
- Modify: `InventoryManager/app/__init__.py`
- Modify: `InventoryManager/app/control/store.py`
- Modify: `InventoryManager/config.py`
- Modify: `InventoryManager/requirements.txt`

**Interfaces:**
- `SmsSender.send_code(phone_e164: str, code: str, minutes: int) -> SmsSendResult`
- `TencentSmsSender` and test `FakeSmsSender`
- `POST /auth/sms/request {phone}`
- `POST /auth/sms/verify {phone, code}`
- `GET /auth/me`; `POST /auth/logout`
- `require_role('admin')` decorator; Operator is allowed when no admin-only decorator is present.

- [ ] **Step 1: 写验证码、会话和权限 RED 测试**

覆盖大陆手机号标准化、6 位随机码、5 分钟、最多 5 次、60 秒/5 次每小时/10 次每天/IP 30 次每小时、Code=Ok 才可用、不存在/disabled 通用响应且不发送、成功消费、退出撤销、CSRF 修改请求、Admin/Operator、过期/暂停/disabled 实时生效。

```python
def test_sms_code_is_usable_only_after_tencent_ok(auth_service, fake_sender):
    fake_sender.result = SmsSendResult(ok=False, code="LimitExceeded")
    auth_service.request_code("13800138000", "127.0.0.1")
    assert auth_service.verify_code("13800138000", fake_sender.last_code) is None

def test_operator_fails_admin_decorator(app, operator_request_context):
    @require_role("admin")
    def admin_only():
        return "ok"

    with operator_request_context:
        response, status = admin_only()
        assert status == 403
        assert response["code"] == "FORBIDDEN"
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_sms_auth.py tests/integration/test_auth_api.py -q
```

- [ ] **Step 3: 实现最小认证服务**

单文件 `app/auth.py` 包含 phone normalize、session token、CSRF、SMS service 和两个装饰器，不拆 DTO/Repository。限流直接查询 `sms_login_codes`；发送新码时删除 7 天前记录。验证码 digest 使用 Task 2 派生键，日志只记掩码手机号。

腾讯云只新增 `tencentcloud-sdk-python-common` 与 `tencentcloud-sdk-python-sms`。Fake Sender 由 app config 注入；生产禁止 Fake/固定码。

- [ ] **Step 4: 注册 API 和错误码**

成功 verify 设置 `tenant_session` Cookie 并在响应 `data` 返回 `{csrf_token, member, tenant}`。`/auth/me` 返回同结构和新 CSRF token。所有非 GET/HEAD/OPTIONS 的租户业务请求校验 `X-CSRF-Token`。

到期和暂停仍允许 `/auth/me`，分别返回 tenant access 状态；业务路由返回 `TENANT_EXPIRED`/`TENANT_SUSPENDED`。disabled 成员删除/拒绝当前 session 并返回 `AUTH_REQUIRED`。

- [ ] **Step 5: 运行测试和现有 API 回归并提交**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_sms_auth.py tests/integration/test_auth_api.py tests/integration/test_tenant_isolation.py -q
python -m pytest tests/unit tests/integration -q
git diff --check
git add app/auth.py app/routes/auth_api.py app/__init__.py app/control/store.py config.py requirements.txt tests/unit/test_sms_auth.py tests/integration/test_auth_api.py
git commit -m "feat: add tenant sms login and fixed roles"
```

---

### Task 5: 实现首个超级管理员和同步租户 Provisioning

**Files:**
- Create: `InventoryManager/app/provisioning.py`
- Create: `InventoryManager/app/routes/platform_api.py`
- Create: `InventoryManager/tests/integration/test_platform_provisioning.py`
- Modify: `InventoryManager/app/__init__.py`
- Modify: `InventoryManager/app/control/store.py`
- Modify: `InventoryManager/config.py`

**Interfaces:**
- Flask CLI: `flask bootstrap-platform-admin --username platform-admin`，密码/TOTP secret 交互输入，不接受命令行明文密码。
- Flask CLI: `flask upgrade-tenant-databases`，顺序升级全部 provisioning active 租户业务库，单租户失败继续，任一失败则最终退出码非 0。
- `POST /platform/auth/login {username,password,totp}`; `GET /platform/auth/me`; `POST /platform/auth/logout`
- `GET /platform/api/tenants`; `POST /platform/api/tenants`; `PATCH /platform/api/tenants/<id>`; `POST /platform/api/tenants/<id>/retry`
- `TenantProvisioner.create(name, admin_phone, expires_at) -> Tenant`; `retry(tenant_id) -> Tenant`

- [ ] **Step 1: 写 CLI、权限和幂等 Provisioning RED 测试**

覆盖：只能 bootstrap 第一个平台管理员、密码哈希/TOTP 加密、平台会话不能访问业务 API、租户会话不能访问平台 API、手机号冲突、数据库/用户最小授权、迁移失败记 failed、retry 复用同名库/用户并最终 active、修改/增加 expires_at、暂停/恢复，以及 upgrade-all 对 active/suspended 租户逐库升级且失败汇总为非 0 退出码。

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python -m pytest tests/integration/test_platform_provisioning.py -q
```

- [ ] **Step 3: 实现同步 Provisioner**

固定生成安全标识：数据库 `inventory_tenant_{tenant_id:08d}`，用户 `im_t{tenant_id:08d}`，格式化后的值先用正则 `^[a-z0-9_]+$` 验证后才拼入带反引号 DDL；密码为 `secrets.token_urlsafe(32)` 并加密保存。

Provisioner 使用单独 `PROVISIONER_DATABASE_URL`：创建库、用户、仅授权该库，建立临时 Flask migration app 后执行现有业务 `migrations` 到 head。retry 逐项检查存在状态，不重新生成标识/密码。错误写截断且脱敏的 `provisioning_error`，API 返回 `PROVISIONING_FAILED`。

- [ ] **Step 4: 实现平台 API 和管理员 CLI**

平台密码用 `generate_password_hash`，TOTP 使用 `pyotp` 和 Task 2 `SecretBox`。`expires_at + N days` 从 `max(current expires_at, now)` 计算。平台 API 只返回 db_name、provisioning 状态与脱敏错误，不返回用户名/密码密文。

`upgrade-tenant-databases` 复用 Provisioner 的 migration helper，不新增版本表之外的状态；它升级所有 provisioning active 租户，包括 tenant status 为 suspended 或已过期者，避免恢复租户时 schema 落后。输出仅包含 tenant id/db_name/head/成功布尔值。

- [ ] **Step 5: 验证 MariaDB grants 和提交**

Run:

```bash
cd InventoryManager
python -m pytest tests/integration/test_platform_provisioning.py tests/integration/test_tenant_isolation.py -q
python -m pytest tests/unit tests/integration -q
git diff --check
git add app/provisioning.py app/routes/platform_api.py app/__init__.py app/control/store.py config.py tests/integration/test_platform_provisioning.py
git commit -m "feat: provision tenants from platform admin"
```

Expected: 新租户数据库用户的 `SHOW GRANTS` 只有 `USAGE` 和自身业务库权限。

---

### Task 6: 交付最小登录、受限和平台页面

**Files:**
- Create: `InventoryManager/frontend/src/api/auth.ts`
- Create: `InventoryManager/frontend/src/stores/auth.ts`
- Create: `InventoryManager/frontend/src/views/LoginView.vue`
- Create: `InventoryManager/frontend/src/views/AccessRestrictedView.vue`
- Create: `InventoryManager/frontend/src/views/PlatformLoginView.vue`
- Create: `InventoryManager/frontend/src/views/PlatformTenantsView.vue`
- Create: `InventoryManager/frontend/tests/unit/auth-navigation.spec.ts`
- Create: `InventoryManager/frontend-mobile/src/stores/auth.ts`
- Modify: `InventoryManager/frontend/src/router/index.ts`
- Modify: `InventoryManager/frontend/src/App.vue`
- Modify: `InventoryManager/frontend-mobile/src/router/index.ts`
- Modify: `InventoryManager/frontend-mobile/src/main.ts`
- Modify: `InventoryManager/app/routes/vue_app.py`

**Interfaces:**
- Desktop auth store: `bootstrap()`, `requestCode(phone)`, `verifyCode(phone, code)`, `logout()`, in-memory `csrfToken`.
- Router meta: `public`, `platform`, `requiresTenant`.
- Mobile only shares `/auth/me` and redirects unauthenticated users to desktop `/login?next=/mobile/...`;不建立移动端设置后台。

- [ ] **Step 1: 写路由与表单 RED 测试**

测试未登录跳 `/login`、登录后返回 next、expired/suspended 跳 `/access-restricted`、Operator 看不到设置入口（阶段 2 header 前先验证 route 403）、平台路由使用独立会话、CSRF 只在 Pinia 内存。

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager/frontend
npm run test:run -- tests/unit/auth-navigation.spec.ts
```

- [ ] **Step 3: 实现最小页面和导航守卫**

平台租户页支持创建租户/首 Admin、修改到期日、增加天数、暂停/恢复、失败重试；不放业务入口。`AccessRestrictedView` 根据 auth store 显示到期或暂停。页面不保存 token、短信验证码或 CSRF 到 localStorage/sessionStorage。

移动端首次导航调用 `/auth/me`；未认证用 `window.location.assign('/login?next=' + encodeURIComponent('/mobile' + to.fullPath))`，认证后继续原页面。

- [ ] **Step 4: 增加 Flask SPA fallback**

`vue_app.py` 明确服务 `/login`、`/access-restricted`、`/settings`、`/platform/login`、`/platform/tenants`；API 路径不得被 SPA fallback 捕获。

- [ ] **Step 5: 运行前端和后端路由验证并提交**

Run:

```bash
cd InventoryManager/frontend
npm run test:run -- tests/unit/auth-navigation.spec.ts
npm run type-check
npm run build-only
cd ../frontend-mobile
npm run build
cd ..
python -m pytest tests/integration/test_auth_api.py tests/integration/test_platform_provisioning.py -q
git diff --check
git add frontend/src frontend/tests/unit/auth-navigation.spec.ts frontend-mobile/src app/routes/vue_app.py static/vue-dist static/vue-mobile-dist
git commit -m "feat: add tenant and platform login pages"
```

---

### Task 7: 阶段 1 审查门

**Files:**
- Verify all files changed in Tasks 1–6.

**Interfaces:**
- Produces: 可登录、可创建租户、可隔离访问现有业务的第一个纵向切片。

- [ ] **Step 1: 运行阶段完整验证**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit tests/integration -q
cd frontend && npm run test:run && npm run type-check && npm run build-only && cd ..
cd frontend-mobile && npm run build && cd ..
git diff --check
```

- [ ] **Step 2: 扫描禁止项和表数**

Run:

```bash
rg -n "Celery|APScheduler|outbox|event_bus|repository|invite|subscription" app control_migrations tests
rg -n "__tablename__" app/control app/models
git diff --numstat my_xianyuagent/main...HEAD
```

Expected: 命中仅为明确删除/测试禁止项或旧 scheduler 待阶段 3 删除；控制新表恰好 5 张，没有新业务表。

- [ ] **Step 3: 自查后提交必要修正**

逐项核对设计 §§4–9、15–17 和本计划接口；搜索 `TODO|TBD|pass$|NotImplemented`。若有修正，先补失败测试再提交：

```bash
git add app control_migrations tests/unit tests/integration frontend/src frontend/tests/unit frontend-mobile/src
git commit -m "fix: close tenant foundation review gaps"
```

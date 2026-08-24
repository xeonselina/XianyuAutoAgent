# SaaS Main Lite Phase 4 Migration and Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在隔离 MariaDB 10.11 中从附件生产备份完成可重复的默认租户迁移演练，验证数据不变量，整理 app/worker 同镜像、`.env`/`.env.example` 和上线/回滚手册。

**Architecture:** 一个有严格库名护栏的本地 Docker 脚本启动测试 MariaDB；Phase 1 提取器把备份中唯一 `inventory_management` 段改写到测试库。一次性默认租户 CLI 先检查旧数据、建立控制记录和受限用户，再跑两条业务迁移、导入现有环境配置并核对行数。镜像默认启动 app，NAS 对 worker 覆盖命令为 `python worker.py`。

**Tech Stack:** Docker CLI、MariaDB 10.11、Python streaming SQL extractor、Alembic、Flask CLI、pytest、Vitest、Vite、Gunicorn

**Spec:** `docs/superpowers/specs/2026-08-24-saas-main-lite-design.md` §§18–22

## Global Constraints

- 原始 `/Users/jimmypan/Downloads/backup_20260824_080001.sql` 只读、不修改、不复制进仓库、不进入 Docker build context。
- 自动测试和演练数据库名必须包含 `test`，且不得等于 `inventory_management`、`mysql` 或其他系统库。
- 本地 Docker 资源固定使用 `xianyu-saas-lite-mariadb-test` 容器和 `xianyu-saas-lite-mariadb-test-data` volume；reset/down 只能操作这两个完整名称。
- 测试端口固定映射 `127.0.0.1:33316`，不暴露到局域网。
- 生产默认租户迁移必须显式输入目标 `inventory_management`、维护模式确认和完整备份确认；CLI 不自行删除、覆盖或恢复数据库。
- 数据库 DDL 回滚依赖完整备份恢复，不把 Alembic downgrade 当生产回滚方案。
- NAS 只交付 app 与 worker；不编写 Compose、MariaDB、Redis、Nginx、花生壳、FRP、Cloudflare 或 NAS 独有配置。
- `.env` 保持 gitignored；`.env.example` 只能含说明和占位值。
- 最终成功声明前必须重新运行全部测试、真实备份演练、镜像构建和敏感信息扫描。

---

### Task 1: 交付安全的本地 MariaDB 10.11 启停与还原脚本

**Files:**
- Create: `InventoryManager/scripts/local_test_db.sh`
- Create: `InventoryManager/tests/unit/test_local_test_db_script.py`
- Modify: `InventoryManager/scripts/extract_inventory_dump.py`
- Modify: `InventoryManager/tests/unit/test_inventory_dump_extractor.py`
- Modify: `InventoryManager/.dockerignore`

**Interfaces:**
- `scripts/local_test_db.sh up|status|reset|down`。
- `extract_inventory_dump.py --source /Users/jimmypan/Downloads/backup_20260824_080001.sql --output /tmp/xianyu-saas-lite-restore/inventory_management_restore_test.sql --target-database inventory_management_restore_test`。
- `reset` 删除并重建固定测试容器/volume；`down` 只停止并移除固定测试容器，默认保留 volume。

- [ ] **Step 1: 写 shell 静态护栏和库名改写 RED 测试**

测试脚本固定 MariaDB image `mariadb:10.11`、绑定 localhost、没有未解析的宽泛 `docker rm/volume rm` 目标；提取器把 `CREATE DATABASE/USE inventory_management` 改为显式测试库，拒绝任何非 test target，且输出不含 `mysql` 段。

```python
def test_dump_is_rewritten_to_explicit_test_database(tmp_path):
    summary = extract_database(
        source_dump,
        tmp_path / "restore.sql",
        target_database="inventory_management_restore_test",
    )
    sql = (tmp_path / "restore.sql").read_text()
    assert "USE `inventory_management_restore_test`" in sql
    assert "USE `inventory_management`" not in sql
    assert summary.target_database == "inventory_management_restore_test"
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_inventory_dump_extractor.py tests/unit/test_local_test_db_script.py -q
```

- [ ] **Step 3: 实现固定目标 Docker 脚本**

`up` 创建随机测试 root password 文件或接受 `TEST_MARIADB_ROOT_PASSWORD`，不得把密码写入 Git/进程日志；创建容器后轮询 `mariadb-admin ping`。`reset` 首先断言变量值逐字等于固定容器/volume 名，再执行删除。不要使用 `~`、工作区根目录或通配符作为删除目标。

`.dockerignore` 增加 `*.sql`、`.env`、测试恢复输出目录，防止备份或密钥进入镜像。

- [ ] **Step 4: 运行单测并做一次空库 smoke test**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_inventory_dump_extractor.py tests/unit/test_local_test_db_script.py -q
read -r -s TEST_MARIADB_ROOT_PASSWORD
export TEST_MARIADB_ROOT_PASSWORD
./scripts/local_test_db.sh up
./scripts/local_test_db.sh status
```

Expected: MariaDB 报告 ready，端口只监听 127.0.0.1:33316。测试密码从密码管理器或交互式终端变量提供，不打印、不写文件。

- [ ] **Step 5: 提交脚本**

Run:

```bash
git diff --check
git add scripts/local_test_db.sh scripts/extract_inventory_dump.py tests/unit/test_inventory_dump_extractor.py tests/unit/test_local_test_db_script.py .dockerignore
git commit -m "build: add isolated mariadb restore harness"
```

---

### Task 2: 实现幂等默认租户迁移 CLI 与数据报告

**Files:**
- Create: `InventoryManager/app/default_tenant_migration.py`
- Create: `InventoryManager/tests/integration/test_default_tenant_migration.py`
- Modify: `InventoryManager/app/__init__.py`
- Modify: `InventoryManager/app/provisioning.py`
- Modify: `InventoryManager/app/services/settings_service.py`

**Interfaces:**
- Flask CLI `migrate-default-tenant` 参数：`--name`、`--admin-phone`、`--expires-at`、`--db-name`、`--province`、`--city`、`--confirm-maintenance`、`--confirm-backup`。
- `DefaultTenantMigrator.preflight() -> MigrationReport`、`run() -> MigrationReport`、`verify() -> MigrationReport`。
- 生产 `--db-name inventory_management` 时两个 confirm 参数必须分别等于 `maintenance-enabled` 与 `backup-verified`；测试库仍须含 `test`。

- [ ] **Step 1: 写预检、幂等和配置导入 RED 测试**

覆盖：旧 Alembic head 必须是 `20260807_damage_notes`；记录全部旧业务表行数；拒绝 orphan device/parent rental、空 alert order、店铺组合冲突；创建控制租户/首 Admin/受限 DB user；运行到新 head；所有 Device 和主子 Rental 绑定默认仓；旧 alert/sync state 绑定默认店；存在的 SF/Kuaimai/Xianyu env 加密导入；缺失项显示 incomplete；重复执行不重复 tenant/member/warehouse/shop；失败记录 provisioning failed。

```python
def test_default_migration_preserves_existing_table_counts(migrated_database):
    report = migrated_database.report
    assert report.before_counts == report.after_existing_table_counts
    assert report.orphan_device_count == 0
    assert report.parent_child_warehouse_mismatch_count == 0
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python -m pytest tests/integration/test_default_tenant_migration.py -q
```

- [ ] **Step 3: 实现只服务默认租户的一次性 migrator**

不抽象成通用 migration framework。顺序固定为：

1. 验证确认词、目标库、旧 head 和数据健康。
2. 记录所有迁移前既有业务表行数。
3. 在控制库创建/复用 db_name 唯一的 provisioning tenant，生成/复用受限用户和加密密码。
4. 用现有 Provisioner 创建用户和授权，但绝不 CREATE/DROP 已存在业务库。
5. 对现有业务库运行 Phase 2 两条迁移。
6. 把默认仓省市/名称更新为 `province + city + '仓库'`。
7. 从旧环境变量导入 SF/Kuaimai/Xianyu；配置不完整时保留行或停用店铺，让 UI 明确显示未配置。
8. 创建/复用首 Admin，设置 tenant provisioning active。
9. 重新计数并验证所有非空、主子同仓、告警店铺、组合唯一性和 grants。

报告只输出表名/数量、内部 IDs、配置完成布尔值和错误摘要，不输出凭证/地址/手机号原文。

- [ ] **Step 4: 运行合成旧库集成测试并提交**

Run:

```bash
cd InventoryManager
python -m pytest tests/integration/test_default_tenant_migration.py tests/integration/test_saas_lite_business_migrations.py tests/integration/test_platform_provisioning.py -q
git diff --check
git add app/default_tenant_migration.py app/__init__.py app/provisioning.py app/services/settings_service.py tests/integration/test_default_tenant_migration.py
git commit -m "feat: migrate production database into default tenant"
```

---

### Task 3: 用附件生产备份完成真实隔离演练

**Files:**
- Read only: `/Users/jimmypan/Downloads/backup_20260824_080001.sql`
- Generate outside Git: `/tmp/xianyu-saas-lite-restore/inventory_management_restore_test.sql`
- Generate outside Git: `/tmp/xianyu-saas-lite-restore/migration-report.json`

**Interfaces:**
- Consumes: 27MB MariaDB 10.11 mysqldump，源库 `inventory_management`。
- Produces: 测试库 `inventory_management_restore_test` 的迁移报告；不保留任何密码或业务明文样本。

- [ ] **Step 1: 创建明确临时目录并提取目标库**

Run:

```bash
mkdir -p /tmp/xianyu-saas-lite-restore
cd InventoryManager
python scripts/extract_inventory_dump.py \
  --source /Users/jimmypan/Downloads/backup_20260824_080001.sql \
  --output /tmp/xianyu-saas-lite-restore/inventory_management_restore_test.sql \
  --target-database inventory_management_restore_test
```

Expected: 摘要只报告源/目标库、statement/byte 数；输出中无 `USE mysql` 和其他数据库。

- [ ] **Step 2: 导入隔离容器并确认旧 head**

使用 `docker exec -i xianyu-saas-lite-mariadb-test mariadb ... < /tmp/...sql` 导入。Run:

```bash
docker exec xianyu-saas-lite-mariadb-test mariadb \
  -N -e "SELECT version_num FROM inventory_management_restore_test.alembic_version"
```

Expected: `20260807_damage_notes`。若不同，暂停并核对备份，不强制 stamp。

- [ ] **Step 3: 用测试控制库运行默认租户 CLI**

为控制库、业务库和 provisioner 设置仅限测试容器的 URL；Admin 手机使用保留测试号码，不使用生产真实手机号。Run:

```bash
flask migrate-default-tenant \
  --name '生产备份迁移演练' \
  --admin-phone '13800138000' \
  --expires-at '2099-12-31T23:59:59+08:00' \
  --db-name inventory_management_restore_test \
  --province '广东省' \
  --city '深圳市'
```

Expected: CLI 成功，控制租户 active，默认仓名为 `广东省深圳市仓库`；缺失生产环境配置只报告 incomplete，不妨碍数据查看。

- [ ] **Step 4: 运行迁移后不变量与 API smoke tests**

Run:

```bash
python -m pytest tests/integration/test_default_tenant_migration.py tests/integration/test_tenant_isolation.py tests/integration/test_warehouse_rental_flow.py tests/integration/test_warehouse_shipping.py tests/integration/test_xianyu_multi_shop.py -q
```

另外以只读 SQL 核对：旧表行数前后相同、Device/Rental/Alert 无空 FK、主子同仓、默认仓包含全部实际 Device、默认店继承 sync state、无重复 `(shop, order)`。

- [ ] **Step 5: 验证可恢复性**

对迁移后的测试库生成完整备份到 `/tmp/xianyu-saas-lite-restore/after.sql`，再还原到另一个名称含 test 的空库 `inventory_management_recovery_test`，重复关键计数与 head 检查。不得把备份加入 Git。

- [ ] **Step 6: 失败即修复测试，不提交生成物**

任何真实备份问题先在对应 integration test 中构造最小复现，再修改代码。`git status --short` 必须看不到 SQL/report 生成物。

---

### Task 4: 整理同镜像 app/worker、环境变量和部署手册

**Files:**
- Create: `docs/deployment/saas-main-lite.md`
- Modify: `InventoryManager/Dockerfile`
- Modify: `InventoryManager/.env.example`
- Modify locally, keep ignored: `InventoryManager/.env`
- Modify: `InventoryManager/Makefile`
- Modify: `InventoryManager/worker.py`
- Create: `InventoryManager/tests/unit/test_production_config.py`

**Interfaces:**
- App command: image default `gunicorn --config gunicorn_config.py run:app`。
- Worker command: `python worker.py`；验证命令 `python worker.py --once`。
- 仅一个 image tag，NAS 以后分别覆盖 command；不生成 NAS 配置文件。

- [ ] **Step 1: 写 production config RED 测试**

测试缺少 `CONTROL_DATABASE_URL`/`SAAS_MASTER_KEY`/tenant DB host 时 production 拒绝启动；`DEV_SMS_CODE`/AUTH bypass 禁止；CORS `*` 在 production 禁止；app 和 worker 均能从相同环境加载；`.env.example` 包含所有必需键且无真实 secret。

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_production_config.py -q
```

- [ ] **Step 3: 整理环境变量示例**

`.env.example` 分为：app/control DB、tenant DB host/port、provisioner（app only）、master key、cookie/public URL/CORS、腾讯短信、闲鱼全局域名、连接池。常规运行区删除全局 SF/Kuaimai/Xianyu 店铺凭证；在“仅默认租户一次迁移”注释区保留被注释的旧键名（如 `# SF_PARTNER_ID=`、`# KUAIMAI_APP_ID=`、`# XIANYU_APP_KEY=`），明确迁移成功后删除，不给真实值。

本地 `.env` 只补缺失 key 并保留用户已有值，不打印、不提交。确认 `.gitignore` 和 `.dockerignore` 同时排除 `.env`。

- [ ] **Step 4: 让镜像同时适配 app/worker**

Dockerfile 保持一个镜像和 app 默认 CMD，删除只适用于 app 的 baked-in HEALTHCHECK，由未来 NAS 配置分别设置健康检查。worker 增加 `--once`：取得 advisory lock、各跑一次两个 cycle、释放资源并退出；正常无参数保持常驻。

不要把 MariaDB client/server、Redis、Nginx 或 Docker Compose 加进镜像。确认镜像中不包含 `.env`、SQL dump、测试恢复目录。

- [ ] **Step 5: 移除仓库内硬编码 NAS 凭证/旧部署命令**

当前 Makefile 中的 NAS host/user/password 和旧自动部署 target 与本次交付不符且包含敏感信息。删除硬编码凭证和 NAS 推送/远程执行逻辑，只保留本地 build、push image（registry 由参数/环境传入）、run-app、run-worker；NAS 专用命令等待用户样例。

- [ ] **Step 6: 写简洁部署与迁移手册**

手册包含：前置备份/维护窗口、控制迁移、默认租户迁移、后续发布运行 `flask upgrade-tenant-databases`、新租户 provisioning、app/worker 命令、环境变量、worker 单实例、日志检查、正式接流量前验收、失败时完整备份恢复、接流量后只前进修复、待 NAS 样例/公网入口事项。

- [ ] **Step 7: 运行配置测试并提交**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_production_config.py tests/unit/test_worker.py -q
git check-ignore .env
git diff --check
git add Dockerfile .env.example Makefile worker.py tests/unit/test_production_config.py ../docs/deployment/saas-main-lite.md
git commit -m "build: package app and worker from one image"
```

---

### Task 5: 完整测试、镜像、安全和规模验收

**Files:**
- Verify entire branch against `my_xianyuagent/main`.

**Interfaces:**
- Produces: 可供用户审查的 `saas-main-lite`；不自动推送、部署或修改 NAS。

- [ ] **Step 1: 调用完成前验证技能**

在执行任何“完成/通过”声明前调用 `superpowers:verification-before-completion`，以下所有命令必须是本次新鲜输出。

- [ ] **Step 2: 运行完整后端测试**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit tests/integration -q
```

Expected: 全部退出码 0；MariaDB 集成测试明确使用 10.11 测试容器。

- [ ] **Step 3: 运行桌面/移动构建**

Run:

```bash
cd InventoryManager/frontend
npm run test:run
npm run type-check
npm run build-only
cd ../frontend-mobile
npm run build
```

- [ ] **Step 4: 构建并启动同一个镜像的两种进程**

Run:

```bash
cd InventoryManager
docker build --platform linux/amd64 -t xianyu-agent:saas-main-lite-test .
docker run --rm --env-file .env xianyu-agent:saas-main-lite-test python worker.py --once
```

再以默认 CMD 启动 app，连接隔离测试控制/业务库，轮询 `/health` 成功后停止该明确命名的测试容器。Expected: app 与 worker 使用同一 image digest，worker 不尝试启动 HTTP server，app 不启动 scheduler。

- [ ] **Step 5: 扫描敏感信息和禁止架构**

Run:

```bash
git grep -n -I -E "(BEGIN (RSA|EC|OPENSSH) PRIVATE KEY|SECRET_KEY=.+[^_]$|app_secret.*[:=].+|monthly_card.*[:=].+|NAS_PASS|***REMOVED***|***REMOVED***)" -- . ':!*.pdf'
rg -n "outbox|Celery|APScheduler|event_bus|job_attempt|lease|fence|inventory_mode|logical_inventory|printer_pool" InventoryManager/app InventoryManager/tests
git ls-files | rg "(^|/)\.env$|\.sql$"
```

Expected: 无真实 secret/地址/旧硬编码寄件人；无禁止框架；Git 不追踪 `.env` 或 SQL。

- [ ] **Step 6: 审计表、迁移、文件和行数**

Run:

```bash
git diff --numstat my_xianyuagent/main...HEAD
git diff --name-status my_xianyuagent/main...HEAD
rg -n "__tablename__" InventoryManager/app/control InventoryManager/app/models
rg -n "^revision =|^down_revision =" InventoryManager/control_migrations InventoryManager/migrations/versions/20260824_saas_lite_*.py
git diff --check
```

Expected: 控制新表=5、业务新表=4、控制迁移=1、业务 SaaS 迁移=2；生产新增不超过 20,000 行、全部手写新增不超过 30,000 行、新生产文件约 30 内、新测试文件约 20 内。超限则暂停并向用户提供逐文件明细，不自行继续。

- [ ] **Step 7: 请求代码审查并修复问题**

调用 `superpowers:requesting-code-review`。任何 review 修复先复现、补测试、实现、重跑对应和完整验证；不要因 review 顺手加入设计外能力。

- [ ] **Step 8: 准备最终交付摘要**

列出实际 commit、测试数/结果、生产备份迁移报告摘要、镜像命令、表/迁移/行数、已知限制，以及“等待用户提供 NAS 配置样例和公网入口条件”。随后调用 `superpowers:finishing-a-development-branch` 让用户决定是否推送/合并。

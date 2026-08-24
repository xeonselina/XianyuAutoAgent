# SaaS Main Lite Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从最新远端 `main` 建立 `saas-main-lite`，以四个可独立验收的阶段完成轻量租户隔离、多仓业务、按仓/店铺集成、Worker、生产数据迁移和单镜像交付。

**Architecture:** 保留现有 Flask-SQLAlchemy 业务模型和 Vue 应用，以独立控制库保存 5 张租户/认证表，请求期把现有业务 Session 绑定到每租户独立 MariaDB 数据库；业务库只新增 4 张配置表和必要外键。app 与 worker 使用同一镜像，worker 只顺序执行预约发货和闲鱼同步两个任务。

**Tech Stack:** Python 3.10、Flask 2.3、Flask-SQLAlchemy 3、SQLAlchemy、Alembic/Flask-Migrate、MariaDB 10.11、PyMySQL、cryptography AES-GCM、Werkzeug、Tencent Cloud SMS SDK、schedule、Vue 3、TypeScript、Pinia、Element Plus、Vant、Vitest、pytest、Docker

**Spec:** `docs/superpowers/specs/2026-08-24-saas-main-lite-design.md`

## Global Constraints

- 目标分支必须是用户指定的 `saas-main-lite`，从执行时最新的远端 `main` 创建；不得以 `saas-main` 为代码基线。
- 当前本地 `main` 已含设计提交 `e146eb8`，但落后远端 4 个提交。创建工作树前先 `git fetch`，再从远端 `main` 建分支，并把设计与计划文档提交带入新分支；不得覆盖或重置用户工作区。
- 控制库固定 5 张表：`platform_admins`、`tenants`、`tenant_members`、`auth_sessions`、`sms_login_codes`。
- 业务库固定新增 4 张表：`warehouses`、`warehouse_sf_configs`、`warehouse_kuaimai_configs`、`xianyu_shops`。任何额外持久表先暂停并请用户决策。
- 不引入 Redis、Celery、APScheduler、outbox、事件总线、Repository 层、通用外部配置框架、自定义权限系统或逻辑库存。
- 生产代码新增目标 8,000–15,000 行、测试新增目标 5,000–10,000 行；生产代码超过 20,000 行或全部新增手写代码超过 30,000 行时暂停并请用户决策。
- 生产新文件目标不超过 30 个，测试新文件目标不超过 20 个；每阶段结束执行文件数和行数审计。
- 数据库行为、外键、枚举、授权与迁移验收使用 MariaDB 10.11；SQLite 只用于不依赖 MariaDB 语义的快速单元测试。
- `/platform/*` 与 `/auth/*` 只能访问控制库；业务 API 必须经租户会话校验后才绑定租户业务库。
- 默认租户继续使用 `inventory_management`，不得复制、重命名或整体导入 SQL 备份中的其他数据库。
- 只交付 `app` 与 `worker` 两个进程模式；不提供 MariaDB、Redis、Nginx、公网穿透或 NAS 专用编排。
- 每个任务先建立失败测试，再写最小实现，再运行针对性和回归测试，再提交。
- 发现必须大改 Flask-SQLAlchemy 核心结构、迁移超过 2 条业务迁移、或突破上述表/文件/行数门槛时停止实施并交由用户决策。

## Plan Map

| 阶段 | 计划文件 | 可交付结果 | 进入下一阶段的门槛 |
|---|---|---|---|
| 1 | `2026-08-24-saas-main-lite-phase-1-tenant-foundation.md` | 安全测试库、控制库、租户路由、平台创建、短信登录、基础页面 | 两租户隔离、权限/到期/暂停/短信测试通过 |
| 2 | `2026-08-24-saas-main-lite-phase-2-warehouse-business.md` | 仓库配置、库存/租赁仓库维度、跨仓修正、验货入仓 | 所有仓库业务事务与现有核心业务回归通过 |
| 3 | `2026-08-24-saas-main-lite-phase-3-integrations-worker.md` | 按仓 SF/快麦、按店闲鱼、独立 worker | 双仓配置、双店同步、失败隔离、重复 worker 锁测试通过 |
| 4 | `2026-08-24-saas-main-lite-phase-4-migration-release.md` | 生产备份演练、默认租户迁移、全回归、app/worker 镜像和环境示例 | 备份可恢复、数据不变量、镜像双命令和安全扫描全部通过 |

---

### Task 1: 建立隔离工作树和执行基线

**Files:**
- Preserve: `docs/superpowers/specs/2026-08-24-saas-main-lite-design.md`
- Preserve: `docs/superpowers/plans/2026-08-24-saas-main-lite-*.md`
- Create outside current worktree: `../XianyuAutoAgent-saas-main-lite/`

**Interfaces:**
- Consumes: 执行时远端 `my_xianyuagent/main` 与本地已提交的设计/计划文档。
- Produces: 分支 `saas-main-lite` 的独立 Git worktree；不修改现有工作树中的用户文件。

- [ ] **Step 1: 确认当前文档提交和工作区状态**

Run:

```bash
git status --short --branch
git log --oneline --decorate -5
git diff --check
```

Expected: 设计与计划已提交；工作区无未提交变更。若存在用户变更，先保留并改用不冲突的 worktree 路径，不清理、不 stash、不 reset。

- [ ] **Step 2: 获取最新远端主分支并核对分叉**

Run:

```bash
git fetch my_xianyuagent main
git log --oneline --left-right main...my_xianyuagent/main
```

Expected: 清楚列出本地文档提交和远端业务提交；不在本地 `main` 上 rebase 或 merge。

- [ ] **Step 3: 创建用户指定分支工作树**

Run:

```bash
git worktree add ../XianyuAutoAgent-saas-main-lite -b saas-main-lite my_xianyuagent/main
git -C ../XianyuAutoAgent-saas-main-lite status --short --branch
```

Expected: 新工作树位于 `saas-main-lite`，基线是最新远端 `main`。

- [ ] **Step 4: 带入已确认的设计与计划提交**

设计提交固定为 `e146eb8`。计划提交用 Phase 4 计划文件定位，避免依赖本地 `main` 后续是否新增其他提交：

```bash
SAAS_LITE_PLAN_COMMIT="$(git log -1 --format=%H -- docs/superpowers/plans/2026-08-24-saas-main-lite-phase-4-migration-release.md)"
git -C ../XianyuAutoAgent-saas-main-lite cherry-pick e146eb8 "$SAAS_LITE_PLAN_COMMIT"
```

Run:

```bash
git -C ../XianyuAutoAgent-saas-main-lite log --oneline --decorate -8
git -C ../XianyuAutoAgent-saas-main-lite diff my_xianyuagent/main...HEAD --stat
```

Expected: 相对远端主分支只新增已确认的设计和实施计划文档。

- [ ] **Step 5: 建立实施前基线报告**

Run:

```bash
cd ../XianyuAutoAgent-saas-main-lite/InventoryManager
python -m pytest -q
cd frontend && npm run test:run && npm run type-check && cd ..
cd frontend-mobile && npm run build && cd ..
```

Expected: 记录当前真实通过/失败项。若最新远端 `main` 自身失败，先按 `superpowers:systematic-debugging` 确认是否为基线问题；不得把无关修复混入 SaaS 任务提交。

- [ ] **Step 6: 不为基线结果制造文件**

不为“记录测试结果”创建代码文件或提交。把基线命令输出保留在执行任务记录中；如果基线自身失败，先按系统化调试流程确认原因，再决定是否需要单独修复。

---

### Task 2: 顺序执行四个阶段并设置审查门

**Files:**
- Follow: `docs/superpowers/plans/2026-08-24-saas-main-lite-phase-1-tenant-foundation.md`
- Follow: `docs/superpowers/plans/2026-08-24-saas-main-lite-phase-2-warehouse-business.md`
- Follow: `docs/superpowers/plans/2026-08-24-saas-main-lite-phase-3-integrations-worker.md`
- Follow: `docs/superpowers/plans/2026-08-24-saas-main-lite-phase-4-migration-release.md`

**Interfaces:**
- Consumes: 上一阶段的已提交、已验证结果。
- Produces: 每阶段一个可运行纵向切片；不得跨阶段预建通用框架。

- [ ] **Step 1: 执行阶段 1**

严格按阶段 1 计划逐任务执行。结束后要求：控制库固定 5 表、两个租户同 ID 数据隔离、Admin/Operator/Super Admin 边界、到期/暂停、短信规则和基础登录/平台页面测试通过。

- [ ] **Step 2: 审计阶段 1 差异**

Run:

```bash
git diff my_xianyuagent/main...HEAD --stat
git diff my_xianyuagent/main...HEAD --numstat
git ls-files InventoryManager/app InventoryManager/tests InventoryManager/frontend/src InventoryManager/frontend/tests | wc -l
```

Expected: 未出现业务表、任务框架或 SaaS 通用层；累计规模仍在总预算内。

- [ ] **Step 3: 执行并审计阶段 2**

严格按阶段 2 计划执行。阶段结束必须验证仓库内可用性、跨仓全有或全无修正、验货仓位同步，以及租赁、库存、统计、接力回归。业务库新增表总数必须恰好为 4。

- [ ] **Step 4: 执行并审计阶段 3**

严格按阶段 3 计划执行。阶段结束必须验证 SF/快麦按租赁仓库解析、闲鱼按店铺解析、180 秒同步、60 秒预约发货、单租户/单店失败隔离和 MariaDB advisory lock。

- [ ] **Step 5: 执行并审计阶段 4**

严格按阶段 4 计划执行。生产 SQL 还原演练只能操作显式包含 `test` 的数据库/账号和独立 Docker volume；不得连接生产库。最终只验证同一镜像的 app/worker 两种命令，不编写 NAS 专用配置。

- [ ] **Step 6: 每阶段结束运行规模门禁**

Run:

```bash
git diff --numstat my_xianyuagent/main...HEAD | awk '{added += $1; deleted += $2} END {print "added", added, "deleted", deleted}'
git diff --name-status my_xianyuagent/main...HEAD
git diff --check
```

Expected: 差异可逐文件解释；若生产新增超过 20,000 行、全部手写新增超过 30,000 行、新增生产文件超过约 30 个、新增测试文件超过约 20 个，立即暂停并向用户报告明细。

---

### Task 3: 最终验收与交付决策

**Files:**
- Verify: `InventoryManager/app/`
- Verify: `InventoryManager/tests/`
- Verify: `InventoryManager/frontend/`
- Verify: `InventoryManager/frontend-mobile/`
- Verify: `InventoryManager/migrations/`
- Verify: `InventoryManager/control_migrations/`
- Verify: `InventoryManager/Dockerfile`
- Verify: `InventoryManager/.env.example`

**Interfaces:**
- Consumes: 四阶段完成后的 `saas-main-lite`。
- Produces: 可供用户代码审查和后续 NAS 样例适配的分支；本计划不自动合并或推送。

- [ ] **Step 1: 使用完成前验证技能执行全套新鲜验证**

必须先调用 `superpowers:verification-before-completion`，再运行阶段 4 列出的完整测试、构建、MariaDB 迁移、镜像和安全扫描命令。不能引用早先缓存结果代替。

- [ ] **Step 2: 请求代码审查**

调用 `superpowers:requesting-code-review`，审查重点为租户越权、错误数据库绑定、迁移不可逆风险、敏感信息泄漏、跨仓部分提交和 worker 重复执行。

- [ ] **Step 3: 生成交付摘要**

摘要必须包含：

- 实际新增/删除行数和新增文件数。
- 实际控制库/业务库表清单与迁移 revision。
- 生产 SQL 演练的库名、行数不变量和恢复结果，不包含任何凭证。
- app/worker 镜像启动命令。
- 尚待用户提供的 NAS 配置样例和公网入口决策。
- 已知限制与人工上线步骤。

- [ ] **Step 4: 选择分支收尾方式**

调用 `superpowers:finishing-a-development-branch`，让用户选择保留分支、合并、PR 或其他处理。除非用户明确说“push 一下”或“提交推送”，否则不自动推送。

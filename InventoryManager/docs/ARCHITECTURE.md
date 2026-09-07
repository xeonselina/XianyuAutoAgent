# ARCHITECTURE — 跨功能域的不变量

改代码前若涉及下列任一机制，**必读**对应章节。这些是「改错就出生产事故」的部分。
功能域到文件的导航见 `docs/INDEX.md`。

## 1. 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Flask + Flask-SQLAlchemy + Flask-Migrate(Alembic)，MySQL(pymysql) |
| 生产服务 | gunicorn + gevent worker（见 `gunicorn_config.py`） |
| PC 前端 | Vue 3 + Element Plus + Pinia + Vite → 构建到 `static/vue-dist/` |
| 移动前端 | Vue 3 + Vant 4 + Pinia + Vite → 构建到 `static/vue-mobile-dist/` |
| 多租户 | **database-per-tenant**：一个控制库 + N 个租户业务库 |

应用工厂：`create_app(config_class, worker_mode=False)`（`app/__init__.py`）。

## 2. 多租户请求链

一次请求的租户绑定过程（`routes/web.py` 的 `bind_request_tenant`，注册为 `before_request`）：

1. 校验 `tenant_session` Cookie → `resolve_tenant_session`
2. CSRF 校验
3. 检查租户 `provisioning_status` / `status` / `expires_at`
4. `TenantEngineRegistry.get(tenant)` 取（或建）该租户的 Engine
5. `bind_tenant()` 把 `(tenant_id, engine)` 写入 ContextVar
6. `teardown_request` 时 `reset_request_tenant` 清理

**关键**：所有 `app/models/*` 无需任何改写即自动落到当前租户库。靠的是
`app/tenant_context.py` 里 `TenantSession.get_bind()` 覆写，按 ContextVar 中的 Engine 分发；
而 `db = SQLAlchemy(session_options={"class_": TenantSession})`。

常用符号：`bind_tenant` / `reset_tenant` / `clear_tenant_binding` / `current_tenant_id` /
`_current_tenant_engine` / `TenantSession` / `TenantEngineRegistry`。

**租户开通**：`app/provisioning.py` 的 `TenantProvisioner` 用 `PROVISIONER_DATABASE_URL`（高权账号）
`CREATE DATABASE inventory_tenant_<id>` + 建 `im_t<id>` 用户 + 跑业务迁移。

## 3. 两套 Alembic 迁移 —— 最容易搞错的地方

| | `control_migrations/` | `migrations/` |
|---|---|---|
| 配置文件 | `control_alembic.ini` | Flask-Migrate（`migrations/alembic.ini`） |
| 目标库 | **控制库（全局仅 1 个）** | **每个租户业务库（N 个）** |
| 版本数 | 1 | 31 |
| 谁执行 | 手动 `alembic -c control_alembic.ini upgrade head` | 新租户由 `TenantProvisioner` 自动 upgrade；既有库走 Flask CLI |

**顺序铁律**：控制库先，租户库后；worker 停机期间执行。详见 `DEPLOY.md` 第 5 章。

`migrations_backup/` 是废弃目录，勿用。

## 4. gevent monkey patch 铁律

`run.py` **首行必须**是（在任何其他 import 之前）：

```python
import gevent.monkey
gevent.monkey.patch_all()
```

原因：若 `urllib3` / `aiohttp` 等模块先于 monkey patch 被导入，SSL 会处于**半 patch 状态**，
在 HTTPS 请求时触发 `RecursionError: maximum recursion depth exceeded`。

配套约束：`gunicorn_config.py` 中 `preload_app = False`。
若为 `True`，主进程会先加载应用、在 fork 前导入 SSL 相关模块，patch 失效。
代价是每个 worker 独立加载，启动略慢、内存略高 —— 这是有意为之。

补充事实：
- 该问题在 x86 服务器上出现，**本地 Mac 不出现**（模块加载顺序与时机差异）。不要因为本地正常就放松约束。
- `gunicorn_config.py` 自身顶部也做了一次 patch（幂等安全），因为 gunicorn 导入时机不同。
- 生产配置：`bind 0.0.0.0:5002`、`workers = 4`、`worker_class = gevent`、`timeout = 120`。

## 5. 前端双应用与部署落点

| 应用 | 源 | 构建产物 | 路由 |
|---|---|---|---|
| PC | `frontend/` | `static/vue-dist/` | 默认 |
| 移动端 | `frontend-mobile/` | `static/vue-mobile-dist/` | `/mobile/` |

`routes/vue_app.py` 按 User-Agent 检测手机并跳 `/mobile/`。
`static/mobile-dist/` 是**旧产物**，已不引用（见 `docs/INDEX.md` 死代码清单）。

任何前端改动都必须**同时考虑 PC 端和移动端两侧**。

## 6. worker 单实例锁

`worker.py` 用控制库 MySQL/MariaDB advisory lock 保证单实例：

- 锁名 `LOCK_NAME = "inventory-manager-worker-v1"`
- 取锁 `SELECT GET_LOCK(:name, 0)`（不等待，拿不到就退出）
- **每个租户周期前**用 `SELECT IS_USED_LOCK(:name)` 复核归属，丢失则抛 `lock ownership lost`
- 释放 `SELECT RELEASE_LOCK(:name)`

含义：**第二个 worker 实例会直接退出，不会接管**。所以部署时不存在双写风险，
但也意味着 worker 挂了没人自动补位。

worker 遍历所有 active 租户逐个 `bind_tenant` 执行：发货调度（60s）+ 闲鱼对账（180s）。
worker 模式通过 `create_app(worker_mode=True)` 启动，**不注册任何蓝图**、
不加载静态资源与短信。

## 7. 安全与配置约束（生产 fail-closed）

`config.py` 与 `app/__init__.py` 会在生产配置下直接拒绝启动，而非降级运行：

- `SAAS_MASTER_KEY` 不得为默认值
- `SECRET_KEY` 不得为默认值
- 禁止 `DEV_SMS_CODE`
- `TENANT_DB_NAME_PREFIX` / `TENANT_DB_USER_PREFIX` 必须恰为 `inventory_tenant_` / `im_t`
- `TENANT_DB_PORT` 必须在 1-65535
- `CORS_ORIGINS` 必须是精确 origin（带凭据的 CORS 要求）；`_is_exact_http_origin` 校验失败会抛 `RuntimeError`
- `TRUSTED_PROXY_HOPS` 按反向代理层数设置，负数直接报错

## 8. 测试

```
tests/unit/          28 个测试模块，不需要数据库
tests/integration/   18 个测试模块，需要数据库
tests/support/       3 个辅助文件
```

运行：`python -m pytest tests/unit/` （`pytest.ini` 的 `testpaths = tests`）

**`tests/unit/test_production_config.py` 是发布安全护栏**，不是普通单测：
它断言 Makefile 只有 6 个 target 且不含主机特定配置、Dockerfile 不含 `COPY . .`、
以及文档中不含旧手机号/地址等敏感残留。改构建配置或删文档前先看它。

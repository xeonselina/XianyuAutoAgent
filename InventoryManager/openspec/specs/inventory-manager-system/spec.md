# InventoryManager 全系统契约

## Purpose

本规格定义当前 InventoryManager 摄影器材租赁库存 SaaS 的应用边界、运行拓扑、导航、跨模块数据规则及复刻验收入口。它与同目录下各功能规格组成**一套**复刻规格；单独复制本文件不能复刻全部业务。规格内容来自当前 `saas-main-lite` 代码，不能把 `openspec/changes/` 中尚未落地的提案当成现有功能。

## Requirements

### Requirement: 控制库与租户业务库隔离

系统 MUST 使用一个控制库保存平台管理员、租户、成员、认证会话和短信验证码，每个租户另有一套完整业务库。一次业务请求 MUST 先确认租户会话、成员状态、开通状态、租户暂停和到期状态，再绑定该租户的数据库引擎；请求结束 MUST 移除 ORM 会话并清除上下文绑定。

#### Scenario: 同一设备 ID 在两个租户中存在
- **WHEN** 租户 A 和 B 各访问 `/api/devices/1`
- **THEN** 两次查询分别落在其租户库中，不得相互读取或写入

#### Scenario: 会话过期
- **WHEN** 过期的 `tenant_session` 调用业务 API
- **THEN** 返回 401、`code=AUTH_REQUIRED`，不查询业务数据库

### Requirement: PC 与移动端共用业务 API

PC MUST 以 Vue 3、Element Plus、Pinia 实现；移动端 MUST 以 Vue 3、Vant 4、Pinia 实现。服务端 MUST 提供两套静态构建产物，PC 为 `static/vue-dist/`，移动端为 `static/vue-mobile-dist/`。手机浏览器访问默认首页时进入 `/mobile/`，移动端的 history base 为 `/mobile/`。两端共享租户会话及业务数据，但分别实现适合各自屏幕的页面。

#### Scenario: 手机打开首页
- **WHEN** 手机 User-Agent 请求 `/`
- **THEN** 进入移动端甘特，访问 `/mobile/edit-rental/<id>` 可在刷新后恢复移动页面

### Requirement: 三个进程入口职责固定

生产 Web MUST 由 `run.py` 作为 WSGI 入口并在任何 SSL/HTTP 客户端导入前执行 gevent monkey patch；Gunicorn MUST 使用 gevent worker 且 `preload_app=False`。`app.py` 仅作开发／Flask CLI 入口，端口 5002。`worker.py` MUST 使用 `create_app(worker_mode=True)`，不注册 HTTP 蓝图、静态资源或短信客户端。

#### Scenario: 第二个 worker 启动
- **WHEN** 已有 worker 持有控制库 advisory lock
- **THEN** 新 worker 不等待、不接管，直接退出

### Requirement: 双套迁移顺序固定

控制库迁移在 `control_migrations/`，租户业务库迁移在 `migrations/`。新部署 MUST 先升级控制库，再升级各租户库；新租户建库后自动执行业务迁移。完整生产数据回滚必须整体恢复控制库与业务库备份，不能只降级部分表。

#### Scenario: 新租户开通
- **WHEN** 平台管理员创建租户
- **THEN** 控制库先记录租户，Provisioner 创建 `inventory_tenant_<id>` 与 `im_t<id>`，执行租户迁移并创建初始仓库／成员后标记 active

### Requirement: 页面导航和权限边界明确

PC 除登录与平台登录页外均需要租户会话；平台租户管理只允许平台会话；租户“设置”只允许管理员。移动端所有业务路由都需租户会话和 active 访问状态。若会话失效，客户端 MUST 带当前路径、查询和 hash 跳至登录；登录成功只接受同源内部 `next` 路径并返回该路由。暂停、到期和未就绪租户显示受限状态，而不是继续写入。

#### Scenario: 租赁编辑中登录过期
- **WHEN** 操作员在编辑页面收到业务 API 的 401 `AUTH_REQUIRED`
- **THEN** 进入 `/login?next=<原内部路径>`；重新登录后回到原路径

#### Scenario: 尝试外站重定向
- **WHEN** 登录链接的 `next` 是 `//evil.example`、含反斜杠、跨源或平台管理路径
- **THEN** 回到安全默认首页，不跳到外部地址或平台区

### Requirement: 业务 HTTP 响应和仓库选择保持一致

现役内部 API 的统一响应壳 MUST 为 `{success,message?,data?,code?}`，HTTP 状态码必须正确。`/api/devices` 等少数旧路径仍返回直接分页对象，具体以功能规格为准。仓库读取可选具体 ID、`all` 或省略；业务写入必须选择具体有效仓库，单仓库租户才可自动补全。不同功能在 `all` 模式下不可把“当前选中仓库”假定为具体 ID。

#### Scenario: 多仓库租户在全部仓库视图创建租赁
- **WHEN** 请求缺少具体 `warehouse_id`
- **THEN** 服务端拒绝写入；客户端要求先切换到具体仓库

### Requirement: 生产配置安全失败关闭

生产环境若缺失或使用默认 `SAAS_MASTER_KEY`、`SECRET_KEY`，启用 `DEV_SMS_CODE`，租户数据库前缀不符合 `inventory_tenant_`／`im_t`，租户库端口无效，可信代理跳数为负，或带凭据 CORS 来源不是精确 HTTP(S) origin，应用 MUST 拒绝启动。worker MUST 不持有建库高权数据库 URL 和短信凭据。

#### Scenario: 生产环境误配通配 CORS
- **WHEN** `CORS_ORIGINS` 含通配域、路径、查询或非法端口
- **THEN** 应用启动抛错，不降级为任意来源可访问

## 运行与导航契约

| 项 | 当前行为 |
|---|---|
| 服务端 | Flask + Flask-SQLAlchemy + Flask-Migrate + MySQL；Gunicorn 绑定 5002，4 个 gevent worker，超时 120s |
| PC | history 路由：`/` 甘特、`/devices` 设备、`/operations` 操作、`/shipping/:id` 发货单、`/batch-shipping-order`、`/batch-shipping`、`/rental-stats`、`/sf-tracking`、`/relay-management`、`/inspection`、`/inspection-records`、`/settings`、`/change-password`、`/login`、`/access-restricted`、`/platform/login`、`/platform/tenants`；`/gantt` 重定向 `/`，`/statistics` 重定向 `/rental-stats` |
| 移动端 | `/mobile/gantt`、`/mobile/batch-shipping`、`/mobile/create-rental`、`/mobile/edit-rental/:id`、`/mobile/device-status`、`/mobile/search`、`/mobile/customer-history`、`/mobile/relay`；`/mobile/` 重定向甘特 |
| 会话 Cookie | `tenant_session` path `/`，7 天；`platform_session` path `/platform`，12 小时；均 HttpOnly、SameSite=Lax，HTTPS 时 Secure |
| 写请求 | 租户和平台 API 使用 `X-CSRF-Token`；当前会话 `/auth/me` 或 `/platform/auth/me` 可取稳定的 CSRF token |
| 健康检查 | `GET /health` 返回 `status=healthy` 和固定 `timestamp=2024-01-01T00:00:00Z`；`GET /external-api/health` 为外部探针 |
| 数据库 | 控制库 5 类表：平台管理员、租户、成员、会话、短信验证码；租户库保存设备、型号、仓库、租赁、验货、接力、统计、闲鱼告警等 |
| 定时任务 | worker 控制库 advisory lock `inventory-manager-worker-v1`；发货调度 60 秒、闲鱼对账 180 秒，逐个 active 租户执行 |

## 功能规格地图

以下规格共同组成复刻输入；各规格只能描述当前已落地的行为。外部 API 的旧路径与新内部 API 不应合并语义。

| 功能域 | 规格目录 | 主要代码入口 |
|---|---|---|
| 租赁、同单、附件、确认 | `rental-management` | `app/routes/rental_api.py`、`app/services/rental/rental_service.py` |
| 认证、开店、设置 | `tenant-access` | `app/routes/auth_api.py`、`platform_api.py`、`settings_api.py` |
| 设备、型号、仓库、移仓 | `device-inventory` | `app/routes/device_api.py`、`device_model_api.py` |
| 甘特与排期重排 | `gantt-scheduling` | `app/routes/gantt_api.py` |
| 发货、面单、快递追踪 | `shipping-fulfillment`、已有 `sf-waybill-api`、`batch-print-ui`、`kuaimai-integration`、`pdf-conversion` | `app/routes/shipping_batch_api.py` 等 |
| 验货 | `inspection-workflow` | `app/routes/inspection.py` |
| 接力／续租 | `rental-relay` | `app/routes/relay_case_api.py` |
| 闲鱼缺单／退款对账 | `xianyu-reconciliation` | `app/routes/xianyu_order_alert_api.py` |
| 客户历史、统计、搜索 | `customer-analytics` | `app/routes/customer_api.py`、`statistics_api.py`、`rental_stats_api.py` |
| 工作进程与外部 API | `runtime-integrations` | `worker.py`、`app/routes/external_api.py` |
| PC／移动端页面外壳 | `interface-design` | `frontend/src/App.vue`、`frontend-mobile/src/App.vue` 与两端 Router |
| 跨模块端到端旅程 | `cross-domain-journeys` | 各领域业务服务、控制库与租户库、PC／移动前端 |

本目录的 `design.md` 按代码列出全部 169 个 HTTP 装饰器绑定与 185 个 ORM 显式列，供复刻时逐条核对；领域语义仍以各功能 `spec.md` 为准。

## 代码依据与复刻验收

代码依据：`app/__init__.py`、`app/routes/web.py`、`app/tenant_context.py`、`app/control/models.py`、`run.py`、`app.py`、`worker.py`、`config.py`、`gunicorn_config.py`、PC／移动路由表和 `DEPLOY.md`。验收必须覆盖：控制库和两个租户库、两端登录与过期恢复、所有导航路由直接刷新、跨仓库行为、worker 互斥、双迁移、新建租户，以及各功能规格的正反例。要验证“99% 相似”，应在干净项目按这些规格实现，再用相同测试数据跑接口与两端用户旅程；仅通过 Markdown 格式校验不等于达到相似度目标。

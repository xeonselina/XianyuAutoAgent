# 独立 Worker、外部 API 和部署边界

## Purpose

定义 HTTP 以外的后台循环、外部 API 实际可用的旧契约及生产进程边界。顺丰、快麦、闲鱼的领域规则在各自功能规格中。

## Requirements

### Requirement: Worker 必须单实例执行并按租户隔离

`worker.py` MUST 以 `create_app(worker_mode=True)` 运行，并在控制库连接上持有名为 `inventory-manager-worker-v1` 的 MySQL/MariaDB advisory lock。拿不到锁直接退出。遍历条件为 `provisioning_status=active,status=active,expires_at>当前 UTC` 的租户，按 ID 升序逐个绑定业务库；每租户／每任务失败只记录日志并继续，结束后清理 ORM session 与租户绑定。每轮及每个租户开始前复核锁仍由原连接持有；失锁必须停止，不能继续双写。

#### Scenario: 一租户业务库出错
- **WHEN** 租户 A 的任务抛异常且租户 B 仍 active
- **THEN** A 的会话／绑定清理，B 仍运行，任何 A 的行不可写到 B 的库

### Requirement: Worker 周期和定时发货语义固定

Worker MUST 启动即执行一轮定时发货和闲鱼店铺对账，随后分别每 60 秒和 180 秒运行；`--once` 各执行一轮后退出。定时发货只挑主租赁、状态 `scheduled_for_shipping` 且 `scheduled_ship_time <=` 当前上海业务墙钟的记录，按 ID 升序逐笔处理。带闲鱼店铺与订单号的租赁先通知闲鱼发货，失败则该笔回滚；成功后主租赁及子租赁写 `shipped` 和相同寄出时间。对账逐 active 店铺独立处理，不因某店失败跳过后续店铺。

#### Scenario: 预约时间已到而闲鱼失败
- **WHEN** 到期主租赁的闲鱼发货接口返回失败
- **THEN** 主、子租赁维持原状态；下一周期可再次尝试，其他到期租赁照常处理

### Requirement: 外部 API 需要两层身份并保持旧响应

除 `/external-api/health` 和 `/external-api/docs`，外部 API MUST 先经过租户会话、租户访问状态和写请求 CSRF，再由 `X-API-Key` 与本机 `API_KEY` 精确比对；API Key 本身不足以确定租户。外部 API 使用旧式 `{success,data?,error?}` 响应，不应被内部统一壳改写。外部 API 健康探针独立于业务租户，返回当前 UTC 时间和 `InventoryManager External API` 服务名。

#### Scenario: 仅持 API Key 调用库存
- **WHEN** 外部客户端无租户 Cookie，只发送正确 `X-API-Key`
- **THEN** 租户边界先返回 401 `AUTH_REQUIRED`，不会跨租户读取库存

### Requirement: 旧外部端点的现状必须如实保留

`GET /external-api/inventory/available` MUST 要求 ISO `ship_out_time,ship_in_time`，寄出早于收回且不早于当前时间，支持设备名子串 `device_type` 与仓库过滤，返回设备 ID、名、序列号、生命周期、`location:null`、总数及 UTC 时间。`POST /external-api/inventory/check` 接 `queries` 数组逐项返回可用设备 ID。设备列表可按 `lifecycle_status` 与仓库筛选，旧 `status` 参数返回 400；`location` 已废弃且响应始终 null。`PUT /devices/<id>/status` 返回 410。租赁读取、简单更新时间／状态与取消端点仍存在；`POST /external-api/rentals` 当前调用旧服务时缺少现役必填参数，不能视作已验证可用的建单接口。复刻实现若要修复，应先提行为变更规格，不能把修复后的结果冒称当前行为。

#### Scenario: 旧设备状态调用
- **WHEN** 使用 API Key 和有效租户会话调用 `PUT /external-api/devices/1/status`
- **THEN** 返回 410 并提示使用生命周期接口

### Requirement: 生产 Web 与 Worker 权限分离

生产 Web MUST 由 `run.py` 在导入 Flask／HTTP 客户端前 gevent monkey patch；Gunicorn 绑定 `0.0.0.0:5002`、4 个 gevent worker、120 秒超时、`preload_app=False`。Worker 不注册 HTTP 蓝图、前端静态资源或短信客户端；其环境不可提供租户建库高权 URL 和腾讯短信密钥。控制库迁移先于业务租户库迁移，迁移期间停 worker，生产回滚需要控制库和租户库同一时间点完整备份。

#### Scenario: Web 重启
- **WHEN** 4 个 Gunicorn Web worker 重启
- **THEN** 它们各自只提供请求处理，不抢后台业务任务；唯一独立 worker 持续持有控制库锁

### Requirement: 前端静态回退和旧页面路径按现状服务

服务端 MUST 让桌面 User-Agent 访问 `/` 或 `/app/` 获得 PC `vue-dist/index.html`，手机 User-Agent 匹配 Android Mobile、iPhone、iPod、BlackBerry、IEMobile、Opera Mini 时重定向 `/mobile/`，平板默认走 PC。PC 业务路径及登录／平台路径直接访问或刷新时返回 PC SPA 壳；`/mobile`、`/mobile/`、`/mobile/<path>` 返回移动 SPA 壳；两端分别从 `/assets/*` 和 `/mobile/assets/*` 提供构建资源。旧 `/vue`、`/vue/`、`/vue/<path>` 仍服务 PC 构建。历史 `/rentals` 服务端页面路由仍注册，但当前缺 `rentals.html` 模板，不能当成可用 Vue 路由。

#### Scenario: 手机直接刷新编辑 URL
- **WHEN** iPhone 浏览器直接 GET `/mobile/edit-rental/17`
- **THEN** 返回移动版 index，客户端在有效会话下恢复对应编辑路由

### Requirement: 开发用顺丰烟测在生产必须不可见

`/api/sf-test/status` 与 `/api/sf-test/order/<rental_id>` MUST 仅在 testing 或 debug 且非生产模式注册可用；生产任何请求先返回 404，即使已有租户会话。烟测仍经过租户会话与 CSRF：status 只回仓库 ID、配置完成和测试模式，order 走真实前置校验／顺丰解析器但不暴露客户或密钥，失败用 `CONFIG_INCOMPLETE`、`WAREHOUSE_MISMATCH`、`EXTERNAL_SERVICE_ERROR` 等码。

#### Scenario: 生产扫描烟测路径
- **WHEN** 生产环境 GET `/api/sf-test/status?warehouse_id=1`
- **THEN** 返回 404，不泄漏仓库配置状态

### Requirement: 审计日志与业务变更同事务写入

移仓、验货跨仓修复和同单减租等操作 MUST 在当前租户的 `audit_logs` 留动作名、资源类型／ID、描述及 JSON `details`；传 `commit=False` 的日志参与调用者的业务事务，回滚时日志同样回滚。日志模型另有可选设备 ID、租赁 ID、IP 和 User-Agent 以及 UTC 创建时间；当前无公开审计查询路由，不能凭模型方法推断有管理页面。

#### Scenario: 移仓执行失败
- **WHEN** 替换租赁过程中事务回滚
- **THEN** 源设备、租赁及本次审计记录均不落库

## 外部 API 矩阵

| 方法与路径（统一前缀 `/external-api`） | 当前语义 |
|---|---|
| `GET /health`、`GET /docs` | 公开健康／静态文档 |
| `PUT /devices/<int:id>/status` | 410，在线／离线功能已移除 |
| `GET /inventory/available` | 时间区间、设备名子串、仓库可用性 |
| `POST /inventory/check` | 多个时间区间逐项检查 |
| `POST /rentals` | 旧建单适配器，尚不能作为现役建单合同 |
| `GET /rentals/<int:id>` | `Rental.to_dict()` |
| `PUT /rentals/<int:id>` | 可更新寄出／寄回时间和状态，UTC 更新时间 |
| `POST /rentals/<int:id>/cancel` | 旧取消服务结果 |
| `GET /devices`、`GET /devices/<id>` | 生命周期／仓库列表，详情含当前租赁 |
| `GET /statistics` | 设备生命周期数量与若干旧租赁状态计数 |

外部 `/statistics` 的租赁状态键 `active,pending,completed,overdue` 是旧兼容统计口径；不能与现役 `not_shipped/scheduled_for_shipping/shipped/returned/cancelled` 的经营统计混为一谈。

## 验收与代码依据

验收涵盖抢锁失败、锁丢失、A 租户失败仍运行 B、到期边界、闲鱼发货失败、会话/API Key 双层身份、旧端点 410／400、`--once` 以及 Web/worker 双进程启动。代码依据：`worker.py`、`app/utils/scheduler_tasks.py`、`app/routes/external_api.py`、`app/routes/web.py`、`run.py`、`gunicorn_config.py`、`app/__init__.py`、`config.py`、`DEPLOY.md`。

# InventoryManager 项目上下文

## 目标

摄影器材租赁库存与档期管理 SaaS。一个平台控制库管理租户、成员和会话；每个租户有独立业务库。操作员使用 PC 或移动页面管理设备、型号、仓库、订单档期、发货、验货、接力、客户历史和统计；管理员管理成员与顺丰、快麦、闲鱼配置。

## 当前技术栈

- 后端：Python、Flask、Flask-SQLAlchemy、Flask-Migrate、MariaDB/MySQL。控制库和租户业务库分别迁移。
- PC：Vue 3、TypeScript、Pinia、Vue Router、Element Plus；构建到 `static/vue-dist/`。
- 移动端：Vue 3、TypeScript、Pinia、Vue Router、Vant 4；构建到 `static/vue-mobile-dist/`。
- 生产：`run.py` + Gunicorn/gevent Web，`worker.py` 独立任务进程，Docker 同一镜像两个角色。
- 外部：顺丰电子运单／轨迹、快麦打印、闲管家订单／发货、腾讯云短信。密钥按平台或仓库／店铺配置保存，敏感值加密。

## 源码地图

| 内容 | 入口 |
|---|---|
| 应用工厂／租户库绑定 | `app/__init__.py`、`app/tenant_context.py`、`app/routes/web.py` |
| 控制库、认证、开店 | `app/control/`、`app/auth.py`、`app/provisioning.py`、`app/routes/auth_api.py`、`platform_api.py` |
| 业务表与迁移 | `app/models/`、`migrations/`；控制库为 `control_migrations/` |
| 业务路由和用例 | `app/routes/`、`app/handlers/`、`app/services/` |
| PC 与移动端 | `frontend/src/`、`frontend-mobile/src/` |
| 后台任务 | `worker.py`、`app/utils/scheduler_tasks.py` |
| 部署 | `DEPLOY.md`、`Dockerfile`、`gunicorn_config.py`、`Makefile` |

## 规格阅读顺序

先读 `specs/inventory-manager-system/spec.md` 的架构、路由和功能地图及同目录 `design.md` 的完整路由／字段索引，再读 `tenant-access`、`interface-design` 和 `cross-domain-journeys`，随后按要实现的业务域读取其规格。`rental-management` 是档期核心；设备、甘特、发货、验货、接力、对账、客户统计与运行集成各有独立规格。顺丰、快麦、PDF 和批量打印的细分规格也已按当前代码复核。`changes/` 是变更计划，未合并的计划不代表当前行为；当前事实以 `specs/` 和源码为准。禁止拿别的子项目行为填补 InventoryManager 规格。

## 业务不变量

- 所有业务查询与写入必须在当前租户库执行，绝不跨租户共享设备、租赁或仓库配置。
- 仓库是当前库存位置；租赁另保存履约时的仓库。移仓不改历史租赁归属。
- 设备型号、生命周期、档期占用、物流状态是不同维度；租赁编辑的冲突提示不等同于自动禁止保存。
- 一个 `RentalBooking` 可对应多个主租赁；附件可用子租赁和设备关联表示。报表对主租赁与 booking 的计数不同。
- 顺丰／快麦配置按履约仓库，闲鱼配置按店铺解析；不得因为某仓或某店缺配置而静默采用别处密钥。
- 预约发货时间作为 Asia/Shanghai 业务墙钟保存；控制库的会话、到期和多数审计时间按 UTC 计算。

## 修改约定

遵循仓库根 `AGENTS.md` 和本目录 `AGENTS.md`。涉及行为的改动先核对／修改相应 OpenSpec 需求和正反场景，再修改代码，并运行相关后端测试、前端 typecheck/build 或对应回归用例；本文件只给项目上下文，具体流程以项目级 `inventory-spec-first` skill 为准。规格必须根据现有代码和已确认的用户需求修订，不能把待实现设计写成已实现事实。部署时遵循 `DEPLOY.md` 的控制库先迁移、租户库后迁移、worker 独立启动与完整备份规则。

## 复刻验收界限

若在另一个目录从零重建，需实现所有当前规格中的数据表、权限、HTTP 输入／输出、错误码、PC／移动路由、业务状态转换、外部集成与后台任务，并用同一批测试数据对两套系统做端点和用户旅程对照。文档能定义目标行为，但不能仅凭规格行数保证“99% 相似”；逐条对照测试才是相似度证据。对不能从代码证实的细节应标记待核实，不能推测成规则。

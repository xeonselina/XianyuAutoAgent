# InventoryManager — 摄影器材租赁库存管理 SaaS

面向摄影器材租赁业务的库存管理系统，支持多租户（database-per-tenant）、
PC 端与移动端双前端、甘特图排期、发货面单与闲鱼订单对接。

## 先读这几份

| 你要做什么 | 读哪个 |
|---|---|
| 改某个功能，不知道动哪些文件 | `docs/INDEX.md`（功能域 → 文件映射，含蓝图注册链与死代码清单） |
| 涉及多租户、迁移、gevent、worker、安全约束 | `docs/ARCHITECTURE.md` |
| 构建、部署、环境变量、数据库迁移、回滚 | **`DEPLOY.md`** |
| 本仓库的 AI 协作硬约束 | `AGENTS.md` |

> **本文件不含部署信息。** 旧版 README 描述的那套构建命令与环境配置文件**均不存在**，
> 早已失效；`makefile.example` 里的 52 个 target 同样全部不可用，真实 `Makefile` 只有 6 个。
> 一切以 `DEPLOY.md` 为准。
>
> 守卫测试 `tests/unit/test_documentation_governance.py` 会校验本文件引用的每个
> `make <target>` 都真实存在，防止再次出现「文档里的命令跑不通」。

## 功能

- **甘特图排期**：设备租赁时间可视化，支持拖拽调整、冲突检测、自动重排
- **租赁管理**：租赁单增删改查，主设备与附件关联，损伤备注，接力/续租
- **库存与仓库**：实时可用设备查询、多仓库、调拨移库
- **设备管理**：设备与型号管理、生命周期状态流转
- **验货检查清单**：出入库验货记录
- **发货与面单**：单笔/批量发货、顺丰面单、快麦打印、物流追踪
- **统计报表**：租赁统计与报表
- **闲鱼对接**：店铺对接、订单对账、缺单告警
- **移动端**：快速预约、设备状态查询、甘特图简版、验货
- **定时任务**：由独立 worker 进程执行（发货调度 + 闲鱼对账）
- **审计日志**：操作记录追踪
- **对外开放 API**：`/external-api/*` 供外部系统集成

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Flask + SQLAlchemy 2 + Flask-Migrate(Alembic)，MySQL |
| 生产运行 | gunicorn + gevent worker（`gunicorn_config.py`） |
| PC 前端 | Vue 3 + Element Plus + Pinia + Vite → `static/vue-dist/` |
| 移动端前端 | Vue 3 + Vant 4 + Pinia + Vite → `static/vue-mobile-dist/` |
| 多租户 | database-per-tenant：一个控制库 + N 个租户业务库 |
| 部署 | Docker 镜像，一个镜像跑 app 与 worker 两个进程 |

## 本地开发

```bash
pip install -r requirements.txt
cp .env.example .env      # 按需填写，勿提交
python app.py             # 开发服务器，端口 5002
```

三个进程入口（职责不同，勿混用）：

| 入口 | 用途 |
|---|---|
| `run.py` | 生产 WSGI 入口，gunicorn 使用。首行 `gevent.monkey.patch_all()` 不可删改 |
| `app.py` | 开发服务器 + Flask CLI，端口 5002 |
| `worker.py` | 定时任务进程，advisory lock 保证单实例 |

主要访问路径（端口 5002）：

| 路径 | 说明 |
|---|---|
| `/` | 按 User-Agent 自动分发 PC / 移动端 |
| `/gantt` `/settings` `/inspection` `/sf-tracking` 等 | PC 端各功能页 |
| `/mobile/` | 移动端 |
| `/platform/login` `/platform/tenants` | 平台管理（租户开通） |
| `/health` `/external-api/health` | 健康检查 |

> `/vue` 与 `/vue/<path>` 是旧版遗留 URL，仅为向后兼容，新代码不要用。

## 测试

```bash
python -m pytest tests/unit/          # 28 个模块，不需要数据库
python -m pytest tests/integration/   # 18 个模块，需要数据库
```

`tests/unit/test_production_config.py` 是**发布安全护栏**：它断言 Makefile 的 target 集合、
Dockerfile 的 COPY 清单、worker 的权限隔离，以及文档中不含敏感残留。
改构建配置或删文档前先跑它。

## 前端开发

两个前端应用必须**同步考虑**：`frontend/`（PC，Element Plus）与
`frontend-mobile/`（移动端，Vant 4）。任何交互或字段变更都要同时覆盖两侧。

## 外部接口文档

- 顺丰：见 `docs/SF_SETUP.md`、`docs/SF_OAUTH2_GUIDE.md`
- 快麦云打印：见 `docs/第三方接口文档/快麦云打印/`
- 闲鱼管家 API：见 `docs/闲鱼管家 api 文档.md`

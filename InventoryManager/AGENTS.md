# AGENTS.md — InventoryManager（摄影器材租赁库存管理 SaaS）

## 硬约束（违反即视为本次任务失败，需回滚）

1. **禁止新建过程性文档。** 不得创建 `*_SUMMARY.md` / `*_COMPLETE.md` / `*_REPORT.md` /
   `*_FIX*.md` / `*_ANALYSIS.md` / `*_INDEX.md` / `QUICK_*.md` / `PHASE_*.md` /
   `ALL_DONE.*` / `READY_TO_*.md` / `*交付*.md` / `*总结.md`。
2. **本目录根级只允许 3 个 md**：`README.md`、`AGENTS.md`、`CLAUDE.md`。
   要新增第 4 个根级 md，先停下来问用户，得到明确同意才创建。
3. **工作总结写在对话回复里，不落盘。** 需要留痕时写进 `openspec/changes/<change-id>/`
   或 commit message，不要新建根级文件。
4. **`docs/archive/**` 是历史垃圾场**：禁止 grep、禁止 Read、禁止引用。
   其中的文件路径、make 命令、环境变量名均已过期，照做会失败。
5. **部署只看 `DEPLOY.md`**。`README.md` 不含部署信息；`makefile.example` 已废弃，
   它里面 52 个 target **全部不存在**（真实 `Makefile` 只有 6 个）。
6. **改代码前先读 `docs/INDEX.md` 定位文件**，禁止上来就全仓 glob/grep。
7. **`Makefile` 只允许 6 个 target**，禁止加入 `NAS_` / `sshpass` / `docker-compose`
   （`tests/unit/test_production_config.py` 会失败）。主机特定脚本写到 `scripts/` 下。
8. **前端改动必须同时考虑 PC 端（`frontend/`）与移动端（`frontend-mobile/`）两侧。**

## 技术栈

Flask + SQLAlchemy 2 + MySQL，gunicorn + gevent，多租户 **database-per-tenant**
（一个控制库 + N 个租户业务库）。PC 前端 Vue3 + Element Plus，移动端 Vue3 + Vant 4。

## 三个进程入口

| 入口 | 用途 | 关键点 |
|---|---|---|
| `run.py` | 生产 WSGI（gunicorn） | 首行必须 `gevent.monkey.patch_all()`，顺序不可改 |
| `app.py` | 开发 + Flask CLI，端口 5002 | 与 `run.py` 无调用关系 |
| `worker.py` | 定时任务 | advisory lock 单实例；第二个实例直接退出不接管 |

## 两套 Alembic（最易错）

`control_migrations/`（控制库，1 个版本，手动 upgrade）与 `migrations/`（每个租户业务库，
31 个版本，走 Flask CLI）。**顺序：控制库先，租户库后。** 详见 `DEPLOY.md` 第 4 章。

## 按需加载（用到时才读，不要预先全部打开）

- `docs/INDEX.md` —— **改功能前先读**：16 个功能域到文件的映射表、蓝图注册链、死代码清单
- `docs/ARCHITECTURE.md` —— 涉及多租户绑定、gevent、worker 锁、迁移、安全约束时读
- `DEPLOY.md` —— 部署、构建、环境变量、迁移、回滚
- `openspec/AGENTS.md` —— 走 OpenSpec 变更流程时读

<!-- OPENSPEC:START -->
# OpenSpec Instructions

These instructions are for AI assistants working in this project.

Always open `@/openspec/AGENTS.md` when the request:
- Mentions planning or proposals (words like proposal, spec, change, plan)
- Introduces new capabilities, breaking changes, architecture shifts, or big performance/security work
- Sounds ambiguous and you need the authoritative spec before coding

Use `@/openspec/AGENTS.md` to learn:
- How to create and apply change proposals
- Spec format and conventions
- Project structure and guidelines

Keep this managed block so 'openspec update' can refresh the instructions.

<!-- OPENSPEC:END -->

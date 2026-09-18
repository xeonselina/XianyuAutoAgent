# InventoryManager Constitution

> 本宪法仅适用 `InventoryManager/`。仓库根的 `.specify/memory/constitution.md`
> 描述的是 `ai_kefu` 项目（FastAPI / Redis / ChromaDB），与本项目无关。

## Core Principles

### I. 文档最小化（Documentation Minimalism）

**语言**：新增文档用简体中文；代码标识符（变量、函数、类）用英文。

**数量（不可协商）**：文档总量只减不增。本项目长期维护的文档只有 5 份：
`README.md`、`AGENTS.md`、`docs/INDEX.md`、`docs/ARCHITECTURE.md`、`DEPLOY.md`。

**禁止**为「记录工作过程」而创建文件——包括但不限于：实施总结、完成报告、修复报告、
验证报告、交付说明、探索记录、阶段进度、以及**文档索引的索引**。
工作结论写在对话回复里；需要留痕时写进 `openspec/changes/<change-id>/` 或 commit message，
变更完成后执行 `openspec archive`，不在仓库根留痕。

**理由**：过程文档的边际信息量接近于零，却会持续抬高每次 AI 协作的上下文成本
（全仓检索时被大量召回），并在与代码漂移后**主动误导**后续工作。
旧原则「所有文档必须中文输出」被误读为「应当多产出中文文档」，
是本项目历史上 68 份根级报告的直接成因——此类文件已归档至 `docs/archive/`，禁止检索。

### II. 代码即事实来源（Code over Docs）

文档与代码冲突时，**以代码为准**，并立即修正文档。
不得依据文档中的路径、命令、环境变量名直接执行而不先验证其存在。

### III. 前端双端对等（Frontend Parity）

`frontend/`（PC，Element Plus）与 `frontend-mobile/`（移动端，Vant 4）必须同步考虑。
任何交互、字段、状态变更都要同时覆盖两侧，不得只改一端。

### IV. 发布护栏不可绕过（Release Guards are Load-Bearing）

`tests/unit/test_production_config.py` 断言的约束（Makefile target 集合、
Dockerfile COPY 清单、worker 权限隔离、文档中无敏感残留）是**有意的设计**，
不是可以随手放宽的历史包袱。需要改变行为时，先讨论为什么，再同时改代码与断言。

### V. 多租户隔离优先（Tenant Isolation First）

一切涉及数据库的改动，先确认落在控制库还是租户业务库（见 `docs/ARCHITECTURE.md`）。
两套 Alembic 迁移不可混用，顺序为控制库先、租户库后。

## Additional Constraints

- `Makefile` 只允许 6 个 target；主机特定的部署脚本写在 `scripts/` 下。
- `docs/archive/**` 为历史归档，AI 禁止 grep / Read / 引用。
- `makefile.example`、`README-Docker.md`、`README-多架构构建.md` 已废弃，不可作为依据。

## Development Workflow

- 规格与计划走 `openspec/changes/<change-id>/`，完成后 `openspec archive`。
- 提交遵循 Conventional Commits（`feat:` / `fix:` / `docs:` / `chore:` / `test:`）。
- **默认不推送远程**，除非用户明确要求；不自动切换分支。

## Governance

本宪法优先于其他约定。修订需说明起因，并同步更新 `AGENTS.md` 中的硬约束。

**Version**: 1.0.0 | **Ratified**: 2026-09-07 | **Last Amended**: 2026-09-07

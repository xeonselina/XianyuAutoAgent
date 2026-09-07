# docs/archive — 历史归档

> **本目录是历史过程报告的归档区。AI 禁止 grep、禁止 Read、禁止引用。**
> 其中的文件路径、make 命令、环境变量名、代码行号均已过期——**照做会失败**。
> 唯一用途：人做变更溯源。用 `git log --follow <file>` 可查每份文件的提交历史。

归档原因：这些文档是历次 AI 会话的**过程产物**（实施总结、修复报告、验证报告、
探索记录、阶段进度、以及为报告生成的报告索引），边际信息量接近于零，
却会在每次全仓检索时被大量召回，抬高 AI 协作成本，并在与代码漂移后主动误导。
有价值的结论已提炼进 `docs/INDEX.md`、`docs/ARCHITECTURE.md`、`DEPLOY.md`。

典型例子：8 份文件 / 71KB（现归 `lifecycle/`）只为记录
`app/routes/gantt_api.py` 里 3 行代码的修复。

## 目录与内容

| 目录 | 份数 | 主题 | 对应代码/变更 |
|---|---|---|---|
| `lifecycle/` | 15 | 设备生命周期功能交付 + lifecycle_status 甘特图 bug 修复 | `app/models/device.py`、`app/routes/device_api.py`、`docs/device-lifecycle.md` |
| `rental/` | 10 | 租赁表单与附件简化（2026-01-04 批次） | `app/models/rental.py`、`docs/form-field-mapping.md` |
| `research/` | 11 | Flask Session 跨设备研究、闲鱼/移动端表单调研 | 方案未全部实施，仅作背景 |
| `exploration/` | 4 | 全仓结构探索快照（含 48KB `project-exploration.md`） | 已被 `docs/INDEX.md` 取代 |
| `phase2/` | 8 | Phase 2 计划/进度（停滞在 40%）、测试套件快照 | 已过期 |
| `ops/` | 10 | gevent SSL 修复、调度器修复、Docker/安装旧文档 | 结论已进 `docs/ARCHITECTURE.md` 与 `DEPLOY.md` |
| `legacy-docs/` | 16 | URL 结构迁移、向后兼容策略、旧部署与迁移说明 | 已被 `DEPLOY.md` 取代 |
| `superpowers/` | 15 | 旧工具链的设计稿与实施计划 | 与 `openspec/changes/` 5 组主题重复，openspec 为唯一规格源 |

## 两份带免责声明的文档

`ops/2026-08-25-修复总结.md` 与 `ops/2026-08-25-模块重构说明.md` 正文提到
已下线的 OCR / 合同功能（文件头已有「历史记录」声明）。
**这正是 `tests/unit/test_production_config.py` 中「合同/OCR 残留」断言排除本目录的原因**——
归档提到已下线功能属正常，活文档再出现才是回归。
注意：另一条「旧手机号 / 旧地址」断言**不排除**本目录，敏感信息没有避风港。

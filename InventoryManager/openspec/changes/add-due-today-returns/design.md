## Context

现有租赁以 `end_date` 表示租赁结束日期，以 `shipped` 表示已寄出，以 `returned` 表示客户已寄回。甘特图数据范围会随用户浏览日期变化，不能可靠承担全局的今日提醒查询。

完整设计见 `docs/superpowers/specs/2026-07-29-due-today-returns-design.md`。

## Goals / Non-Goals

- Goals: 服务器端准确筛选、甘特图快捷入口、行内状态更新、状态文案统一。
- Non-Goals: 逾期列表、自动发送客户消息、任意状态下拉框、数据库枚举迁移。

## Decisions

- 新增专用后端接口，不从当前甘特图缓存筛选。
- 只返回 `end_date = today - 1 day`、`status = shipped`、`parent_rental_id IS NULL` 的租赁。
- 状态更新复用现有接口，由现有服务同步子租赁。
- 保留底层 `returned` 值，只统一用户界面文案。

## Risks / Trade-offs

- 服务器本地日期决定“今天”，部署环境必须保持业务时区配置。
- 专用接口用途较窄，但避免通用列表接口出现难以理解的组合筛选参数。

## Migration Plan

不修改数据库。回滚时移除新增接口、组合式函数、抽屉和入口即可；文案可独立恢复。

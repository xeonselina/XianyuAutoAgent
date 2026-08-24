## Context

Rental 是编辑、API 返回和验货查询共同使用的数据源。验货清单由 rental 当前内容动态生成，提交后再以独立检查项保存。

完整设计见 `docs/superpowers/specs/2026-08-07-rental-damage-notes-design.md`。

## Goals / Non-Goals

- Goals: 保存一条当前损坏备注、覆盖桌面与移动编辑、在验货时强提醒并要求显式处理、保留验货文本快照。
- Non-Goals: 多次反馈历史、维修工单、设备生命周期自动变更、独立移动端验货路由。

## Decisions

- 使用 nullable `rentals.damage_note TEXT` 作为唯一数据源，不增加冗余布尔开关。
- 仅编辑流程维护该字段，创建 rental 流程不增加输入项。
- 空白备注标准化为 `NULL`，非空备注限制为最多 1000 字符。
- 验货清单协议增加可选 `default_checked`，损坏处理项为 `false`，旧响应默认按 `true` 兼容。
- 验货提交沿用现有异常判定：任意未勾选项均产生 `abnormal`。

## Risks / Trade-offs

- 单字段不保留备注修改历史，但符合当前范围，并避免额外状态机。
- 在检查项名称中保存完整备注会增加文本长度；当前检查项列长度需同步扩展以容纳 1000 字符备注及前缀。
- 当前验货入口位于桌面前端，但页面已有手机与 iPad 响应式布局；本次不复制到独立移动前端。

## Migration Plan

新增 nullable 字段不会影响现有行。回滚时先停止包含 `damage_note` 的应用版本，再删除该列；已保存的损坏备注将随回滚丢失。


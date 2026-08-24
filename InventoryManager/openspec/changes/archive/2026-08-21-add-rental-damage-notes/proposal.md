# Change: 增加租赁损坏备注与验货提醒

## Why

客户在租赁过程中反馈设备损坏后，目前没有结构化位置保存该信息，验货人员也可能按常规清单操作而漏掉用户已指出的问题。

## What Changes

- 为 rental 增加一条可编辑、可清空的当前损坏备注
- 在桌面端和移动端 rental 编辑流程中维护损坏备注
- 在验货页突出显示损坏反馈
- 为损坏反馈生成默认未勾选的验货处理项，并在验货记录中保存文本快照

## Impact

- Affected specs: `rental-damage-notes`（新增）
- Affected backend: rental 模型、数据库迁移、更新 handler、验货清单生成
- Affected frontend: 桌面 rental 编辑、移动 rental 编辑、桌面/响应式验货页面与类型
- Database: `rentals` 新增 nullable `damage_note TEXT`


# Change: 增加今日应归还提醒列表

## Why

租赁结束次日需要提醒客户寄回设备，但当前甘特图没有聚合入口，运营人员需要逐单查找，容易漏跟进。

## What Changes

- 在甘特图顶部增加带数量的“今日应归还”按钮
- 在抽屉中列出今天应归还的主租赁及手机型号、租赁时间、地址和电话
- 支持每行一键标记为已寄回
- 将 `returned` 状态的所有界面文案统一为“已寄回”

## Impact

- Affected specs: `due-today-returns`（新增）
- Affected backend: 租赁服务、handler 和 API
- Affected frontend: 甘特图、提醒抽屉、桌面端和移动端租赁状态文案
- Database: 无迁移，保留 `returned` 枚举值

# Change: 完善待归还联系人和状态操作

## Why

待归还列表只有电话号码，运营人员无法直接确认租赁人；同时旧页面持有已轮换的 CSRF 令牌时，标记已寄回会被拒绝，必须手动刷新页面才能继续。

## What Changes

- 待归还接口返回租赁人姓名
- 电话列合并展示租赁人姓名和电话号码
- 标记已寄回遇到 CSRF 令牌失效时刷新当前租户会话并自动重试一次
- 非 CSRF 错误或重试仍失败时保留原有错误反馈，不进行无限重试

## Impact

- Affected specs: `due-today-returns`
- Affected backend: 待归还租赁序列化
- Affected frontend: 待归还列表、租户认证状态和状态更新流程
- Database: 无迁移

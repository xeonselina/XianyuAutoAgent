# Change: 在待归还列表显示机器编号

## Why

待归还列表目前只显示设备型号，同型号有多台机器时，运营人员无法直接确认具体需要跟进的机器。

## What Changes

- 待归还接口返回主设备的设备名称（业务上作为机器编号使用）
- 待归还抽屉在每条记录的设备型号下方显示机器编号
- 保持一个主租赁一条记录，附件不拆分为独立待归还记录

## Impact

- Affected specs: `due-today-returns`
- Affected backend: 待归还租赁序列化
- Affected frontend: 待归还抽屉及类型定义
- Database: 无迁移

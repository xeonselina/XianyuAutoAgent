# Change: 在待归还列表标记接力订单

## Why

已确认接力的前单需要由当前客户直接寄给下一位客户，但待归还列表目前与普通寄回记录外观相同，运营人员容易按普通回仓流程处理。

## What Changes

- 待归还接口批量识别作为永久接力绑定前单的记录
- 返回接力标记和后一单 rental ID
- 在待归还设备信息旁显示醒目的“接力”标签
- 仅标记已确认的接力绑定，不标记尚未同意的自动候选

## Impact

- Affected specs: `due-today-returns`
- Affected backend: 待归还查询序列化
- Affected frontend: 待归还类型和抽屉
- Database: 无迁移

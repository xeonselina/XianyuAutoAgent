# Change: 在待归还列表复制电话号码

## Why

运营人员需要把待归还客户的电话号码粘贴到沟通工具，当前只能手动选择文本，在触屏设备上操作不便。

## What Changes

- 在每条待归还记录的电话号码右侧增加复制图标按钮
- 点击后只复制纯电话号码并显示成功或失败提示
- 兼容安全上下文的 Clipboard API 和当前 IP/HTTP 环境的文本框回退复制
- 没有电话号码时不显示复制按钮

## Impact

- Affected specs: `due-today-returns`
- Affected frontend: 待归还抽屉及组件测试
- Backend/Database: 无变更

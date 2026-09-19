## ADDED Requirements

### Requirement: Shared order with independent device configurations
系统 SHALL 支持一次预约任意台数的同型号设备（受实际可用库存限制），共享订单及租期、客户、地址、仓库信息，分别保存实际主机、镜头、附件及代传照片配置；默认保持一台，PC 和移动端行为一致。

#### Scenario: Different configurations
- **WHEN** 用户添加第二台并选择第一台 400mm、第二台 200mm
- **THEN** 系统一次提交两条关联的独立主租赁，分别显示正确配置

#### Scenario: Add and remove multiple device cards
- **WHEN** 用户连续添加第二、第三或更多台，并移除其中一台
- **THEN** 仅移除该未提交设备配置，其余设备选择和独立配置保持不变，可继续添加

#### Scenario: Shared selector and availability search
- **WHEN** 用户为任意一台选择设备或点击查找档期
- **THEN** 使用相同的“选择设备”下拉和查找入口，排除本次预约其他卡片已选设备，异步结果不能重新填入已移除卡片

### Requirement: Atomic and idempotent booking
系统 SHALL 联合验证主机和库存附件占用，排除批次内重复选用，全部成功或全部不保存，并对重复请求返回同一结果。

#### Scenario: Conflict on second device
- **WHEN** 提交时任意一台或其库存附件已被占用
- **THEN** 所有设备均不新增，保留表单并定位冲突

#### Scenario: Retry after timeout
- **WHEN** 保存已成功但响应超时后重试相同请求
- **THEN** 返回已有结果，不新增租赁

### Requirement: Declared quantity reconciliation
系统 SHALL 保存用户确认的应录台数，以同租户同店铺同订单的有效主租赁数量判断是否录齐，排除附件和取消记录，支持在已有订单上直接补齐。

#### Scenario: One of two recorded
- **WHEN** 订单应录两台但只有一条有效主租赁
- **THEN** 保留已录 1/2 的待补齐提醒，仅创建缺少的一台

#### Scenario: Cancellation without quantity reduction
- **WHEN** 两台订单取消一台且没有明确减租
- **THEN** 订单恢复待补齐提醒；明确减租需记录应录台数变更原因

### Requirement: Order amount and fulfillment clarity
系统 SHALL 将订单收入计一次，按需分摊至设备且合计等于订单总额；逐台展示配置、验货及归还状态，呈现同单数量和发货进度，避免重复平台回传或运单覆盖。

#### Scenario: Two rentals for one paid order
- **WHEN** 一个订单建立两条主租赁
- **THEN** 订单计数为一、设备计数为二、收入不翻倍，发货清单明确每台配置

#### Scenario: Partial shipment
- **WHEN** 同单只有一台已发货
- **THEN** 汇总显示已发 1/2，不把另一台自动标记为已发货

#### Scenario: Exact amount across three or more devices
- **WHEN** 订单包含三台或更多设备，含总金额不能被台数整除或总金额小于台数分币的情况
- **THEN** 每台金额非负且精确到分，合计始终等于订单总金额；取消后补齐也保持该总额

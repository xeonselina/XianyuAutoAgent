# 闲鱼订单对账与告警

## Purpose

从 `xianyu_order_reconciliation_service.py`、告警模型与 API 处理器反推当前已实现的缺单及退款提醒。租赁建单、闲鱼订单查询和发货分别由 `rental-management`、`shipping-fulfillment` 定义。

## Requirements

### Requirement: 店铺配置和同步状态按租户与店铺隔离

每个租户库 MUST 保存自己的 `xianyu_shops`，只有 active 店铺参加全量对账；具体店铺的告警、忽略记录和同步错误不可混到另一店铺。无店铺时读取告警 MUST 返回 409 `CONFIG_INCOMPLETE`。手动刷新 `POST /api/xianyu-order-alerts/refresh` 仅允许 tenant admin；普通登录成员可读取和忽略提醒。

#### Scenario: 没有店铺
- **WHEN** 租户访问 `GET /api/xianyu-order-alerts` 而尚未设置店铺
- **THEN** 返回 409 `CONFIG_INCOMPLETE`，不显示其他租户的告警

### Requirement: 漏录订单只按规定的订单窗口和金额生成

对账 MUST 从闲鱼状态 12 与 21 的订单列表取数据，以去空格的订单号合并重复项。只有付款金额 `pay_amount` 严格大于 5000 分（50 元）的订单符合漏录检查；等于 5000 不符合。当前店铺已经有完整本地 `RentalBooking` 对应的订单、或被永久忽略的订单不可成为待补录告警。尚未录足 `expected_quantity` 的同单订单必须继续可见，并显示 `recorded_quantity/expected_quantity`，即使上游订单已经离开待发货列表。

#### Scenario: 金额边界与同单缺台
- **WHEN** 两个未录订单分别支付 5000 和 5001 分，后一订单声明需要两台但只录入一台
- **THEN** 5000 分订单不告警；后一订单显示待补齐 `1/2`，直到主租赁数量达到 2

### Requirement: 待补录缓存按店铺原子更新

每店铺对账 MUST 持有以数据库和店铺 ID 区分的 MariaDB advisory lock；锁已被占用时返回当前快照并标明 `refreshing=true`。成功拉取后，在一笔事务内删除已消失的 pending、更新仍存在的 pending、创建新 pending；ignored 历史不删除。条目保留首见时间，更新末次见时间、付款分数、买家、收件人、拼接地址、商品标题与 SKU、订单时间。上游查询失败不能以空列表清空可信缓存，必须保留先前快照并记录 `last_error`。

#### Scenario: 上游接口故障
- **WHEN** 店铺已有待处理告警且闲鱼列表查询失败
- **THEN** 旧告警仍可读；店铺同步错误更新，不能把旧告警当作已解决

### Requirement: 已录档期的退款关闭提醒独立于漏单提醒

对已关联店铺和订单号、状态为 `not_shipped`、`scheduled_for_shipping` 或 `shipped` 的本地租赁，系统 MUST 核对真实闲鱼订单状态；订单不在待发货列表时需查详情，不能推断交易关闭。状态 23/24 产生 `closed`；未关闭而退款状态 1/2/3/5/8 产生 `refund_review`，状态 5 且退款金额小于付款金额显示“部分退款，请核对”。退款成功而交易仍有效时只提示核对，不自动取消整单。平台确定查无订单产生 `not_found`，随后在仍不出现在列表时可避免重复详情请求。单笔查询失败保留该笔旧提醒并继续处理其他订单；不再属于活跃档期的提醒删除。

#### Scenario: 订单从待发货列表消失
- **WHEN** 已录档期对应订单不在状态 12/21 列表
- **THEN** 查询订单详情；只有详情显示 23/24 或相应退款状态才生成提醒，租赁状态不被自动修改

### Requirement: 快照包含可操作列表与明确的新鲜度

`GET /api/xianyu-order-alerts` MUST 返回 `alerts,count,rental_alerts,sync,refreshing,shops`。`alerts` 按订单时间／ID 倒序，仅列未被本地完整录入的 pending，再拼接同单缺台项。`rental_alerts` 按首次发现时间倒序，关联该订单当前活跃租赁的设备、仓库、日期和状态。`sync.is_stale` 在从未成功或成功时间超过 600 秒时为真；多 active 店铺汇总取最早的成功时间。不能把失败或陈旧同步展示为最新结果。

#### Scenario: 一个店铺十分钟未成功同步
- **WHEN** 多个 active 店铺中一个 `last_success_at` 超过 600 秒
- **THEN** 汇总 `sync.is_stale=true`，已有告警照常显示

### Requirement: 忽略必须可审计且区分告警类型

`POST /api/xianyu-order-alerts/<shop_id>/<order_no>/ignore` MUST 只忽略当前 pending 漏录告警；`.../rental-ignore` 只忽略未忽略的档期提醒。两者均要求去空格后非空且不超过 500 字的原因，保存原因和 UTC 时间；不存在返回 404。漏录忽略跨后续对账持续生效。档期提醒忽略记录只影响展示，不改租赁与上游状态。

#### Scenario: 忽略后再次同步
- **WHEN** 操作员以原因忽略某店铺订单的漏单告警并刷新
- **THEN** 同店铺同订单不再进入 pending；另一个店铺的同号订单不受影响

### Requirement: 对账快照的合成欠录项和同步元数据保留当前形状

尚未补齐的 `RentalBooking` 在快照里 MUST 生成 `id=-booking.id` 的合成 `alerts` 项，覆盖同店铺同订单的普通漏单告警。该项使用 booking 金额换算分、首条关联租赁的客户姓名／电话、店铺名称，并提供 `expected_quantity,recorded_quantity`；完整录入后这项消失。`count` 等于最终 `alerts` 长度，不包含 `rental_alerts`。`sync` 包含 `last_attempt_at:null,last_success_at,last_error,is_stale,stale_after_seconds:600`；`shops` 只列 active 店铺 `{id,name}`。档期提醒项包含 `order_no,xianyu_shop_id,xianyu_shop_name,kind,status_text,last_seen_at,rentals`，其中每条租赁包含 `id,customer_name,device_name,warehouse_id,warehouse_name,start_date,end_date,status,parent_rental_id`。

#### Scenario: 缓存漏单和本地欠录同时存在
- **WHEN** 同店铺同订单既有 pending 漏单行又有已录 1/2 台的 booking
- **THEN** `alerts` 中只出现一条负 ID 的欠录项，`count` 加 1，`rental_alerts` 不因此添加退款提醒

## HTTP 与数据契约

| 路径 | 行为 |
|---|---|
| `GET /api/xianyu-order-alerts` | 快照；无店铺 409 `CONFIG_INCOMPLETE` |
| `POST /api/xianyu-order-alerts/refresh` | admin 手动同步所有 active 店铺并返回快照 |
| `POST /api/xianyu-order-alerts/<shop_id>/<order_no>/ignore` | `{reason}`，永久忽略待补录订单 |
| `POST /api/xianyu-order-alerts/<shop_id>/<order_no>/rental-ignore` | `{reason}`，忽略已录档期的退款／关闭提醒 |
| `POST /api/settings/xianyu-shops/<shop_id>/sync` | 设置页触发单店铺同步，参见 `tenant-access` |

`xianyu_order_alerts` 以 `(xianyu_shop_id,order_no)` 唯一，`state` 只允许 `pending/ignored`，存分为单位的金额与检测／忽略时间；`xianyu_rental_alerts` 同样按店铺订单唯一，保存 `kind,status_text,order_status,refund_status,first_detected_at,last_seen_at,ignored_at,ignored_reason`。`xianyu_shops` 保存加密密钥、启停和上次成功／错误。两个提醒表没有任何自动取消租赁的副作用。

## 页面与验收

PC 甘特中的闲鱼提醒区显示漏录、同单缺台与已录档期退款／关闭提醒、店铺及同步新鲜度，提供刷新与填写原因后忽略。移动端若显示这些数据也必须使用同一租户快照，不自行以订单列表缺席推断退款。验收数据至少含 50 元边界、同单 1/2、同号不同店、部分退款、查无订单、上游失败、单笔失败、永久忽略及 600 秒过期。

依据：`app/services/xianyu_order_reconciliation_service.py`、`app/handlers/xianyu_order_alert_handlers.py`、`app/routes/xianyu_order_alert_api.py`、`app/models/{xianyu_shop,xianyu_order_alert,xianyu_rental_alert}.py`、`app/utils/scheduler_tasks.py`。

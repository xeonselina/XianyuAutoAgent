# 客户历史、经营统计与预测

## Purpose

从客户检索、统计路由、计算服务和页面反推当前可见的数据口径；这些统计端点有旧响应格式，应按实际 API 保留，不套用其它模块的统一响应壳。

## Requirements

### Requirement: 客户候选按电话优先聚合

`GET /api/customers/search?q=` MUST 在关键词空白时返回空列表；非空时用客户名、买家 ID 或电话号码片段找最近创建的最多 500 条租赁，再按去掉非数字字符的手机号聚合；没有电话时按 `(去空格姓名,去空格买家 ID)` 聚合。候选按租赁数量倒序取最多 20 条，代表姓名与买家 ID 取该组最新订单。返回 `customer_name,customer_phone,customer_phone_masked,buyer_id,total_rentals`；掩码为 `****` 加末四位（不足四位保留原数字）。

#### Scenario: 同一电话不同格式
- **WHEN** 两条订单的客户电话分别写作 `138 0000 1234` 和 `13800001234`
- **THEN** 搜索结果合成一个客户候选，数量为 2，电话展示可使用掩码 `****1234`

### Requirement: 客户最近租赁的匹配与截断固定

`GET /api/customers/rentals` MUST 要求 phone/name/buyer_id 至少一个；电话含数字时以数字归一化后的包含匹配为优先，不再附加姓名或买家 ID 过滤；没有有效电话数字时，以提供的姓名和买家 ID 精确匹配。按 `start_date DESC,created_at DESC` 最多取 200 个候选，再截断到 `limit`（默认 5，限制 1–50）。返回设备型号名和展示名、租赁组合、金额、起止日期、天数、姓名、电话。该客户历史以全部租赁记录为数据源，不自动剔除取消、附件或子租赁。

#### Scenario: 未传识别字段
- **WHEN** 不传电话、姓名和买家 ID 请求客户历史
- **THEN** 返回 400；`limit=100` 实际最多返回 50 条

### Requirement: 周月经营统计以主设备在役天数为分母

`GET /api/rental-stats/periodic` MUST 接受 `period_type=week/month`（默认 month）、`model=all/型号 ID/兼容旧短名`、仓库和日期（默认过去 365 天到今天）。主设备中永久排除名称 `代发01`、`代发02`、`代发03`、`代发 04 深圳`。设备投入日为首笔未取消主租赁的开始日期；出售／报废／损坏／退役且有 `lifecycle_date` 时，该日期是独占在役终点。每期 `available_device_weeks = 在役自然日数 / 7`，`rental_rate = 当期设备租赁条数 / available_device_weeks`，分母为 0 则 0；该率不强制封顶。`order_count` 按 `booking_id` 去重，未归 booking 的按 rental ID 计数。

#### Scenario: 出售设备跨期
- **WHEN** 设备在某周中途出售且有生命周期日期
- **THEN** 可用周数只计首单到出售日期之前与该周交集的自然日；出售日及之后不进分母

### Requirement: 订单收入、折旧和净利使用明确公式

周期统计 MUST 按订单 `start_date` 归期，忽略已取消及子租赁；仓库筛选订单用租赁当时的 `warehouse_id`，设备分母用当前设备仓库。`order_amount` 缺失视 0，`profit = order_amount - 15 × 设备租赁条数`。设备价值取型号 `device_value`，无值视 0；首单日起按 52 周半衰期折旧，在统计期与在役期交集上计算 `price × (0.5^(起始周数/52) - 0.5^(终止周数/52))`；`net_profit = profit - depreciation`。总计为各期求和；平均出租率是设备数大于 0 的周期出租率的简单算术平均。

#### Scenario: 同单双机
- **WHEN** 一个 booking 的两台主设备同月各有一条 100 元租赁
- **THEN** `order_count=1`、收入 200 元、快递成本 30 元，折旧另行扣除

### Requirement: X200U 预测保持当前专用模型

`GET /api/rental-stats/x200u-forecast` MUST 使用型号 ID 1、过滤代发设备，并接受 `warehouse_id` 与 `new_devices_july`。当前实现固定预测 **2026 年 5–8 月**，而不是自动滚动月份；这是当前行为，复刻时不可悄悄改为动态预测。模型价值缺失时购买单价回退 7299 元，使用近 6 个已有完整月的月均订单金额做线性回归，数据不足时斜率 0、单价回退最近均价或 178 元；预测价格下限 100 元。乐观／中立／悲观出租率分别 0.90/0.70/0.50，每台预计月订单数为月天数÷7×出租率，每单扣 15 元物流，7 月起叠加新增设备与折旧；累计年化 ROI 是累计净利÷累计购买成本÷运营年数×100%。

#### Scenario: 新增设备场景
- **WHEN** `new_devices_july=2`
- **THEN** 5、6 月设备数不变，7、8 月加 2，并计入对应折旧和成本

### Requirement: 旧统计快照按日保存最近三十天

`POST /api/statistics/calculate` MUST 读取结束日在今天前 30 天至今天的主租赁（此路径当前没有取消状态过滤），计算每条 `rental_days=(end_date-start_date).days`；有 `order_amount` 用该金额，否则租金 `178+(rental_days-1)×30`；收入价值为租金减 15。按当天 `stat_date` 更新或插入 `rental_statistics` 唯一日记录。`/recent?days=30` 返回最近 N 个快照按日期升序，`/date-range` 按区间读取，`/latest` 无数据时 404。

#### Scenario: 同一天重复计算
- **WHEN** 当天两次 POST `/api/statistics/calculate`
- **THEN** 第二次更新当天同一行，`stat_date` 不产生重复记录

## API 与页面契约

| 路径 | 返回重点 |
|---|---|
| `GET /api/customers/search?q=` | `{success:true,data:{customers:[...]}}` |
| `GET /api/customers/rentals?phone=&name=&buyer_id=&limit=` | `{success:true,data:{rentals:[...]}}` |
| `GET /api/rental-stats/models` | active 主设备型号，按 ID 升序 |
| `GET /api/rental-stats/periodic` | `period_type,model,data:[period,period_start,period_end,device_count,available_device_weeks,order_count,rental_rate,order_amount,avg_revenue_per_device,profit,depreciation,net_profit],summary` |
| `GET /api/rental-stats/x200u-forecast` | `device_count,purchase_price,total_cost,hist_net_profit,avg_order_amount,price_slope,scenarios` |
| `GET /api/statistics/{recent,date-range,latest}` | 旧式 `{success,data}`，错误为 `{success:false,error}` |
| `POST /api/statistics/calculate` | 计算／保存当天三十日快照，返回 `stat_id,stat_date,is_new,statistics` |

PC `/rental-stats` 展示型号、仓库、周期和 X200U 预测；移动 `/mobile/search` 与 `/mobile/customer-history` 使用客户和租赁搜索；甘特客户历史入口使用相同客户 API。PC `/operations` 仅是发货、接力、验货、物流四张导航卡，不额外计算统计。

`rental_statistics` 的 `stat_date` 唯一，存 `period_start,period_end,total_rentals,total_rent,total_value,created_at,updated_at`。验收用跨仓移机、出售中途、同单双机、取消订单、缺少金额、预测数据不足和每天重复写入覆盖各口径，特别验证新旧统计 API 的公式不同。

依据：`app/routes/{customer_api,rental_stats_api,statistics_api}.py`、`app/services/rental_statistics_service.py`、`app/models/rental_statistics.py`、`frontend/src/views/{RentalStatsView,OperationsView}.vue`、`frontend-mobile/src/views/{SearchView,CustomerHistoryView}.vue`。

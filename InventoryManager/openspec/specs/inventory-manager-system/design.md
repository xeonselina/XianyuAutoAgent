# 代码提取的接口与数据结构索引

本索引按当前 `app/routes/` 和 ORM 模型源码提取，用于核对复刻范围。接口的业务输入、错误码、状态转换以各功能 `spec.md` 为准；源码函数与行号供补全冷门路径时定位。Vue 静态回退路由、旧 HTML 路由也如实列出。表中“首行说明”直接取函数 docstring，可能过时：例如 `/api/inventory/available` 注释称“无需认证”，实际在全局请求钩子下仍需租户会话；已废弃的物流／设备状态函数仍有路由绑定但返回 410。

## HTTP 路由（169 个装饰器绑定）

| 方法 | 路径 | 服务端函数 | 源码 | 首行说明 |
|---|---|---|---|---|
| `GET` | `/` | `unified_index` | `app/routes/vue_app.py:31` | 统一入口路由 - 手机自动跳移动端，桌面返回 PC 端 |
| `GET` | `/access-restricted` | `vue_router_routes` | `app/routes/vue_app.py:75` | 处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/api/customers/rentals` | `get_customer_rentals` | `app/routes/customer_api.py:128` | 获取指定客户的最近 N 单（默认 5），按 start_date desc, created_at desc。 |
| `GET` | `/api/customers/search` | `search_customers` | `app/routes/customer_api.py:52` | 模糊搜索客户候选列表。 |
| `GET` | `/api/device-models` | `get_device_models` | `app/routes/device_model_api.py:34` | 获取所有激活的设备型号及其附件 |
| `POST` | `/api/device-models` | `create_device_model` | `app/routes/device_model_api.py:55` |  |
| `DELETE` | `/api/device-models/<int:model_id>` | `delete_device_model` | `app/routes/device_model_api.py:69` |  |
| `PUT` | `/api/device-models/<int:model_id>` | `update_device_model` | `app/routes/device_model_api.py:62` |  |
| `GET` | `/api/device-models/<int:model_id>/accessories` | `get_model_accessories` | `app/routes/device_model_api.py:41` | 获取指定型号的附件 |
| `POST` | `/api/device-models/assign-legacy` | `assign_legacy_device_model` | `app/routes/device_model_api.py:76` |  |
| `GET` | `/api/device-models/library` | `get_device_model_library` | `app/routes/device_model_api.py:48` | 获取完整型号库、引用数和历史自由文本分组。 |
| `POST` | `/api/device/force-update-status` | `force_update_single_device_status` | `app/routes/tracking_api.py:179` |  |
| `GET` | `/api/device/status-summary` | `get_devices_status_summary` | `app/routes/tracking_api.py:187` |  |
| `POST` | `/api/device/update-status` | `update_device_status` | `app/routes/tracking_api.py:171` |  |
| `GET` | `/api/devices` | `get_devices` | `app/routes/device_api.py:61` | 获取设备列表 - 支持过滤和搜索 |
| `POST` | `/api/devices` | `create_device` | `app/routes/device_api.py:113` | 创建设备 |
| `DELETE` | `/api/devices/<device_id>` | `delete_device` | `app/routes/device_api.py:332` | 删除设备 |
| `GET` | `/api/devices/<device_id>` | `get_device` | `app/routes/device_api.py:76` | 获取单个设备信息 |
| `PUT` | `/api/devices/<device_id>` | `update_device` | `app/routes/device_api.py:176` | 更新设备信息 |
| `PUT` | `/api/devices/<device_id>/lifecycle` | `update_device_lifecycle` | `app/routes/device_api.py:371` | 更新设备生命周期状态 |
| `PUT` | `/api/devices/<device_id>/mark-sold` | `mark_device_sold` | `app/routes/device_api.py:428` | 快速标记设备为已销售 |
| `POST` | `/api/devices/<int:device_id>/move` | `move_device` | `app/routes/device_api.py:309` | Apply one signed warehouse movement preview atomically. |
| `POST` | `/api/devices/<int:device_id>/movement-preview` | `preview_device_movement` | `app/routes/device_api.py:290` | Preview future-rental repairs before moving a device. |
| `GET` | `/api/devices/lifecycle/list` | `get_devices_by_lifecycle_status` | `app/routes/device_api.py:531` | 按生命周期状态过滤获取设备列表 |
| `GET` | `/api/devices/lifecycle/summary` | `get_lifecycle_summary` | `app/routes/device_api.py:472` | 获取设备生命周期状态汇总 |
| `POST` | `/api/devices/search` | `search_devices` | `app/routes/device_api.py:68` | 搜索设备 - 支持多字段搜索 |
| `GET` | `/api/gantt/daily-stats` | `get_daily_stats` | `app/routes/gantt_api.py:22` | 获取每日统计信息 |
| `GET` | `/api/gantt/data` | `gantt_data` | `app/routes/gantt_api.py:15` | 获取甘特图数据 |
| `POST` | `/api/gantt/reorder/analyze` | `analyze_reorder` | `app/routes/gantt_api.py:36` | 分析接力关系。 |
| `POST` | `/api/gantt/reorder/execute` | `execute_reorder` | `app/routes/gantt_api.py:50` | 执行档期重排。 |
| `POST` | `/api/gantt/reorder/preview` | `preview_reorder` | `app/routes/gantt_api.py:43` | 生成档期重排预览。 |
| `GET` | `/api/inspections` | `list_inspections` | `app/routes/inspection.py:263` | 获取验货记录列表（支持筛选和分页） |
| `POST` | `/api/inspections` | `create_inspection` | `app/routes/inspection.py:122` | 创建验货记录 |
| `GET` | `/api/inspections/<int:inspection_id>` | `get_inspection` | `app/routes/inspection.py:173` | 获取验货记录详情 |
| `PUT` | `/api/inspections/<int:inspection_id>` | `update_inspection` | `app/routes/inspection.py:207` | 更新验货记录 |
| `GET` | `/api/inspections/rental/latest/<int:device_id>` | `get_latest_rental_by_device` | `app/routes/inspection.py:23` | 根据设备ID获取最近的租赁记录（在今天之前） |
| `GET` | `/api/inspections/rental/latest/by-name/<device_name>` | `get_latest_rental_by_device_name` | `app/routes/inspection.py:72` | 根据设备名称获取最近的租赁记录（在今天之前） |
| `GET` | `/api/inventory/available` | `get_internal_available_inventory` | `app/routes/inventory_api.py:15` | 内部库存查询接口（无需认证） |
| `GET` | `/api/relay-cases` | `list_relay_cases` | `app/routes/relay_case_api.py:14` |  |
| `POST` | `/api/relay-cases/<int:case_id>/tracking/refresh` | `refresh_relay_tracking` | `app/routes/relay_case_api.py:44` |  |
| `PUT` | `/api/relay-cases/<int:predecessor_id>/<int:successor_id>` | `update_relay_case` | `app/routes/relay_case_api.py:35` |  |
| `POST` | `/api/relay-cases/manual` | `create_manual_relay_case` | `app/routes/relay_case_api.py:26` |  |
| `GET` | `/api/relay-cases/manual-options` | `list_manual_relay_options` | `app/routes/relay_case_api.py:20` |  |
| `POST` | `/api/relay-cases/tracking/refresh-batch` | `refresh_relay_tracking_batch` | `app/routes/relay_case_api.py:53` |  |
| `GET` | `/api/rental-stats/models` | `get_models` | `app/routes/rental_stats_api.py:51` | 返回可用的主设备型号列表（供前端下拉使用） |
| `GET` | `/api/rental-stats/periodic` | `get_periodic_stats` | `app/routes/rental_stats_api.py:119` | 按周或按月，按型号统计出租数据 |
| `GET` | `/api/rental-stats/x200u-forecast` | `get_x200u_forecast` | `app/routes/rental_stats_api.py:382` | x200u 年化收益率预测（5-8月） |
| `GET` | `/api/rentals` | `get_rentals` | `app/routes/rental_api.py:23` | 获取租赁记录列表 |
| `POST` | `/api/rentals` | `create_rental` | `app/routes/rental_api.py:51` | 创建租赁记录 |
| `POST` | `/api/rentals/<int:rental_id>/declare-booking` | `declare_booking` | `app/routes/rental_api.py:220` | Persist an explicit two-device declaration before filling the missing slot. |
| `POST` | `/api/rentals/<int:rental_id>/reduce-booking` | `reduce_booking` | `app/routes/rental_api.py:179` | Explicitly reduce a declared order after cancelling a device. |
| `DELETE` | `/api/rentals/<rental_id>` | `delete_rental` | `app/routes/rental_api.py:66` | 删除租赁记录 |
| `GET` | `/api/rentals/<rental_id>` | `get_rental` | `app/routes/rental_api.py:44` | 获取单个租赁记录 |
| `PUT` | `/api/rentals/<rental_id>` | `update_rental` | `app/routes/rental_api.py:58` | 更新租赁记录 |
| `POST` | `/api/rentals/<rental_id>/ship-to-xianyu` | `ship_rental_to_xianyu` | `app/routes/rental_api.py:80` | 单个租赁发货到闲鱼 |
| `PUT` | `/api/rentals/<rental_id>/status` | `update_rental_status` | `app/routes/rental_api.py:73` | 更新租赁状态 |
| `GET` | `/api/rentals/booking-context` | `booking_context` | `app/routes/rental_api.py:161` | Read same-shop order records before explicitly appending a device. |
| `GET` | `/api/rentals/by-ship-date` | `get_rentals_by_ship_date` | `app/routes/rental_api.py:154` | 根据发货日期范围查询租赁记录（用于批量打印） |
| `POST` | `/api/rentals/check-conflict` | `check_rental_conflict` | `app/routes/rental_api.py:89` | 检查租赁冲突 |
| `POST` | `/api/rentals/check-device-conflicts` | `check_device_conflicts` | `app/routes/rental_api.py:96` | 批量检查设备在同一租期内的冲突 |
| `POST` | `/api/rentals/check-duplicate` | `check_duplicate_rental` | `app/routes/rental_api.py:103` | 检查重复租赁 |
| `GET` | `/api/rentals/due-today` | `get_due_today_rentals` | `app/routes/rental_api.py:37` | 待归还租赁记录的兼容接口 |
| `GET` | `/api/rentals/estimate-logistics` | `estimate_logistics` | `app/routes/rental_api.py:17` | 根据目的地预估顺丰标快物流时效 |
| `POST` | `/api/rentals/fetch-xianyu-order` | `fetch_xianyu_order` | `app/routes/rental_api.py:135` | 获取闲鱼订单详情 |
| `POST` | `/api/rentals/find-slot` | `find_rental_slot` | `app/routes/gantt_api.py:29` | 查找可用的租赁时间段 |
| `GET` | `/api/rentals/pending-returns` | `get_pending_returns` | `app/routes/rental_api.py:30` | 获取今天及以前应归还的租赁记录 |
| `POST` | `/api/rentals/search` | `search_rentals` | `app/routes/rental_api.py:146` | 搜索租赁记录 - 支持多字段搜索 |
| `GET` | `/api/settings/members` | `list_members` | `app/routes/settings_api.py:88` |  |
| `POST` | `/api/settings/members` | `create_member` | `app/routes/settings_api.py:94` |  |
| `PATCH` | `/api/settings/members/<int:member_id>` | `update_member` | `app/routes/settings_api.py:134` |  |
| `PUT` | `/api/settings/members/<int:member_id>/password` | `reset_member_password` | `app/routes/settings_api.py:116` |  |
| `GET` | `/api/settings/warehouses` | `list_warehouses` | `app/routes/settings_api.py:149` |  |
| `POST` | `/api/settings/warehouses` | `create_warehouse` | `app/routes/settings_api.py:155` |  |
| `PATCH` | `/api/settings/warehouses/<int:warehouse_id>` | `update_warehouse` | `app/routes/settings_api.py:172` |  |
| `PUT` | `/api/settings/warehouses/<int:warehouse_id>/kuaimai` | `upsert_kuaimai_config` | `app/routes/settings_api.py:214` |  |
| `PUT` | `/api/settings/warehouses/<int:warehouse_id>/sf` | `upsert_sf_config` | `app/routes/settings_api.py:189` |  |
| `GET` | `/api/settings/xianyu-shops` | `list_xianyu_shops` | `app/routes/settings_api.py:232` |  |
| `POST` | `/api/settings/xianyu-shops` | `create_xianyu_shop` | `app/routes/settings_api.py:238` |  |
| `PATCH` | `/api/settings/xianyu-shops/<int:shop_id>` | `update_xianyu_shop` | `app/routes/settings_api.py:252` |  |
| `POST` | `/api/settings/xianyu-shops/<int:shop_id>/sync` | `sync_xianyu_shop` | `app/routes/settings_api.py:268` |  |
| `POST` | `/api/sf-test/order/<int:rental_id>` | `test_sf_order` | `app/routes/sf_test_api.py:37` | Exercise the real resolver and preflight without exposing PII. |
| `GET` | `/api/sf-test/status` | `test_sf_status` | `app/routes/sf_test_api.py:73` | Return only non-sensitive configuration state for one warehouse. |
| `POST` | `/api/sf-tracking/batch-query` | `batch_query_tracking` | `app/routes/sf_tracking_api.py:193` | 批量查询运单物流轨迹 |
| `GET` | `/api/sf-tracking/list` | `get_rental_list` | `app/routes/sf_tracking_api.py:23` | 获取所有有顺丰运单号的租赁订单列表 |
| `POST` | `/api/sf-tracking/query` | `query_tracking` | `app/routes/sf_tracking_api.py:112` | 查询单个运单的物流轨迹 |
| `PATCH` | `/api/shipping-batch/express-type` | `update_express_type` | `app/routes/shipping_batch_api.py:29` | 更新租赁订单的快递类型 |
| `POST` | `/api/shipping-batch/print-waybills` | `print_waybills` | `app/routes/shipping_batch_api.py:43` | 批量打印快递面单 |
| `GET` | `/api/shipping-batch/printers` | `get_printers` | `app/routes/shipping_batch_api.py:36` | 获取打印机配置信息 |
| `POST` | `/api/shipping-batch/schedule` | `schedule_shipment` | `app/routes/shipping_batch_api.py:15` | 预约发货 |
| `POST` | `/api/shipping-batch/ship-to-xianyu/<int:rental_id>` | `ship_to_xianyu` | `app/routes/shipping_batch_api.py:50` | 发货到闲鱼 |
| `GET` | `/api/shipping-batch/status` | `get_status` | `app/routes/shipping_batch_api.py:22` | 获取批量发货状态摘要 |
| `POST` | `/api/statistics/calculate` | `calculate_statistics` | `app/routes/statistics_api.py:271` | 计算并保存最近30天的租赁统计数据 |
| `GET` | `/api/statistics/date-range` | `get_statistics_by_date_range` | `app/routes/statistics_api.py:58` | 获取指定日期范围的统计数据 |
| `GET` | `/api/statistics/latest` | `get_latest_statistics` | `app/routes/statistics_api.py:109` | 获取最新的一条统计记录 |
| `GET` | `/api/statistics/recent` | `get_recent_statistics` | `app/routes/statistics_api.py:15` | 获取最近的统计数据 |
| `POST` | `/api/tracking/batch-query` | `batch_query_tracking` | `app/routes/tracking_api.py:95` | 批量查询快递状态 |
| `POST` | `/api/tracking/query` | `query_tracking` | `app/routes/tracking_api.py:42` | 手动查询快递状态 |
| `GET` | `/api/tracking/scheduler-status` | `get_tracking_scheduler_status` | `app/routes/tracking_api.py:162` |  |
| `POST` | `/api/tracking/update-now` | `update_tracking_now` | `app/routes/tracking_api.py:154` |  |
| `GET` | `/api/warehouses` | `list_public_warehouses` | `app/routes/web.py:161` | Return the current tenant's non-secret warehouse navigation data. |
| `GET` | `/api/xianyu-order-alerts` | `get_alerts` | `app/routes/xianyu_order_alert_api.py:17` |  |
| `POST` | `/api/xianyu-order-alerts/<int:shop_id>/<order_no>/ignore` | `ignore_alert` | `app/routes/xianyu_order_alert_api.py:30` |  |
| `POST` | `/api/xianyu-order-alerts/<int:shop_id>/<order_no>/rental-ignore` | `ignore_rental_alert` | `app/routes/xianyu_order_alert_api.py:36` |  |
| `POST` | `/api/xianyu-order-alerts/refresh` | `refresh_alerts` | `app/routes/xianyu_order_alert_api.py:24` |  |
| `GET` | `/app/` | `unified_index` | `app/routes/vue_app.py:31` | 统一入口路由 - 手机自动跳移动端，桌面返回 PC 端 |
| `GET` | `/assets/<path:filename>` | `unified_assets` | `app/routes/vue_app.py:40` | 统一静态资源路由 |
| `GET` | `/auth/config` | `tenant_auth_config` | `app/routes/auth_api.py:111` |  |
| `POST` | `/auth/logout` | `logout_tenant_member` | `app/routes/auth_api.py:311` |  |
| `GET` | `/auth/me` | `current_tenant_member` | `app/routes/auth_api.py:290` |  |
| `POST` | `/auth/password/change` | `change_password` | `app/routes/auth_api.py:232` |  |
| `POST` | `/auth/password/login` | `login_with_password` | `app/routes/auth_api.py:195` |  |
| `POST` | `/auth/sms/request` | `request_sms_code` | `app/routes/auth_api.py:118` |  |
| `POST` | `/auth/sms/verify` | `verify_sms_code` | `app/routes/auth_api.py:157` |  |
| `GET` | `/batch-shipping` | `vue_router_routes` | `app/routes/vue_app.py:75` | 处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/batch-shipping` | `batch_shipping` | `app/routes/web_pages.py:46` | 批量发货管理页面 - 服务Vue应用 |
| `GET` | `/batch-shipping-order` | `vue_router_routes` | `app/routes/vue_app.py:75` | 处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/batch-shipping-order` | `batch_shipping_order` | `app/routes/web_pages.py:55` | 批量发货单打印页面 - 服务Vue应用 |
| `GET` | `/change-password` | `vue_router_routes` | `app/routes/vue_app.py:75` | 处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/devices` | `vue_router_routes` | `app/routes/vue_app.py:75` | 处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/devices` | `devices` | `app/routes/web_pages.py:73` | 设备管理页面 - 服务 Vue 应用。 |
| `GET` | `/external-api/devices` | `get_devices` | `app/routes/external_api.py:344` | 获取设备列表 |
| `GET` | `/external-api/devices/<device_id>` | `get_device` | `app/routes/external_api.py:409` | 获取设备详情 |
| `PUT` | `/external-api/devices/<int:device_id>/status` | `update_device_status` | `app/routes/external_api.py:34` | 旧在线/离线状态接口已移除。 |
| `GET` | `/external-api/docs` | `api_docs` | `app/routes/external_api.py:521` | API文档 |
| `GET` | `/external-api/health` | `health_check` | `app/routes/external_api.py:511` | 健康检查（无需认证） |
| `GET` | `/external-api/inventory/available` | `get_available_inventory` | `app/routes/external_api.py:44` | 查询可用库存 - 主要API端点 |
| `POST` | `/external-api/inventory/check` | `check_inventory_availability` | `app/routes/external_api.py:132` | 批量检查库存可用性 |
| `POST` | `/external-api/rentals` | `create_rental` | `app/routes/external_api.py:212` | 创建租赁记录 |
| `GET` | `/external-api/rentals/<int:rental_id>` | `get_rental` | `app/routes/external_api.py:247` | 获取租赁记录详情 |
| `PUT` | `/external-api/rentals/<int:rental_id>` | `update_rental` | `app/routes/external_api.py:272` | 更新租赁记录 |
| `POST` | `/external-api/rentals/<int:rental_id>/cancel` | `cancel_rental` | `app/routes/external_api.py:324` | 取消租赁记录 |
| `GET` | `/external-api/statistics` | `get_statistics` | `app/routes/external_api.py:445` | 获取统计信息 |
| `GET` | `/favicon.ico` | `unified_favicon` | `app/routes/vue_app.py:47` | 统一 favicon 路由 |
| `GET` | `/gantt` | `vue_router_routes` | `app/routes/vue_app.py:75` | 处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/gantt` | `gantt` | `app/routes/web_pages.py:19` | 甘特图页面 - 直接显示Vue应用 |
| `GET` | `/health` | `health_check` | `app/routes/web.py:151` | 健康检查 |
| `GET` | `/inspection` | `vue_router_routes` | `app/routes/vue_app.py:75` | 处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/inspection` | `inspection` | `app/routes/web_pages.py:64` | 验货页面 - 服务Vue应用 |
| `GET` | `/inspection-records` | `vue_router_routes` | `app/routes/vue_app.py:75` | 处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/login` | `vue_router_routes` | `app/routes/vue_app.py:75` | 处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/mobile` | `mobile_index` | `app/routes/vue_app.py:87` | 移动端 Vue 应用入口 |
| `GET` | `/mobile/` | `mobile_index` | `app/routes/vue_app.py:87` | 移动端 Vue 应用入口 |
| `GET` | `/mobile/<path:subpath>` | `mobile_router_routes` | `app/routes/vue_app.py:101` | 处理所有移动端 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/mobile/assets/<path:filename>` | `mobile_assets` | `app/routes/vue_app.py:94` | 移动端静态资源 |
| `GET` | `/operations` | `vue_router_routes` | `app/routes/vue_app.py:75` | 处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/platform/api/tenants` | `list_tenants` | `app/routes/platform_api.py:281` |  |
| `POST` | `/platform/api/tenants` | `create_tenant` | `app/routes/platform_api.py:291` |  |
| `PATCH` | `/platform/api/tenants/<int:tenant_id>` | `patch_tenant` | `app/routes/platform_api.py:398` |  |
| `POST` | `/platform/api/tenants/<int:tenant_id>/retry` | `retry_tenant` | `app/routes/platform_api.py:333` |  |
| `POST` | `/platform/auth/login` | `login_platform_admin` | `app/routes/platform_api.py:165` |  |
| `POST` | `/platform/auth/logout` | `logout_platform_admin` | `app/routes/platform_api.py:261` |  |
| `GET` | `/platform/auth/me` | `current_platform_admin` | `app/routes/platform_api.py:247` |  |
| `GET` | `/platform/login` | `vue_router_routes` | `app/routes/vue_app.py:75` | 处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/platform/tenants` | `vue_router_routes` | `app/routes/vue_app.py:75` | 处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/relay-management` | `vue_router_routes` | `app/routes/vue_app.py:75` | 处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/rental-stats` | `vue_router_routes` | `app/routes/vue_app.py:75` | 处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/rentals` | `rentals` | `app/routes/web_pages.py:82` | 租赁管理页面 |
| `GET` | `/settings` | `vue_router_routes` | `app/routes/vue_app.py:75` | 处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/sf-tracking` | `vue_router_routes` | `app/routes/vue_app.py:75` | 处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/sf-tracking` | `sf_tracking` | `app/routes/web_pages.py:37` | 顺丰物流追踪页面 - 服务Vue应用 |
| `GET` | `/shipping/<int:rental_id>` | `shipping_order` | `app/routes/web_pages.py:28` | 出货单页面 - 服务Vue应用 |
| `GET` | `/shipping/<path:subpath>` | `vue_router_routes` | `app/routes/vue_app.py:75` | 处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/statistics` | `vue_router_routes` | `app/routes/vue_app.py:75` | 处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理 |
| `GET` | `/vue` | `vue_index` | `app/routes/vue_app.py:113` | Vue应用首页(PC端) - 向后兼容的旧URL |
| `GET` | `/vue/` | `vue_index` | `app/routes/vue_app.py:113` | Vue应用首页(PC端) - 向后兼容的旧URL |
| `GET` | `/vue/<path:filename>` | `vue_assets` | `app/routes/vue_app.py:121` | Vue应用静态资源(PC端) |
| `DELETE` | `/web/rentals/<rental_id>` | `web_delete_rental` | `app/routes/rental_api.py:126` | Web界面删除租赁记录 |
| `GET` | `/web/rentals/<rental_id>` | `web_get_rental` | `app/routes/rental_api.py:112` | Web界面获取租赁记录 |
| `PUT` | `/web/rentals/<rental_id>` | `web_update_rental` | `app/routes/rental_api.py:119` | Web界面更新租赁记录 |

路由来源还需考虑 `app/__init__.py` 的蓝图注册：`web` 嵌套 `web_pages`、`gantt_api`、`device_api`、`rental_api`、`inventory_api`、`customer_api`、`xianyu_order_alert_api` 和 `relay_case_api`；`external_api` 顶层前缀为 `/external-api`。部分同路径绑定来自旧 HTML 页和 Vue 回退路由，保留注册顺序的实际结果。

## ORM 列（185 个显式列）

字段类型和约束直接来自模型定义，迁移脚本才是生产数据库结构的最终依据；此表不包含继承的 timestamp mixin、关系属性和 `__table_args__` 中的复合约束。

| 表 | 字段 | 类型 | 外键 | 列约束／默认值 | 源码 |
|---|---|---|---|---|---|
| `audit_logs` | `action` | `db.String(50)` | `` | `nullable=False` | `audit_log.py:22` |
| `audit_logs` | `created_at` | `db.DateTime` | `` | `default=datetime.utcnow` | `audit_log.py:33` |
| `audit_logs` | `description` | `db.Text` | `` | `` | `audit_log.py:27` |
| `audit_logs` | `details` | `db.JSON` | `` | `` | `audit_log.py:28` |
| `audit_logs` | `device_id` | `db.Integer` | `db.ForeignKey('devices.id')` | `` | `audit_log.py:18` |
| `audit_logs` | `id` | `db.Integer` | `` | `primary_key=True` | `audit_log.py:15` |
| `audit_logs` | `ip_address` | `db.String(45)` | `` | `` | `audit_log.py:29` |
| `audit_logs` | `rental_id` | `db.Integer` | `db.ForeignKey('rentals.id')` | `` | `audit_log.py:19` |
| `audit_logs` | `resource_id` | `db.String(50)` | `` | `` | `audit_log.py:24` |
| `audit_logs` | `resource_type` | `db.String(50)` | `` | `` | `audit_log.py:23` |
| `audit_logs` | `user_agent` | `db.String(500)` | `` | `` | `audit_log.py:30` |
| `device_models` | `allowed_lens_combos` | `db.Text` | `` | `nullable=True` | `device_model.py:39` |
| `device_models` | `created_at` | `db.DateTime` | `` | `default=datetime.utcnow` | `device_model.py:45` |
| `device_models` | `default_accessories` | `db.Text` | `` | `nullable=True` | `device_model.py:37` |
| `device_models` | `default_lens_combo` | `db.String(30)` | `` | `nullable=True` | `device_model.py:40` |
| `device_models` | `default_rental_package_id` | `db.String(64)` | `` | `nullable=True` | `device_model.py:42` |
| `device_models` | `description` | `db.Text` | `` | `nullable=True` | `device_model.py:29` |
| `device_models` | `device_value` | `db.Numeric(precision=10, scale=2)` | `` | `nullable=True` | `device_model.py:38` |
| `device_models` | `display_name` | `db.String(100)` | `` | `nullable=False` | `device_model.py:28` |
| `device_models` | `id` | `db.Integer` | `` | `primary_key=True` | `device_model.py:24` |
| `device_models` | `is_accessory` | `db.Boolean` | `` | `default=False,nullable=False` | `device_model.py:33` |
| `device_models` | `is_active` | `db.Boolean` | `` | `default=True` | `device_model.py:30` |
| `device_models` | `name` | `db.String(50)` | `` | `nullable=False,unique=True` | `device_model.py:27` |
| `device_models` | `parent_model_id` | `db.Integer` | `db.ForeignKey('device_models.id')` | `nullable=True` | `device_model.py:34` |
| `device_models` | `rental_packages` | `db.Text` | `` | `nullable=True` | `device_model.py:41` |
| `device_models` | `updated_at` | `db.DateTime` | `` | `default=datetime.utcnow` | `device_model.py:46` |
| `devices` | `created_at` | `db.DateTime` | `` | `default=datetime.utcnow` | `device.py:49` |
| `devices` | `id` | `db.Integer` | `` | `primary_key=True` | `device.py:15` |
| `devices` | `is_accessory` | `db.Boolean` | `` | `default=False` | `device.py:22` |
| `devices` | `lifecycle_date` | `db.DateTime` | `` | `nullable=True` | `device.py:42` |
| `devices` | `lifecycle_reason` | `db.String(255)` | `` | `nullable=True` | `device.py:37` |
| `devices` | `lifecycle_status` | `db.Enum('active', 'sold', 'decommissioned', 'damaged', 'retired', name='device_lifecycle_status')` | `` | `default='active',nullable=False` | `device.py:31` |
| `devices` | `model` | `db.String(50)` | `` | `nullable=False,default='x200u'` | `device.py:20` |
| `devices` | `model_id` | `db.Integer` | `db.ForeignKey('device_models.id')` | `nullable=True` | `device.py:21` |
| `devices` | `name` | `db.String(100)` | `` | `nullable=False` | `device.py:18` |
| `devices` | `serial_number` | `db.String(100)` | `` | `unique=True` | `device.py:19` |
| `devices` | `updated_at` | `db.DateTime` | `` | `default=datetime.utcnow` | `device.py:50` |
| `devices` | `warehouse_id` | `db.Integer` | `db.ForeignKey('warehouses.id', ondelete='RESTRICT')` | `nullable=False` | `device.py:23` |
| `inspection_check_item` | `id` | `db.Integer` | `` | `primary_key=True` | `inspection_check_item.py:11` |
| `inspection_check_item` | `inspection_record_id` | `db.Integer` | `db.ForeignKey('inspection_record.id', ondelete='CASCADE')` | `nullable=False,index=True` | `inspection_check_item.py:12` |
| `inspection_check_item` | `is_checked` | `db.Boolean` | `` | `nullable=False,default=False` | `inspection_check_item.py:19` |
| `inspection_check_item` | `item_name` | `db.String(1020)` | `` | `nullable=False` | `inspection_check_item.py:18` |
| `inspection_check_item` | `item_order` | `db.Integer` | `` | `nullable=False,default=0` | `inspection_check_item.py:20` |
| `inspection_record` | `created_at` | `db.DateTime` | `` | `nullable=False,default=datetime.now,index=True` | `inspection_record.py:23` |
| `inspection_record` | `device_id` | `db.Integer` | `db.ForeignKey('devices.id')` | `nullable=False,index=True` | `inspection_record.py:14` |
| `inspection_record` | `id` | `db.Integer` | `` | `primary_key=True` | `inspection_record.py:12` |
| `inspection_record` | `inspector_user_id` | `db.Integer` | `` | `nullable=True` | `inspection_record.py:22` |
| `inspection_record` | `rental_id` | `db.Integer` | `db.ForeignKey('rentals.id')` | `nullable=False,index=True` | `inspection_record.py:13` |
| `inspection_record` | `status` | `db.String(20)` | `` | `nullable=False,default='abnormal',index=True` | `inspection_record.py:15` |
| `inspection_record` | `updated_at` | `db.DateTime` | `` | `nullable=False,default=datetime.now` | `inspection_record.py:24` |
| `rental_accessories` | `created_at` | `db.DateTime` | `` | `default=datetime.utcnow` | `rental_accessory.py:27` |
| `rental_accessories` | `device_id` | `db.Integer` | `db.ForeignKey('devices.id')` | `nullable=False` | `rental_accessory.py:24` |
| `rental_accessories` | `id` | `db.Integer` | `` | `primary_key=True` | `rental_accessory.py:20` |
| `rental_accessories` | `rental_id` | `db.Integer` | `db.ForeignKey('rentals.id')` | `nullable=False` | `rental_accessory.py:23` |
| `rental_accessories` | `updated_at` | `db.DateTime` | `` | `default=datetime.utcnow` | `rental_accessory.py:28` |
| `rental_booking_requests` | `id` | `db.String(36)` | `` | `primary_key=True` | `rental.py:511` |
| `rental_booking_requests` | `payload_hash` | `db.String(64)` | `` | `nullable=False` | `rental.py:512` |
| `rental_booking_requests` | `rental_ids` | `db.JSON` | `` | `nullable=False,default=list` | `rental.py:513` |
| `rental_bookings` | `expected_quantity` | `db.Integer` | `` | `nullable=False,default=2` | `rental.py:481` |
| `rental_bookings` | `id` | `db.Integer` | `` | `primary_key=True` | `rental.py:478` |
| `rental_bookings` | `order_no` | `db.String(50)` | `` | `` | `rental.py:480` |
| `rental_bookings` | `quantity_change_reason` | `db.Text` | `` | `` | `rental.py:483` |
| `rental_bookings` | `total_amount` | `db.Numeric(10, 2)` | `` | `` | `rental.py:482` |
| `rental_bookings` | `xianyu_shop_id` | `db.Integer` | `db.ForeignKey('xianyu_shops.id', ondelete='RESTRICT')` | `` | `rental.py:479` |
| `rental_bookings` | `xianyu_waybill_no` | `db.String(50)` | `` | `` | `rental.py:484` |
| `rental_relay_bindings` | `confirmed_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `rental_relay_binding.py:34` |
| `rental_relay_bindings` | `created_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `rental_relay_binding.py:35` |
| `rental_relay_bindings` | `id` | `db.Integer` | `` | `primary_key=True` | `rental_relay_binding.py:23` |
| `rental_relay_bindings` | `predecessor_rental_id` | `db.Integer` | `db.ForeignKey('rentals.id', ondelete='CASCADE')` | `nullable=False` | `rental_relay_binding.py:24` |
| `rental_relay_bindings` | `successor_rental_id` | `db.Integer` | `db.ForeignKey('rentals.id', ondelete='CASCADE')` | `nullable=False` | `rental_relay_binding.py:29` |
| `rental_relay_bindings` | `updated_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `rental_relay_binding.py:36` |
| `rental_relay_cases` | `agreed_at` | `db.DateTime` | `` | `` | `rental_relay_case.py:57` |
| `rental_relay_cases` | `completed_at` | `db.DateTime` | `` | `` | `rental_relay_case.py:59` |
| `rental_relay_cases` | `created_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `rental_relay_case.py:60` |
| `rental_relay_cases` | `id` | `db.Integer` | `` | `primary_key=True` | `rental_relay_case.py:25` |
| `rental_relay_cases` | `notified_at` | `db.DateTime` | `` | `` | `rental_relay_case.py:56` |
| `rental_relay_cases` | `predecessor_rental_id` | `db.Integer` | `db.ForeignKey('rentals.id', ondelete='CASCADE')` | `nullable=False,index=True` | `rental_relay_case.py:26` |
| `rental_relay_cases` | `sf_last_checked_at` | `db.DateTime` | `` | `` | `rental_relay_case.py:54` |
| `rental_relay_cases` | `sf_tracking_number` | `db.String(50)` | `` | `` | `rental_relay_case.py:51` |
| `rental_relay_cases` | `sf_tracking_status` | `db.String(50)` | `` | `` | `rental_relay_case.py:52` |
| `rental_relay_cases` | `sf_tracking_summary` | `db.String(500)` | `` | `` | `rental_relay_case.py:53` |
| `rental_relay_cases` | `shipped_at` | `db.DateTime` | `` | `` | `rental_relay_case.py:58` |
| `rental_relay_cases` | `status` | `db.Enum('pending', 'notified', 'agreed', 'shipped', 'completed', name='relay_case_status')` | `` | `nullable=False,default='pending'` | `rental_relay_case.py:38` |
| `rental_relay_cases` | `successor_rental_id` | `db.Integer` | `db.ForeignKey('rentals.id', ondelete='CASCADE')` | `nullable=False,index=True` | `rental_relay_case.py:32` |
| `rental_relay_cases` | `updated_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `rental_relay_case.py:61` |
| `rental_statistics` | `created_at` | `db.DateTime` | `` | `default=datetime.utcnow` | `rental_statistics.py:30` |
| `rental_statistics` | `id` | `db.Integer` | `` | `primary_key=True` | `rental_statistics.py:15` |
| `rental_statistics` | `period_end` | `db.Date` | `` | `nullable=False` | `rental_statistics.py:22` |
| `rental_statistics` | `period_start` | `db.Date` | `` | `nullable=False` | `rental_statistics.py:21` |
| `rental_statistics` | `stat_date` | `db.Date` | `` | `nullable=False,unique=True,index=True` | `rental_statistics.py:18` |
| `rental_statistics` | `total_rent` | `db.Numeric(precision=10, scale=2)` | `` | `nullable=False,default=0` | `rental_statistics.py:26` |
| `rental_statistics` | `total_rentals` | `db.Integer` | `` | `nullable=False,default=0` | `rental_statistics.py:25` |
| `rental_statistics` | `total_value` | `db.Numeric(precision=10, scale=2)` | `` | `nullable=False,default=0` | `rental_statistics.py:27` |
| `rental_statistics` | `updated_at` | `db.DateTime` | `` | `default=datetime.utcnow` | `rental_statistics.py:31` |
| `rentals` | `booking_id` | `db.Integer` | `db.ForeignKey('rental_bookings.id', ondelete='RESTRICT')` | `nullable=True,index=True` | `rental.py:15` |
| `rentals` | `buyer_id` | `db.String(100)` | `` | `nullable=True` | `rental.py:50` |
| `rentals` | `created_at` | `db.DateTime` | `` | `default=datetime.utcnow` | `rental.py:73` |
| `rentals` | `customer_name` | `db.String(100)` | `` | `nullable=False` | `rental.py:37` |
| `rentals` | `customer_phone` | `db.String(20)` | `` | `` | `rental.py:38` |
| `rentals` | `damage_note` | `db.Text` | `` | `nullable=True` | `rental.py:53` |
| `rentals` | `destination` | `db.String(100)` | `` | `` | `rental.py:39` |
| `rentals` | `device_id` | `db.Integer` | `db.ForeignKey('devices.id')` | `nullable=False` | `rental.py:22` |
| `rentals` | `end_date` | `db.Date` | `` | `nullable=False` | `rental.py:32` |
| `rentals` | `express_type_id` | `db.Integer` | `` | `default=2` | `rental.py:63` |
| `rentals` | `id` | `db.Integer` | `` | `primary_key=True` | `rental.py:19` |
| `rentals` | `includes_handle` | `db.Boolean` | `` | `default=False,server_default='0',nullable=False` | `rental.py:80` |
| `rentals` | `includes_lens_mount` | `db.Boolean` | `` | `default=False,server_default='0',nullable=False` | `rental.py:81` |
| `rentals` | `lens_combo` | `db.Enum('lens_400mm', 'lens_200mm', 'bare', 'lens_dual', name='rental_lens_combo')` | `` | `nullable=False,server_default='lens_400mm'` | `rental.py:87` |
| `rentals` | `order_amount` | `db.DECIMAL(10, 2)` | `` | `nullable=True` | `rental.py:49` |
| `rentals` | `parent_rental_id` | `db.Integer` | `db.ForeignKey('rentals.id', ondelete='CASCADE')` | `nullable=True` | `rental.py:77` |
| `rentals` | `photo_transfer` | `db.Boolean` | `` | `default=False,server_default='0',nullable=False` | `rental.py:84` |
| `rentals` | `rental_package_id` | `db.String(64)` | `` | `nullable=True` | `rental.py:93` |
| `rentals` | `rental_package_items` | `db.Text` | `` | `nullable=True` | `rental.py:95` |
| `rentals` | `rental_package_name` | `db.String(100)` | `` | `nullable=True` | `rental.py:94` |
| `rentals` | `scheduled_ship_time` | `db.DateTime` | `` | `` | `rental.py:62` |
| `rentals` | `ship_in_time` | `db.DateTime` | `` | `nullable=True` | `rental.py:34` |
| `rentals` | `ship_in_tracking_no` | `db.String(50)` | `` | `` | `rental.py:61` |
| `rentals` | `ship_out_time` | `db.DateTime` | `` | `nullable=True` | `rental.py:33` |
| `rentals` | `ship_out_tracking_no` | `db.String(50)` | `` | `` | `rental.py:60` |
| `rentals` | `start_date` | `db.Date` | `` | `nullable=False` | `rental.py:31` |
| `rentals` | `status` | `db.Enum('not_shipped', 'scheduled_for_shipping', 'shipped', 'returned', 'completed', 'cancelled', name='rental_status')` | `` | `default='not_shipped'` | `rental.py:66` |
| `rentals` | `updated_at` | `db.DateTime` | `` | `default=datetime.utcnow` | `rental.py:74` |
| `rentals` | `warehouse_id` | `db.Integer` | `db.ForeignKey('warehouses.id', ondelete='RESTRICT')` | `nullable=False` | `rental.py:23` |
| `rentals` | `xianyu_order_no` | `db.String(50)` | `` | `nullable=True` | `rental.py:42` |
| `rentals` | `xianyu_shop_id` | `db.Integer` | `db.ForeignKey('xianyu_shops.id', ondelete='RESTRICT')` | `nullable=True` | `rental.py:43` |
| `warehouse_kuaimai_configs` | `app_id` | `db.String(100)` | `` | `` | `warehouse.py:194` |
| `warehouse_kuaimai_configs` | `app_secret_ciphertext` | `db.Text` | `` | `` | `warehouse.py:195` |
| `warehouse_kuaimai_configs` | `created_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `warehouse.py:197` |
| `warehouse_kuaimai_configs` | `printer_sn` | `db.String(100)` | `` | `` | `warehouse.py:196` |
| `warehouse_kuaimai_configs` | `updated_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `warehouse.py:200` |
| `warehouse_kuaimai_configs` | `warehouse_id` | `db.Integer` | `db.ForeignKey('warehouses.id', ondelete='RESTRICT')` | `primary_key=True` | `warehouse.py:189` |
| `warehouse_sf_configs` | `checkword_ciphertext` | `db.Text` | `` | `` | `warehouse.py:151` |
| `warehouse_sf_configs` | `created_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `warehouse.py:157` |
| `warehouse_sf_configs` | `monthly_card_ciphertext` | `db.Text` | `` | `` | `warehouse.py:152` |
| `warehouse_sf_configs` | `partner_id` | `db.String(100)` | `` | `` | `warehouse.py:150` |
| `warehouse_sf_configs` | `sender_address` | `db.String(500)` | `` | `` | `warehouse.py:156` |
| `warehouse_sf_configs` | `sender_name` | `db.String(100)` | `` | `` | `warehouse.py:154` |
| `warehouse_sf_configs` | `sender_phone` | `db.String(30)` | `` | `` | `warehouse.py:155` |
| `warehouse_sf_configs` | `test_mode` | `db.Boolean` | `` | `nullable=False,default=False` | `warehouse.py:153` |
| `warehouse_sf_configs` | `updated_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `warehouse.py:160` |
| `warehouse_sf_configs` | `warehouse_id` | `db.Integer` | `db.ForeignKey('warehouses.id', ondelete='RESTRICT')` | `primary_key=True` | `warehouse.py:145` |
| `warehouses` | `city` | `db.String(64)` | `` | `nullable=False` | `warehouse.py:71` |
| `warehouses` | `created_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `warehouse.py:73` |
| `warehouses` | `id` | `db.Integer` | `` | `primary_key=True` | `warehouse.py:69` |
| `warehouses` | `name` | `db.String(100)` | `` | `nullable=False` | `warehouse.py:72` |
| `warehouses` | `province` | `db.String(64)` | `` | `nullable=False` | `warehouse.py:70` |
| `warehouses` | `updated_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `warehouse.py:76` |
| `xianyu_order_alerts` | `address` | `db.String(500)` | `` | `` | `xianyu_order_alert.py:40` |
| `xianyu_order_alerts` | `buyer_nick` | `db.String(100)` | `` | `` | `xianyu_order_alert.py:37` |
| `xianyu_order_alerts` | `created_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `xianyu_order_alert.py:52` |
| `xianyu_order_alerts` | `first_detected_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `xianyu_order_alert.py:44` |
| `xianyu_order_alerts` | `goods_sku_text` | `db.String(500)` | `` | `` | `xianyu_order_alert.py:42` |
| `xianyu_order_alerts` | `goods_title` | `db.String(500)` | `` | `` | `xianyu_order_alert.py:41` |
| `xianyu_order_alerts` | `id` | `db.Integer` | `` | `primary_key=True` | `xianyu_order_alert.py:26` |
| `xianyu_order_alerts` | `ignored_at` | `db.DateTime` | `` | `` | `xianyu_order_alert.py:51` |
| `xianyu_order_alerts` | `ignored_reason` | `db.String(500)` | `` | `` | `xianyu_order_alert.py:50` |
| `xianyu_order_alerts` | `last_seen_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `xianyu_order_alert.py:47` |
| `xianyu_order_alerts` | `order_no` | `db.String(50)` | `` | `nullable=False,index=True` | `xianyu_order_alert.py:27` |
| `xianyu_order_alerts` | `order_time` | `db.DateTime` | `` | `` | `xianyu_order_alert.py:43` |
| `xianyu_order_alerts` | `pay_amount` | `db.BigInteger` | `` | `nullable=False` | `xianyu_order_alert.py:36` |
| `xianyu_order_alerts` | `receiver_mobile` | `db.String(20)` | `` | `` | `xianyu_order_alert.py:39` |
| `xianyu_order_alerts` | `receiver_name` | `db.String(100)` | `` | `` | `xianyu_order_alert.py:38` |
| `xianyu_order_alerts` | `state` | `db.String(20)` | `` | `nullable=False,default='pending',index=True` | `xianyu_order_alert.py:33` |
| `xianyu_order_alerts` | `updated_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `xianyu_order_alert.py:55` |
| `xianyu_order_alerts` | `xianyu_shop_id` | `db.Integer` | `db.ForeignKey('xianyu_shops.id', ondelete='RESTRICT')` | `nullable=False` | `xianyu_order_alert.py:28` |
| `xianyu_rental_alerts` | `first_detected_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `xianyu_rental_alert.py:23` |
| `xianyu_rental_alerts` | `id` | `db.Integer` | `` | `primary_key=True` | `xianyu_rental_alert.py:14` |
| `xianyu_rental_alerts` | `ignored_at` | `db.DateTime` | `` | `nullable=True` | `xianyu_rental_alert.py:25` |
| `xianyu_rental_alerts` | `ignored_reason` | `db.String(500)` | `` | `nullable=True` | `xianyu_rental_alert.py:26` |
| `xianyu_rental_alerts` | `kind` | `db.String(20)` | `` | `nullable=False` | `xianyu_rental_alert.py:19` |
| `xianyu_rental_alerts` | `last_seen_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `xianyu_rental_alert.py:24` |
| `xianyu_rental_alerts` | `order_no` | `db.String(50)` | `` | `nullable=False` | `xianyu_rental_alert.py:18` |
| `xianyu_rental_alerts` | `order_status` | `db.Integer` | `` | `nullable=False` | `xianyu_rental_alert.py:21` |
| `xianyu_rental_alerts` | `refund_status` | `db.Integer` | `` | `nullable=False` | `xianyu_rental_alert.py:22` |
| `xianyu_rental_alerts` | `status_text` | `db.String(100)` | `` | `nullable=False` | `xianyu_rental_alert.py:20` |
| `xianyu_rental_alerts` | `xianyu_shop_id` | `db.Integer` | `db.ForeignKey('xianyu_shops.id', ondelete='RESTRICT')` | `nullable=False` | `xianyu_rental_alert.py:15` |
| `xianyu_shops` | `app_key` | `db.String(255)` | `` | `nullable=False` | `xianyu_shop.py:23` |
| `xianyu_shops` | `app_secret_ciphertext` | `db.Text` | `` | `` | `xianyu_shop.py:24` |
| `xianyu_shops` | `created_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `xianyu_shop.py:28` |
| `xianyu_shops` | `id` | `db.Integer` | `` | `primary_key=True` | `xianyu_shop.py:21` |
| `xianyu_shops` | `is_active` | `db.Boolean` | `` | `nullable=False,default=False` | `xianyu_shop.py:25` |
| `xianyu_shops` | `last_error` | `db.String(1000)` | `` | `` | `xianyu_shop.py:27` |
| `xianyu_shops` | `last_success_at` | `db.DateTime` | `` | `` | `xianyu_shop.py:26` |
| `xianyu_shops` | `name` | `db.String(100)` | `` | `nullable=False` | `xianyu_shop.py:22` |
| `xianyu_shops` | `updated_at` | `db.DateTime` | `` | `nullable=False,default=datetime.utcnow` | `xianyu_shop.py:31` |

## 复刻核对

逐一覆盖每个业务路由的输入、成功和失败响应；先满足各功能规格中的场景，再用原系统同一测试数据对照该索引中的低频路径。对每张表校验字段、唯一性、外键、索引和迁移结果；不能仅凭此字段清单推断级联或状态规则。

## 数据库约束与关系补充

上面的显式列索引不包含控制库 `TimestampMixin` 继承的 `created_at,updated_at`。控制库的五张表及约束如下；业务库的最终物理结构仍须以 `control_migrations/` 与 `migrations/` 迁移执行结果为准，尤其不能把 ORM 关系级联当成数据库外键级联。

| 库与表 | 非主键唯一约束、检查约束及关系 |
|---|---|
| 控制库 `platform_admins` | `username` 唯一；继承两个时间戳 |
| 控制库 `tenants` | `db_name`、`db_username` 分别唯一；`status ∈ {active,suspended}`，`provisioning_status ∈ {provisioning,active,failed}`；继承两个时间戳 |
| 控制库 `tenant_members` | `phone` 在**所有租户**中唯一；`tenant_id → tenants.id ON DELETE CASCADE`；`role ∈ {admin,operator}`、`status ∈ {active,disabled}`；继承两个时间戳 |
| 控制库 `auth_sessions` | `token_hash` 唯一；`tenant_id → tenants.id ON DELETE CASCADE` 可空；`kind ∈ {platform,tenant}`；时间列是 `created_at,last_seen_at,expires_at`，不继承 mixin |
| 控制库 `sms_login_codes` | 无非主键唯一约束；手机号、IP、摘要、失败次数、发送与消费状态组成验证记录 |
| 业务库 `devices`、`device_models` | 设备序列号唯一、型号编码 `name` 唯一；`devices.model_id` 与 `device_models.parent_model_id` 可空；设备仓库外键 `ON DELETE RESTRICT`。删除历史设备的限制由服务层租赁检查补足 |
| 业务库 `rental_bookings`、`rental_booking_requests` | `(xianyu_shop_id,order_no)` 唯一；重试表以 UUID 字符串 `id` 作主键并存 payload hash 与租赁 ID 列表；`rentals.booking_id` 外键 `ON DELETE RESTRICT` |
| 业务库 `rentals`、`rental_accessories` | 主租赁的 `parent_rental_id=NULL`，附件新架构使用子 `rentals.parent_rental_id → rentals.id ON DELETE CASCADE`；`rental_accessories` 是仍存在的旧表，新流程不以它表达附件；租赁仓库与闲鱼店铺外键 `ON DELETE RESTRICT` |
| 业务库 `rental_relay_cases` | `(predecessor_rental_id,successor_rental_id)` 唯一，两 ID 不得相同；两端都外键到 `rentals.id ON DELETE CASCADE`，另有 `status` 索引 |
| 业务库 `rental_relay_bindings` | 前单 ID 独立唯一、后单 ID 独立唯一，两 ID 不得相同；两端外键到 `rentals.id ON DELETE CASCADE`。这使一笔主租赁最多接一个前继和一个后继 |
| 业务库 `xianyu_order_alerts` | `(xianyu_shop_id,order_no)` 唯一；`state ∈ {pending,ignored}`；同一租户不同店铺可有相同订单号 |
| 业务库 `xianyu_rental_alerts` | `(xianyu_shop_id,order_no)` 唯一；其 `kind` 由同步服务产生，与漏单告警分表 |
| 业务库 `inspection_record`、`inspection_check_item` | 验货记录关联租赁及设备；检查项的验货记录外键 `ON DELETE CASCADE`，ORM 关系也使用 `delete-orphan` |
| 业务库 `warehouse_sf_configs`、`warehouse_kuaimai_configs` | 每张配置表都以 `warehouse_id` 作主键和仓库外键，故每仓至多一条同类配置；外键 `ON DELETE RESTRICT` |
| 业务库 `rental_statistics` | `stat_date` 唯一，旧快照一天一行 |

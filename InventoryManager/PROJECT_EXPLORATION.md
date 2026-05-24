# InventoryManager 项目深度探索报告

## 概览
**项目名**: XianyuAutoAgent - InventoryManager (二手设备库存管理系统)  
**位置**: `/Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager`  
**主要技术栈**:
- **后端**: Flask (Python)
- **前端PC**: Vue 3 + TypeScript + Vite + Element Plus
- **前端移动**: Vue 3 + TypeScript + Vite + Vant UI
- **测试**: Vitest (单元/集成测试)，Playwright (E2E)
- **状态管理**: Pinia
- **数据库**: MySQL (via SQLAlchemy)
- **构建**: Docker

---

## 1. 整体目录结构

```
InventoryManager/
├── app/                          # 后端Flask应用
│   ├── routes/                   # API路由（18个蓝图）
│   │   ├── gantt_api.py         # 甘特图API
│   │   ├── rental_api.py        # 租赁管理API
│   │   ├── device_api.py        # 设备管理API
│   │   ├── device_model_api.py  # 设备型号API
│   │   └── [其他API]
│   ├── models/                   # 数据模型
│   │   ├── rental.py
│   │   ├── device.py
│   │   └── [其他模型]
│   ├── services/                 # 业务逻辑服务
│   ├── handlers/                 # 请求处理器
│   └── utils/                    # 工具函数
│
├── frontend/                     # PC端前端
│   ├── src/
│   │   ├── views/               # 页面组件（9个）
│   │   │   ├── GanttView.vue           # 甘特图主页
│   │   │   ├── RentalContractView.vue  # 租赁合同
│   │   │   ├── ShippingOrderView.vue   # 发货单
│   │   │   ├── BatchShippingView.vue   # 批量发货
│   │   │   ├── StatisticsView.vue      # 统计数据
│   │   │   ├── RentalStatsView.vue     # 租赁周期统计
│   │   │   ├── SFTrackingView.vue      # 物流查询
│   │   │   ├── InspectionView.vue      # 验机
│   │   │   └── InspectionRecordsView.vue
│   │   ├── components/          # 组件库（20+）
│   │   │   ├── GanttChart.vue          # 主甘特图容器
│   │   │   ├── GanttRow.vue            # 甘特图行（颜色/状态逻辑）
│   │   │   ├── RentalTooltip.vue       # 悬停提示
│   │   │   ├── BookingDialog.vue       # 预定表单
│   │   │   ├── rental/
│   │   │   │   ├── EditRentalDialogNew.vue  # 编辑表单（3层分割）
│   │   │   │   ├── RentalBasicForm.vue
│   │   │   │   ├── RentalShippingForm.vue
│   │   │   │   ├── RentalAccessorySelector.vue
│   │   │   │   ├── RentalActionButtons.vue
│   │   │   │   └── BatchPrintDialog.vue
│   │   │   ├── ImagePreviewDialog.vue
│   │   │   ├── inspection/
│   │   │   └── printing/
│   │   ├── stores/              # Pinia存储
│   │   │   ├── gantt.ts         # 主甘特图状态
│   │   │   ├── inspection.ts
│   │   │   └── counter.ts
│   │   ├── composables/         # Vue组合式API
│   │   │   ├── useAvailabilityCheck.ts
│   │   │   ├── useConflictDetection.ts
│   │   │   ├── useDeviceManagement.ts
│   │   │   └── useRentalFormValidation.ts
│   │   ├── utils/
│   │   │   ├── dateUtils.ts     # 日期工具
│   │   │   └── phoneExtractor.ts
│   │   ├── types/
│   │   │   ├── rental.ts
│   │   │   └── inspection.ts
│   │   ├── api/
│   │   ├── router/              # 路由配置
│   │   ├── App.vue
│   │   └── main.ts
│   ├── public/
│   ├── tests/                   # 测试套件
│   │   ├── unit/                # 单元测试
│   │   │   └── stores/gantt.spec.ts
│   │   └── integration/         # 集成测试
│   │       ├── api-workflow.spec.ts
│   │       ├── gantt-workflow.spec.ts
│   │       └── ...
│   ├── package.json             # Node依赖 (Vue 3.5.18)
│   └── vite.config.ts
│
├── frontend-mobile/             # 移动端前端
│   ├── src/
│   │   ├── views/              # 页面（4个）
│   │   │   ├── GanttView.vue          # 甘特图（移动版）
│   │   │   ├── CreateRentalView.vue   # 创建租赁
│   │   │   ├── EditRentalView.vue     # 编辑租赁
│   │   │   └── BatchShippingView.vue
│   │   ├── components/         # 组件（4个）
│   │   │   ├── GanttGrid.vue          # 移动版甘特表格
│   │   │   ├── RentalBottomSheet.vue  # 底部弹窗
│   │   │   ├── BatchShippingCard.vue
│   │   │   └── RentalBottomSheet.vue
│   │   ├── stores/
│   │   │   └── gantt.ts         # 共享的状态存储
│   │   ├── router/
│   │   ├── composables/
│   │   ├── utils/
│   │   └── main.ts
│   └── package.json             # Vant UI库
│
├── tests/                       # Python后端测试
│   ├── unit/
│   │   └── test_rental_service.py
│   └── integration/
│       └── test_rental_api.py
│
├── .env                         # 配置文件（MySQL连接、Aliyun、顺丰、闲鱼API）
├── .env.docker
├── .env.example
├── requirements.txt             # Python依赖
├── Dockerfile
├── docker-compose.yml
└── app.py                       # 应用入口
```

---

## 2. 移动端 frontend-mobile 现有代码结构

### 2.1 目录树
```
frontend-mobile/src/
├── App.vue                      # 根组件
├── main.ts                      # 应用入口
├── router/
│   └── index.ts                 # 路由配置（4个路由）
├── stores/
│   └── gantt.ts                 # Pinia 状态存储
├── views/
│   ├── GanttView.vue            # 甘特图主页
│   ├── CreateRentalView.vue     # 新建租赁页
│   ├── EditRentalView.vue       # 编辑租赁页
│   └── BatchShippingView.vue    # 批量发货页
├── components/
│   ├── GanttGrid.vue            # 移动版甘特表格
│   ├── RentalBottomSheet.vue    # 租赁详情弹窗
│   ├── BatchShippingCard.vue    # 发货卡片
│   └── ...
├── composables/
│   └── useConflictDetection.ts  # 冲突检测Hooks
├── utils/
│   ├── dateUtils.ts             # 日期工具
│   └── phoneExtractor.ts        # 手机号提取
└── types/
    └── (共用前端类型定义)
```

### 2.2 页面路由
```typescript
// 路由配置示例
[
  { path: '/', component: GanttView },           // 甘特图
  { path: '/create-rental', component: CreateRentalView },
  { path: '/edit-rental/:id', component: EditRentalView },
  { path: '/batch-shipping', component: BatchShippingView }
]
```

### 2.3 关键组件
**GanttGrid.vue** - 移动版甘特表格
- 使用虚拟滚动优化性能
- 支持单日统计显示
- 点击租赁条显示详情

**RentalBottomSheet.vue** - 底部详情弹窗
- 使用Vant的ActionSheet
- 显示租赁详细信息
- 快速操作按钮

---

## 3. PC端 frontend 功能实现解析

### 3.1 查看某一天空闲/待寄出设备数量

**实现文件**: `GanttChart.vue` + `GanttRow.vue`

**日历/时间线组件**:
```typescript
// GanttChart.vue - L184-206
// 日期头部显示统计
<div class="date-header" @click="handleDateClick(date)">
  <div class="date-stats">
    <span class="stat-available">{{ getStatsForDate(date).available_count }} 闲</span>
    <span class="stat-ship-out clickable" @click="filterByShipOutDate(date)">
      {{ getStatsForDate(date).ship_out_count }} 寄
    </span>
    <span class="stat-accessory-ship-out clickable">
      {{ getStatsForDate(date).accessory_ship_out_count }} 附寄
    </span>
  </div>
</div>
```

**统计数据加载** (L902-972):
```typescript
const loadDailyStats = async () => {
  // 防抖处理
  const response = await axios.get('/api/gantt/daily-stats', { 
    params: { date: dateStr, device_model: selectedDeviceModel.value }
  })
  dailyStats.value[stat.date] = {
    available_count,
    ship_out_count,
    accessory_ship_out_count
  }
}
```

**API 端点**: `/api/gantt/daily-stats?date=YYYY-MM-DD`

**统计逻辑**:
- **空闲设备**: 该日期无租赁的设备
- **待寄出**: `ship_out_time` 为该日期的设备
- **附件待寄出**: 附件设备需要寄出

### 3.2 预定设备表单 (BookingDialog)

**实现文件**: `components/BookingDialog.vue`

**表单字段**:
```typescript
{
  selectedDeviceModel: string      // 设备型号（可选限制）
  selectedDevice: number           // 选中的设备ID
  startDate: Date                  // 租赁开始日期
  endDate: Date                    // 租赁结束日期
  customerName: string             // 客户名称
  customerPhone: string            // 客户电话
  destination: string              // 目的地
  shipOutTime: Date               // 发货时间
  shipInTime: Date                // 收货时间
  bundledAccessories: string[]    // 配套附件 ['handle', 'lens_mount']
  accessories: number[]           // 库存附件ID列表
}
```

**交互流程**:
1. 选择设备型号 → 获取可用设备
2. 选择具体设备 → 检查档期冲突
3. 选择日期 → 自动计算物流时间
4. 选择附件 → 检查附件可用性
5. 提交 → 调用 `/api/rentals` POST

### 3.3 编辑租赁记录表单 (EditRentalDialogNew)

**实现文件**: `components/rental/EditRentalDialogNew.vue` + 3个子组件

**三层分割结构**:
```
EditRentalDialogNew (主控制器)
├── RentalBasicForm          # 📋 基础信息（设备、日期）
├── RentalShippingForm       # 🚚 客户与物流信息
└── RentalAccessorySelector  # 🔧 附件选择
```

**表单数据结构** (L140-160):
```typescript
const form = ref({
  deviceId: 0,                      // 设备ID
  endDate: null as Date | null,     // 租赁结束日期
  customerPhone: '',                // 客户电话
  destination: '',                  // 目的地
  shipOutTrackingNo: '',           // 发货单号
  shipInTrackingNo: '',            // 收货单号
  shipOutTime: null,               // 发货时间
  shipInTime: null,                // 收货时间
  status: 'not_shipped',           // 租赁状态
  // 配套附件（布尔值标记）
  bundledAccessories: ['handle', 'lens_mount'],
  // 库存附件（ID数组）
  phoneHolderId: null as number | null,
  tripodId: null as number | null,
  accessories: [] as number[],
  xianyuOrderNo: '',               // 闲鱼订单号
  orderAmount: '',                 // 订单金额
  buyerId: '',                      // 买家ID
  photoTransfer: false             // 代传照片标记
})
```

**编辑提交逻辑** (L214-257):
```typescript
const handleSubmit = async () => {
  await formRef.value?.validate()
  
  const updateData = {
    device_id: form.value.deviceId,
    end_date: dayjs(form.value.endDate).format('YYYY-MM-DD'),
    customer_phone: form.value.customerPhone,
    destination: form.value.destination,
    ship_out_time: form.value.shipOutTime 
      ? dayjs(form.value.shipOutTime).format('YYYY-MM-DD HH:mm:ss')
      : null,
    status: form.value.status,
    // 配套附件用布尔值
    includes_handle: form.value.bundledAccessories.includes('handle'),
    includes_lens_mount: form.value.bundledAccessories.includes('lens_mount'),
    // 库存附件用ID数组
    accessories: accessoryIds,
    photo_transfer: form.value.photoTransfer
  }
  
  await ganttStore.updateRental(props.rental!.id, updateData)
}
```

**API 端点**: `/web/rentals/<rental_id>` PUT

### 3.4 修改设备使用状态

**实现文件**: `GanttChart.vue` L843-859

**状态修改方法**:
```typescript
const handleUpdateDeviceStatus = async (device: Device, newStatus: string) => {
  await ganttStore.updateDeviceStatus(device.id, newStatus)
  await ganttStore.loadData()
}

const handleUpdateDeviceLifecycle = async (device: Device, newLifecycle: string) => {
  // 调用 updateDeviceLifecycle
  await ganttStore.updateDeviceLifecycle(device.id, newLifecycle)
  // 生命周期状态: 'active' | 'sold' | 'damaged' | 'decommissioned' | 'retired'
}
```

**设备状态选择** (GanttRow.vue L10-21):
```vue
<el-select :model-value="device.lifecycle_status || 'active'" @change="updateLifecycleStatus">
  <el-option label="🟢 使用中" value="active" />
  <el-option label="💰 已售出" value="sold" />
  <el-option label="🔧 已损坏" value="damaged" />
  <el-option label="⛔ 已停用" value="decommissioned" />
  <el-option label="📦 已退役" value="retired" />
</el-select>
```

**API 端点**: `/api/devices/<device_id>/lifecycle` PUT

### 3.5 搜索地址/手机号功能

**实现文件**: `GanttChart.vue` L94-106

**搜索输入框**:
```vue
<el-input
  v-model="searchKeyword"
  placeholder="搜索租赁人名/地址"
  clearable
  @input="onSearchInput"
>
  <template #prefix>
    <el-icon><Search /></el-icon>
  </template>
</el-input>
```

**搜索逻辑** (L487-500):
```typescript
const filteredDevices = computed(() => {
  if (searchKeyword.value.trim()) {
    const keyword = searchKeyword.value.toLowerCase().trim()
    devices = devices.filter(device => {
      // 获取该设备的所有租赁记录
      const rentals = ganttStore.getRentalsForDevice(device.id)
      // 检查租赁记录中的客户名或地址
      return rentals.some(rental => {
        const customerName = rental.customer_name?.toLowerCase() || ''
        const destination = rental.destination?.toLowerCase() || ''
        return customerName.includes(keyword) || destination.includes(keyword)
      })
    })
  }
  return devices
})
```

**防抖处理** (L570-588):
```typescript
const onSearchInput = (value: string) => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    searchKeyword.value = value
  }, 300) // 300ms 防抖
}
```

### 3.6 筛选设备型号功能

**实现文件**: `GanttChart.vue` L108-122

**设备型号筛选器**:
```vue
<el-select
  v-model="selectedDeviceModel"
  placeholder="设备型号"
  clearable
  @change="applyFilters"
>
  <el-option
    v-for="model in availableDeviceModels"
    :key="model"
    :label="model"
    :value="model"
  />
</el-select>
```

**可用型号计算** (L450-461):
```typescript
const availableDeviceModels = computed(() => {
  const models = new Set<string>()
  ganttStore.devices.forEach(device => {
    // 优先使用 device_model.display_name
    if (device.device_model?.display_name) {
      models.add(device.device_model.display_name)
    } else if (device.model && device.model.trim()) {
      models.add(device.model)
    }
  })
  return Array.from(models).sort()
})
```

**型号筛选逻辑** (L503-509):
```typescript
if (selectedDeviceModel.value) {
  devices = devices.filter(device => {
    const deviceModelName = device.device_model?.display_name || device.model
    return deviceModelName === selectedDeviceModel.value
  })
}
```

### 3.7 租赁条目的颜色标记逻辑

**实现文件**: `GanttRow.vue` L325-418

#### 3.7.1 颜色生成算法
```typescript
// L325-344 - 64种预定义颜色
const generateRandomColor = (rentalId: number): string => {
  const colors = [
    '#f44336', '#e91e63', '#9c27b0', '#673ab7', '#3f51b5',
    '#2196f3', '#03a9f4', '#00bcd4', '#009688', '#4caf50',
    // ... 共64个颜色
  ]
  return colors[rentalId % colors.length]  // 按rental ID循环使用
}
```

**颜色的RGBA转换**:
```typescript
const hexToRgba = (hex: string, alpha: number): string => {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}
```

#### 3.7.2 双层条形结构

**外层条**: 跨越 `ship_out_time → ship_in_time` (L354-374)
```typescript
const getShipRangeStyle = (rental: Rental, date: Date) => {
  // 半透明背景，表示物流范围
  return {
    width: `${daysToEnd * 100}%`,
    background: hexToRgba(color, 0.22),      // 22% 透明度背景
    border: `1px solid ${hexToRgba(color, 0.4)}`,  // 40% 透明度边框
  }
}
```

**内层条**: 跨越 `start_date → end_date` (L378-419)
```typescript
const getRentalPeriodStyle = (rental: Rental, date: Date) => {
  // 不透明实色条，表示实际租赁期
  return {
    position: 'absolute',
    background: color,        // 完全不透明的颜色
    borderRadius: '4px',
    display: 'flex',
    alignItems: 'center',
    padding: '0 8px',
    color: 'white',          // 白色字体
    fontSize: '12px',
    overflow: 'hidden',
    // 位置根据相对外层条计算
    left: `${leftPercent}%`,
    width: `${widthPercent}%`,
  }
}
```

#### 3.7.3 状态指示图标
```vue
<!-- L56-58 -->
<span v-if="rental.status === 'shipped'" class="status-icon shipped-icon">🚀</span>
<span v-else-if="rental.status === 'returned'" class="status-icon returned-icon">✅</span>
<span v-else-if="rental.status === 'not_shipped'" class="status-icon">📦</span>
```

**状态映射**:
- `not_shipped` (未发货): 📦 灰色
- `shipped` (已发货): 🚀 蓝色
- `returned` (已返回): ✅ 绿色

#### 3.7.4 设备生命周期颜色样式
```css
/* L539-553 */
.device-cell.device-lifecycle-sold {
  opacity: 0.55;
  border-left: 4px solid #fa8c16 !important;  /* 橙色 */
}

.device-cell.device-lifecycle-damaged {
  opacity: 0.55;
  border-left: 4px solid #eb2f96 !important;  /* 粉色 */
}

.device-cell.device-lifecycle-decommissioned,
.device-cell.device-lifecycle-retired {
  opacity: 0.45;
  border-left: 4px solid #8c8c8c !important;  /* 灰色 */
}
```

**生命周期状态颜色**:
| 状态 | 颜色 | 透明度 | 说明 |
|------|------|-------|------|
| active (使用中) | 绿色 | 100% | 正常使用 |
| sold (已售出) | 橙色 | 55% | 半透明标记 |
| damaged (已损坏) | 粉色 | 55% | 半透明标记 |
| decommissioned (已停用) | 灰色 | 45% | 更深的半透明 |
| retired (已退役) | 灰色 | 45% | 更深的半透明 |

#### 3.7.5 档期冲突警告
```vue
<!-- L69-76 -->
<span
  v-if="rentalConflicts.get(rental.id)?.hasConflict"
  class="conflict-warning-icon"
  @click.stop="showConflictDetails(rental)"
>
  ⚠️
</span>
```

**冲突检测逻辑** (L238-273):
```typescript
const rentalConflicts = computed(() => {
  const conflicts = new Map<number, ConflictInfo>()
  const sortedRentals = [...props.rentals]
    .filter(r => r.status !== 'cancelled')
    .sort((a, b) => dayjs(a.start_date).diff(dayjs(b.start_date)))

  for (let i = 0; i < sortedRentals.length - 1; i++) {
    const current = sortedRentals[i]
    const next = sortedRentals[i + 1]

    // 计算时间间隔
    const endDate = dayjs(current.end_date)
    const nextStartDate = dayjs(next.start_date)
    const hourGap = nextStartDate.diff(endDate, 'hour')

    // 冲突规则:
    // - 时间间隔 ≤ 4天 且位置不在广东 OR
    // - 时间间隔 ≤ 3天 (任意位置)
    const currentHasGuangdong = current.destination?.includes('广东') ?? false
    const nextHasGuangdong = next.destination?.includes('广东') ?? false
    const locationConflict = !currentHasGuangdong || !nextHasGuangdong

    if ((hourGap <= 5*24 && locationConflict) || (hourGap <= 3*24)) {
      conflicts.set(current.id, {
        hasConflict: true,
        nextRentalId: next.id,
        dayGap: hourGap/24-1,
        currentDestination: current.destination,
        nextDestination: next.destination
      })
    }
  }
  return conflicts
})
```

---

## 4. 后端 API 结构

### 4.1 API 路由概览

**文件位置**: `app/routes/` (18个蓝图)

```python
# 路由注册示例
@bp.route('/api/gantt/data')                     # GET 甘特图数据
@bp.route('/api/gantt/daily-stats')              # GET 每日统计
@bp.route('/api/rentals')                        # GET/POST 租赁列表
@bp.route('/api/rentals/<rental_id>')            # GET/PUT/DELETE 单个租赁
@bp.route('/api/rentals/<rental_id>/status')     # PUT 更新租赁状态
@bp.route('/api/rentals/check-conflict')         # POST 检查冲突
@bp.route('/api/devices')                        # GET 设备列表
@bp.route('/api/devices/<device_id>/lifecycle')  # PUT 更新生命周期
@bp.route('/api/device-models')                  # GET 设备型号列表
@bp.route('/api/rentals/search')                 # POST 搜索租赁
@bp.route('/api/rentals/by-ship-date')           # GET 按发货日期查询
```

### 4.2 关键 API 端点

#### 获取甘特图数据
```http
GET /api/gantt/data?start_date=2026-05-24&end_date=2026-06-24
```
**返回**:
```json
{
  "success": true,
  "data": {
    "devices": [
      {
        "id": 1,
        "name": "Sony A7R",
        "serial_number": "SN001",
        "model": "Alpha 7R",
        "device_model": { "id": 1, "display_name": "索尼A7R" },
        "lifecycle_status": "active",
        "rentals": [...]
      }
    ],
    "rentals": [
      {
        "id": 1,
        "device_id": 1,
        "start_date": "2026-05-24",
        "end_date": "2026-05-31",
        "customer_name": "张三",
        "customer_phone": "13800138000",
        "destination": "广东省深圳市",
        "ship_out_time": "2026-05-23 10:00:00",
        "ship_in_time": "2026-06-01 16:00:00",
        "status": "shipped",
        "accessories": [...]
      }
    ]
  }
}
```

#### 获取每日统计
```http
GET /api/gantt/daily-stats?date=2026-05-24&device_model=索尼A7R
```
**返回**:
```json
{
  "success": true,
  "data": {
    "available_count": 3,      # 空闲设备数
    "ship_out_count": 2,       # 待寄出设备数
    "accessory_ship_out_count": 1  # 待寄出附件数
  }
}
```

#### 更新租赁
```http
PUT /web/rentals/<rental_id>
Content-Type: application/json

{
  "device_id": 1,
  "end_date": "2026-05-31",
  "customer_phone": "13800138000",
  "destination": "广东省深圳市",
  "ship_out_time": "2026-05-23 10:00:00",
  "ship_in_time": "2026-06-01 16:00:00",
  "status": "shipped",
  "includes_handle": true,
  "includes_lens_mount": false,
  "accessories": [5, 6, 7],
  "photo_transfer": false
}
```

#### 检查档期冲突
```http
POST /api/rentals/check-conflict
Content-Type: application/json

{
  "device_id": 1,
  "start_date": "2026-05-24",
  "end_date": "2026-05-31",
  "exclude_rental_id": 123  # 可选，编辑时排除自己
}
```
**返回**:
```json
{
  "success": true,
  "data": {
    "has_conflict": false,
    "conflicting_rentals": []
  }
}
```

#### 更新设备生命周期
```http
PUT /api/devices/<device_id>/lifecycle
Content-Type: application/json

{
  "lifecycle_status": "sold",
  "lifecycle_reason": "Equipment sold"
}
```

### 4.3 后端处理器层次

**文件**: `app/handlers/`

```
handlers/
├── rental_handlers.py          # 租赁处理
│   ├── handle_get_rentals()
│   ├── handle_create_rental()
│   ├── handle_update_rental()
│   ├── handle_web_update_rental()
│   ├── handle_delete_rental()
│   ├── handle_check_rental_conflict()
│   └── ...
├── device_handlers.py
├── gantt_handlers.py
└── ...
```

**处理器模式**:
```python
class RentalHandlers:
    @staticmethod
    def handle_get_rentals():
        """业务逻辑处理"""
        return {
            'success': True,
            'data': [...],
            'message': 'OK'
        }
```

---

## 5. E2E 测试框架

### 5.1 测试框架信息

**框架**: Vitest (不是Playwright)
- **类型**: 单元测试 + 集成测试
- **位置**: `frontend/tests/` 和 `tests/`

### 5.2 测试文件位置

```
frontend/tests/
├── unit/
│   ├── rental-types.spec.ts
│   ├── components/
│   │   ├── GanttRow.spec.ts
│   │   ├── RentalBasicForm.spec.ts
│   │   ├── RentalAccessorySelector.spec.ts
│   │   └── RentalShippingForm.spec.ts
│   └── stores/
│       └── gantt.spec.ts
└── integration/
    ├── api-workflow.spec.ts
    ├── gantt-workflow.spec.ts
    ├── store-workflow.spec.ts
    ├── performance.spec.ts
    ├── user-events.spec.ts

tests/  (Python后端)
├── unit/
│   └── test_rental_service.py
└── integration/
    └── test_rental_api.py
```

### 5.3 Vitest 配置

**package.json 脚本**:
```json
{
  "scripts": {
    "test": "vitest",           # 监视模式
    "test:ui": "vitest --ui",   # UI模式
    "test:run": "vitest run",   # 单次运行
    "test:coverage": "vitest run --coverage"
  }
}
```

**依赖**:
```json
{
  "@vitest/ui": "^4.1.6",
  "@vue/test-utils": "^2.4.10",
  "happy-dom": "^20.9.0",
  "vitest": "^4.1.6"
}
```

### 5.4 测试示例

**Gantt Store 单元测试** (gantt.spec.ts):
```typescript
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useGanttStore } from '@/stores/gantt'

describe('Gantt Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('should initialize with empty devices', () => {
    const store = useGanttStore()
    expect(store.devices).toEqual([])
  })

  it('should update device lifecycle status', async () => {
    const store = useGanttStore()
    store.devices = [{ id: 1, lifecycle_status: 'active', ... }]
    
    vi.mocked(axios.put).mockResolvedValueOnce({
      data: { success: true, data: { lifecycle_status: 'sold' } }
    })
    
    await store.updateDeviceLifecycle(1, 'sold')
    expect(store.devices[0].lifecycle_status).toBe('sold')
  })
})
```

---

## 6. 环境配置 (.env)

### 6.1 关键配置项

**数据库配置**:
```env
DATABASE_URL=mysql+pymysql://root:<DB_PASSWORD>@192.168.50.132:33601/inventory_management
```

**云服务配置**:
```env
# 阿里云 OSS
ALIYUN_ACCESS_KEY_ID=<ALIYUN_ACCESS_KEY_ID>
ALIYUN_ACCESS_KEY_SECRET=<ALIYUN_ACCESS_KEY_SECRET>

# 顺丰快递
SF_PARTNER_ID=<SF_PARTNER_ID>
SF_CHECKWORD=<SF_CHECKWORD>
SF_SENDER_NAME=张女士
SF_SENDER_PHONE=<PHONE_NUMBER>
SF_SENDER_ADDRESS=广东省深圳市南山区松坪村 9 栋 4 单元 415
SF_MONTHLY_CARD=<SF_MONTHLY_CARD>

# 闲鱼 API
XIANYU_APP_KEY=<XIANYU_APP_KEY>
XIANYU_APP_SECRET=<XIANYU_APP_SECRET>
XIANYU_API_DOMAIN=open.goofish.pro

# 快麦打印
KUAIMAI_APP_ID=1765586419825
KUAIMAI_APP_SECRET=f3d0d6f376db474284146eee5fc54172
KUAIMAI_PRINTER_SN=KME31W25160089
```

**应用配置**:
```env
FLASK_ENV=development
SECRET_KEY=dev-secret-key-local-development
API_KEY=dev-api-key-local-development
APP_PORT=5001
APP_HOST=0.0.0.0

# 业务配置
DEFAULT_RENTAL_DAYS=7
MAX_RENTAL_DAYS=30
MIN_ADVANCE_BOOKING_DAYS=1
TIMEZONE=Asia/Shanghai

# 数据库连接池
DB_POOL_SIZE=5
DB_POOL_RECYCLE=3600
DB_POOL_PRE_PING=true

# 分页
POSTS_PER_PAGE=20

# 调试
DEBUG=true
SQLALCHEMY_ECHO=true
WTF_CSRF_ENABLED=false
```

---

## 7. 关键文件深度对照表

| 功能 | PC端文件 | 移动端文件 | 后端文件 | 数据库模型 |
|------|---------|----------|---------|----------|
| 甘特图显示 | GanttChart.vue | GanttView.vue | gantt_api.py | Device, Rental |
| 日期统计 | GanttChart.vue (L902-972) | GanttView.vue (L72-85) | /api/gantt/daily-stats | - |
| 预定设备 | BookingDialog.vue | CreateRentalView.vue | rental_api.py POST | Rental |
| 编辑租赁 | EditRentalDialogNew.vue | EditRentalView.vue | rental_api.py PUT | Rental |
| 搜索功能 | GanttChart.vue (L94-106) | - | rental_api.py /search | - |
| 筛选型号 | GanttChart.vue (L108-122) | - | device_model_api.py | DeviceModel |
| 颜色标记 | GanttRow.vue (L325-418) | GanttGrid.vue | - | - |
| 冲突检测 | GanttRow.vue (L238-273) | useConflictDetection.ts | /check-conflict | - |
| 设备状态 | GanttChart.vue (L843-874) | - | device_api.py | Device |
| 虚拟滚动 | GanttChart.vue (L394-533) | GanttGrid.vue | - | - |

---

## 8. 核心业务流程

### 8.1 租赁创建流程
```
前端 (BookingDialog.vue)
  ↓
选择设备 → 检查冲突 → 选择日期
  ↓
POST /api/rentals
  ↓
后端 (rental_handlers.py)
  ↓
RentalService.create_rental()
  ↓
db.session.add(rental) → commit
  ↓
前端 ganttStore.loadData()
  ↓
GET /api/gantt/data
  ↓
刷新甘特图
```

### 8.2 租赁编辑流程
```
点击租赁条 (GanttRow.vue)
  ↓
EditRentalDialogNew.vue 打开
  ↓
加载最新数据 (getRentalById)
  ↓
渲染三个子表单
  ↓
修改数据 + 验证
  ↓
PUT /web/rentals/<rental_id>
  ↓
后端验证 & 保存
  ↓
ganttStore.loadData() 刷新
```

### 8.3 颜色标记流程
```
Rental 记录加载
  ↓
getRandomColor(rental.id) 生成颜色
  ↓
  ├─ 外层条: hexToRgba(color, 0.22) 22%透明
  │
  ├─ 内层条: color 100%不透明
  │
  ├─ 状态图标: 📦/🚀/✅ 根据status
  │
  └─ 冲突警告: ⚠️ 根据档期分析
```

---

## 9. 数据流向总结

### 9.1 前端状态管理 (Pinia)

**gantt.ts 中的主要状态**:
```typescript
// 核心数据
const devices = ref<Device[]>([])      # 设备列表
const rentals = ref<Rental[]>([])      # 租赁列表

// 页面导航
const currentDate = ref(Date)           # 当前显示日期
const selectedDate = ref<Date | null>() # 选中日期

// UI状态
const loading = ref(false)
const error = ref<string | null>()

// 计算属性
const dateRange = computed(...)         # 周期范围
const availableDevices = computed(...)  # 可用设备
```

### 9.2 组件通信模式

**GanttChart.vue** (容器) → 子组件:
```
GanttChart.vue
├── props: selectedDeviceModel
├── emits: edit-rental, delete-rental
│
└─ GanttRow.vue
   ├── props: device, rentals, dates
   ├── emits: update-device-status
   │
   └─ RentalTooltip.vue (异步加载)
```

**EditRentalDialogNew.vue** (容器) → 子组件:
```
EditRentalDialogNew.vue
│
├─ RentalBasicForm.vue          (基础信息)
├─ RentalShippingForm.vue       (物流信息)
├─ RentalAccessorySelector.vue  (附件选择)
└─ RentalActionButtons.vue      (操作按钮)
```

---

## 10. 重要工具函数位置

| 工具函数 | 文件位置 | 用途 |
|---------|---------|------|
| toSystemDateString() | utils/dateUtils.ts | 转换日期为系统格式 |
| formatDisplayDate() | utils/dateUtils.ts | 格式化显示日期 |
| generateDateRange() | utils/dateUtils.ts | 生成日期范围 |
| isToday() | utils/dateUtils.ts | 检查是否今天 |
| extractPhoneNumbers() | utils/phoneExtractor.ts | 提取手机号 |
| generateRandomColor() | GanttRow.vue L325 | 为租赁条生成颜色 |
| hexToRgba() | GanttRow.vue L346 | 十六进制转RGBA |
| checkDeviceConflict() | useConflictDetection.ts | 检查设备冲突 |

---

## 11. 项目亮点特性

### 11.1 性能优化
✅ **虚拟滚动**: 处理大量设备列表  
✅ **缓存机制**: 租赁日期缓存 (rentalDateCache)  
✅ **防抖处理**: 搜索 (300ms)、统计加载 (300ms)  
✅ **异步组件**: RentalTooltip 懒加载  

### 11.2 UI/UX 特性
✅ **64种配色**: 不同租赁自动分配颜色  
✅ **双层条形**: 物流范围 + 实际租赁期  
✅ **实时统计**: 显示每日空闲/待寄出设备数  
✅ **档期冲突警告**: 相邻租赁冲突提示  
✅ **响应式设计**: PC端 + 移动端全覆盖  

### 11.3 数据整合
✅ **多维度搜索**: 客户名、地址、手机号  
✅ **灵活筛选**: 型号、设备类型、生命周期状态  
✅ **配套+库存附件**: 两套附件管理系统  
✅ **物流追踪**: 顺丰+快麦集成  
✅ **闲鱼对接**: 自动同步订单信息  

---

## 总结

这是一个功能完整的二手设备租赁管理系统，前后端分离架构，包含：

- **PC端**: 功能丰富的甘特图管理界面，支持搜索、筛选、编辑、颜色标记
- **移动端**: 轻量化的数据查看和快速操作界面
- **后端**: RESTful API，完整的业务逻辑和数据验证
- **测试**: Vitest 单元 + 集成测试框架
- **部署**: Docker 容器化，支持多环境配置

颜色标记和编辑表单是核心业务逻辑的最佳实践范例。


---

## 12. 移动端前端 (frontend-mobile) 详细解析

### 12.1 架构概述

移动端采用 **Vant UI (Vue3) + TypeScript** 构建，优化移动设备交互体验。通过 **Pinia** 与 PC 端共享状态管理，实现后端 API 复用。

**特点**:
- 轻量化设计，支持触屏交互
- 组件库 Vant 4.9.11（专为移动设计）
- 相对 PC 端功能精简，专注核心操作流程
- 共享后端 API，无需维护两套服务

### 12.2 移动端路由结构

**文件**: `frontend-mobile/src/router/index.ts`

```typescript
Routes:
/ → 重定向到 /gantt
/gantt              (GanttView)        # 甘特图主页 - 租赁查看
/batch-shipping    (BatchShippingView) # 批量发货 - 发货管理
/create-rental     (CreateRentalView)  # 新建租赁 - 创建新记录
/edit-rental/:id   (EditRentalView)    # 编辑租赁 - 修改记录

基础路径: /mobile/
```

### 12.3 核心视图（Views）

#### 12.3.1 甘特图视图 (GanttView.vue)
**功能**: 移动版甘特图 - 显示设备租赁档期和每日统计

**核心特性**:
- **14天滑动窗口**: 默认显示 `today-2` 到 `today+11` 的14天
- **周期导航**: 左右箭头按7天切换窗口
- **每日统计**: 显示日期、空闲设备数、待寄出设备数
- **点击查看**: 点击租赁条弹出底部详情表

**关键代码** (L72-110):
```typescript
const fetchDailyStats = async () => {
  const start = dayjs(windowStart.value)
  const dates = Array.from({ length: DAYS }, (_, i) => 
    start.add(i, 'day').format('YYYY-MM-DD'))
  const results = await Promise.allSettled(
    dates.map(date => axios.get('/api/gantt/daily-stats', { params: { date } }))
  )
  // 聚合每日统计结果
}

const shiftWindow = (days: number) => {
  windowOffset.value += days / 7
  ganttStore.loadData()
  fetchDailyStats()
}
```

**API 调用**: 
- `GET /api/gantt/data` - 获取甘特图数据
- `GET /api/gantt/daily-stats?date=YYYY-MM-DD` - 获取每日统计

#### 12.3.2 批量发货视图 (BatchShippingView.vue)
**功能**: 批量操作发货记录

**核心特性**:
- **日期范围查询**: 按发货时间范围筛选待发货单据
- **状态筛选**: 支持 `全部 / 待发货 / 已预约` 三种筛选
- **批量选择**: 全选/取消全选，支持单项选择
- **批量操作**: 预约发货、打印面单（两种操作）
- **实时禁用**: 已发货/已还租/已完成的订单无法选择

**关键数据结构** (L120-150):
```typescript
const startDate = ref(dayjs().format('YYYY-MM-DD'))
const endDate = ref(dayjs().add(1, 'day').format('YYYY-MM-DD'))
const statusFilter = ref<string>('all')
const rentals = ref<Rental[]>([])
const checkedIds = reactive<Record<number, boolean>>({})

const filteredRentals = computed(() => {
  if (statusFilter.value === 'all') return rentals.value
  return rentals.value.filter(r => r.status === statusFilter.value)
})

const selectedIds = computed(() => 
  Object.entries(checkedIds)
    .filter(([, v]) => v)
    .map(([id]) => Number(id))
)
```

**API 调用**:
- `GET /api/rentals/by-ship-date?start_date=X&end_date=Y` - 按发货日期查询
- `POST /api/shipping-batch/schedule` - 批量预约发货（发送 rental_ids 数组）
- `POST /api/shipping-batch/print-waybills` - 打印面单（发送 rental_ids 数组）

#### 12.3.3 新建租赁视图 (CreateRentalView.vue)
**功能**: 创建新租赁记录，包括设备预订和配件选择

**表单结构** (L260-276):
```typescript
const form = ref({
  xianyuOrderNo: '',        // 闲鱼订单号（可选，可拉取）
  customerName: '',         // 必填
  customerPhone: '',        // 客户电话
  destination: '',          // 收货地址（textarea）
  orderAmount: '',          // 订单金额
  buyerId: '',              // 买家ID
  modelId: null,            // 设备型号ID
  deviceId: null,           // 选中设备ID
  startDate: '',            // 起租日期
  endDate: '',              // 还租日期
  logisticsDays: 1,         // 物流天数（默认1）
  bundledAccessories: [],   // 随机配件：['handle', 'lens_mount']
  phoneHolderId: null,      // 手机支架ID（库存）
  tripodId: null,           // 三脚架ID（库存）
  photoTransfer: false      // 代传照片标志
})
```

**关键特性**:
1. **闲鱼订单拉取** (L424-450): 
   - 输入闲鱼订单号，点击"拉取"按钮
   - 自动填充客户名、电话、地址、订单金额等字段
   - API: `POST /api/rentals/fetch-xianyu-order`

2. **自动计算发货/入库时间** (L329-342):
   ```typescript
   const shipOutDisplay = computed(() => {
     if (!form.value.startDate) return '—'
     return dayjs(form.value.startDate)
       .subtract(form.value.logisticsDays + 1, 'day')
       .format('YYYY-MM-DD')
   })
   ```

3. **地址→手机号自动提取** (L344-350):
   ```typescript
   watch(() => form.value.destination, (val) => {
     if (val && !form.value.customerPhone) {
       const phone = extractPhoneNumber(val)  // 使用 phoneExtractor
       if (phone) form.value.customerPhone = phone
     }
   })
   ```

4. **可用设备自动查询** (L352-384):
   - 监听日期、型号、物流天数变化
   - 自动调用 `ganttStore.findAvailableSlot()` 查询可用设备
   - Picker 中展示可用设备列表

5. **配件选择**:
   - **随机配件** (bundledAccessories): 手柄、镜头座（复选框，bool数组）
   - **库存配件** (inventory): 手机支架、三脚架（Picker选择）
   - 提交时转换为 API 格式

**提交流程** (L453-521):
```typescript
const onSubmit = async () => {
  // 1. 重复租赁检测
  const { hasDuplicate } = await conflictDetection.checkDuplicateRental({
    customerName, destination, startDate, endDate
  })
  
  if (hasDuplicate) {
    // 弹窗确认
    await showConfirmDialog(...)
  }

  // 2. 计算发货/入库时间
  const shipTimes = conflictDetection.calculateShipTimes(
    startDate, endDate, logisticsDays
  )

  // 3. 构建配件数组
  const accessoriesArr: any[] = []
  if (phoneHolderId) accessoriesArr.push({ id: phoneHolderId, is_bundled: false })
  if (tripodId) accessoriesArr.push({ id: tripodId, is_bundled: false })

  // 4. 提交
  const rentalData = {
    device_id, start_date, end_date, customer_name, ...,
    ship_out_time, ship_in_time,
    includes_handle, includes_lens_mount,  // bool字段
    photo_transfer,
    accessories: accessoriesArr             // 库存配件
  }
  
  await ganttStore.createRental(rentalData)
  router.back()
}
```

#### 12.3.4 编辑租赁视图 (EditRentalView.vue)
**功能**: 编辑现有租赁记录

**主要差异**:
- 起租日为**只读**（不可改）
- 还租日可编辑（Picker）
- 设备可换，触发冲突检测 (L431-439, L472-493)
- 发货/入库时间可编辑（自定义日期+时间选择器，L228-277）
- 支持修改配件和代传标志

**冲突检测** (L472-493):
```typescript
const checkDeviceConflict = async () => {
  if (!form.value.deviceId || !form.value.startDate || !form.value.endDate) return
  checkingConflict.value = true
  conflictWarning.value = false
  try {
    const hasConflict = await conflictDetection.checkDeviceConflict({
      deviceId: form.value.deviceId,
      startDate: form.value.startDate,
      endDate: form.value.endDate,
      logisticsDays: form.value.logisticsDays,
      excludeRentalId: rentalId.value  // 排除当前租赁本身
    })
    conflictWarning.value = hasConflict
    if (hasConflict) {
      showToast({ message: '所选设备在该时段有冲突', type: 'fail' })
    }
  } catch {
    // 忽略检测错误
  } finally {
    checkingConflict.value = false
  }
}
```

**提交 API**: `PUT /web/rentals/<rentalId>`

### 12.4 核心组件（Components）

#### 12.4.1 甘特图网格 (GanttGrid.vue)
**功能**: 移动版甘特图表格渲染

**特点**:
- **响应式网格**: 14天固定列宽，自适应设备宽度
- **虚拟行**: 根据设备列表渲染甘特行
- **双层条**: 物流期（22% 半透明）+ 租赁期（100% 实色）
- **点击交互**: 点击租赁条弹出详情

**代码分析**:

1. **颜色生成** (L124-143):
   ```typescript
   const generateRandomColor = (rentalId: number): string => {
     const colors = [ /* 64种颜色 */ ]
     return colors[rentalId % colors.length]  // 确定性选择
   }
   
   const hexToRgba = (hex: string, alpha: number): string => {
     const r = parseInt(hex.slice(1, 3), 16)
     const g = parseInt(hex.slice(3, 5), 16)
     const b = parseInt(hex.slice(5, 7), 16)
     return `rgba(${r}, ${g}, ${b}, ${alpha})`
   }
   ```

2. **物流范围条** (L169-197):
   ```typescript
   const getShipRangeBarStyle = (rental: Rental) => {
     const barStart = rental.ship_out_time ? dayjs(rental.ship_out_time).startOf('day')
                                          : dayjs(rental.start_date).startOf('day')
     const barEnd   = rental.ship_in_time  ? dayjs(rental.ship_in_time).startOf('day')
                                          : dayjs(rental.end_date).startOf('day')
     
     // ... 窗口裁剪逻辑 ...
     
     return {
       left, width,
       background: hexToRgba(color, 0.22),    // 22% 半透明
       border: `1px solid ${hexToRgba(color, 0.4)}`,  // 40% 边框
       zIndex: 1
     }
   }
   ```

3. **租赁期条** (L202-229):
   ```typescript
   const getRentalPeriodBarStyle = (rental: Rental) => {
     const startDate = dayjs(rental.start_date).startOf('day')
     const endDate = dayjs(rental.end_date).startOf('day')
     
     // ... 窗口裁剪逻辑 ...
     
     return {
       left, width,
       background: color,              // 100% 实色
       zIndex: 2
     }
   }
   ```

**样式特性**:
- 设备列固定 54px 宽度
- 日期列百分比宽度（100/14%）
- 租赁条圆角 2px，2px 内边距
- 条形标签超长截断（6px 字体）

#### 12.4.2 批量发货卡片 (BatchShippingCard.vue)
**功能**: 单条发货记录卡片

**布局**:
```
[复选框] 
  设备名 · 客户名        [状态标签]
  📅 2024/05/25  📍 地址（省略号截断18字）
  🎁 运单号: 或 —
```

**状态颜色映射** (L72-81):
```typescript
const STATUS_MAP: Record<string, { label: string; color: string }> = {
  not_shipped:           { label: '待发货',  color: '#ff976a' },   // 橙色
  scheduled_for_shipping: { label: '已预约', color: '#1989fa' },   // 蓝色
  shipped:               { label: '已发货',  color: '#07c160' },   // 绿色
  returned:              { label: '已还租',  color: '#7232dd' },   // 紫色
  completed:             { label: '已完成',  color: '#333' },      // 灰色
  cancelled:             { label: '已取消',  color: '#999' }       // 浅灰
}
```

**交互**:
- 已发货/已还租/已完成状态禁用复选
- 点击卡片切换复选状态（未禁用时）

#### 12.4.3 底部详情表 (RentalBottomSheet.vue)
**功能**: 弹出式租赁详情查看和编辑/删除

**布局**:
```
━━━━━━━━━━━ (拖动把手)
设备名 (标题)
━━━━━━━━━━━
租客     | 值
发货日   | 值
起租日   | 值
还租日   | 值
入库日   | 值
地址     | 值（行限2行）
运单号   | 值
状态     | [标签]
━━━━━━━━━━━
[编辑] [删除]
```

**关键功能**:
- 双向绑定 v-model 控制显隐
- 编辑按钮导航到 `edit-rental` 路由
- 删除前弹窗确认
- 删除成功后触发 `@deleted` 事件，父组件刷新数据

### 12.5 共享服务和工具

#### 12.5.1 冲突检测组合式 (useConflictDetection.ts)

**接口定义**:
```typescript
export interface ConflictCheckParams {
  deviceId: number
  startDate: string | Date
  endDate: string | Date
  logisticsDays?: number
  excludeRentalId?: number
}
```

**核心方法**:

1. **calculateShipTimes** (L19-28):
   ```typescript
   const calculateShipTimes = (startDate, endDate, logisticsDays = 1) => {
     const start = dayjs(startDate)
     const end = dayjs(endDate)
     const shipOutTime = start.subtract(logisticsDays + 1, 'day')
       .hour(9).minute(0).second(0)
     const shipInTime = end.add(logisticsDays + 1, 'day')
       .hour(18).minute(0).second(0)
     return {
       ship_out_time: shipOutTime.format('YYYY-MM-DD HH:mm:ss'),
       ship_in_time: shipInTime.format('YYYY-MM-DD HH:mm:ss')
     }
   }
   ```

2. **checkDeviceConflict** (L30-48):
   - 调用 `POST /api/rentals/check-conflict`
   - 入参: device_id, ship_out_time, ship_in_time, exclude_rental_id
   - 返回: boolean (是否有冲突)

3. **checkDuplicateRental** (L50-76):
   - 调用 `POST /api/rentals/check-duplicate`
   - 检测客户是否在相同时间已有租赁
   - 返回: { hasDuplicate: boolean, duplicates: Rental[] }

#### 12.5.2 手机号提取工具 (phoneExtractor.ts)

**函数**: `extractPhoneNumber(text: string): string`

**正则匹配**: `1[3-9]\d[\s\-]?\d{4}[\s\-]?\d{4}`

**支持格式**:
- 纯数字: `13812345678`
- 带空格: `138 1234 5678`
- 带横杠: `138-1234-5678`

**测试用例** (L38-58):
```typescript
const testCases = [
  { input: '张三 13812345678 北京市朝阳区', expected: '13812345678' },
  { input: '李四，138-1234-5678，上海市浦东新区', expected: '13812345678' },
  { input: '王五 138 1234 5678 广州市天河区', expected: '13812345678' },
  { input: '收件人：赵六\n电话：15912345678\n地址：深圳市南山区', 
    expected: '15912345678' },
  { input: '没有手机号的地址', expected: '' },
  { input: '座机：010-12345678', expected: '' }  // 座机不匹配
]
```

### 12.6 移动端与 PC 端对比

| 特性 | PC 端 (frontend) | 移动端 (frontend-mobile) |
|-----|-----------------|------------------------|
| **UI 框架** | Element Plus | Vant 4 |
| **甘特图** | 完整功能（搜索、筛选、冲突检测） | 简化版（查看为主） |
| **表单** | 3层组件分离（Basic/Shipping/Accessor） | 单个表单（Form组件组织） |
| **设备列表** | 虚拟滚动 + 搜索 + 多维度筛选 | 无额外筛选，依赖 Picker |
| **发货管理** | 不存在对应视图 | **专门的批量发货页面** |
| **交互模式** | 鼠标 + 键盘 | 触屏 + Picker 弹窗 |
| **附件管理** | 直观选择器（复选框+下拉） | 多个 Picker 弹窗（mobile友好） |
| **物流时间** | 自动计算（基于型号物流天数） | 手动选择日期+时间 |
| **API 数据流** | 共用后端 | 共用后端 |
| **状态管理** | Pinia (gantt.ts) | 共享相同 Pinia store |

### 12.7 移动端 API 端点总结

| 端点 | 方法 | 用途 |
|-----|------|------|
| `/api/gantt/data` | GET | 获取甘特图数据 |
| `/api/gantt/daily-stats` | GET | 获取每日统计（date 参数） |
| `/api/rentals` | GET, POST | 获取/创建租赁 |
| `/api/rentals/<id>` | GET, PUT, DELETE | 单条操作 |
| `/api/rentals/by-ship-date` | GET | 按发货日期范围查询 |
| `/api/rentals/check-conflict` | POST | 检查设备冲突 |
| `/api/rentals/check-duplicate` | POST | 检查重复租赁 |
| `/api/rentals/fetch-xianyu-order` | POST | 拉取闲鱼订单 |
| `/api/shipping-batch/schedule` | POST | 批量预约发货 |
| `/api/shipping-batch/print-waybills` | POST | 打印面单 |
| `/api/device-models` | GET | 获取设备型号列表 |
| `/api/devices?is_accessory=true` | GET | 获取附件设备列表 |
| `/api/shipping/track/<trackingNo>` | GET | 查询物流状态 |

### 12.8 移动端开发小贴士

1. **Picker 交互**: 所有单选/多选都使用 van-popup + van-picker (mobile friendly)
2. **日期处理**: 使用 van-date-picker，返回 [yyyy, MM, DD] 数组
3. **表单验证**: van-form 自动处理验证规则（:rules 属性）
4. **异步操作**: 使用 showToast/showConfirmDialog 进行用户反馈
5. **虚拟滚动**: 列表中的 van-loading 和 van-empty 处理空状态
6. **性能**: 避免在模板中调用方法，使用 computed 代替
7. **路由**: 后退时用 router.back()，响应式导航用 router.push()


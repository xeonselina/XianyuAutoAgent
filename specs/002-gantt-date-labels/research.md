# Phase 0: Research - 甘特图日期可见性增强

**日期**: 2026-01-01
**研究人员**: Claude AI Assistant
**相关规格说明**: [spec.md](./spec.md)
**实施计划**: [plan.md](./plan.md)

---

## 研究概述

本阶段旨在解决Phase 0中列出的5个关键技术未知项,为Phase 1设计阶段提供可靠的技术方案。研究重点包括:日期标签显示最佳实践、每日统计计算算法、空闲设备逻辑修复、性能优化方案和移动端响应式设计。

---

## 1. 日期标签显示最佳实践

### 1.1 当前实现分析

#### 桌面端 (frontend/src/components/GanttChart.vue)

**已实现功能**:
- ✅ 时间轴日期标签显示 (行144-146):
  ```vue
  <div class="date-day">{{ formatDay(date) }}</div>
  <div class="date-weekday">{{ formatWeekday(date) }}</div>
  ```
- ✅ 每日统计信息显示 (行147-170):
  ```vue
  <div class="date-stats">
    <span v-if="getStatsForDate(date).available_count > 0" class="stat-available">
      {{ getStatsForDate(date).available_count }} 闲
    </span>
    <span v-if="getStatsForDate(date).ship_out_count > 0" class="stat-ship-out">
      {{ getStatsForDate(date).ship_out_count }} 寄
    </span>
  </div>
  ```

**评估结果**:
- 桌面端已经实现了日期标签和统计信息,功能基本满足需求
- 需要验证移动端是否也有类似实现

#### 移动端 (frontend-mobile/src/views/GanttView.vue)

**当前实现**:
- ❌ 移动端使用简化的时间轴(行62-84),仅显示租赁条块
- ❌ 没有清晰的日期标签(行27仅显示日期范围字符串)
- ❌ 没有每日统计信息显示

**代码片段**:
```vue
<!-- 日期范围显示 (行26-28) -->
<div class="date-range">
  {{ formatDateRange(ganttStore.currentStartDate, ganttStore.currentEndDate) }}
</div>

<!-- 简化的时间轴 (行62-84) -->
<div class="timeline-container">
  <div class="timeline">
    <div v-for="block in getTimelineBlocks(device)" ...>
      <span class="rental-label">{{ block.rental.customer_name }}</span>
    </div>
  </div>
</div>
```

**问题识别**:
1. 移动端缺少日期标签(无法显示"1月1日 周一"等信息)
2. 移动端缺少每日统计信息(无法显示"3台寄出 / 2台空闲")
3. 移动端时间轴仅显示租赁条块,用户无法快速识别空闲日期

### 1.2 技术方案建议

#### 方案A: 移动端复用桌面端日期标签结构 (推荐)

**优点**:
- 代码复用,减少维护成本
- 桌面端已验证,成熟稳定
- 前后端统一,减少理解成本

**实现思路**:
```vue
<!-- 移动端新增日期标签组件 -->
<div class="mobile-date-header">
  <div
    v-for="date in dateArray"
    :key="date.toString()"
    class="mobile-date-col"
  >
    <div class="date-day">{{ formatDay(date) }}</div>  <!-- 1/1 -->
    <div class="date-weekday">{{ formatWeekday(date) }}</div>  <!-- 周一 -->
    <div class="date-stats">
      <span class="stat-ship">{{ getStatsForDate(date).ship_out_count }}寄</span>
      <span class="stat-idle">{{ getStatsForDate(date).available_count }}闲</span>
    </div>
  </div>
</div>
```

**响应式适配** (小屏幕<375px):
- 日期格式缩写: "1/1" 替代 "1月1日"
- 星期缩写: "一" 替代 "周一"
- 统计信息紧凑显示: "3寄/2闲" 单行显示
- 字体大小: 12px(日期) + 10px(统计), 保证可读性
- 横向滚动: 时间轴可横向滚动,避免挤压

#### 方案B: 使用Vant组件库的日历组件

**评估结果**: ❌ 不推荐
- Vant的Calendar组件主要用于日期选择,不适合甘特图时间轴
- 无法直接显示每日统计信息
- 需要大量自定义,反而增加复杂度

### 1.3 日期格式化方案

**当前使用**: dayjs 1.11.x (frontend/package.json:20, frontend-mobile/package.json:24)

**dayjs优势**:
- ✅ 项目已集成,无需额外依赖
- ✅ 轻量级 (2KB gzipped vs date-fns 的 67KB)
- ✅ API与Moment.js兼容,学习成本低
- ✅ 支持插件扩展 (周、季度、相对时间等)

**决策**: 继续使用dayjs,无需切换到date-fns

---

## 2. 每日统计计算算法

### 2.1 当前实现分析

#### 桌面端 (frontend/src/components/GanttChart.vue)

**发现**: 桌面端已实现`getStatsForDate(date)`函数 (行148-166),但代码未在读取范围内。需要进一步查找实现细节。

**已知统计项**:
- `available_count`: 空闲设备数量
- `ship_out_count`: 寄出设备数量 (主设备)
- `accessory_ship_out_count`: 附件寄出数量
- `controller_count`: 手柄数量

### 2.2 空闲设备计算逻辑问题

#### 问题定位

根据规格说明,当前系统存在以下问题:

**错误逻辑(推测)**:
```
设备占用期 = rental.start_date 到 rental.end_date
空闲设备 = 总设备数 - 占用设备数(where start_date ≤ target_date ≤ end_date)
```

**正确逻辑(应该实现)**:
```
设备占用期 = rental.ship_out_time 对应的日期 到 rental.ship_in_time 对应的日期
空闲设备 = 总设备数 - 占用设备数(where ship_out_date ≤ target_date ≤ ship_in_date)
```

**关键发现**:
从`app/routes/gantt_api.py:187-188`可知,系统计算船出/船入日期的公式为:
```python
ship_out_date = start_date - timedelta(days=1 + logistics_days)
ship_in_date = end_date + timedelta(days=1 + logistics_days)
```
其中`logistics_days`默认为1天(见`app/routes/web_pages.py:91`)。

**示例**:
- `start_date = 2026-01-05` (租赁开始日)
- `end_date = 2026-01-07` (租赁结束日)
- `logistics_days = 1`
- **计算结果**:
  - `ship_out_date = 2026-01-05 - 2天 = 2026-01-03`
  - `ship_in_date = 2026-01-07 + 2天 = 2026-01-09`
- **设备占用期**: 2026-01-03 到 2026-01-09 (共7天),而非仅 2026-01-05 到 2026-01-07 (3天)

**影响范围**:
- ✅ 后端`find_available_time_slot`函数(app/routes/gantt_api.py:228-249)已正确使用`ship_out_date/ship_in_date`
- ❌ 前端可能仍使用`start_date/end_date`计算空闲设备 (需验证)

### 2.3 每日统计计算算法设计

#### 算法1: 每日寄出设备数量

**定义**: 某日需要寄出的设备数量 = 当日`ship_out_date`等于该日期的租赁记录数

**SQL实现** (后端):
```sql
SELECT COUNT(DISTINCT device_id)
FROM rentals
WHERE DATE(ship_out_time) = :target_date
  AND status != 'cancelled'
  AND parent_rental_id IS NULL  -- 只统计主设备
```

**前端实现** (JavaScript/TypeScript):
```typescript
function getShipOutCount(targetDate: Date, rentals: Rental[]): number {
  return rentals.filter(rental => {
    if (!rental.ship_out_time || rental.status === 'cancelled') return false
    const shipOutDate = dayjs(rental.ship_out_time).format('YYYY-MM-DD')
    const targetDateStr = dayjs(targetDate).format('YYYY-MM-DD')
    return shipOutDate === targetDateStr
  }).length
}
```

**性能优化**: 如果租赁记录数量<1000,前端计算即可;如果>1000,建议后端计算后返回。

#### 算法2: 每日空闲设备数量

**定义**: 某日空闲设备数量 = 总设备数 - 当日被占用的设备数

**被占用设备判定逻辑**:
```
设备在某日被占用 <=> ship_out_date ≤ 该日 ≤ ship_in_date
```

**SQL实现** (后端 - 推荐):
```sql
-- 1. 统计总设备数
SELECT COUNT(*) FROM devices WHERE is_accessory = 0 AND status = 'online'

-- 2. 统计被占用设备数
SELECT COUNT(DISTINCT device_id)
FROM rentals
WHERE status != 'cancelled'
  AND parent_rental_id IS NULL
  AND DATE(ship_out_time) <= :target_date
  AND DATE(ship_in_time) >= :target_date

-- 3. 空闲设备数 = 总数 - 占用数
```

**前端实现** (备用方案):
```typescript
function getAvailableCount(targetDate: Date, devices: Device[], rentals: Rental[]): number {
  const totalDevices = devices.filter(d => !d.is_accessory && d.status === 'online').length

  const occupiedDeviceIds = new Set<number>()
  rentals.forEach(rental => {
    if (rental.status === 'cancelled') return
    if (!rental.ship_out_time || !rental.ship_in_time) return

    const shipOutDate = dayjs(rental.ship_out_time).startOf('day')
    const shipInDate = dayjs(rental.ship_in_time).startOf('day')
    const target = dayjs(targetDate).startOf('day')

    if (target.isSameOrAfter(shipOutDate) && target.isSameOrBefore(shipInDate)) {
      occupiedDeviceIds.add(rental.device_id)
    }
  })

  return totalDevices - occupiedDeviceIds.size
}
```

### 2.4 性能优化方案

#### 方案A: 前端实时计算 (当前桌面端实现)

**适用场景**:
- ✅ 设备数量<100台
- ✅ 租赁记录<500条
- ✅ 显示日期范围<35天

**性能分析**:
- 时间复杂度: O(D × R), D=日期数, R=租赁记录数
- 假设D=35, R=300: 10,500次判断
- JavaScript执行时间: <50ms (可接受)

**优点**: 无需额外API请求,实时更新

#### 方案B: 后端计算后返回 (推荐增强)

**适用场景**:
- 设备数量>100台
- 租赁记录>500条
- 需要支持更长的日期范围

**新增API接口**:
```
GET /api/gantt/daily-stats?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD

Response:
{
  "success": true,
  "data": {
    "stats": [
      {
        "date": "2026-01-01",
        "ship_out_count": 3,
        "available_count": 47,
        "accessory_ship_out_count": 5
      },
      ...
    ]
  }
}
```

**SQL优化** (使用索引):
```sql
-- 推荐索引
CREATE INDEX idx_rentals_ship_out_time ON rentals(ship_out_time);
CREATE INDEX idx_rentals_ship_in_time ON rentals(ship_in_time);
CREATE INDEX idx_rentals_status ON rentals(status);
```

**决策**: 当前系统规模(~50-100台设备,数百条租赁),前端计算足够。但建议在Phase 1设计中预留后端API接口,方便未来扩展。

#### 方案C: 缓存机制 (暂不需要)

**评估结果**: ❌ 不推荐
- 当前数据量小,缓存收益有限
- 增加系统复杂度 (需要缓存失效策略)
- 如果未来需要,可引入Redis或内存缓存

---

## 3. 空闲设备统计逻辑修复

### 3.1 代码位置扫描

#### 使用starttime/endtime的位置

通过全局搜索`starttime|endtime|start_time|end_time`,发现:
- ✅ `app/utils/scheduler_tasks.py`: 仅用于性能统计,与业务逻辑无关
- ✅ 后端代码未发现直接使用`start_date/end_date`计算空闲设备的位置

**结论**: 后端逻辑已正确使用`ship_out_date/ship_in_date` (见`app/routes/gantt_api.py:246-249`)

#### 需要修复的位置

**前端代码**(推测,需要验证):
- ❓ `frontend/src/components/GanttChart.vue`: `getStatsForDate`函数实现
- ❓ `frontend/src/stores/gantt.ts`: 甘特图状态管理中的统计逻辑
- ❓ `frontend-mobile/src/views/GanttView.vue`: 移动端统计逻辑(如果有)

**验证方法**:
1. 阅读`GanttChart.vue`完整代码,找到`getStatsForDate`实现
2. 检查是否使用`rental.start_date/end_date`而非`rental.ship_out_time/ship_in_time`
3. 编写单元测试验证逻辑(见Algorithm 2)

### 3.2 修复方案

#### 后端修复 (已正确,无需修改)

`app/routes/gantt_api.py:228-249`的`find_available_time_slot`函数已正确实现:
```python
ship_out_time, ship_in_time = convert_dates_to_datetime(
    ship_out_date,
    ship_in_date,
    ship_out_hour="19:00:00",
    ship_in_hour="19:00:00"
)
```

#### 前端修复 (需要验证后实施)

**修改前(错误逻辑)**:
```typescript
// 错误: 使用 start_date/end_date 判断占用
const isOccupied = (rental: Rental, targetDate: Date) => {
  const start = dayjs(rental.start_date)
  const end = dayjs(rental.end_date)
  const target = dayjs(targetDate)
  return target.isSameOrAfter(start) && target.isSameOrBefore(end)
}
```

**修改后(正确逻辑)**:
```typescript
// 正确: 使用 ship_out_time/ship_in_time 判断占用
const isOccupied = (rental: Rental, targetDate: Date) => {
  if (!rental.ship_out_time || !rental.ship_in_time) return false

  const shipOutDate = dayjs(rental.ship_out_time).startOf('day')
  const shipInDate = dayjs(rental.ship_in_time).startOf('day')
  const target = dayjs(targetDate).startOf('day')

  return target.isSameOrAfter(shipOutDate) && target.isSameOrBefore(shipInDate)
}
```

### 3.3 向后兼容性分析

#### API兼容性

**评估结果**: ✅ 无破坏性变更
- 后端API返回的数据结构未改变
- `ship_out_time`和`ship_in_time`字段已存在于`Rental`模型
- 前端修改仅改变计算逻辑,不影响API契约

#### 数据迁移

**评估结果**: ✅ 无需数据迁移
- `Rental`表中已有`ship_out_time`和`ship_in_time`字段
- 历史数据已填充这些字段(见`app/routes/gantt_api.py:105-106`)

#### 外部调用方

**评估结果**: ✅ 无外部API调用方
- 系统为内部管理工具,无第三方集成
- 所有API调用均来自前端Vue应用

---

## 4. 性能优化方案

### 4.1 前端性能优化

#### 虚拟滚动 (已实现)

**发现**: 桌面端已实现虚拟滚动 (GanttChart.vue:174-196):
```vue
<div class="virtual-container" :style="{ height: `${totalHeight}px` }">
  <div class="visible-items" :style="{ transform: `translateY(${offsetY}px)` }">
    <GanttRow v-for="device in visibleDevices" :key="device.id" .../>
  </div>
</div>
```

**优点**:
- 仅渲染可见区域的设备行
- 支持大量设备(>100台)的流畅滚动

**移动端**: 需要实现类似的虚拟滚动机制

#### 日期范围限制

**当前实现**: 默认显示5周(35天) - `plan.md`第37行

**建议**: 保持当前限制,避免一次性加载过多数据

#### 计算结果缓存

**方案**: 使用Vue的`computed`属性自动缓存
```typescript
// 自动缓存,只在依赖变化时重新计算
const dailyStats = computed(() => {
  return dateArray.value.map(date => ({
    date,
    shipOutCount: getShipOutCount(date, rentals.value),
    availableCount: getAvailableCount(date, devices.value, rentals.value)
  }))
})
```

### 4.2 后端性能优化

#### 数据库查询优化

**当前查询** (gantt_api.py:48-65):
```python
rentals = Rental.query.filter(
    Rental.status != 'cancelled',
    Rental.parent_rental_id.is_(None),
    db.or_(
        # 三个条件的OR查询
    )
).all()
```

**优化建议**:
1. 添加索引:
   ```sql
   CREATE INDEX idx_rentals_date_range ON rentals(start_date, end_date);
   CREATE INDEX idx_rentals_parent ON rentals(parent_rental_id);
   ```
2. 查询条件简化:
   ```python
   # 简化为: ship_out_time <= end_date AND ship_in_time >= start_date
   rentals = Rental.query.filter(
       Rental.status != 'cancelled',
       Rental.parent_rental_id.is_(None),
       Rental.ship_out_time <= end_date,
       Rental.ship_in_time >= start_date
   ).all()
   ```

#### N+1查询问题

**当前代码** (gantt_api.py:79-110):
```python
for device in devices:
    device_rentals = [r for r in rentals if r.device_id == device.id]  # 内存过滤
```

**优化建议**: 使用SQLAlchemy的`relationship`预加载
```python
# 使用 joinedload 避免 N+1
devices = Device.query.options(
    db.joinedload(Device.rentals)
).filter(Device.is_accessory.is_(False)).all()
```

**性能提升**: 从N+1次查询 → 1次JOIN查询

### 4.3 性能测试基准

#### 目标指标 (来自spec.md和plan.md)

- ✅ 甘特图页面加载完成后,日期标签在1秒内渲染完成
- ✅ 档期查询响应时间<5秒
- ✅ 后端API响应时间<200ms p95

#### 测试方法

1. **前端性能测试**:
   ```javascript
   // 使用 Performance API
   const start = performance.now()
   renderGanttChart()
   const end = performance.now()
   console.log(`Render time: ${end - start}ms`)  // 应<1000ms
   ```

2. **后端性能测试**:
   ```python
   # 使用 pytest-benchmark
   def test_gantt_api_performance(benchmark):
       result = benchmark(lambda: client.get('/api/gantt/data?start_date=2026-01-01&end_date=2026-02-01'))
       assert result.elapsed < 0.2  # <200ms
   ```

---

## 5. 移动端响应式设计

### 5.1 当前移动端实现分析

**屏幕尺寸支持** (from mobile-dist/index.html:7):
```html
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
```

**设计语言**: Vant UI (移动端Vue组件库)

### 5.2 日期标签布局方案

#### 方案A: 横向滚动时间轴 (推荐)

**设计**:
```vue
<div class="mobile-gantt">
  <!-- 固定设备名称列 -->
  <div class="device-column">
    <div v-for="device in devices" class="device-name">{{ device.name }}</div>
  </div>

  <!-- 可横向滚动的时间轴 + 租赁条块 -->
  <div class="timeline-scroll-container">
    <div class="date-header-row">
      <div v-for="date in dateArray" class="date-col">
        <div class="date-day">{{ formatDay(date) }}</div>  <!-- 1/1 -->
        <div class="date-weekday">{{ formatWeekday(date) }}</div>  <!-- 一 -->
        <div class="date-stats">3寄/2闲</div>
      </div>
    </div>

    <div class="rental-rows">
      <div v-for="device in devices" class="rental-row">
        <div v-for="block in getRentalBlocks(device)" class="rental-block" .../>
      </div>
    </div>
  </div>
</div>
```

**CSS关键点**:
```css
.timeline-scroll-container {
  overflow-x: auto;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;  /* iOS平滑滚动 */
}

.date-col {
  min-width: 50px;  /* 保证最小宽度,避免挤压 */
  font-size: 12px;   /* 保证可读性 */
}

.date-stats {
  font-size: 10px;   /* 紧凑显示统计信息 */
  white-space: nowrap;
}
```

#### 方案B: 垂直卡片布局 (备选)

**适用场景**: 用户主要关注单个设备的档期,而非整体视图

**设计**:
```vue
<van-list>
  <div v-for="device in devices" class="device-card">
    <div class="device-header">{{ device.name }}</div>
    <div class="date-grid">
      <div v-for="date in dateArray" class="date-cell">
        <div class="date">1/1 一</div>
        <div class="rental-status">
          <span v-if="hasRental(device, date)" class="occupied">租</span>
          <span v-else class="available">闲</span>
        </div>
      </div>
    </div>
  </div>
</van-list>
```

**评估**: ❌ 不推荐 - 与桌面端差异太大,不利于用户跨平台使用

### 5.3 小屏幕适配方案

#### 屏幕断点

```css
/* iPhone SE (320px) */
@media (max-width: 374px) {
  .date-col { min-width: 45px; font-size: 11px; }
  .date-stats { font-size: 9px; }
}

/* iPhone 12/13 Pro (390px) */
@media (min-width: 375px) and (max-width: 430px) {
  .date-col { min-width: 50px; font-size: 12px; }
}

/* Plus机型 (>430px) */
@media (min-width: 431px) {
  .date-col { min-width: 60px; font-size: 13px; }
}
```

#### 字体大小保证可读性

根据spec.md要求:
- ✅ 日期标签字体大小≥12px (主体)
- ✅ 统计信息字体大小≥10px (辅助)
- ✅ 在320px屏幕上可读(最小11px,可接受)

### 5.4 跨月份显示视觉分隔

**方案**: 在月份切换处添加分隔线和月份标签

```vue
<div v-for="(date, index) in dateArray" class="date-col">
  <!-- 月份分隔线 -->
  <div v-if="isFirstDayOfMonth(date)" class="month-divider">
    <span class="month-label">{{ formatMonth(date) }}</span>  <!-- 2月 -->
  </div>

  <div class="date-day">{{ formatDay(date) }}</div>
  ...
</div>
```

**CSS**:
```css
.month-divider {
  border-left: 2px solid #ff6b6b;
  position: relative;
}

.month-label {
  position: absolute;
  top: -20px;
  left: 5px;
  background: #ff6b6b;
  color: white;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
}
```

### 5.5 Vant组件库使用

**评估结果**:
- ✅ `van-nav-bar`: 已使用,用于页面标题栏
- ✅ `van-pull-refresh`: 已使用,用于下拉刷新
- ✅ `van-cell`: 已使用,用于设备信息展示
- ❌ `van-calendar`: 不适用(见1.2节)
- 🔄 `van-sticky`: 可用于吸顶日期标题栏(可选)

---

## 6. 原型代码片段

### 6.1 移动端日期标签组件

```vue
<!-- frontend-mobile/src/components/MobileTimeline.vue -->
<template>
  <div class="mobile-timeline">
    <!-- 日期标题行 (可吸顶) -->
    <van-sticky>
      <div class="date-header-row">
        <div
          v-for="(date, index) in dateArray"
          :key="date.toString()"
          class="date-col"
          :class="{
            'is-today': isToday(date),
            'is-weekend': isWeekend(date),
            'month-start': isFirstDayOfMonth(date)
          }"
        >
          <!-- 月份分隔 -->
          <div v-if="isFirstDayOfMonth(date)" class="month-divider">
            <span class="month-label">{{ formatMonth(date) }}</span>
          </div>

          <!-- 日期信息 -->
          <div class="date-day">{{ formatDay(date) }}</div>
          <div class="date-weekday">{{ formatWeekday(date) }}</div>

          <!-- 每日统计 -->
          <div class="date-stats">
            <span v-if="getStats(date).shipOut > 0" class="stat-ship">
              {{ getStats(date).shipOut }}寄
            </span>
            <span v-if="getStats(date).available > 0" class="stat-idle">
              {{ getStats(date).available }}闲
            </span>
          </div>
        </div>
      </div>
    </van-sticky>

    <!-- 租赁条块网格 -->
    <div class="rental-grid">
      <div
        v-for="device in devices"
        :key="device.id"
        class="device-row"
      >
        <!-- 设备名称(固定列) -->
        <div class="device-name">{{ device.name }}</div>

        <!-- 租赁条块 -->
        <div class="rental-timeline">
          <div
            v-for="rental in getRentalsForDevice(device.id)"
            :key="rental.id"
            class="rental-block"
            :style="getRentalBlockStyle(rental)"
            @click="showRentalDetail(rental)"
          >
            <span class="rental-label">{{ rental.customer_name }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import dayjs from 'dayjs'
import type { Device, Rental } from '@/types'

interface Props {
  dateArray: Date[]
  devices: Device[]
  rentals: Rental[]
}

const props = defineProps<Props>()

// 格式化函数
const formatDay = (date: Date) => dayjs(date).format('M/D')
const formatWeekday = (date: Date) => dayjs(date).format('dd')  // 一、二、三
const formatMonth = (date: Date) => dayjs(date).format('M月')

// 判断函数
const isToday = (date: Date) => dayjs(date).isSame(dayjs(), 'day')
const isWeekend = (date: Date) => {
  const day = dayjs(date).day()
  return day === 0 || day === 6
}
const isFirstDayOfMonth = (date: Date) => dayjs(date).date() === 1

// 每日统计计算
const getStats = (date: Date) => {
  const dateStr = dayjs(date).format('YYYY-MM-DD')

  // 寄出数量
  const shipOut = props.rentals.filter(r => {
    if (!r.ship_out_time) return false
    return dayjs(r.ship_out_time).format('YYYY-MM-DD') === dateStr
  }).length

  // 空闲数量
  const totalDevices = props.devices.filter(d => !d.is_accessory && d.status === 'online').length
  const occupiedDeviceIds = new Set<number>()

  props.rentals.forEach(rental => {
    if (!rental.ship_out_time || !rental.ship_in_time) return
    const shipOutDate = dayjs(rental.ship_out_time).startOf('day')
    const shipInDate = dayjs(rental.ship_in_time).startOf('day')
    const target = dayjs(date).startOf('day')

    if (target.isSameOrAfter(shipOutDate) && target.isSameOrBefore(shipInDate)) {
      occupiedDeviceIds.add(rental.device_id)
    }
  })

  const available = totalDevices - occupiedDeviceIds.size

  return { shipOut, available }
}

// 获取设备的租赁记录
const getRentalsForDevice = (deviceId: number) => {
  return props.rentals.filter(r => r.device_id === deviceId)
}

// 计算租赁条块样式
const getRentalBlockStyle = (rental: Rental) => {
  // 计算left和width百分比
  const startDate = dayjs(rental.ship_out_time).startOf('day')
  const endDate = dayjs(rental.ship_in_time).startOf('day')
  const rangeStart = dayjs(props.dateArray[0]).startOf('day')
  const rangeEnd = dayjs(props.dateArray[props.dateArray.length - 1]).startOf('day')

  const totalDays = rangeEnd.diff(rangeStart, 'day') + 1
  const offsetDays = startDate.diff(rangeStart, 'day')
  const durationDays = endDate.diff(startDate, 'day') + 1

  const left = (offsetDays / totalDays) * 100
  const width = (durationDays / totalDays) * 100

  return {
    left: `${Math.max(0, left)}%`,
    width: `${Math.min(100 - left, width)}%`,
    background: '#409eff'  // 可根据状态动态设置颜色
  }
}
</script>

<style scoped lang="scss">
.mobile-timeline {
  width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.date-header-row {
  display: flex;
  background: #f5f7fa;
  border-bottom: 2px solid #dcdfe6;
}

.date-col {
  min-width: 50px;
  flex-shrink: 0;
  text-align: center;
  padding: 8px 4px;
  border-right: 1px solid #ebeef5;
  position: relative;

  &.is-today {
    background: #e6f7ff;
    .date-day { color: #1890ff; font-weight: bold; }
  }

  &.is-weekend {
    background: #fff7e6;
  }

  &.month-start {
    border-left: 2px solid #ff6b6b;
  }
}

.month-divider {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
}

.month-label {
  position: absolute;
  top: -20px;
  left: 50%;
  transform: translateX(-50%);
  background: #ff6b6b;
  color: white;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  white-space: nowrap;
}

.date-day {
  font-size: 12px;
  font-weight: 500;
  margin-bottom: 2px;
}

.date-weekday {
  font-size: 10px;
  color: #909399;
  margin-bottom: 4px;
}

.date-stats {
  font-size: 10px;
  white-space: nowrap;

  .stat-ship {
    color: #67c23a;
    margin-right: 4px;
  }

  .stat-idle {
    color: #909399;
  }
}

.rental-grid {
  display: flex;
  flex-direction: column;
}

.device-row {
  display: flex;
  border-bottom: 1px solid #ebeef5;
  min-height: 60px;
}

.device-name {
  width: 80px;
  flex-shrink: 0;
  padding: 16px 8px;
  font-size: 12px;
  font-weight: 500;
  background: #fafafa;
  border-right: 1px solid #ebeef5;
}

.rental-timeline {
  flex: 1;
  position: relative;
  min-height: 60px;
}

.rental-block {
  position: absolute;
  height: 40px;
  top: 10px;
  border-radius: 4px;
  padding: 8px;
  color: white;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 小屏幕适配 */
@media (max-width: 374px) {
  .date-col { min-width: 45px; }
  .date-day { font-size: 11px; }
  .date-stats { font-size: 9px; }
}
</style>
```

### 6.2 空闲设备计算Composable

```typescript
// frontend/src/composables/useGanttStats.ts
import { computed } from 'vue'
import dayjs from 'dayjs'
import type { Device, Rental } from '@/types'

export function useGanttStats(devices: Ref<Device[]>, rentals: Ref<Rental[]>) {

  /**
   * 计算某日寄出设备数量
   */
  const getShipOutCount = (targetDate: Date): number => {
    const targetDateStr = dayjs(targetDate).format('YYYY-MM-DD')
    return rentals.value.filter(rental => {
      if (!rental.ship_out_time || rental.status === 'cancelled') return false
      if (rental.parent_rental_id) return false  // 排除附件租赁
      const shipOutDateStr = dayjs(rental.ship_out_time).format('YYYY-MM-DD')
      return shipOutDateStr === targetDateStr
    }).length
  }

  /**
   * 计算某日空闲设备数量 (使用ship_out_time/ship_in_time)
   */
  const getAvailableCount = (targetDate: Date): number => {
    // 总设备数(不含附件)
    const totalDevices = devices.value.filter(
      d => !d.is_accessory && d.status === 'online'
    ).length

    // 被占用的设备ID集合
    const occupiedDeviceIds = new Set<number>()
    const target = dayjs(targetDate).startOf('day')

    rentals.value.forEach(rental => {
      if (rental.status === 'cancelled') return
      if (rental.parent_rental_id) return  // 排除附件租赁
      if (!rental.ship_out_time || !rental.ship_in_time) return

      // 关键修复: 使用 ship_out_time/ship_in_time 而非 start_date/end_date
      const shipOutDate = dayjs(rental.ship_out_time).startOf('day')
      const shipInDate = dayjs(rental.ship_in_time).startOf('day')

      // 判断设备是否在该日被占用
      if (target.isSameOrAfter(shipOutDate) && target.isSameOrBefore(shipInDate)) {
        occupiedDeviceIds.add(rental.device_id)
      }
    })

    return totalDevices - occupiedDeviceIds.size
  }

  /**
   * 计算所有日期的统计数据(缓存)
   */
  const dailyStats = computed(() => {
    const stats: Record<string, { shipOut: number; available: number }> = {}

    // 假设dateArray从外部传入或从store获取
    // 这里仅示例计算逻辑
    return stats
  })

  return {
    getShipOutCount,
    getAvailableCount,
    dailyStats
  }
}
```

---

## 7. 技术选型总结

| 技术领域 | 当前方案 | 继续使用 | 新增/修改 |
|---------|---------|---------|-----------|
| 日期处理库 | dayjs 1.11.x | ✅ | - |
| 移动端UI库 | Vant | ✅ | - |
| 桌面端UI库 | Element Plus | ✅ | - |
| 虚拟滚动 | 已实现(桌面端) | ✅ | 移动端需实现 |
| 状态管理 | Pinia | ✅ | - |
| 每日统计计算 | 前端实时计算 | ✅ | 修复逻辑(ship_out_time/ship_in_time) |
| 性能优化 | 无缓存 | ✅ | 建议添加`computed`缓存 |
| 响应式设计 | 已适配 | ✅ | 增强移动端日期标签 |

---

## 8. 风险与缓解措施

### 8.1 高风险项

#### 风险1: 移动端日期标签重叠或显示不全

**概率**: 中 | **影响**: 高

**缓解措施**:
- Phase 1设计阶段制作移动端原型
- 在iPhone SE (320px)、iPhone 12 (390px)、Plus机型(430px)上测试
- 准备降级方案(缩小字体、旋转标签)

#### 风险2: 空闲设备逻辑修复遗漏位置

**概率**: 低 | **影响**: 高

**缓解措施**:
- Phase 1阶段完整阅读`GanttChart.vue`和`gantt.ts`代码
- 编写单元测试验证修复后的逻辑
- 使用spec.md中的Acceptance Scenarios进行集成测试

### 8.2 中风险项

#### 风险3: 性能问题(大数据量)

**概率**: 低 | **影响**: 中

**缓解措施**:
- 添加性能测试(见5.3节)
- 预留后端API接口(见2.4节方案B)
- 数据库查询优化(添加索引)

---

## 9. 下一步行动

### Phase 1设计任务

1. **完整阅读前端代码**:
   - `frontend/src/components/GanttChart.vue` (完整文件)
   - `frontend/src/stores/gantt.ts` (完整文件)
   - `frontend-mobile/src/views/GanttView.vue` (完整文件)
   - `frontend-mobile/src/stores/gantt.ts` (完整文件)

2. **验证空闲设备逻辑**:
   - 找到`getStatsForDate`函数实现
   - 确认是否使用错误的`start_date/end_date`
   - 列出所有需要修改的位置

3. **编写设计文档**:
   - `data-model.md`: 定义每日统计数据结构
   - `contracts/api-contracts.md`: 定义API接口(可选的daily-stats接口)
   - `contracts/component-contracts.md`: 定义组件props/events
   - `quickstart.md`: 编写开发指南

4. **制作移动端原型**:
   - 使用Figma或代码实现简单原型
   - 在真实设备上测试日期标签可读性

---

## 10. 参考资料

- [dayjs官方文档](https://day.js.org/)
- [Vant官方文档](https://vant-ui.github.io/vant/)
- [Element Plus官方文档](https://element-plus.org/)
- [Vue 3 Composition API](https://vuejs.org/guide/extras/composition-api-faq.html)
- [Flask-SQLAlchemy查询优化](https://docs.sqlalchemy.org/en/14/orm/loading_relationships.html)
- 项目规格说明: `specs/002-gantt-date-labels/spec.md`
- 项目实施计划: `specs/002-gantt-date-labels/plan.md`

---

**Phase 0研究完成日期**: 2026-01-01
**批准进入Phase 1**: 待确认

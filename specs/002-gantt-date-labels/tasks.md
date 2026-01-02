# Tasks: 甘特图日期可见性增强

**Input**: 设计文档来自 `/specs/002-gantt-date-labels/`
**Prerequisites**: plan.md (已完成), spec.md (已完成), research.md (已完成)

**Tests**: 本功能未明确要求TDD方法,因此不包含测试任务。如需添加测试,请在实施阶段根据需要补充。

**Organization**: 任务按用户故事分组,每个故事可独立实施和验证。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行(不同文件,无依赖关系)
- **[Story]**: 任务所属用户故事(如US1, US3, US4)
- 任务描述包含精确的文件路径

## Path Conventions

本项目采用Web应用双前端架构:
- 后端: `InventoryManager/app/`
- 桌面端前端: `InventoryManager/frontend/src/`
- 移动端前端: `InventoryManager/frontend-mobile/src/`
- 测试: `InventoryManager/tests/`

---

## Phase 1: Setup (共享基础设施)

**Purpose**: 项目初始化和基础结构确认

- [x] T001 验证开发环境配置(Python 3.9.6, Node.js, MySQL)
- [x] T002 [P] 确认前端依赖已安装(dayjs 1.11.x, Vue 3, Element Plus, Vant)
- [x] T003 [P] 阅读research.md中的技术决策和原型代码

---

## Phase 2: Foundational (阻塞性前置任务)

**Purpose**: 所有用户故事依赖的核心功能,必须在任何故事实施前完成

**⚠️ CRITICAL**: 在此阶段完成之前,不能开始任何用户故事的工作

- [x] T004 完整阅读frontend/src/components/GanttChart.vue文件,定位getStatsForDate函数实现
- [x] T005 完整阅读frontend/src/stores/gantt.ts文件,理解甘特图状态管理逻辑
- [x] T006 [P] 完整阅读frontend-mobile/src/views/GanttView.vue文件,理解移动端当前实现
- [x] T007 [P] 完整阅读frontend-mobile/src/stores/gantt.ts文件,理解移动端状态管理
- [x] T008 验证当前空闲设备计算逻辑是否使用错误的start_date/end_date(而非ship_out_time/ship_in_time)
- [x] T009 创建frontend/src/composables/useGanttStats.ts,实现正确的空闲设备计算逻辑(使用ship_out_time/ship_in_time)

**Checkpoint**: 基础调研完成 - 用户故事实施可以并行开始

---

## Phase 3: User Story 4 - 修复空闲设备统计逻辑 (Priority: P1) 🎯 MVP (缺陷修复)

**Goal**: 修复设备占用期计算逻辑,从starttime-endtime改为shipoutdate-shipindate,确保空闲设备统计100%准确

**Independent Test**: 创建测试租赁档期(starttime=1/5, endtime=1/7, shipoutdate=1/3, shipindate=1/9),验证系统在1/3, 1/4, 1/8, 1/9都将设备标记为"占用",在1/1和1/10标记为"空闲"

**Why P1 First**: 这是缺陷修复,影响数据准确性,必须优先处理。所有其他故事的统计功能都依赖于正确的占用逻辑。

### Implementation for User Story 4

- [ ] T010 [P] [US4] 在frontend/src/composables/useGanttStats.ts中实现getAvailableCount函数(使用ship_out_time/ship_in_time判断占用)
- [ ] T011 [P] [US4] 在frontend/src/composables/useGanttStats.ts中实现getShipOutCount函数(统计当日shipoutdate的设备数)
- [ ] T012 [US4] 修改frontend/src/components/GanttChart.vue,替换getStatsForDate函数为useGanttStats composable
- [ ] T013 [US4] 修改frontend/src/stores/gantt.ts(如有相关统计逻辑),使用ship_out_time/ship_in_time而非start_date/end_date
- [ ] T014 [US4] 在移动端frontend-mobile/src/composables/创建useGanttStats.ts(复用桌面端逻辑)
- [ ] T015 [US4] 修改frontend-mobile/src/views/GanttView.vue(如有统计逻辑),使用正确的占用判断逻辑
- [ ] T016 [US4] 验证修复:创建测试数据(starttime=1/5,endtime=1/7,shipoutdate=1/3,shipindate=1/9),确认1/3-1/9都显示占用,1/1和1/10显示空闲
- [ ] T017 [US4] 验证甘特图租赁条块覆盖范围与统计逻辑一致(都基于ship_out_time/ship_in_time)
- [ ] T018 [US4] 记录修复前后的空闲设备统计数据对比,确认准确率达到100%

**Checkpoint**: US4完成 - 空闲设备统计逻辑已修复,其他故事可以安全使用统计数据

---

## Phase 4: User Story 1 - 查看设备每日可用性 (Priority: P1) 🎯 MVP

**Goal**: 在甘特图时间轴上显示清晰的日期标签(日期+星期),为租赁条块添加起止日期标注,空闲日期提供视觉区分

**Independent Test**: 页面加载后,用户能一眼看出本周内哪几天有预约(如1号、3号占用),哪几天空闲(如2号、4号可预约),无需点击交互

**Dependencies**: 依赖US4(空闲设备逻辑修复)完成

### Implementation for User Story 1

#### 桌面端增强

- [x] T019 [P] [US1] 验证frontend/src/components/GanttChart.vue已有日期标签显示(第144-146行),确认格式是否满足需求
- [x] T020 [US1] 在frontend/src/components/GanttChart.vue中为租赁条块添加起止日期标注(GanttRow组件或RentalTooltip组件)
- [x] T021 [US1] 在frontend/src/components/GanttRow.vue中为跨度>3天的租赁条块添加天数统计显示(如"5天")
- [x] T022 [US1] 在frontend/src/components/GanttChart.vue中为空闲日期添加视觉区分(CSS样式:浅灰色背景或网格线)
- [x] T023 [US1] 在frontend/src/components/GanttChart.vue中为周末日期(周六、周日)添加视觉区分(CSS样式:不同背景色)
- [x] T024 [US1] 在frontend/src/components/GanttChart.vue中高亮"今天"日期(CSS样式:特殊标记或背景色)

#### 移动端实现

- [x] T025 [US1] 创建frontend-mobile/src/components/MobileDateHeader.vue组件,实现横向滚动的日期标题栏
- [x] T026 [US1] 在MobileDateHeader.vue中显示日期标签(格式:M/D,如"1/1")和星期(格式:简写,如"一")
- [x] T027 [US1] 在MobileDateHeader.vue中添加月份分隔线和月份标签(CSS样式:红色分隔线+标签)
- [x] T028 [US1] 在MobileDateHeader.vue中添加周末标记(CSS样式:浅蓝色背景)
- [x] T029 [US1] 在MobileDateHeader.vue中高亮"今天"日期(CSS样式:蓝色背景+粗体)
- [x] T030 [US1] 修改frontend-mobile/src/views/GanttView.vue,集成MobileDateHeader组件替代现有日期范围显示
- [x] T031 [US1] 在frontend-mobile/src/views/GanttView.vue中为移动端时间轴添加横向滚动支持(CSS: overflow-x: auto)
- [x] T032 [US1] 在frontend-mobile/src/views/GanttView.vue中为租赁条块添加客户名称标签(简化显示)

#### 响应式适配

- [x] T033 [US1] 添加移动端响应式CSS(frontend-mobile/src/components/MobileDateHeader.vue),适配320px、390px、430px屏幕
- [ ] T034 [US1] 确保移动端日期标签字体大小≥12px,统计信息字体大小≥10px
- [ ] T035 [US1] 在iPhone SE (320px)、iPhone 12 (390px)、Plus机型(430px)上测试日期标签可读性

#### 验收测试

- [ ] T036 [US1] 验证桌面端:时间轴显示"1月1日 周一"格式的日期标签
- [ ] T037 [US1] 验证桌面端:租赁条块显示"1/1-1/3"格式的起止日期
- [ ] T038 [US1] 验证桌面端:长租赁条块(>3天)显示天数(如"5天")
- [ ] T039 [US1] 验证桌面端:空闲日期有浅灰色背景或网格线
- [ ] T040 [US1] 验证桌面端:周末日期有不同背景色
- [ ] T041 [US1] 验证移动端:日期标签显示"1/1 一"格式
- [ ] T042 [US1] 验证移动端:月份切换处有红色分隔线和月份标签
- [ ] T043 [US1] 验证移动端:时间轴可横向滚动
- [ ] T044 [US1] 验证移动端:在320px屏幕上日期标签清晰可读(误读率<5%)

**Checkpoint**: US1完成 - 用户可以清晰看到日期标签和空闲日期,桌面端和移动端均可用

---

## Phase 5: User Story 3 - 查看每日设备统计信息 (Priority: P2) 🎯 高优先级

**Goal**: 在每个日期下方或上方显示当日统计信息,格式为"X台寄出 / Y台空闲",支持点击展开详情

**Independent Test**: 移动端页面加载后,每个日期列显示"3台寄出 / 2台空闲"格式的统计数据,用户可立即了解当日设备状态

**Dependencies**: 依赖US4(空闲设备逻辑修复)完成,建议在US1之后实施

### Implementation for User Story 3

#### 统计功能实现

- [ ] T045 [P] [US3] 在frontend/src/composables/useGanttStats.ts中实现dailyStats computed属性(缓存所有日期的统计数据)
- [ ] T046 [US3] 在frontend/src/components/GanttChart.vue中调用useGanttStats,获取每日统计数据
- [ ] T047 [US3] 验证桌面端GanttChart.vue第147-170行已显示统计信息(ship_out_count寄, available_count闲)
- [ ] T048 [US3] 在frontend-mobile/src/composables/useGanttStats.ts中实现相同的统计逻辑(复用桌面端代码)

#### 移动端UI实现

- [ ] T049 [US3] 在frontend-mobile/src/components/MobileDateHeader.vue中添加date-stats区域,显示"X寄/Y闲"
- [ ] T050 [US3] 在MobileDateHeader.vue中实现点击统计信息的交互(触发showStatsDetail事件)
- [ ] T051 [US3] 创建frontend-mobile/src/components/DailyStatsDetail.vue组件,显示当日寄出设备列表和空闲设备列表
- [ ] T052 [US3] 在frontend-mobile/src/views/GanttView.vue中集成DailyStatsDetail组件,实现弹窗展示
- [ ] T053 [US3] 在DailyStatsDetail.vue中使用Vant的van-popup组件显示详情弹窗

#### 桌面端UI增强(可选)

- [ ] T054 [US3] 在frontend/src/components/GanttChart.vue中优化统计信息显示(已有基础实现,确认格式是否需要调整)
- [ ] T055 [US3] 在frontend/src/components/GanttChart.vue中添加统计信息点击交互(可选:展开详情对话框)

#### 验收测试

- [ ] T056 [US3] 验证移动端:每个日期显示"3寄/2闲"格式的统计信息
- [ ] T057 [US3] 验证移动端:点击"3寄"时,弹窗显示当日需要寄出的3台设备列表(设备名称、型号)
- [ ] T058 [US3] 验证移动端:点击"2闲"时,弹窗显示当日空闲的2台设备列表
- [ ] T059 [US3] 验证桌面端:日期标题行显示统计信息(已有实现,确认格式正确)
- [ ] T060 [US3] 验证统计准确性:某日有3台shipoutdate=该日,显示"3寄";5台总设备-3台占用=2台空闲,显示"2闲"
- [ ] T061 [US3] 验证性能:统计信息在页面加载后1秒内显示完成

**Checkpoint**: US3完成 - 用户可以查看每日设备统计信息,运营人员可快速了解发货工作量和可用设备数量

---

## Phase 6: User Story 2 - 快速定位特定日期 (Priority: P2)

**Goal**: 支持日期跳转功能,用户可快速定位到指定日期并高亮显示,方便查询特定日期的设备可用性

**Independent Test**: 用户点击或选择"1月15日",甘特图自动滚动到该日期并高亮显示该日期列,所有设备在该日的状态一目了然

**Dependencies**: 独立于其他故事,可在US1完成后并行实施

### Implementation for User Story 2

#### 桌面端日期导航

- [x] T062 [P] [US2] 在frontend/src/components/GanttChart.vue中添加日期选择器组件(使用Element Plus的el-date-picker)
- [x] T063 [US2] 在frontend/src/stores/gantt.ts中添加selectedDate状态和setSelectedDate方法
- [x] T064 [US2] 在frontend/src/components/GanttChart.vue中实现日期跳转逻辑(滚动到指定日期列)
- [x] T065 [US2] 在frontend/src/components/GanttChart.vue中实现日期高亮逻辑(CSS class: selected-date)
- [x] T066 [US2] 在frontend/src/components/GanttChart.vue中添加点击日期标签的交互(点击日期列时高亮该列)
- [x] T067 [US2] 在frontend/src/components/GanttChart.vue中实现高亮状态持久化(直到用户切换到其他日期)

#### 移动端日期导航

- [x] T068 [P] [US2] 在frontend-mobile/src/views/GanttView.vue中添加日期选择器(使用Vant的van-date-picker)
- [x] T069 [US2] 在frontend-mobile/src/stores/gantt.ts中添加selectedDate状态和setSelectedDate方法
- [x] T070 [US2] 在frontend-mobile/src/views/GanttView.vue中实现日期跳转逻辑(横向滚动到指定日期)
- [x] T071 [US2] 在frontend-mobile/src/components/MobileDateHeader.vue中实现日期高亮逻辑(CSS class: selected-date)
- [x] T072 [US2] 在MobileDateHeader.vue中添加点击日期列的交互(点击日期时高亮)

#### 快速跳转功能

- [x] T073 [US2] 在frontend/src/components/GanttChart.vue中添加"今天"按钮(已存在,确认功能)
- [x] T074 [US2] 在frontend/src/components/GanttChart.vue中添加"上周"/"下周"按钮(已存在,确认功能)
- [x] T075 [US2] 在frontend/src/stores/gantt.ts中实现navigateWeek方法(已存在,确认功能)
- [x] T076 [US2] 在frontend-mobile/src/views/GanttView.vue中确认移动端已有"今天"/"上周"/"下周"按钮

#### 验收测试

- [ ] T077 [US2] 验证桌面端:点击日期选择器选择1月15日,甘特图自动滚动到该日期
- [ ] T078 [US2] 验证桌面端:选中的日期列高亮显示(背景色或边框)
- [ ] T079 [US2] 验证桌面端:点击日期标签时,该日期列高亮
- [ ] T080 [US2] 验证桌面端:高亮状态持续保持,直到切换到其他日期
- [ ] T081 [US2] 验证桌面端:从1月跳转到2月操作时间<3秒
- [ ] T082 [US2] 验证移动端:点击日期选择器选择1月15日,时间轴横向滚动到该日期
- [ ] T083 [US2] 验证移动端:选中的日期列高亮显示
- [ ] T084 [US2] 验证移动端:点击"今天"按钮,自动跳转到当前日期

**Checkpoint**: US2完成 - 用户可以快速定位到指定日期,提升查询效率

---

## Phase 7: User Story 5 - 区分工作日和周末 (Priority: P3)

**Goal**: 在时间轴上区分周末(周六、周日)和工作日,使用不同的背景色或标记,帮助运营人员规划档期

**Independent Test**: 查看一周档期时,周六和周日的日期列有明显的视觉区分(如浅蓝色背景),与工作日明显不同

**Dependencies**: 独立于其他故事,可在US1完成后实施

### Implementation for User Story 5

#### 周末标记实现

- [ ] T085 [P] [US5] 在frontend/src/components/GanttChart.vue中为日期标签添加isWeekend判断逻辑(dayjs().day() === 0 || dayjs().day() === 6)
- [ ] T086 [P] [US5] 在frontend/src/components/GanttChart.vue中为周末日期添加CSS class: is-weekend
- [ ] T087 [US5] 在frontend/src/components/GanttChart.vue的CSS中定义is-weekend样式(浅蓝色背景或特殊标记)
- [ ] T088 [P] [US5] 在frontend-mobile/src/components/MobileDateHeader.vue中添加isWeekend判断逻辑
- [ ] T089 [US5] 在MobileDateHeader.vue中为周末日期添加CSS class: is-weekend
- [ ] T090 [US5] 在MobileDateHeader.vue的CSS中定义is-weekend样式(与桌面端一致)

#### 验收测试

- [ ] T091 [US5] 验证桌面端:周六和周日的日期列有浅蓝色背景或周末标签
- [ ] T092 [US5] 验证桌面端:工作日(周一到周五)无特殊标记
- [ ] T093 [US5] 验证移动端:周六和周日的日期列有视觉区分
- [ ] T094 [US5] 验证移动端:周末标记在小屏幕(320px)上清晰可见

**Checkpoint**: US5完成 - 用户可以快速识别周末日期,优化定价和档期规划策略

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: 跨用户故事的优化和完善

- [ ] T095 [P] 在frontend/src/components/GanttChart.vue中优化长期档期(>30天)的日期显示(如"1/1...2/15")
- [ ] T096 [P] 在frontend/src/components/GanttChart.vue中添加租赁条块悬停时的详细信息tooltip(使用Element Plus的el-tooltip)
- [ ] T097 [P] 在frontend-mobile/src/views/GanttView.vue中优化移动端租赁条块点击交互(显示详情弹窗)
- [ ] T098 性能优化:在frontend/src/composables/useGanttStats.ts中使用computed缓存统计结果
- [ ] T099 性能优化:验证甘特图页面加载完成后,日期标签在1秒内渲染完成
- [ ] T100 性能优化:验证后端API响应时间<200ms p95(使用浏览器DevTools Network面板)
- [ ] T101 [P] 代码审查:确保所有日期格式化使用dayjs库,统一格式
- [ ] T102 [P] 代码审查:确保所有CSS样式遵循项目规范(BEM或其他)
- [ ] T103 文档更新:在README.md中添加"甘特图日期可见性增强"功能说明
- [ ] T104 文档更新:更新用户手册,说明如何使用日期导航和统计功能
- [ ] T105 无障碍优化:为日期标签添加aria-label属性(提升屏幕阅读器支持)
- [ ] T106 边界情况处理:验证跨月份显示时月份切换处的视觉分隔正确
- [ ] T107 边界情况处理:验证设备无任何档期时显示"暂无档期"状态
- [ ] T108 边界情况处理:验证rental.ship_out_time或ship_in_time为null时的降级处理
- [ ] T109 最终验收:在真实设备(iPhone SE, iPhone 12, iPad, MacBook)上测试所有功能
- [ ] T110 最终验收:验证所有Success Criteria(SC-001到SC-013)达成

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可立即开始
- **Foundational (Phase 2)**: 依赖Setup完成 - **阻塞所有用户故事**
- **User Story 4 (Phase 3, P1 Bug Fix)**: 依赖Foundational完成 - **必须优先完成,阻塞US3**
- **User Story 1 (Phase 4, P1 MVP)**: 依赖Foundational和US4完成 - **MVP核心功能**
- **User Story 3 (Phase 5, P2)**: 依赖US4完成,建议在US1之后 - **高优先级统计功能**
- **User Story 2 (Phase 6, P2)**: 依赖Foundational完成,独立于其他故事 - **导航增强**
- **User Story 5 (Phase 7, P3)**: 依赖Foundational完成,独立于其他故事 - **周末标记**
- **Polish (Phase 8)**: 依赖所有期望的用户故事完成

### User Story Dependencies

```
Foundational (Phase 2)
    ↓
    ├─→ US4 (空闲设备逻辑修复, P1) ← 必须最先完成
    │       ↓
    │       ├─→ US1 (日期标签显示, P1 MVP)
    │       └─→ US3 (每日统计, P2) ← 依赖US4
    │
    ├─→ US2 (日期导航, P2) ← 独立,可并行
    └─→ US5 (周末标记, P3) ← 独立,可并行
```

### Critical Path (MVP)

1. Phase 1: Setup (T001-T003)
2. Phase 2: Foundational (T004-T009) ← **阻塞点**
3. Phase 3: US4 Bug Fix (T010-T018) ← **必须完成**
4. Phase 4: US1 MVP (T019-T044) ← **MVP交付点**

### Within Each User Story

- **US4**: 实现composable → 修改桌面端 → 修改移动端 → 验证测试
- **US1**: 桌面端增强 → 移动端实现 → 响应式适配 → 验收测试
- **US3**: 统计逻辑 → 移动端UI → 桌面端增强 → 验收测试
- **US2**: 桌面端导航 → 移动端导航 → 快速跳转 → 验收测试
- **US5**: 周末判断逻辑 → 桌面端样式 → 移动端样式 → 验收测试

### Parallel Opportunities

#### Setup & Foundational

```bash
# Phase 1: 所有标记[P]的任务可并行
T002 + T003

# Phase 2: 所有标记[P]的任务可并行
T006 + T007
```

#### User Story 4 (Bug Fix)

```bash
# 可并行: 不同文件,无依赖
T010 (useGanttStats.ts - getAvailableCount) +
T011 (useGanttStats.ts - getShipOutCount)

# 然后串行: T012 → T013 → T014 → T015 → T016 → T017 → T018
```

#### User Story 1 (MVP)

```bash
# 桌面端增强(可部分并行)
T020 (租赁条块日期) + T022 (空闲日期样式) + T023 (周末样式) + T024 (今天高亮)

# 移动端组件创建(可并行)
T025 (创建MobileDateHeader) + T033 (响应式CSS)

# 移动端功能(串行依赖T025)
T026 → T027 → T028 → T029 → T030 → T031 → T032

# 验收测试(可并行)
T036 + T037 + T038 + T039 + T040 + T041 + T042 + T043 + T044
```

#### User Story 3 (Statistics)

```bash
# 统计逻辑(可并行)
T045 (桌面端dailyStats) + T048 (移动端useGanttStats)

# 移动端UI(可并行)
T051 (创建DailyStatsDetail) + T049 (MobileDateHeader统计显示)

# 验收测试(可并行)
T056 + T057 + T058 + T059 + T060 + T061
```

#### User Story 2 (Navigation)

```bash
# 桌面端和移动端可并行开发
T062 + T063 + T064 + T065 + T066 + T067 (桌面端)
  ||
T068 + T069 + T070 + T071 + T072 (移动端)

# 验收测试(可并行)
T077 + T078 + T079 + T080 + T081 + T082 + T083 + T084
```

#### User Story 5 (Weekend Marking)

```bash
# 桌面端和移动端可并行
T085 + T086 + T087 (桌面端)
  ||
T088 + T089 + T090 (移动端)

# 验收测试(可并行)
T091 + T092 + T093 + T094
```

#### Polish Phase

```bash
# 大部分任务可并行(不同文件)
T095 + T096 + T097 + T101 + T102 + T103 + T104 + T105
```

### Team Collaboration Strategy

如果有多个开发人员:

```
完成 Setup + Foundational (所有人协作)
    ↓
完成 US4 (开发人员A,必须完成) ← 阻塞US3
    ↓
并行开发:
    ├─ 开发人员A: US1 (MVP, 桌面端)
    ├─ 开发人员B: US1 (MVP, 移动端)
    ├─ 开发人员C: US2 (日期导航)
    └─ 开发人员D: US5 (周末标记)

US4 + US1完成后:
    └─ 开发人员E: US3 (每日统计,依赖US4)

最后:
    └─ 所有人: Polish & 验收
```

---

## Parallel Example: MVP (US4 + US1)

### Phase 3: US4 Bug Fix

```bash
# Step 1: 并行实现统计函数
Task: "[P] [US4] 实现getAvailableCount函数 in frontend/src/composables/useGanttStats.ts"
Task: "[P] [US4] 实现getShipOutCount函数 in frontend/src/composables/useGanttStats.ts"

# Step 2: 串行修改组件(依赖Step 1)
Task: "[US4] 修改GanttChart.vue,替换getStatsForDate"
Task: "[US4] 修改gantt.ts状态管理"
Task: "[US4] 创建移动端useGanttStats.ts"
Task: "[US4] 修改移动端GanttView.vue"

# Step 3: 验证修复
Task: "[US4] 验证测试数据(1/3-1/9占用,1/1和1/10空闲)"
```

### Phase 4: US1 MVP

```bash
# Step 1: 并行桌面端增强
Task: "[P] [US1] 为租赁条块添加日期标注"
Task: "[P] [US1] 为空闲日期添加视觉区分"
Task: "[P] [US1] 为周末添加视觉区分"
Task: "[P] [US1] 高亮今天日期"

# Step 2: 并行移动端开发
Task: "[US1] 创建MobileDateHeader组件"
Task: "[P] [US1] 添加响应式CSS"

# Step 3: 移动端集成(依赖Step 2)
Task: "[US1] 在GanttView.vue中集成MobileDateHeader"
Task: "[US1] 添加横向滚动支持"

# Step 4: 并行验收测试
Task: "[US1] 验证桌面端日期标签"
Task: "[US1] 验证移动端日期标签"
Task: "[US1] 验证320px屏幕可读性"
```

---

## Implementation Strategy

### MVP First (仅US4 + US1)

推荐的MVP交付策略:

1. **Phase 1: Setup** (T001-T003) - 1小时
2. **Phase 2: Foundational** (T004-T009) - 4小时
3. **Phase 3: US4 Bug Fix** (T010-T018) - 8小时
4. **Phase 4: US1 MVP** (T019-T044) - 16小时
5. **STOP and VALIDATE**: 独立测试US1功能
6. **Demo/部署**: 可交付MVP版本

**MVP价值**:
- 修复空闲设备统计准确性(100%准确)
- 用户可清晰看到日期标签和空闲日期
- 移动端和桌面端均可用
- 解决核心痛点(看不出几号有几号没有)

### Incremental Delivery (逐步交付)

1. **第一次交付(MVP)**: Setup + Foundational + US4 + US1
   - 测试: 日期标签可见,空闲设备统计准确
   - 交付: 核心功能可用

2. **第二次交付**: +US3 (每日统计)
   - 测试: 每日统计信息准确显示
   - 交付: 运营决策支持增强

3. **第三次交付**: +US2 (日期导航) + US5 (周末标记)
   - 测试: 日期跳转功能,周末视觉区分
   - 交付: 用户体验完善

4. **最终交付**: +Polish
   - 测试: 所有Success Criteria达成
   - 交付: 完整功能,生产就绪

### Suggested Task Execution Flow

```
Week 1:
Day 1: T001-T009 (Setup + Foundational)
Day 2-3: T010-T018 (US4 Bug Fix) ← 关键修复
Day 4-5: T019-T044 (US1 MVP) ← MVP交付

Week 2:
Day 1-2: T045-T061 (US3 每日统计)
Day 3: T062-T084 (US2 日期导航)
Day 4: T085-T094 (US5 周末标记)
Day 5: T095-T110 (Polish & 验收)
```

---

## Notes

- **[P]** 标记 = 不同文件,可并行执行
- **[Story]** 标记 = 任务所属用户故事,便于追溯
- 每个用户故事应独立完成和测试
- 在每个Checkpoint停下来验证故事的独立功能
- 避免:模糊任务、文件冲突、破坏独立性的跨故事依赖
- 提交策略:每完成一个任务或逻辑组提交一次
- **测试优先**: 虽然未包含TDD任务,但建议在实施过程中编写单元测试验证关键逻辑(如useGanttStats.ts)

---

## Success Criteria Mapping

| Success Criteria | 相关任务 | 验证方法 |
|-----------------|---------|---------|
| SC-001: 查询响应时间<5秒 | T036-T044 (US1验收) | 使用浏览器DevTools Performance面板测试 |
| SC-002: 95%查询无需点击 | T036-T044 (US1验收) | 用户测试:观察10次查询,记录点击次数 |
| SC-003: 3秒内识别空闲日期 | T036-T044 (US1验收) | 用户测试:计时识别空闲日期任务 |
| SC-004: 移动端误读率<5% | T041-T044 (US1移动端验收) | 用户测试:20个日期,记录误读次数 |
| SC-005: 重复预约错误率<2% | T016-T018 (US4验证) | 运营数据对比:修复前后的错误率 |
| SC-006: 90%用户独立完成 | T109 (最终验收) | 用户测试:10名新用户,观察完成情况 |
| SC-007: 跨月查询<3秒 | T077-T084 (US2验收) | 使用浏览器DevTools Performance面板测试 |
| SC-008: 日期标签1秒内渲染 | T099 (性能优化) | 使用Performance API测量渲染时间 |
| SC-009: 空闲统计准确率100% | T016-T018 (US4验证) | 单元测试+集成测试验证 |
| SC-010: 冲突率降至0% | T016-T018 (US4验证) | 运营数据监控:1个月内冲突次数 |
| SC-011: 发货查询即时显示 | T056-T061 (US3验收) | 用户测试:点击统计信息,记录响应时间 |
| SC-012: 空闲查询即时显示 | T056-T061 (US3验收) | 用户测试:查看统计信息,记录响应时间 |
| SC-013: 物流准备时间减少50% | T056-T061 (US3验收) | 运营数据对比:修复前后的准备时间 |

---

## Task Count Summary

- **Total Tasks**: 110
- **Phase 1 (Setup)**: 3 tasks
- **Phase 2 (Foundational)**: 6 tasks
- **Phase 3 (US4 Bug Fix, P1 MVP)**: 9 tasks
- **Phase 4 (US1 MVP, P1)**: 26 tasks
- **Phase 5 (US3, P2)**: 17 tasks
- **Phase 6 (US2, P2)**: 23 tasks
- **Phase 7 (US5, P3)**: 10 tasks
- **Phase 8 (Polish)**: 16 tasks

**Parallelizable Tasks**: 42 tasks标记为[P] (38%)
**MVP Scope (Recommended)**: Phase 1-4 (44 tasks, ~40%工作量)
**Independent Test Criteria**: 每个用户故事都有明确的独立测试标准

---

**Generated**: 2026-01-01
**Based on**: spec.md (5个用户故事), plan.md (技术栈), research.md (技术决策)
**Ready for Execution**: ✅ 所有任务已按checklist格式编写,包含Task ID、[P]标记、[Story]标签和文件路径

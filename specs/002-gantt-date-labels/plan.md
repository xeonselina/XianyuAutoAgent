# Implementation Plan: 甘特图日期可见性增强

**Branch**: `002-gantt-date-labels` | **Date**: 2026-01-01 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-gantt-date-labels/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

本功能旨在解决移动端甘特图日期标签不清晰的问题,增强日期可见性和每日设备统计信息。主要包括:
1. **改进日期标签显示** - 在时间轴上显示清晰的日期和星期,为租赁条块添加起止日期标注
2. **新增每日设备统计** - 显示每日寄出设备数量和空闲设备数量,格式为"X台寄出 / Y台空闲"
3. **修复空闲设备统计逻辑(Bug Fix)** - 将设备占用期定义从starttime-endtime修正为shipoutdate-shipindate(包含两端)
4. **优化日期导航** - 支持日期跳转、高亮选中日期、月份切换视觉分隔

技术实现方案:主要涉及前端Vue.js组件(桌面端和移动端)改进,以及后端Flask API增强以支持每日统计查询。采用dayjs库进行日期处理,通过响应式设计适配移动端小屏幕。

## Technical Context

**Language/Version**: Python 3.9.6 (后端), TypeScript/JavaScript (前端Vue 3.5.18)
**Primary Dependencies**: Flask (后端), Vue 3 + Element Plus (桌面端), Vue 3 + Vant (移动端), dayjs 1.11.x (日期处理), axios (HTTP客户端), MySQL + SQLAlchemy (数据持久化)
**Storage**: MySQL数据库 (通过mysql+pymysql连接), 租赁和设备数据已存储在`devices`和`rentals`表
**Testing**: pytest (后端单元测试和集成测试), 前端组件测试(待确认框架)
**Target Platform**: Web应用 (桌面端和移动端H5), 通过User-Agent自动检测设备类型并提供对应前端版本
**Project Type**: Web应用 (Flask后端 + 双前端架构: frontend/desktop端 + frontend-mobile/移动端)
**Performance Goals**:
- 甘特图页面加载完成后,所有日期标签应在1秒内渲染完成
- 档期查询响应时间<5秒
- 每日统计信息即时显示(无需额外请求)
**Constraints**:
- 移动端最小屏幕宽度320px (iPhone SE)
- 日期标签必须在小屏幕上可读(字体大小≥12px)
- 空闲设备统计准确率必须达到100%
- 后端API响应时间<200ms p95
**Scale/Scope**:
- 支持~50-100台设备的甘特图显示
- 默认显示范围: 当前周±2周 (共5周, 35天)
- 租赁记录数量级: 数百到数千条

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### 检查项: 中文文档规范

✅ **通过** - 所有规格说明、任务描述、代码注释均使用中文编写,技术术语保留英文原文并提供中文解释。

### 检查项: 其他原则

**状态**: ⚠️ 宪法文件尚未完全定义 (仅包含中文文档规范原则)

由于项目宪法文件(`.specify/memory/constitution.md`)中除中文文档规范外的原则尚未填写,无法执行完整的宪法检查。建议在Phase 0完成后,与项目负责人确认是否需要补充以下原则:
- 库优先(Library-First)原则
- 测试优先(Test-First)原则
- 集成测试(Integration Testing)要求
- 可观测性(Observability)标准
- 版本控制和破坏性变更(Versioning & Breaking Changes)规范

**当前决策**: 继续执行Phase 0研究,在Phase 1设计完成后再次检查。

## Project Structure

### Documentation (this feature)

```text
specs/002-gantt-date-labels/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   ├── api-contracts.md      # 后端API接口契约
│   └── component-contracts.md # 前端组件接口契约
├── checklists/
│   └── requirements.md  # 规格说明质量检查清单 (已完成)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
InventoryManager/
├── app/                          # Flask后端应用
│   ├── routes/
│   │   ├── gantt.py             # 甘特图API路由 (需修改: 每日统计接口)
│   │   └── rentals.py           # 租赁API路由 (需修改: 空闲设备查询逻辑)
│   ├── models/
│   │   ├── device.py            # 设备模型 (可能需要新增查询方法)
│   │   └── rental.py            # 租赁模型 (可能需要新增查询方法)
│   ├── services/                # 业务逻辑层 (可能新增)
│   │   └── statistics.py        # 统计服务 (新增: 每日统计计算逻辑)
│   └── utils/
│       └── date_utils.py        # 日期工具函数 (可能新增)
├── tests/
│   ├── unit/
│   │   ├── test_statistics.py   # 统计服务单元测试 (新增)
│   │   └── test_rental_logic.py # 租赁逻辑测试 (修改: 空闲设备计算)
│   ├── integration/
│   │   ├── test_gantt_api.py    # 甘特图API集成测试 (修改)
│   │   └── test_statistics_api.py # 统计API集成测试 (新增)
│   └── contract/
│       └── test_api_contracts.py # API契约测试 (新增)
├── frontend/                    # 桌面端Vue应用
│   ├── src/
│   │   ├── components/
│   │   │   ├── GanttChart.vue   # 甘特图主组件 (需修改: 日期标签、统计信息)
│   │   │   ├── GanttRow.vue     # 甘特图行组件 (可能需要修改)
│   │   │   └── DateNavigator.vue # 日期导航组件 (新增或修改)
│   │   ├── stores/
│   │   │   └── gantt.ts         # 甘特图状态管理 (需修改: 统计数据处理)
│   │   ├── utils/
│   │   │   └── dateUtils.ts     # 日期工具函数 (已存在, 可能需要扩展)
│   │   └── composables/
│   │       └── useGanttStats.ts # 统计数据Composable (新增)
│   └── tests/
│       └── components/
│           └── GanttChart.spec.ts # 组件测试 (修改)
└── frontend-mobile/             # 移动端Vue应用
    ├── src/
    │   ├── views/
    │   │   └── GanttView.vue    # 移动端甘特图视图 (需修改: 日期标签、统计信息)
    │   ├── components/
    │   │   ├── MobileTimeline.vue # 移动端时间轴组件 (新增或修改)
    │   │   └── DailyStats.vue   # 每日统计组件 (新增)
    │   ├── stores/
    │   │   └── gantt.ts         # 移动端甘特图状态 (需修改)
    │   └── utils/
    │       └── dateUtils.ts     # 日期工具函数 (可能需要扩展)
    └── tests/
        └── views/
            └── GanttView.spec.ts # 视图测试 (修改)
```

**Structure Decision**:

本项目采用**Web应用双前端架构**:
- **后端**: Flask应用位于`app/`目录,使用SQLAlchemy ORM管理MySQL数据库
- **桌面端前端**: Vue 3 + Element Plus,位于`frontend/`目录,构建产物输出到`static/vue-dist/`
- **移动端前端**: Vue 3 + Vant,位于`frontend-mobile/`目录,构建产物输出到`static/mobile-dist/`
- **设备检测**: 后端通过User-Agent自动检测设备类型,从统一路由`/`提供对应前端版本

本功能主要涉及:
1. **后端修改**: 主要集中在`app/routes/gantt.py`和可能新增的`app/services/statistics.py`
2. **前端修改**: 桌面端(`frontend/src/components/GanttChart.vue`)和移动端(`frontend-mobile/src/views/GanttView.vue`)
3. **测试新增**: 单元测试、集成测试、契约测试

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

**无违反项** - 本功能符合已定义的中文文档规范原则,且未涉及需要特殊复杂度审批的架构变更。

---

## Phase 0: Research

*详见 [research.md](./research.md)*

### 研究目标

Phase 0需要解决以下技术未知项和最佳实践调研:

1. **日期标签显示最佳实践**
   - Vue.js中如何实现响应式甘特图日期标签?
   - 如何在移动端小屏幕(<375px)上保证日期标签可读性?
   - 有哪些成熟的日期格式化方案(dayjs vs date-fns)?

2. **每日统计计算算法**
   - 如何高效计算每日寄出设备数量(shipoutdate == target_date)?
   - 如何高效计算每日空闲设备数量(total - occupied, where shipoutdate ≤ target_date ≤ shipindate)?
   - SQL查询优化方案(索引、预聚合、缓存)?

3. **空闲设备统计逻辑修复**
   - 当前系统使用starttime-endtime的位置在哪些文件?
   - 需要修改哪些API接口、数据库查询、前端组件?
   - 如何保证修复后的向后兼容性?

4. **性能优化方案**
   - 每日统计数据是否需要后端计算后返回,还是前端实时计算?
   - 如何避免大量日期范围查询导致的性能问题?
   - 是否需要引入缓存机制(Redis/内存缓存)?

5. **移动端响应式设计**
   - 如何在小屏幕上优化日期标签布局(横向滚动、缩略、分层)?
   - Vant组件库是否提供日期选择器/时间轴组件?
   - 如何处理跨月份显示的视觉分隔?

### 输出物

- `research.md`: 详细记录上述问题的调研结果、技术选型建议、原型代码片段

---

## Phase 1: Design

*详见 data-model.md, contracts/, quickstart.md*

### 设计目标

Phase 1需要完成以下设计文档:

1. **data-model.md**: 数据模型和业务逻辑设计
   - 每日统计数据结构定义
   - 空闲设备计算逻辑的数学模型
   - 数据库查询语句示例(SQL)
   - 日期范围处理规则

2. **contracts/**: API和组件接口契约
   - `api-contracts.md`: 后端API接口契约
     - GET `/api/gantt/daily-stats?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`
     - 修改后的租赁档期查询接口(使用shipoutdate/shipindate)
   - `component-contracts.md`: 前端组件接口契约
     - `GanttChart.vue` props/events
     - `DailyStats.vue` props/events
     - `useGanttStats` composable接口

3. **quickstart.md**: 快速开始指南
   - 本地开发环境设置
   - 如何运行单元测试
   - 如何验证日期标签显示
   - 如何验证每日统计准确性
   - 如何验证空闲设备逻辑修复

---

## Phase 2: Tasks

*由 `/speckit.tasks` 命令生成,不在本文件中*

Phase 2将基于Phase 0研究和Phase 1设计,生成详细的任务清单(`tasks.md`),包括:
- 依赖关系排序的任务列表
- 每个任务的验收标准
- 测试用例编写任务
- 代码实现任务
- 集成测试任务
- 文档更新任务

---

## Risk Assessment

### 高风险项

1. **空闲设备逻辑修复影响范围不明确**
   - **风险**: 当前使用starttime-endtime的代码位置可能分散在多个文件,遗漏修改会导致数据不一致
   - **缓解措施**: Phase 0阶段进行全局代码搜索(grep "starttime"/"endtime"),列出所有需要修改的位置

2. **性能问题**
   - **风险**: 每日统计计算可能涉及大量日期范围查询,影响页面加载速度
   - **缓解措施**: Phase 0阶段进行性能测试,确定是否需要引入缓存或预聚合

3. **移动端布局兼容性**
   - **风险**: 小屏幕(<375px)上日期标签可能重叠或显示不全
   - **缓解措施**: Phase 0阶段制作移动端原型,在真实设备上测试

### 中风险项

1. **前后端数据同步**
   - **风险**: 前端和后端对"每日统计"的计算逻辑理解不一致
   - **缓解措施**: Phase 1阶段明确定义API契约和数据结构,编写契约测试

2. **向后兼容性**
   - **风险**: 修复空闲设备逻辑后,旧的API调用方(如果存在)可能受影响
   - **缓解措施**: Phase 0阶段确认是否有外部API调用方,如有则需要版本控制

### 低风险项

1. **日期格式化库选择**
   - **风险**: dayjs和date-fns功能相似,选择不当可能需要重构
   - **缓解措施**: 项目已使用dayjs,继续使用即可

---

## Success Metrics

### 功能性指标

- ✅ 所有日期标签在桌面端和移动端清晰可读(字体大小≥12px)
- ✅ 每日统计信息准确显示(寄出数量、空闲数量)
- ✅ 空闲设备统计准确率达到100%(使用shipoutdate-shipindate逻辑)
- ✅ 支持日期跳转、高亮选中日期、月份切换

### 性能指标

- ✅ 甘特图页面加载完成后,日期标签在1秒内渲染完成
- ✅ 档期查询响应时间<5秒
- ✅ 后端API响应时间<200ms p95

### 用户体验指标

- ✅ 95%的档期查询无需点击或交互,仅通过视觉扫描即可完成
- ✅ 用户在3秒内能识别任意设备在当前显示周内的空闲日期数量
- ✅ 移动端用户能够清晰阅读所有日期标签,误读率低于5%

### 测试覆盖率指标

- ✅ 单元测试覆盖率≥80%(统计服务、日期工具函数)
- ✅ 集成测试覆盖所有API接口
- ✅ 契约测试覆盖前后端数据交互

---

## Next Steps

1. **执行 Phase 0: Research** - 调研技术方案,解决上述未知项
2. **执行 Phase 1: Design** - 编写数据模型、API契约、快速开始指南
3. **执行 `/speckit.tasks` 命令** - 生成详细任务清单
4. **开始实施** - 按照tasks.md中的任务顺序逐步实现

**预计时间线**: Phase 0 (研究) → Phase 1 (设计) → Phase 2 (任务生成) → 实施阶段

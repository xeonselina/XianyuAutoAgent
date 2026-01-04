# Implementation Plan: 简化租赁附件选择

**Branch**: `001-simplify-rental-accessories` | **Date**: 2026-01-04 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-simplify-rental-accessories/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

简化租赁订单中的附件选择流程:将已与设备1:1配齐的手柄和镜头支架从下拉选择改为复选框,保留手机支架和三脚架的下拉选择方式,同时确保面单、发货单和甘特图的附件信息显示不受影响。

**技术方法**:修改前端`BookingDialog.vue`和`RentalAccessorySelector.vue`组件的附件选择UI,调整后端数据模型以支持布尔值标记的配套附件,保持打印和甘特图服务的兼容性。

## Technical Context

**Language/Version**: 
- 后端: Python 3.10
- 前端: TypeScript 5.8.0, Node.js ^20.19.0 || >=22.12.0

**Primary Dependencies**:
- 后端: Flask 2.3.3, Flask-SQLAlchemy 3.0.5, PyMySQL 1.1.0, Pillow 10.0.0
- 前端: Vue 3.5.18, Element Plus 2.11.1, Pinia 3.0.3, Vite 7.0.6, ECharts 6.0.0

**Storage**: MySQL (通过PyMySQL驱动)

**Testing**: 
- 后端: pytest (待确认版本)
- 前端: Vitest (待确认配置)

**Target Platform**: 
- 后端: Linux服务器 (Docker容器部署)
- 前端: 现代浏览器 (Chrome/Firefox/Safari/Edge)

**Project Type**: 前后端分离 (web)

**Performance Goals**: 
- 附件选择界面渲染和交互响应 < 1秒
- 订单创建API响应时间 < 500ms
- 打印服务响应时间 < 3秒

**Constraints**:
- 必须保持与现有打印系统(顺丰API + 快麦云打印)的兼容性
- 历史订单数据必须正确显示
- 甘特图附件显示功能不能中断

**Scale/Scope**:
- 影响2个主要UI组件
- 涉及4-5个后端服务模块
- 需要数据库schema迁移
- 预计影响约15-20个文件

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### 检查项

#### ✅ I. 中文文档规范
- 所有规范文档、计划文档、任务描述均使用中文 ✓
- 代码注释将使用中文 ✓
- 提交信息将使用中文 ✓

#### ⚠️ 其他原则
**状态**: Constitution文件为模板状态,项目特定原则尚未定义。

**处理方式**: 在Phase 1设计完成后,建议与团队确认并补充项目Constitution中的具体原则(如测试策略、代码规范、部署流程等)。

### 结论
**可以继续进入Phase 0研究阶段**。唯一识别的原则(中文文档规范)已满足。

## Project Structure

### Documentation (this feature)

```text
specs/001-simplify-rental-accessories/
├── spec.md              # 功能规范
├── plan.md              # 本文件 (/speckit.plan 输出)
├── research.md          # Phase 0 输出 (技术调研)
├── data-model.md        # Phase 1 输出 (数据模型设计)
├── quickstart.md        # Phase 1 输出 (快速开始指南)
├── contracts/           # Phase 1 输出 (API合约)
│   └── api-spec.yaml   # OpenAPI规范
├── checklists/          # 质量检查清单
│   └── requirements.md # 需求验证清单
└── tasks.md             # Phase 2 输出 (/speckit.tasks 生成)
```

### Source Code (repository root)

```text
InventoryManager/
├── app/                          # 后端应用
│   ├── models/                   # 数据模型层
│   │   ├── rental.py            # [修改] 租赁模型 - 添加手柄/镜头支架布尔字段
│   │   ├── device.py            # [不变] 设备模型
│   │   └── device_model.py      # [不变] 设备型号模型
│   │
│   ├── routes/                   # API路由层
│   │   ├── rental_api.py        # [可能修改] 租赁API路由
│   │   ├── gantt_api.py         # [审查] 甘特图API - 确认附件显示逻辑
│   │   └── shipping_batch_api.py # [审查] 发货批次API
│   │
│   ├── services/                 # 业务逻辑层
│   │   ├── rental/
│   │   │   └── rental_service.py # [修改] 租赁服务 - 调整附件创建逻辑
│   │   ├── shipping/
│   │   │   ├── sf_express_service.py    # [审查] 顺丰API
│   │   │   └── waybill_print_service.py # [审查] 面单打印服务
│   │   └── printing/
│   │       ├── kuaimai_service.py       # [不变] 快麦打印
│   │       └── shipping_slip_image_service.py # [审查] 发货单生成 - 确认附件显示
│   │
│   ├── handlers/                 # 请求处理器
│   │   └── rental_handlers.py   # [可能修改] 租赁处理器
│   │
│   └── utils/                    # 工具函数
│       └── response.py          # [不变] 响应格式化
│
├── frontend/                     # 前端应用 (PC端)
│   ├── src/
│   │   ├── components/
│   │   │   ├── BookingDialog.vue           # [重要修改] 预订对话框 - UI改造
│   │   │   ├── GanttChart.vue             # [审查] 甘特图主组件
│   │   │   ├── GanttRow.vue               # [审查] 甘特图行组件
│   │   │   └── rental/
│   │   │       ├── EditRentalDialogNew.vue      # [修改] 编辑对话框
│   │   │       └── RentalAccessorySelector.vue   # [重要修改] 附件选择器 - UI改造
│   │   │
│   │   ├── views/
│   │   │   ├── GanttView.vue              # [审查] 甘特图视图
│   │   │   └── BatchShippingView.vue      # [审查] 批量发货视图
│   │   │
│   │   ├── stores/
│   │   │   └── gantt.ts                   # [可能修改] 甘特图状态管理
│   │   │
│   │   ├── composables/
│   │   │   ├── useDeviceManagement.ts     # [审查] 设备管理钩子
│   │   │   └── useAvailabilityCheck.ts    # [可能修改] 可用性检查逻辑
│   │   │
│   │   └── types/
│   │       └── rental.ts                  # [新增] TypeScript类型定义
│   │
│   └── tests/
│       ├── unit/
│       │   └── RentalAccessorySelector.spec.ts # [新增] 组件单元测试
│       └── integration/
│           └── rental-flow.spec.ts        # [新增] 租赁流程集成测试
│
├── migrations/                   # 数据库迁移
│   └── versions/
│       └── [timestamp]_add_bundled_accessory_flags.py # [新增] 迁移脚本
│
└── tests/                        # 后端测试
    ├── unit/
    │   ├── test_rental_model.py          # [新增] 模型测试
    │   └── test_rental_service.py        # [修改] 服务测试
    └── integration/
        ├── test_rental_api.py            # [修改] API集成测试
        └── test_print_services.py        # [新增] 打印服务测试
```

**Structure Decision**: 
本项目采用典型的Web应用前后端分离架构:
- **后端** (`app/`): Flask应用,分层清晰(models → services → handlers → routes)
- **前端** (`frontend/`): Vue 3 SPA,组件化设计,使用Composables模式
- **迁移** (`migrations/`): Flask-Migrate管理数据库schema变更

此功能主要修改:
1. **前端UI层**: `BookingDialog.vue`和`RentalAccessorySelector.vue`的附件选择部分
2. **后端数据层**: `Rental`模型添加布尔字段
3. **后端业务层**: `rental_service.py`的附件处理逻辑
4. **打印和可视化层**: 审查并确保兼容性(不做大改)

## Complexity Tracking

> **当前无Constitution违规需要说明**

本功能是对现有附件选择流程的简化,不引入新的架构复杂度。所有变更都在现有模块内进行,遵循当前的设计模式。

---

## Phase 0: Outline & Research

**状态**: ✅ 已完成

**输出文件**: [research.md](./research.md)

**主要决策**:
1. **数据模型方案**: 选择在`Rental`表添加布尔字段(`includes_handle`, `includes_lens_mount`)
2. **前端UI组件**: 使用Element Plus的`el-checkbox`和`el-checkbox-group`
3. **历史数据处理**: 通过迁移脚本转换,保留旧记录作为备份
4. **打印服务**: 调整发货单生成逻辑,面单无需修改(由顺丰API生成)
5. **性能优化**: 添加数据库索引,使用`joinedload`避免N+1查询

## Phase 1: Design & Contracts

**状态**: ✅ 已完成

**输出文件**:
- [data-model.md](./data-model.md) - 数据模型设计
- [contracts/api-spec.yaml](./contracts/api-spec.yaml) - API合约规范
- [quickstart.md](./quickstart.md) - 快速开始指南

**关键设计**:
1. **Rental模型扩展**: 添加2个布尔字段,10个新方法
2. **API接口**: 扩展现有`POST /api/rentals`和`PUT /api/rentals/{id}`
3. **数据迁移**: 设计完整的upgrade和downgrade脚本
4. **TypeScript类型**: 定义`RentalFormData`和`RentalCreatePayload`接口

**Constitution复查**: 所有设计遵循"中文文档规范"原则,无新增违规项。

## Phase 2: Task Generation

*(通过 /speckit.tasks 命令执行)*

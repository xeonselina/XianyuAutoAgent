# Implementation Plan: 设备验货系统

**Branch**: `002-device-inspection` | **Date**: 2026-01-04 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `/specs/002-device-inspection/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

为设备租赁管理系统添加验货功能，使工作人员能够在 iPad 上通过输入设备编号快速完成设备验货。系统将自动关联最近的租赁记录，根据订单内容动态生成检查清单（包括基础检查项和附件检查项），记录验货结果并支持查询和编辑历史验货记录。

**技术方法**: 
- 后端新增验货记录（InspectionRecord）和验货检查项（InspectionCheckItem）模型
- 扩展租赁记录（Rental）模型，添加"代传照片"字段
- 前端新增验货页面和验货记录管理页面，采用移动优先的响应式设计适配 iPad
- 使用 RESTful API 实现前后端交互

## Technical Context

**Language/Version**: 
- Backend: Python 3.10
- Frontend: TypeScript + Vue 3.5

**Primary Dependencies**: 
- Backend: Flask 2.3.3, Flask-SQLAlchemy 3.0.5, PyMySQL 1.1.0
- Frontend: Vue 3.5, Element Plus 2.11, Pinia 3.0, Vue Router 4.5, Axios 1.11

**Storage**: MySQL (通过 Flask-SQLAlchemy ORM)

**Testing**: 
- Backend: pytest
- Frontend: Vitest + Vue Test Utils

**Target Platform**: 
- Backend: Linux server (Docker 容器化部署)
- Frontend: 现代浏览器，特别优化 iPad Safari 体验

**Project Type**: Web application (前后端分离)

**Performance Goals**: 
- 验货记录查询响应时间 < 2 秒
- 设备编号查询租赁信息响应时间 < 1 秒
- 支持至少 5 个工作人员并发验货操作
- 验货表单提交响应时间 < 3 秒

**Constraints**: 
- 验货页面必须支持 iPad 触屏操作
- 数字输入框必须自动弹出数字键盘
- 验货清单动态生成准确率 100%
- 验货记录数据完整性 100%（不允许数据丢失）
- 网络中断时需要明确提示用户（不支持离线缓存）

**Scale/Scope**: 
- 预计日均验货量: 20-50 条
- 验货记录保留期: 永久保留（用于审计追溯）
- 并发用户数: 5-10 人
- 检查项数量: 5 个基础检查项 + 0-10 个动态检查项

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Principle I: 中文文档规范

- ✅ **符合**: 所有规格说明、实施计划、任务描述使用中文
- ✅ **符合**: 代码注释使用中文
- ✅ **符合**: 数据库模型、API 端点命名使用英文（符合例外规则）

### 项目一致性检查

- ✅ **符合**: 使用现有技术栈（Flask + Vue 3），不引入新的框架
- ✅ **符合**: 遵循现有项目结构（backend/app/models, frontend/src/views）
- ✅ **符合**: 使用现有数据库（MySQL）和 ORM（SQLAlchemy）
- ✅ **符合**: API 设计遵循现有 RESTful 风格

### 复杂度检查

- ✅ **无额外复杂度**: 使用现有架构和模式，无需引入新的架构组件
- ✅ **数据模型简单**: 仅新增 2 个实体（InspectionRecord, InspectionCheckItem），扩展 1 个实体（Rental）
- ✅ **UI 复杂度可控**: 新增 2 个页面（验货表单页、验货记录列表页），可复用现有组件

**评估结果**: ✅ 通过所有宪法检查

## Project Structure

### Documentation (this feature)

```text
specs/002-device-inspection/
├── spec.md              # 功能规格说明
├── plan.md              # 本文件 - 实施计划
├── research.md          # Phase 0 技术调研结果
├── data-model.md        # Phase 1 数据模型设计
├── quickstart.md        # Phase 1 快速开发指南
├── contracts/           # Phase 1 API 接口定义
│   ├── inspection-api.yaml       # 验货相关 API (OpenAPI)
│   └── rental-extension-api.yaml # 租赁记录扩展 API (OpenAPI)
├── checklists/          # 质量检查清单
│   └── requirements.md  # 需求质量检查
└── tasks.md             # Phase 2 任务分解（由 /speckit.tasks 生成）
```

### Source Code (repository root)

```text
backend/
└── app/
    ├── models/
    │   ├── inspection_record.py    # 新增：验货记录模型
    │   ├── inspection_check_item.py # 新增：验货检查项模型
    │   └── rental.py               # 修改：添加 photo_transfer 字段
    │
    ├── routes/
    │   ├── inspection_api.py       # 新增：验货 API 路由
    │   └── rental_api.py           # 修改：添加代传照片字段
    │
    ├── services/
    │   ├── inspection_service.py   # 新增：验货业务逻辑
    │   └── checklist_generator.py  # 新增：动态检查清单生成
    │
    └── __init__.py                 # 修改：注册新的蓝图

frontend/
└── src/
    ├── views/
    │   ├── InspectionView.vue          # 新增：验货表单页面
    │   └── InspectionRecordsView.vue   # 新增：验货记录列表页面
    │
    ├── components/
    │   └── inspection/
    │       ├── DeviceSearch.vue        # 新增：设备编号搜索组件
    │       ├── RentalInfo.vue          # 新增：租赁信息展示组件
    │       ├── ChecklistForm.vue       # 新增：验货检查清单组件
    │       └── InspectionRecordCard.vue # 新增：验货记录卡片组件
    │
    ├── stores/
    │   └── inspection.ts               # 新增：验货状态管理
    │
    ├── services/
    │   └── inspectionApi.ts            # 新增：验货 API 调用服务
    │
    └── router/
        └── index.ts                    # 修改：添加验货相关路由

migrations/
└── versions/
    └── xxxx_add_inspection_tables.py   # 新增：数据库迁移脚本
```

**Structure Decision**: 
采用现有的 Web 应用结构（Option 2），后端使用 Flask 提供 RESTful API，前端使用 Vue 3 构建单页应用。新增功能完全符合现有项目结构，无需重构或调整架构。

## Complexity Tracking

> 无需填写 - 本功能未引入任何违反宪法原则的复杂度。

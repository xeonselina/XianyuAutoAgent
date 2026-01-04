# Tasks: 简化租赁附件选择

**Input**: Design documents from `/specs/001-simplify-rental-accessories/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api-spec.yaml

**Tests**: 本规范未明确要求TDD方法,测试任务设为可选,建议在实现后编写。

**Organization**: 任务按用户故事分组,每个故事可独立实现和测试。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行(不同文件,无依赖)
- **[Story]**: 任务所属用户故事(US1, US2, US3)
- 包含精确文件路径

## Path Conventions

- **后端**: `app/models/`, `app/services/`, `app/routes/`
- **前端**: `frontend/src/components/`, `frontend/src/types/`
- **迁移**: `migrations/versions/`
- **测试**: `tests/unit/`, `tests/integration/`, `frontend/tests/unit/`

---

## Phase 1: Setup (共享基础设施)

**目的**: 环境准备和数据库迁移

- [ ] T001 备份生产数据库到 backup_before_accessory_simplification_$(date +%Y%m%d_%H%M%S).sql
- [ ] T002 生成数据库迁移脚本 flask db migrate -m "添加配套附件标记字段" 在 migrations/versions/
- [ ] T003 [P] 审查并调整迁移脚本 migrations/versions/[timestamp]_add_bundled_accessory_flags.py 添加数据迁移逻辑
- [ ] T004 在开发环境执行迁移 flask db upgrade 并验证字段添加成功
- [ ] T005 [P] 运行数据完整性验证SQL检查 includes_handle 和 includes_lens_mount 字段迁移正确性

---

## Phase 2: Foundational (阻塞前置条件)

**目的**: 核心模型和验证器,所有用户故事依赖

**⚠️ 关键**: 所有用户故事工作必须等待此阶段完成

- [ ] T006 在 app/models/rental.py 添加新字段 includes_handle 和 includes_lens_mount (Boolean, default=False)
- [ ] T007 在 app/models/rental.py 更新 to_dict() 方法包含新的配套附件字段
- [ ] T008 [P] 在 app/models/rental.py 实现 get_all_accessories_for_display() 方法返回配套附件和库存附件列表
- [ ] T009 [P] 在 app/models/rental.py 实现 _infer_accessory_type() 辅助方法根据设备名称识别附件类型
- [ ] T010 [P] 创建 app/utils/rental_validator.py 实现 RentalValidator 类包含 validate_create_data() 和 validate_update_data() 方法

**Checkpoint**: 基础模型和验证器就绪 - 用户故事实现现在可以并行开始

---

## Phase 3: User Story 1 - 创建租赁订单时选择附件 (Priority: P1) 🎯 MVP

**目标**: 简化附件选择界面,手柄和镜头支架改为复选框,手机支架和三脚架保持下拉选择

**独立测试**: 创建完整租赁订单并验证附件选择界面变化,确认手柄和镜头支架显示为复选框,手机支架保持下拉选择

### 后端实现 User Story 1

- [ ] T011 [P] [US1] 在 app/services/rental/rental_service.py 更新 create_rental_with_accessories() 方法接受 includes_handle 和 includes_lens_mount 参数
- [ ] T012 [P] [US1] 在 app/services/rental/rental_service.py 调整附件创建逻辑,只为手机支架和三脚架创建子租赁记录,不为手柄和镜头支架创建
- [ ] T013 [US1] 在 app/handlers/rental_handlers.py 的 handle_create_rental() 方法中提取新的布尔参数并传递给服务层
- [ ] T014 [US1] 在 app/routes/rental_api.py 验证 POST /api/rentals 端点接受 includes_handle, includes_lens_mount, accessory_ids 参数
- [ ] T015 [US1] 在 app/services/rental/rental_service.py 实现 update_rental_with_accessories() 方法支持更新附件配置

### 前端实现 User Story 1

- [ ] T016 [P] [US1] 创建 frontend/src/types/rental.ts 定义 AccessorySelection, RentalFormData, RentalCreatePayload 接口
- [ ] T017 [US1] 在 frontend/src/components/BookingDialog.vue 将手柄和镜头支架的下拉选择器替换为 el-checkbox-group (约第175-250行)
- [ ] T018 [US1] 在 frontend/src/components/BookingDialog.vue 实现 computed 属性 createPayload 转换 bundledAccessories 数组为 includes_handle 和 includes_lens_mount 布尔值
- [ ] T019 [US1] 在 frontend/src/components/rental/RentalAccessorySelector.vue 重构附件选择器,配套附件用复选框,库存附件用下拉框
- [ ] T020 [US1] 在 frontend/src/components/rental/EditRentalDialogNew.vue 实现 loadRentalData() 方法正确加载历史订单的配套附件状态到复选框
- [ ] T021 [US1] 在 frontend/src/components/rental/EditRentalDialogNew.vue 更新表单提交逻辑使用新的API格式 (includes_handle, includes_lens_mount, accessory_ids)

### 测试 User Story 1 (可选)

- [ ] T022 [P] [US1] 编写 tests/unit/test_rental_service.py 测试 create_rental_with_bundled_accessories() 和 create_rental_with_mixed_accessories()
- [ ] T023 [P] [US1] 编写 tests/integration/test_rental_api.py 测试 POST /api/rentals 和 PUT /api/rentals/{id} 端点附件参数处理
- [ ] T024 [P] [US1] 编写 frontend/tests/unit/RentalAccessorySelector.spec.ts 测试复选框显示和历史数据加载

**Checkpoint**: 此时User Story 1应该完全功能且可独立测试。工作人员可以创建和编辑订单,选择配套附件和库存附件。

---

## Phase 4: User Story 2 - 打印面单和发货单 (Priority: P1)

**目标**: 确保打印系统正确显示所有附件信息(配套附件和库存附件)

**独立测试**: 创建包含各种附件组合的订单,打印面单和发货单,验证所有附件信息正确显示

**依赖**: User Story 1 (需要能创建包含配套附件的订单进行测试)

### 实现 User Story 2

- [ ] T025 [P] [US2] 在 app/services/printing/shipping_slip_image_service.py 更新 _draw_accessories_section() 方法调用 rental.get_all_accessories_for_display()
- [ ] T026 [P] [US2] 在 app/services/printing/shipping_slip_image_service.py 修改附件显示逻辑,配套附件显示为 "✓ 手柄 (配套)",库存附件显示具体编号
- [ ] T027 [US2] 审查 app/services/shipping/waybill_print_service.py 确认面单打印流程无需修改(由顺丰API生成)
- [ ] T028 [US2] 在 app/routes/shipping_batch_api.py 验证 POST /shipping-batch/generate-packing-slip 端点正确传递附件信息

### 测试 User Story 2 (可选)

- [ ] T029 [P] [US2] 编写 tests/integration/test_print_services.py 测试发货单生成包含配套附件和库存附件的各种组合
- [ ] T030 [US2] 手动测试打印发货单,验证配套附件显示为 "(配套)" 标记,库存附件显示序列号

**Checkpoint**: 此时User Story 1和2都应该独立工作。打印系统能够正确显示新旧两种附件信息格式。

---

## Phase 5: User Story 3 - 甘特图显示附件信息 (Priority: P2)

**目标**: 甘特图工具提示正确显示订单的所有附件信息(配套和库存)

**独立测试**: 在甘特图中查看包含不同附件组合的订单,验证附件信息正确显示并区分配套/库存附件

**依赖**: User Story 1 (需要能创建包含配套附件的订单数据)

### 后端实现 User Story 3

- [ ] T031 [P] [US3] 在 app/routes/gantt_api.py 更新 format_rental_for_gantt() 函数调用 rental.get_all_accessories_for_display()
- [ ] T032 [P] [US3] 在 app/routes/gantt_api.py 确保 GET /api/gantt/data 响应包含 accessories 数组,每个附件包含 is_bundled 字段
- [ ] T033 [US3] 审查甘特图API的性能,确保使用 joinedload 避免 N+1 查询加载附件信息

### 前端实现 User Story 3

- [ ] T034 [P] [US3] 在 frontend/src/components/GanttRow.vue 更新工具提示模板显示 rental.accessories 数组
- [ ] T035 [P] [US3] 在 frontend/src/components/GanttRow.vue 为配套附件添加 <el-tag type="info">配套</el-tag> 标签
- [ ] T036 [US3] 在 frontend/src/stores/gantt.ts 审查状态管理确保附件数据结构正确传递

### 测试 User Story 3 (可选)

- [ ] T037 [P] [US3] 编写集成测试验证甘特图API返回正确的附件数据格式
- [ ] T038 [US3] 手动测试甘特图,悬停订单条验证工具提示显示所有附件并正确标记配套/库存

**Checkpoint**: 所有用户故事现在应该独立功能完整。创建订单、打印单据、甘特图可视化三个流程都能正确处理新的附件模型。

---

## Phase 6: Polish & Cross-Cutting Concerns

**目的**: 影响多个用户故事的改进和完善

- [ ] T039 [P] 在 app/models/rental.py 添加数据库索引 CREATE INDEX idx_rentals_includes_handle, idx_rentals_includes_lens_mount (如需要)
- [ ] T040 [P] 编写 tests/unit/test_rental_model.py 测试新方法 get_all_accessories_for_display(), _infer_accessory_type(), is_main_rental()
- [ ] T041 [P] 在相关Python文件添加中文注释说明配套附件和库存附件的区别
- [ ] T042 审查 frontend/src/composables/useAvailabilityCheck.ts 确保附件可用性检查逻辑对库存附件仍然有效
- [ ] T043 审查 frontend/src/composables/useDeviceManagement.ts 确认设备加载逻辑区分配套附件设备和库存附件设备
- [ ] T044 [P] 性能测试: 使用 pytest-benchmark 测试 get_all_accessories_for_display() 方法性能
- [ ] T045 [P] 性能测试: 前端使用 Lighthouse 测试订单创建界面渲染性能 (目标<1秒)
- [ ] T046 执行 quickstart.md 中的完整测试场景验证所有功能流程
- [ ] T047 [P] 更新 CODEBUDDY.md 和其他agent上下文文件反映新的数据模型和API变更
- [ ] T048 代码审查: 检查所有文件确保遵循中文注释规范(Constitution原则)
- [ ] T049 安全审查: 验证 RentalValidator 正确验证 includes_handle 和 includes_lens_mount 参数防止注入攻击
- [ ] T050 准备生产部署清单: 备份脚本、迁移验证SQL、回滚计划

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可立即开始
- **Foundational (Phase 2)**: 依赖Setup完成 - **阻塞所有用户故事**
- **User Stories (Phase 3-5)**: 全部依赖Foundational阶段完成
  - US1 可以在Foundational后立即开始
  - US2 依赖US1 (需要能创建测试数据)
  - US3 依赖US1 (需要能创建测试数据)
  - 如果有多人,US1/US2/US3可在各自测试数据准备好后并行工作
- **Polish (Phase 6)**: 依赖所需用户故事完成

### User Story Dependencies

- **User Story 1 (P1) - MVP**: Foundational完成后即可开始 - 无其他用户故事依赖
- **User Story 2 (P1)**: 依赖US1完成(需要订单数据测试打印)
- **User Story 3 (P2)**: 依赖US1完成(需要订单数据测试甘特图)

### Within Each User Story

- 后端模型 → 后端服务 → 后端API → 前端类型 → 前端UI
- 核心实现 → 集成测试 → 边缘情况处理
- 故事完成再移至下一优先级

### Parallel Opportunities

- **Phase 1**: T003, T005 可并行(不同文件)
- **Phase 2**: T008, T009, T010 可并行(不同文件)
- **US1 后端**: T011, T012 可并行(同文件但不同函数)
- **US1 前端**: T016, T017, T019 可并行(不同文件)
- **US1 测试**: T022, T023, T024 可并行(不同测试文件)
- **US2**: T025, T026, T027 可并行(不同文件)
- **US3 后端**: T031, T032 可并行(同文件但可能不同函数)
- **US3 前端**: T034, T035 可并行(同组件内不同部分)
- **Polish**: T039, T040, T041, T044, T045, T047 可并行(完全不同文件)

---

## Parallel Example: User Story 1 后端

```bash
# 同时启动US1后端任务(不同文件或不同函数):
Task: "在 app/services/rental/rental_service.py 更新 create_rental_with_accessories()"
Task: "在 app/services/rental/rental_service.py 实现 update_rental_with_accessories()"
# 注意: T011和T012在同一文件,需要协调或使用分支合并
```

## Parallel Example: User Story 1 前端

```bash
# 同时启动US1前端任务(不同文件):
Task: "创建 frontend/src/types/rental.ts 定义类型接口"
Task: "在 frontend/src/components/BookingDialog.vue 重构附件选择UI"
Task: "在 frontend/src/components/rental/RentalAccessorySelector.vue 重构组件"
```

---

## Implementation Strategy

### MVP First (仅User Story 1)

1. 完成 Phase 1: Setup (数据库迁移)
2. 完成 Phase 2: Foundational (模型和验证器) - **关键 - 阻塞所有故事**
3. 完成 Phase 3: User Story 1 (附件选择简化)
4. **停止并验证**: 独立测试User Story 1
   - 创建订单,勾选手柄复选框,选择手机支架
   - 编辑订单,修改附件配置
   - 验证API返回正确数据
5. 如果就绪,部署/演示MVP

### Incremental Delivery (推荐)

1. 完成 Setup + Foundational → 基础就绪
2. 添加 User Story 1 → 独立测试 → 部署/演示 (MVP!)
   - **价值**: 工作人员立即受益于简化的附件选择流程
3. 添加 User Story 2 → 独立测试 → 部署/演示
   - **价值**: 仓库人员能在发货单上看到新的附件标记
4. 添加 User Story 3 → 独立测试 → 部署/演示
   - **价值**: 管理人员在甘特图上获得更清晰的附件可视化
5. 每个故事增加价值而不破坏之前故事

### Parallel Team Strategy

如果有多个开发者:

1. 团队一起完成 Setup + Foundational
2. Foundational完成后:
   - **开发者A**: User Story 1 (附件选择UI + 后端)
   - **开发者B**: 等待US1数据后开始 User Story 2 (打印服务)
   - **开发者C**: 等待US1数据后开始 User Story 3 (甘特图)
3. 或者US1完成后,US2和US3可并行开发

**注意**: US2和US3都依赖US1提供测试数据,所以现实中是US1→(US2||US3)的执行顺序

---

## Task Count Summary

- **Setup**: 5 tasks
- **Foundational**: 5 tasks (阻塞)
- **User Story 1 (P1 - MVP)**: 14 tasks (后端5 + 前端6 + 测试3)
- **User Story 2 (P1)**: 6 tasks (实现4 + 测试2)
- **User Story 3 (P2)**: 8 tasks (后端3 + 前端3 + 测试2)
- **Polish**: 12 tasks
- **Total**: 50 tasks

**Parallel Opportunities**: 约30%的任务可并行执行(标记为[P])

**MVP Scope** (最小可行产品):
- Setup (5) + Foundational (5) + User Story 1 (14) = **24 tasks**
- 预计: 3-4个工作日完成MVP

**Full Feature** (所有用户故事):
- Setup (5) + Foundational (5) + US1 (14) + US2 (6) + US3 (8) + Polish (12) = **50 tasks**
- 预计: 5-6.5个工作日完成全部功能

---

## Notes

- [P] 任务 = 不同文件,无依赖,可并行
- [Story] 标签映射任务到具体用户故事以便追溯
- 每个用户故事应该独立完成和测试
- 在任何checkpoint停止以独立验证故事
- 提交每个任务或逻辑组后的代码
- 避免: 模糊任务、同文件冲突、破坏独立性的跨故事依赖

---

## Validation Checklist

完成所有任务后,验证:

- [ ] 工作人员可以创建订单,手柄和镜头支架显示为复选框
- [ ] 工作人员可以编辑订单,修改配套附件配置
- [ ] 历史订单在新界面正确显示配套附件状态
- [ ] 发货单打印正确显示配套附件 "(配套)" 标记和库存附件编号
- [ ] 面单打印不受影响(由顺丰API生成)
- [ ] 甘特图工具提示显示所有附件并区分配套/库存
- [ ] 数据库迁移正确,includes_handle 和 includes_lens_mount 字段已添加
- [ ] 历史数据迁移准确,布尔值正确反映旧的子租赁记录
- [ ] API性能满足要求: 订单创建<500ms, 附件选择界面<1秒, 打印<3秒
- [ ] 所有代码包含中文注释(遵循Constitution)
- [ ] 无数据丢失,打印和甘特图功能未中断

---

**生成日期**: 2026-01-04  
**预估工作量**: MVP 3-4天 / 全功能 5-6.5天  
**下一步**: 开始 Phase 1 Setup 任务,或运行 `/speckit.implement` 自动执行

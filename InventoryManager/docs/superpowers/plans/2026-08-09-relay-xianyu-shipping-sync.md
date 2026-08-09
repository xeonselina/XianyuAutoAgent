# 接力已寄出联动后一单与闲鱼发货 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接力首次变为 `shipped` 时，在同一事务中同步后一单 rental 的发货状态与运单，并在提交后调用闲鱼发货服务，把结果反馈给桌面端和移动端操作员。

**Architecture:** `RelayCaseService.update_case()` 负责本地事务和提交后的闲鱼编排，并通过 `RelayCaseUpdateOutcome` 返回接力记录与规范化同步结果。HTTP handler 保留现有顺丰轨迹刷新流程并扩展 mutation payload；两个前端只根据新增的 `xianyu_sync` 字段选择成功或警告提示。

**Tech Stack:** Flask, SQLAlchemy, pytest, Vue 3, TypeScript, Element Plus, Vant, Vitest

## Global Constraints

- 只在旧状态早于 `shipped` 且目标状态恰好为 `shipped` 时联动和上报闲鱼。
- 接力记录、后一单 rental、绑定、里程碑和审计必须在同一数据库事务中提交。
- 闲鱼调用必须发生在本地提交之后；失败不得回滚本地“已寄出”状态。
- 不增加数据库字段、迁移、自动重试、后台队列或新重试按钮。
- 保留现有顺丰运单校验、物流刷新、状态机和绑定规则。

---

### Task 1: 后端本地联动与闲鱼编排

**Files:**
- Modify: `InventoryManager/app/services/relay/relay_case_service.py`
- Test: `InventoryManager/tests/unit/test_relay_case_transitions.py`

**Interfaces:**
- Consumes: `get_xianyu_service().ship_order(successor: Rental) -> dict`
- Produces: `RelayCaseUpdateOutcome(relay_case: RentalRelayCase, xianyu_sync: dict)`；`RelayCaseService.update_case(...) -> RelayCaseUpdateOutcome`

- [ ] **Step 1: 写首次进入 `shipped` 的失败测试**

  在 `test_relay_case_transitions.py` 增加用例：给后一单设置闲鱼订单号，替换外部闲鱼服务为成功 fake，调用 `update_case(..., "shipped", sf_tracking_number="SF123")`，断言后一单的 `ship_out_tracking_no == "SF123"`、`status == "shipped"`、空的 `ship_out_time` 被写入传入的 `now`，并断言 outcome 的 `xianyu_sync` 为成功。

- [ ] **Step 2: 运行测试并确认因缺少联动而失败**

  Run: `cd InventoryManager && pytest tests/unit/test_relay_case_transitions.py -q`

  Expected: FAIL，后一单仍为 `not_shipped` 或返回值不存在 `xianyu_sync`。

- [ ] **Step 3: 实现最小本地联动和提交后调用**

  在服务模块新增冻结 dataclass：

  ```python
  @dataclass(frozen=True)
  class RelayCaseUpdateOutcome:
      relay_case: RentalRelayCase
      xianyu_sync: dict
  ```

  计算 `entering_shipped = STATUS_ORDER[old_status] < STATUS_ORDER["shipped"] and status == "shipped"`。为真时，在提交前设置：

  ```python
  successor.ship_out_tracking_no = tracking_number
  successor.status = "shipped"
  if successor.ship_out_time is None:
      successor.ship_out_time = now
  ```

  本地 `commit()` 成功后才调用 `get_xianyu_service().ship_order(successor)`；将成功、业务失败或异常统一转换为 `{attempted, success, message}`。非首次进入 `shipped` 返回 `attempted=False`。

- [ ] **Step 4: 增加失败与幂等回归测试**

  分别覆盖：后一单已有 `ship_out_time` 时不覆盖；闲鱼返回失败或抛异常时本地仍提交；重复保存 `shipped`、直接改 `completed` 时不再次调用；提交前审计异常时闲鱼不调用且本地回滚。

- [ ] **Step 5: 运行后端单元测试**

  Run: `cd InventoryManager && pytest tests/unit/test_relay_case_transitions.py tests/unit/test_relay_case_tracking.py -q`

  Expected: PASS。

### Task 2: API 返回闲鱼同步结果并保留顺丰刷新

**Files:**
- Modify: `InventoryManager/app/handlers/relay_case_handlers.py`
- Test: `InventoryManager/tests/integration/test_relay_case_api.py`

**Interfaces:**
- Consumes: `RelayCaseUpdateOutcome`
- Produces: mutation payload 的可选字段 `xianyu_sync: { attempted: bool, success: bool, message: str }`

- [ ] **Step 1: 写 API 失败测试**

  新增或扩展 `PUT /api/relay-cases/{predecessor}/{successor}` 用例，替换闲鱼外部调用与顺丰查询，断言 HTTP 200、后一单已写入运单和 `shipped` 状态、响应含 `xianyu_sync`，且顺丰刷新仍返回轨迹摘要。

- [ ] **Step 2: 运行测试并确认响应缺少 `xianyu_sync`**

  Run: `cd InventoryManager && pytest tests/integration/test_relay_case_api.py -q`

  Expected: FAIL，handler 仍把 outcome 当作 relay case 或 payload 不含同步结果。

- [ ] **Step 3: 适配 handler**

  从 outcome 取 `relay_case` 继续执行现有 `refresh_tracking()`；调用 `_case_payload()` 后加入 `payload["xianyu_sync"] = outcome.xianyu_sync` 并返回。

- [ ] **Step 4: 运行接力后端测试**

  Run: `cd InventoryManager && pytest tests/unit/test_relay_case_service.py tests/unit/test_relay_case_transitions.py tests/unit/test_relay_case_tracking.py tests/integration/test_relay_case_api.py -q`

  Expected: PASS。

### Task 3: 桌面端同步提示

**Files:**
- Modify: `InventoryManager/frontend/src/types/relayCase.ts`
- Modify: `InventoryManager/frontend/src/components/relay/RelayStatusDialog.vue`
- Test: `InventoryManager/frontend/tests/unit/components/RelayStatusDialog.spec.ts`

**Interfaces:**
- Consumes: `RelayCaseMutationResponse.xianyu_sync?`
- Produces: 成功提示“接力状态已更新，已同步闲鱼”；失败警告“接力已标记已寄出，但闲鱼上报失败：{message}”

- [ ] **Step 1: 写提示行为失败测试**

  spy `ElMessage.success` 与 `ElMessage.warning`，分别让 API 返回成功及失败的 `xianyu_sync`；断言对应文案，且失败分支仍触发 `saved` 并关闭弹窗。

- [ ] **Step 2: 运行测试并确认旧通用提示导致失败**

  Run: `cd InventoryManager/frontend && npm run test:run -- tests/unit/components/RelayStatusDialog.spec.ts`

  Expected: FAIL，组件始终调用“接力状态已更新”。

- [ ] **Step 3: 扩展类型并实现提示选择**

  给 `RelayCaseMutationResponse` 增加可选 `xianyu_sync`，保存成功后根据 `attempted` 和 `success` 选择 `ElMessage.success` 或 `ElMessage.warning`；无字段时保留旧提示。

- [ ] **Step 4: 运行桌面端组件测试与构建**

  Run: `cd InventoryManager/frontend && npm run test:run -- tests/unit/components/RelayStatusDialog.spec.ts && npm run build`

  Expected: PASS。

### Task 4: 移动端同步提示与全量验证

**Files:**
- Modify: `InventoryManager/frontend-mobile/src/types/relayCase.ts`
- Modify: `InventoryManager/frontend-mobile/src/components/RelayStatusSheet.vue`

**Interfaces:**
- Consumes: `RelayCaseMutationResponse.xianyu_sync?`
- Produces: 与桌面端相同语义的成功/失败即时提示，同时失败仍刷新列表并关闭 sheet。

- [ ] **Step 1: 扩展移动端响应类型并使用 API 结果**

  保存时保留 `const result = await updateRelayCase(...)`；`attempted && success` 调用 `showSuccessToast`，`attempted && !success` 调用 Vant 普通 toast 展示警告文案，其余沿用旧成功提示。

- [ ] **Step 2: 运行移动端类型检查与构建**

  Run: `cd InventoryManager/frontend-mobile && npm run build`

  Expected: PASS。

- [ ] **Step 3: 运行最终后端和桌面端验证**

  Run: `cd InventoryManager && pytest tests/unit/test_relay_case_service.py tests/unit/test_relay_case_transitions.py tests/unit/test_relay_case_tracking.py tests/integration/test_relay_case_api.py -q`

  Run: `cd InventoryManager/frontend && npm run test:run -- tests/unit/components/RelayStatusDialog.spec.ts && npm run build`

  Run: `cd InventoryManager/frontend-mobile && npm run build`

  Expected: 所有命令退出码为 0。

- [ ] **Step 4: 审查差异和现有数据处理范围**

  Run: `git diff --check && git status --short`

  确认只修改计划内文件；现有已经处于 `shipped` 的历史接力不会被自动重复上报，需在得到明确授权后单独修复真实数据并调用闲鱼。

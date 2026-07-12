# 甘特图求解状态中文化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将一键重排预览中的 OR-Tools 英文求解状态转换为清晰的中文文案。

**Architecture:** 后端接口和执行判断继续使用英文状态码。前端组件通过纯展示映射生成表格数据副本，因此不会修改预览令牌、原始响应或可执行状态判断。

**Tech Stack:** Vue 3、TypeScript、Element Plus、Vitest、Vue Test Utils

## Global Constraints

- 仅修改前端展示，后端 API 状态码保持不变。
- `OPTIMAL`、`FEASIBLE`、`INFEASIBLE`、`UNKNOWN`、`MODEL_INVALID` 必须使用设计文档中的固定中文文案。
- 未识别的状态码显示“未知状态”，不得直接暴露英文内部值。
- 执行按钮仍仅以原始 `OPTIMAL` 和 `FEASIBLE` 状态判断是否可用。

---

### Task 1: 求解状态中文展示

**Files:**
- Modify: `InventoryManager/frontend/src/components/ScheduleReorderDialog.vue:90-105,190-220`
- Test: `InventoryManager/frontend/tests/unit/components/ScheduleReorderDialog.spec.ts:1-110`

**Interfaces:**
- Consumes: `ReorderPreview.models[].status: string` 返回的英文后端状态码。
- Produces: `formatSolverStatus(status: string): string` 和只供表格使用的 `localizedModels` 计算值；原始 `preview` 保持不变。

- [x] **Step 1: 写入失败测试**

将现有成功流程断言从英文改成中文：

```ts
expect(wrapper.text()).toContain('最优方案')
expect(wrapper.text()).not.toContain('OPTIMAL')
```

在同一个 `describe` 中增加参数化用例，逐项验证所有已知状态和未识别状态：

```ts
const statuses = [
  ['OPTIMAL', '最优方案'],
  ['FEASIBLE', '可行方案'],
  ['INFEASIBLE', '无可行方案'],
  ['UNKNOWN', '未得出结果'],
  ['MODEL_INVALID', '求解模型无效'],
  ['NEW_SOLVER_STATUS', '未知状态'],
  ['constructor', '未知状态'],
] as const

it.each(statuses)('将 %s 显示为 %s', async (status, label) => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useGanttStore()
  vi.spyOn(store, 'analyzeScheduleReorder').mockResolvedValue({
    today: '2026-07-12',
    overlaps: [],
  })
  vi.spyOn(store, 'previewScheduleReorder').mockResolvedValue({
    token: 'signed',
    models: [{
      model_id: 3,
      status,
      before_devices: 2,
      after_devices: 1,
      movable_rentals: 2,
      changed_rentals: 1,
      total_gap_days: 0,
    }],
    changes: [],
    skipped: [],
    overlaps: [],
  })

  const wrapper = mount(ScheduleReorderDialog, {
    props: { modelValue: true },
    global: {
      plugins: [pinia, ElementPlus],
      stubs: {
        ElDialog: {
          props: ['modelValue'],
          template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>',
        },
        ElTable: {
          props: ['data'],
          template: '<div>{{ JSON.stringify(data) }}</div>',
        },
        ElTableColumn: true,
        teleport: true,
        transition: false,
      },
    },
  })
  await flushPromises()
  await wrapper.get('[data-test="calculate-preview"]').trigger('click')
  await flushPromises()

  expect(wrapper.text()).toContain(label)
  expect(wrapper.text()).not.toContain(status)
})
```

- [x] **Step 2: 运行测试并确认按预期失败**

Run:

```bash
cd InventoryManager/frontend
npx vitest run tests/unit/components/ScheduleReorderDialog.spec.ts
```

Expected: FAIL，现有组件仍显示 `OPTIMAL`，页面中不存在“最优方案”。

- [x] **Step 3: 实现最小中文映射**

在 `ScheduleReorderDialog.vue` 的脚本区域加入：

```ts
const solverStatusLabels = new Map<string, string>([
  ['OPTIMAL', '最优方案'],
  ['FEASIBLE', '可行方案'],
  ['INFEASIBLE', '无可行方案'],
  ['UNKNOWN', '未得出结果'],
  ['MODEL_INVALID', '求解模型无效'],
])

const formatSolverStatus = (status: string) => {
  return solverStatusLabels.get(status) ?? '未知状态'
}

const localizedModels = computed(() => {
  return (preview.value?.models || []).map(model => ({
    ...model,
    status: formatSolverStatus(model.status),
  }))
})
```

将型号结果表格的数据源改为 `localizedModels`：

```vue
<el-table v-if="preview?.models.length" :data="localizedModels" border>
```

保留 `hasUnsolvedModel` 对 `preview.value.models` 原始英文状态的判断。

- [x] **Step 4: 运行目标测试并确认通过**

Run:

```bash
cd InventoryManager/frontend
npx vitest run tests/unit/components/ScheduleReorderDialog.spec.ts
```

Expected: PASS，现有流程用例和七个状态映射用例均通过。

- [x] **Step 5: 运行前端回归和构建验证**

Run:

```bash
cd InventoryManager/frontend
npm test -- --run
npm run build
```

Expected: 两条命令退出码均为 0；TypeScript 和 Vite 构建无错误。

- [x] **Step 6: 提交实现**

```bash
git add InventoryManager/frontend/src/components/ScheduleReorderDialog.vue InventoryManager/frontend/tests/unit/components/ScheduleReorderDialog.spec.ts
git commit -m "fix: localize gantt solver statuses"
```

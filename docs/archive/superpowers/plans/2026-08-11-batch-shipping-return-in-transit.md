# Batch Shipping Return-In-Transit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在桌面端批量发货列表中，将上一单状态为 `returned` 的设备显示为紫色“寄回在途”，并保持其他设备状态展示不变。

**Architecture:** 保留现有 API 字段和完成状态定义，只在 `BatchShippingView.vue` 的设备状态条件链中优先识别 `previous_rental_status === 'returned'`。通过挂载真实视图、向表格列插槽传入不同上一单状态的租赁数据，验证文字、标签类型和自定义颜色。

**Tech Stack:** Vue 3、TypeScript、Element Plus、Vue Test Utils、Vitest、happy-dom

## Global Constraints

- 仅修改桌面端批量发货视图；不修改后端或移动端。
- `returned` 标签文案必须为“寄回在途”，颜色必须为 `#7232dd`。
- `completed` 和 `cancelled` 继续显示绿色“✓ 设备在库”。
- `shipped` 等未完成状态继续显示红色“⚠ 上一单未结束”。
- 无上一单时继续显示 `-`。

---

### Task 1: 区分上一单“寄回在途”状态

**Files:**
- Create: `InventoryManager/frontend/tests/unit/views/BatchShippingView.spec.ts`
- Modify: `InventoryManager/frontend/src/views/BatchShippingView.vue:79-89`
- Regenerate: `InventoryManager/static/vue-dist/`

**Interfaces:**
- Consumes: API 已有字段 `has_previous_rental: boolean`、`previous_rental_status: string | null`、`previous_rental_completed: boolean | null`。
- Produces: “设备状态”列新增 `returned` 专用展示分支，不改变任何脚本接口或 API。

- [x] **Step 1: 写入视图回归测试**

在新测试文件中模拟 `vue-router`，用 Element Plus 挂载 `BatchShippingView`，并将 `ElTableColumn` 插槽渲染为指定租赁记录。核心断言如下：

```ts
it('shows a returned previous rental as purple return-in-transit', async () => {
  const wrapper = await mountWithRental({
    has_previous_rental: true,
    previous_rental_status: 'returned',
    previous_rental_completed: true,
  })

  const tag = wrapper.findAllComponents(ElTag)
    .find((item) => item.text().includes('寄回在途'))

  expect(tag).toBeDefined()
  expect(tag?.props('color')).toBe('#7232dd')
  expect(wrapper.text()).not.toContain('设备在库')
})

it.each([
  ['completed', true, '设备在库', 'success'],
  ['shipped', false, '上一单未结束', 'danger'],
])('keeps the %s previous-rental display unchanged', async (
  previous_rental_status,
  previous_rental_completed,
  expectedText,
  expectedType,
) => {
  const wrapper = await mountWithRental({
    has_previous_rental: true,
    previous_rental_status,
    previous_rental_completed,
  })

  const tag = wrapper.findAllComponents(ElTag)
    .find((item) => item.text().includes(expectedText))

  expect(tag?.props('type')).toBe(expectedType)
})

it('keeps a dash when the device has no previous rental', async () => {
  const wrapper = await mountWithRental({
    has_previous_rental: false,
    previous_rental_status: null,
    previous_rental_completed: null,
  })

  expect(wrapper.text()).toContain('-')
})
```

- [x] **Step 2: 运行新增测试并确认 RED**

Run:

```bash
cd InventoryManager/frontend
npm run test:run -- tests/unit/views/BatchShippingView.spec.ts
```

Expected: `returned` 用例失败，因为当前页面没有“寄回在途”标签；其他现状保护用例通过。

- [x] **Step 3: 写入最小模板实现**

在无上一单分支之后、`previous_rental_completed` 分支之前插入：

```vue
<el-tag
  v-else-if="row.previous_rental_status === 'returned'"
  color="#7232dd"
  effect="dark"
  size="small"
>
  寄回在途
</el-tag>
```

不修改后端 `previous_rental_completed` 的计算，也不改动后续绿色和红色分支。

- [x] **Step 4: 运行新增测试并确认 GREEN**

Run:

```bash
cd InventoryManager/frontend
npm run test:run -- tests/unit/views/BatchShippingView.spec.ts
```

Expected: 全部用例通过，失败数为 0。

- [x] **Step 5: 运行前端完整验证**

Run:

```bash
cd InventoryManager/frontend
npm run test:run
npm run type-check
npm run build-only
```

Expected: Vitest、Vue TypeScript 检查和 Vite 构建全部退出码为 0。

- [x] **Step 6: 检查最终差异**

Run:

```bash
git diff --check
git status --short
git diff -- InventoryManager/frontend/src/views/BatchShippingView.vue InventoryManager/frontend/tests/unit/views/BatchShippingView.spec.ts
```

Expected: 只包含计划文档、新回归测试、桌面批量发货视图和由本次生产构建更新的 `static/vue-dist` 产物；没有空白错误或无关文件。

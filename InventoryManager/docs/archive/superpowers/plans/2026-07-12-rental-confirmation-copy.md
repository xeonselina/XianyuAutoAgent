# Rental 保存后客户确认信息实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每次成功新建或编辑 rental 后，读取数据库最终记录，弹出可一键复制到闲鱼聊天框的五行客户确认信息。

**Architecture:** 用纯函数统一生成地址、日期、型号、镜头和附件文案；用一个共用 Vue 对话框负责展示及兼容剪贴板复制。新建和编辑组件只上报保存后的 rental ID，`GanttChart` 统一重新查询详情并控制确认弹窗，避免复制表单临时值。

**Tech Stack:** Vue 3、TypeScript、Pinia、Element Plus、dayjs、Vitest、Vue Test Utils

## Global Constraints

- 保存成功后必须按 rental ID 调用现有详情接口，确认信息只能使用数据库最终记录。
- 复制内容固定为五行：`收货地址`、`寄出时间`、`预计收货`、`客户归还`、`寄出型号`，不得增加标题、空行或额外说明。
- 三个时间只显示 `YYYY-MM-DD`，不得显示分钟，也不得显示 `ship_in_time`。
- 收件信息缺少单独填写的客户电话时自动追加电话；不得使用闲鱼 ID 作为联系人。
- 寄出型号只列实际包含的附件并去重；无附件显示“无附件”。
- 不显示设备编号、序列号、闲鱼 ID、预计收回时间或代传照片。
- 保存成功但详情查询失败时不显示旧数据，提示“保存成功，但确认信息加载失败”。
- 复制优先使用 Clipboard API，失败或不可用时使用临时 `textarea` 兼容复制；两种方式均失败时提示“自动复制失败，请手动选择文本复制”。
- 不修改数据库结构和后端保存业务。

---

### Task 1: 客户确认文本生成器

**Files:**
- Create: `InventoryManager/frontend/src/utils/rentalConfirmation.ts`
- Create: `InventoryManager/frontend/tests/unit/rental-confirmation.spec.ts`

**Interfaces:**
- Consumes: `Rental` from `@/stores/gantt` and `lensComboDisplay` from `@/config/lensCombo`.
- Produces: `RentalConfirmationContent { lines: string[]; text: string }` and `buildRentalConfirmation(rental: Rental): RentalConfirmationContent`.

- [x] **Step 1: 写入失败的纯函数测试**

创建测试夹具和以下四类断言：

```ts
import { describe, expect, it } from 'vitest'
import type { Rental } from '@/stores/gantt'
import { buildRentalConfirmation } from '@/utils/rentalConfirmation'

const rental = (overrides: Partial<Rental> = {}): Rental => ({
  id: 42,
  device_id: 8,
  device: {
    id: 8,
    name: '3618',
    serial_number: 'SN-PRIVATE',
    model: 'x300u',
    device_model: {
      id: 3,
      name: 'x300u',
      display_name: 'VIVO X300 Ultra',
      is_active: true,
      created_at: '2026-01-01',
      updated_at: '2026-01-01',
      accessories: [],
    },
  },
  start_date: '2026-07-14',
  end_date: '2026-07-20',
  ship_out_time: '2026-07-12T19:30:00',
  ship_in_time: '2026-07-22T12:00:00',
  customer_name: '闲鱼用户ABC',
  customer_phone: '13800138000',
  destination: '张三，广东省广州市天河区一号路',
  status: 'not_shipped',
  includes_handle: true,
  includes_lens_mount: true,
  photo_transfer: true,
  lens_combo: 'lens_dual',
  accessories: [
    { name: '手机支架 12', model: '手机支架', type: 'phone_holder', is_bundled: false },
    { name: '备用手机支架', model: 'phone holder', type: 'phone_holder', is_bundled: false },
    { name: '三脚架 03', model: '三脚架', type: 'tripod', is_bundled: false },
  ],
  ...overrides,
})

describe('buildRentalConfirmation', () => {
  it('生成严格五行并补充地址中的缺失电话', () => {
    const result = buildRentalConfirmation(rental())
    expect(result.lines).toEqual([
      '收货地址：张三，广东省广州市天河区一号路，13800138000',
      '寄出时间：2026-07-12',
      '预计收货：2026-07-14',
      '客户归还：2026-07-20',
      '寄出型号：VIVO X300 Ultra + 双镜头 + 镜头支架 + 手柄 + 手机支架 + 三脚架',
    ])
    expect(result.text).toBe(result.lines.join('\n'))
    expect(result.text).not.toContain('2026-07-22')
    expect(result.text).not.toContain('闲鱼用户ABC')
    expect(result.text).not.toContain('SN-PRIVATE')
  })

  it('地址已经包含格式化电话时不重复追加', () => {
    const result = buildRentalConfirmation(rental({
      destination: '张三 138-0013-8000 广东省广州市',
    }))
    expect(result.lines[0]).toBe('收货地址：张三 138-0013-8000 广东省广州市')
  })

  it('无附件和缺失值使用固定兜底文案', () => {
    const result = buildRentalConfirmation(rental({
      destination: '',
      customer_phone: '',
      ship_out_time: undefined,
      start_date: '',
      end_date: '',
      device: undefined,
      lens_combo: undefined,
      includes_handle: false,
      includes_lens_mount: false,
      accessories: [],
    }))
    expect(result.lines).toEqual([
      '收货地址：未填写',
      '寄出时间：未填写',
      '预计收货：未填写',
      '客户归还：未填写',
      '寄出型号：未识别型号 + 未填写镜头组合 + 无附件',
    ])
  })

  it('其他附件使用名称并去重', () => {
    const result = buildRentalConfirmation(rental({
      includes_handle: false,
      includes_lens_mount: false,
      accessories: [
        { name: '补光灯', type: 'other', is_bundled: false },
        { name: '补光灯', type: 'other', is_bundled: false },
      ],
    }))
    expect(result.lines[4]).toBe('寄出型号：VIVO X300 Ultra + 双镜头 + 补光灯')
  })
})
```

- [x] **Step 2: 运行测试并确认因模块不存在而失败**

Run:

```bash
cd InventoryManager/frontend
npx vitest run tests/unit/rental-confirmation.spec.ts
```

Expected: FAIL，无法解析 `@/utils/rentalConfirmation`。

- [x] **Step 3: 实现最小纯函数**

实现下列确定接口；附件分类必须同时识别 `type`、中文名称和英文 model：

```ts
import dayjs from 'dayjs'
import { lensComboDisplay } from '@/config/lensCombo'
import type { Rental } from '@/stores/gantt'

export interface RentalConfirmationContent {
  lines: string[]
  text: string
}

const dateOnly = (value?: string | null): string => {
  if (!value) return '未填写'
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD') : '未填写'
}

const addressWithPhone = (destination?: string, phone?: string): string => {
  const address = destination?.trim() || ''
  const rawPhone = phone?.trim() || ''
  if (!address) return rawPhone || '未填写'
  if (!rawPhone) return address
  const phoneDigits = rawPhone.replace(/\D/g, '')
  const addressDigits = address.replace(/\D/g, '')
  return phoneDigits && addressDigits.includes(phoneDigits)
    ? address
    : `${address}，${rawPhone}`
}

const accessoryLabel = (accessory: NonNullable<Rental['accessories']>[number]): string => {
  const type = accessory.type?.toLowerCase() || ''
  const searchable = `${accessory.name || ''} ${accessory.model || ''}`.toLowerCase()
  if (type === 'phone_holder' || searchable.includes('手机支架') || searchable.includes('phone')) {
    return '手机支架'
  }
  if (type === 'tripod' || searchable.includes('三脚架') || searchable.includes('tripod')) {
    return '三脚架'
  }
  return accessory.name?.trim() || accessory.model?.trim() || ''
}

export const buildRentalConfirmation = (rental: Rental): RentalConfirmationContent => {
  const model = rental.device?.device_model?.display_name
    || rental.device?.device_model?.name
    || rental.device?.model
    || '未识别型号'
  const lens = rental.lens_combo ? lensComboDisplay(rental.lens_combo) : '未填写镜头组合'
  const accessories = new Set<string>()
  if (rental.includes_lens_mount) accessories.add('镜头支架')
  if (rental.includes_handle) accessories.add('手柄')
  for (const accessory of rental.accessories || []) {
    const label = accessoryLabel(accessory)
    if (label) accessories.add(label)
  }
  const accessoryParts = accessories.size ? [...accessories] : ['无附件']
  const lines = [
    `收货地址：${addressWithPhone(rental.destination, rental.customer_phone)}`,
    `寄出时间：${dateOnly(rental.ship_out_time)}`,
    `预计收货：${dateOnly(rental.start_date)}`,
    `客户归还：${dateOnly(rental.end_date)}`,
    `寄出型号：${[model, lens, ...accessoryParts].join(' + ')}`,
  ]
  return { lines, text: lines.join('\n') }
}
```

- [x] **Step 4: 运行目标测试并确认通过**

Run: `cd InventoryManager/frontend && npx vitest run tests/unit/rental-confirmation.spec.ts`

Expected: 4 tests PASS。

- [x] **Step 5: 提交纯函数**

```bash
git add InventoryManager/frontend/src/utils/rentalConfirmation.ts InventoryManager/frontend/tests/unit/rental-confirmation.spec.ts
git commit -m "feat: build rental confirmation text"
```

---

### Task 2: 客户确认弹窗与兼容复制

**Files:**
- Create: `InventoryManager/frontend/src/components/RentalConfirmationDialog.vue`
- Create: `InventoryManager/frontend/tests/unit/components/RentalConfirmationDialog.spec.ts`

**Interfaces:**
- Consumes: `modelValue: boolean`, `rental: Rental | null`, `buildRentalConfirmation(rental)`.
- Produces: `update:modelValue` close event; UI actions `[data-test="copy-confirmation"]` and `[data-test="confirmation-text"]`.

- [x] **Step 1: 写入失败的弹窗测试**

测试使用 Task 1 的完整 rental 夹具，覆盖：

```ts
it('展示五行并通过 Clipboard API 复制全部文本', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  const wrapper = mountDialog(savedRental)
  const text = wrapper.get('[data-test="confirmation-text"]').text()
  expect(text.split('\n')).toHaveLength(5)
  await wrapper.get('[data-test="copy-confirmation"]').trigger('click')
  await flushPromises()
  expect(writeText).toHaveBeenCalledWith(buildRentalConfirmation(savedRental).text)
  expect(ElMessage.success).toHaveBeenCalledWith('确认信息已复制')
  expect(wrapper.emitted('update:modelValue')).toBeUndefined()
})

it('Clipboard API 失败时使用 textarea 兼容复制', async () => {
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
  })
  const execCommand = vi.fn().mockReturnValue(true)
  Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand })
  const wrapper = mountDialog(savedRental)
  await wrapper.get('[data-test="copy-confirmation"]').trigger('click')
  await flushPromises()
  expect(execCommand).toHaveBeenCalledWith('copy')
  expect(ElMessage.success).toHaveBeenCalledWith('确认信息已复制')
})

it('两种复制方式都失败时提示手动复制', async () => {
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined })
  Object.defineProperty(document, 'execCommand', { configurable: true, value: vi.fn().mockReturnValue(false) })
  const wrapper = mountDialog(savedRental)
  await wrapper.get('[data-test="copy-confirmation"]').trigger('click')
  await flushPromises()
  expect(ElMessage.error).toHaveBeenCalledWith('自动复制失败，请手动选择文本复制')
  expect(wrapper.get('[data-test="confirmation-text"]').text()).toContain('收货地址：')
})
```

`mountDialog` 必须用 `ElDialog` 和 `ElButton` stub 渲染默认及 footer slot，并在每个测试后恢复 `navigator.clipboard`、`document.execCommand` 和消息 spy。

- [x] **Step 2: 运行测试并确认组件不存在**

Run: `cd InventoryManager/frontend && npx vitest run tests/unit/components/RentalConfirmationDialog.spec.ts`

Expected: FAIL，无法解析 `@/components/RentalConfirmationDialog.vue`。

- [x] **Step 3: 实现弹窗和复制回退**

核心模板和复制逻辑必须如下：

```vue
<template>
  <el-dialog v-model="visible" title="客户确认信息" width="min(680px, 94vw)" :close-on-click-modal="false">
    <pre class="confirmation-text" data-test="confirmation-text">{{ confirmation.text }}</pre>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button type="primary" data-test="copy-confirmation" @click="copyAll">复制全部</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import type { Rental } from '@/stores/gantt'
import { buildRentalConfirmation } from '@/utils/rentalConfirmation'

const props = defineProps<{ modelValue: boolean; rental: Rental | null }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void }>()
const visible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value),
})
const confirmation = computed(() => props.rental
  ? buildRentalConfirmation(props.rental)
  : { lines: [], text: '' })

const fallbackCopy = (text: string): boolean => {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    textarea.remove()
  }
}

const copyAll = async () => {
  let copied = false
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(confirmation.value.text)
      copied = true
    }
  } catch {
    copied = false
  }
  if (!copied) copied = fallbackCopy(confirmation.value.text)
  if (copied) ElMessage.success('确认信息已复制')
  else ElMessage.error('自动复制失败，请手动选择文本复制')
}
</script>
```

样式必须保留换行、允许选择、自动换行，并使用可读背景和边框；不得用禁用输入框承载正文。

- [x] **Step 4: 运行弹窗和纯函数测试**

Run:

```bash
cd InventoryManager/frontend
npx vitest run tests/unit/rental-confirmation.spec.ts tests/unit/components/RentalConfirmationDialog.spec.ts
```

Expected: 7 tests PASS。

- [x] **Step 5: 提交弹窗**

```bash
git add InventoryManager/frontend/src/components/RentalConfirmationDialog.vue InventoryManager/frontend/tests/unit/components/RentalConfirmationDialog.spec.ts
git commit -m "feat: add rental confirmation dialog"
```

---

### Task 3: 新建和编辑成功事件携带 rental ID

**Files:**
- Modify: `InventoryManager/frontend/src/components/BookingDialog.vue:342-350,815-818`
- Modify: `InventoryManager/frontend/src/components/rental/EditRentalDialogNew.vue:112-120,250-253`
- Create: `InventoryManager/frontend/tests/unit/components/RentalSaveSuccessEvents.spec.ts`

**Interfaces:**
- Changes `BookingDialog` event from `success: []` to `success: [rentalId?: number]`.
- Changes `EditRentalDialogNew` event from `success: []` to `success: [rentalId?: number]`.
- Consumes create response shape `response.data.main_rental.id` and edit prop `rental.id`.
- Creation and edit saves emit a numeric rental ID; the existing edit-dialog delete path keeps emitting `success()` without an ID so callers can refresh without querying a deleted rental.

- [x] **Step 1: 写入失败的事件测试**

使用 Pinia 和模块 mock 挂载两个组件。`BookingDialog` 的 `createRental` 返回：

```ts
{
  success: true,
  data: { main_rental: { id: 42 } },
}
```

触发提交后断言：

```ts
expect(wrapper.emitted('success')).toEqual([[42]])
```

`EditRentalDialogNew` 使用 `id: 77` 的 rental，`updateRental` 成功后断言：

```ts
expect(wrapper.emitted('success')).toEqual([[77]])
```

再覆盖删除兼容和两个异常分支：通过 `RentalActionButtons` stub 的删除按钮触发真实 `handleDelete`，删除成功后断言 `success` 为 `[[]]`（刷新信号不携带已删除 ID）；创建接口成功但缺少 `main_rental.id` 时不发出 `success`，并提示“保存成功，但确认信息加载失败”；创建或更新接口拒绝时不发出 `success`，继续显示现有保存失败提示。共 5 个测试。

测试必须 mock `useConflictDetection().checkDuplicateRental` 返回 `{ hasDuplicate: false, duplicates: [] }`，并 stub 表单校验、设备/附件 composable 及子表单组件；不得通过直接调用 `wrapper.vm.$emit` 伪造被测行为。

- [x] **Step 2: 运行测试并确认旧事件没有参数**

Run: `cd InventoryManager/frontend && npx vitest run tests/unit/components/RentalSaveSuccessEvents.spec.ts`

Expected: FAIL，实际事件为 `[[]]` 而不是 `[[42]]`/`[[77]]`。

- [x] **Step 3: 修改两个成功事件**

`BookingDialog.vue`：

```ts
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'success': [rentalId?: number]
}>()

const result = await ganttStore.createRental(rentalData)
const rentalId = result.data?.main_rental?.id
ElMessage.success('租赁记录创建成功')
if (typeof rentalId === 'number') {
  emit('success', rentalId)
} else {
  ElMessage.error('保存成功，但确认信息加载失败')
}
handleClose()
```

`EditRentalDialogNew.vue`：

```ts
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'success': [rentalId?: number]
}>()

const handleDelete = async () => {
  // ...删除成功后保存原有刷新语义，不传已删除的 ID
  emit('success')
  handleClose()
}

const handleSubmit = async () => {
  // ...编辑保存成功路径携带当前 ID
  await ganttStore.updateRental(props.rental!.id, updateData)
  ElMessage.success('租赁记录更新成功')
  emit('success', props.rental!.id)
  handleClose()
}
```

- [x] **Step 4: 运行事件测试并确认通过**

Run: `cd InventoryManager/frontend && npx vitest run tests/unit/components/RentalSaveSuccessEvents.spec.ts`

Expected: 5 tests PASS，覆盖新建、编辑、删除无 ID、缺失 ID 和保存失败。

- [x] **Step 5: 提交事件契约**

```bash
git add InventoryManager/frontend/src/components/BookingDialog.vue InventoryManager/frontend/src/components/rental/EditRentalDialogNew.vue InventoryManager/frontend/tests/unit/components/RentalSaveSuccessEvents.spec.ts
git commit -m "feat: emit saved rental ids"
```

---

### Task 4: GanttChart 保存后重新查询并打开确认弹窗

**Files:**
- Modify: `InventoryManager/frontend/src/components/GanttChart.vue:249-275,377-405,721-762`
- Create: `InventoryManager/frontend/tests/unit/components/GanttRentalConfirmationFlow.spec.ts`

**Interfaces:**
- Consumes `success(rentalId?: number)` from Task 3 and `RentalConfirmationDialog` from Task 2.
- Always runs the existing refresh flow; only when `typeof rentalId === 'number'` does it use `ganttStore.getRentalById(rentalId): Promise<Rental | null>` afterward.
- Produces `confirmationRental: Ref<Rental | null>` and `showRentalConfirmationDialog: Ref<boolean>`.

- [x] **Step 1: 写入失败的流程测试**

浅挂载 `GanttChart`，用 Pinia spy 替换 `loadData`、`getRentalById`，并 stub 甘特图行、Element Plus 及无关对话框。成功场景必须由 `BookingDialog`/`EditRentalDialogNew` stub 发出真实 `success` 事件触发：

```ts
vi.spyOn(store, 'getRentalById').mockResolvedValue(savedRental)
wrapper.findComponent(BookingDialog).vm.$emit('success', 42)
await flushPromises()
expect(store.getRentalById).toHaveBeenCalledWith(42)
const confirmation = wrapper.findComponent(RentalConfirmationDialog)
expect(confirmation.props('modelValue')).toBe(true)
expect(confirmation.props('rental')).toEqual(savedRental)
```

编辑场景用 ID `77` 验证相同流程。查询失败场景：

```ts
vi.spyOn(store, 'getRentalById').mockResolvedValue(null)
wrapper.findComponent(BookingDialog).vm.$emit('success', 42)
await flushPromises()
expect(wrapper.findComponent(RentalConfirmationDialog).props('modelValue')).toBe(false)
expect(ElMessage.error).toHaveBeenCalledWith('保存成功，但确认信息加载失败')
```

删除场景由 `EditRentalDialogNew` stub 发出无参数 `success`，必须仍执行原刷新流程，但不得查询或打开确认弹窗：

```ts
vi.spyOn(store, 'getRentalById')
wrapper.findComponent(EditRentalDialogNew).vm.$emit('success')
await flushPromises()
expect(store.loadData).toHaveBeenCalled()
expect(store.getRentalById).not.toHaveBeenCalled()
expect(wrapper.findComponent(RentalConfirmationDialog).props('modelValue')).toBe(false)
```

流程测试共 4 个：新建、编辑、确认查询失败、删除无 ID。

- [x] **Step 2: 运行流程测试并确认确认弹窗不存在**

Run: `cd InventoryManager/frontend && npx vitest run tests/unit/components/GanttRentalConfirmationFlow.spec.ts`

Expected: FAIL，`GanttChart` 中不存在 `RentalConfirmationDialog`，成功处理器也不接收 ID。

- [x] **Step 3: 接入统一确认流程**

模板加入：

```vue
<RentalConfirmationDialog
  v-model="showRentalConfirmationDialog"
  :rental="confirmationRental"
/>
```

脚本加入状态和方法：

```ts
import RentalConfirmationDialog from './RentalConfirmationDialog.vue'

const showRentalConfirmationDialog = ref(false)
const confirmationRental = ref<Rental | null>(null)

const openRentalConfirmation = async (rentalId: number) => {
  const latestRental = await ganttStore.getRentalById(rentalId)
  if (!latestRental) {
    confirmationRental.value = null
    showRentalConfirmationDialog.value = false
    ElMessage.error('保存成功，但确认信息加载失败')
    return
  }
  confirmationRental.value = latestRental
  showRentalConfirmationDialog.value = true
}
```

`handleBookingSuccess(rentalId?: number)` 和 `handleEditSuccess(rentalId?: number)` 保留现有关闭表单、刷新甘特图、统计缓存与 `nextTick` 行为；无论是否有 ID 都必须完成这些步骤，之后仅对数字 ID 调用确认查询：

```ts
if (typeof rentalId === 'number') {
  await openRentalConfirmation(rentalId)
}
```

编辑成功时可在查询前清空 `selectedRental`，但不得用 `selectedRental` 作为确认弹窗数据。

- [x] **Step 4: 运行全部新增测试**

Run:

```bash
cd InventoryManager/frontend
npx vitest run \
  tests/unit/rental-confirmation.spec.ts \
  tests/unit/components/RentalConfirmationDialog.spec.ts \
  tests/unit/components/RentalSaveSuccessEvents.spec.ts \
  tests/unit/components/GanttRentalConfirmationFlow.spec.ts
```

Expected: 全部新增测试 PASS；其中 `GanttRentalConfirmationFlow.spec.ts` 为 4 tests，删除无 ID 场景只刷新、不查询、不弹窗。

- [x] **Step 5: 运行完整前端回归、类型检查和隔离构建**

Run:

```bash
cd InventoryManager/frontend
npm test -- --run
npx vue-tsc --build
npx vite build --outDir /tmp/xianyu-rental-confirmation-build --emptyOutDir
rm -rf /tmp/xianyu-rental-confirmation-build
git diff --check
```

Expected: 全部测试通过；TypeScript 与 Vite 退出码为 0；只有既存的大 chunk 警告；`git diff --check` 无输出。

- [x] **Step 6: 提交集成**

```bash
git add InventoryManager/frontend/src/components/GanttChart.vue InventoryManager/frontend/tests/unit/components/GanttRentalConfirmationFlow.spec.ts
git commit -m "feat: show confirmation after rental save"
```

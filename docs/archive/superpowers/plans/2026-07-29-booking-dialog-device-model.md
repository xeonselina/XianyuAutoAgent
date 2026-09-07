# Booking Dialog Device Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let desktop users choose a device model inside the booking dialog while using the Gantt filter only as the dialog's initial value.

**Architecture:** `BookingDialog.vue` owns a `selectedModelId` form field. Computed state resolves the selected model and filters the device options; model changes invalidate any selected device, availability result, and automatically found slot. The existing `selectedDeviceModel` prop remains a one-way initialization input.

**Tech Stack:** Vue 3 Composition API, TypeScript, Element Plus, Pinia, Vitest, Vue Test Utils

## Global Constraints

- Do not modify the mobile booking flow.
- Do not change Gantt filtering, backend APIs, or database structures.
- Preserve existing lifecycle-based device disabling and all unrelated booking behavior.
- Opening the dialog defaults to the current Gantt model; changing it inside the dialog never changes the Gantt filter.

---

### Task 1: Add independent model selection to `BookingDialog`

**Files:**
- Create: `InventoryManager/frontend/tests/unit/components/BookingDialogDeviceModel.spec.ts`
- Create: `InventoryManager/frontend/tests/unit/composables/useAvailabilityCheck.spec.ts`
- Modify: `InventoryManager/frontend/src/components/BookingDialog.vue`
- Modify: `InventoryManager/frontend/src/composables/useAvailabilityCheck.ts`
- Modify: `InventoryManager/frontend/src/composables/useRentalFormValidation.ts`

**Interfaces:**
- Consumes: `selectedDeviceModel?: string`, `DeviceModel.id`, `DeviceModel.name`, `DeviceModel.display_name`, `Device.model_id`, and `Device.device_model`.
- Produces: `form.selectedModelId: number | null`, `filteredDevices`, `handleModelChange(modelId: number | null)`, and availability searches whose fifth argument is the dialog-selected model ID as a string.

- [x] **Step 1: Write failing component tests**

Create fixtures with two models and devices, mock only API-backed composables, mount the real `BookingDialog`, and cover these behaviors:

```ts
it('defaults to the Gantt model and filters device choices', async () => {
  const wrapper = await mountDialog({ selectedDeviceModel: 'VIVO X200 Ultra' })
  expect((wrapper.vm as any).form.selectedModelId).toBe(1)
  expect((wrapper.vm as any).filteredDevices.map((device: Device) => device.id)).toEqual([11, 12])
})

it('changing the dialog model clears stale selection without updating the parent prop', async () => {
  const wrapper = await mountDialog({ selectedDeviceModel: 'VIVO X200 Ultra' })
  ;(wrapper.vm as any).form.selectedDeviceId = 11
  ;(wrapper.vm as any).availableSlot = { device: devices[0] }
  await (wrapper.vm as any).handleModelChange(2)
  expect((wrapper.vm as any).form.selectedDeviceId).toBeNull()
  expect((wrapper.vm as any).availableSlot).toBeNull()
  expect(wrapper.emitted('update:selectedDeviceModel')).toBeUndefined()
})

it('searches availability with the model selected inside the dialog', async () => {
  const wrapper = await mountDialog({ selectedDeviceModel: 'VIVO X200 Ultra' })
  const vm = wrapper.vm as any
  vm.form.startDate = new Date('2026-08-01T00:00:00')
  vm.form.endDate = new Date('2026-08-03T00:00:00')
  await vm.handleModelChange(2)
  await vm.findAvailableSlot()
  expect(findAvailableSlot).toHaveBeenCalledWith('2026-08-01', '2026-08-03', 1, '2', false)
})

it('does not search without a dialog model', async () => {
  const wrapper = await mountDialog()
  const vm = wrapper.vm as any
  vm.form.startDate = new Date('2026-08-01T00:00:00')
  vm.form.endDate = new Date('2026-08-03T00:00:00')
  await vm.findAvailableSlot()
  expect(findAvailableSlot).not.toHaveBeenCalled()
  expect(ElMessage.warning).toHaveBeenCalledWith('请先选择设备型号')
})
```

The production mutation each test catches is respectively: missing initialization/filtering, stale cross-model state or two-way coupling, continued use of the Gantt prop in searches, and an unguarded empty-model search.

- [x] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd InventoryManager/frontend
npx vitest run tests/unit/components/BookingDialogDeviceModel.spec.ts
```

Expected: FAIL because `selectedModelId`, `filteredDevices`, `handleModelChange`, and the independent search behavior do not exist.

- [x] **Step 3: Add the model field and derived state**

Add this field to the form and reset object:

```ts
selectedModelId: null as number | null,
```

Resolve the selected model and filter devices, preferring IDs and falling back to names only for legacy records without model IDs:

```ts
const selectedModel = computed(() =>
  deviceManagement.deviceModels.value.find(model => model.id === form.value.selectedModelId) || null
)

const filteredDevices = computed(() => {
  if (!selectedModel.value) return []
  return deviceManagement.devices.value.filter(device => {
    if (device.model_id != null) return device.model_id === selectedModel.value?.id
    if (device.device_model?.id != null) return device.device_model.id === selectedModel.value?.id
    return [selectedModel.value?.name, selectedModel.value?.display_name]
      .filter(Boolean)
      .includes(device.model)
  })
})
```

Render an Element Plus select with `v-model="form.selectedModelId"` and `@change="handleModelChange"`, then render device options from `filteredDevices`.

- [x] **Step 4: Add initialization, invalidation, validation, and search behavior**

Initialize after all dialog data has loaded:

```ts
const initializeSelectedModel = () => {
  form.value.selectedModelId =
    deviceManagement.deviceModels.value.find(
      model => model.display_name === props.selectedDeviceModel
    )?.id ?? null
}
```

Invalidate stale state on user changes:

```ts
const handleModelChange = (modelId: number | null) => {
  form.value.selectedModelId = modelId
  form.value.selectedDeviceId = null
  availableSlot.value = null
  availability.resetAll()
}
```

Use `form.selectedModelId` in `findAvailableSlot`; warn with `请先选择设备型号` when empty. Add a `selectedModelId` required rule with message `请选择设备型号`, and derive `selectedModelName` from `selectedModel.name`.

Invalidate pending slot-search results with a component generation counter, and invalidate pending device/accessory availability checks inside `useAvailabilityCheck` when reset methods run. This prevents responses started for an old model or date from restoring stale state.

- [x] **Step 5: Run the focused test and verify GREEN**

Run:

```bash
cd InventoryManager/frontend
npx vitest run tests/unit/components/BookingDialogDeviceModel.spec.ts
```

Expected: PASS.

- [x] **Step 6: Run regression checks**

Run:

```bash
cd InventoryManager/frontend
npm run type-check
npm run test:run
npm run build-only
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit and push**

```bash
git add docs/superpowers/specs/2026-07-29-booking-dialog-device-model-design.md \
  docs/superpowers/plans/2026-07-29-booking-dialog-device-model.md \
  InventoryManager/frontend/src/components/BookingDialog.vue \
  InventoryManager/frontend/src/composables/useAvailabilityCheck.ts \
  InventoryManager/frontend/src/composables/useRentalFormValidation.ts \
  InventoryManager/frontend/tests/unit/components/BookingDialogDeviceModel.spec.ts \
  InventoryManager/frontend/tests/unit/composables/useAvailabilityCheck.spec.ts
git commit -m "feat: select device model in booking dialog"
git push
```

import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { ElMessage } from 'element-plus'
import { defineComponent } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import BookingDialog from '@/components/BookingDialog.vue'
import { useGanttStore, type Device } from '@/stores/gantt'

const testState = vi.hoisted(() => ({
  deviceManagement: {
    loading: { value: false },
    devices: { value: [] as any[] },
    accessories: { value: [] as any[] },
    deviceModels: { value: [] as any[] },
    loadDevices: vi.fn().mockResolvedValue(undefined),
    loadAccessories: vi.fn().mockResolvedValue(undefined),
    loadDeviceModels: vi.fn().mockResolvedValue(undefined),
  },
  availability: {
    deviceAvailability: {
      value: { checked: false, availableItems: [], unavailableItems: [] },
    },
    accessoryAvailability: {
      value: { checked: false, availableItems: [], unavailableItems: [] },
    },
    resetAll: vi.fn(),
    checkDevicesAvailability: vi.fn().mockResolvedValue(undefined),
    checkAccessoriesAvailability: vi.fn().mockResolvedValue(undefined),
    isDeviceAvailable: vi.fn(() => true),
    isAccessoryAvailable: vi.fn(() => true),
  },
}))

vi.mock('@/composables/useDeviceManagement', () => ({
  useDeviceManagement: () => testState.deviceManagement,
}))

vi.mock('@/composables/useAvailabilityCheck', () => ({
  useAvailabilityCheck: () => testState.availability,
}))

vi.mock('@/composables/useConflictDetection', () => ({
  useConflictDetection: () => ({
    checkDuplicateRental: vi.fn().mockResolvedValue({
      hasDuplicate: false,
      duplicates: [],
    }),
  }),
}))

vi.mock('@/utils/logisticsWarning', () => ({
  getLogisticsMismatch: vi.fn().mockResolvedValue(null),
  formatLogisticsWarning: vi.fn(() => ''),
}))

const models = [
  {
    id: 1,
    name: 'x200u',
    display_name: 'VIVO X200 Ultra',
    is_active: true,
    accessories: [],
    created_at: '',
    updated_at: '',
  },
  {
    id: 2,
    name: 'x300u',
    display_name: 'VIVO X300 Ultra',
    is_active: true,
    accessories: [],
    created_at: '',
    updated_at: '',
  },
]

const devices: Device[] = [
  {
    id: 11,
    name: 'VIVO X200 Ultra 01',
    serial_number: 'X200-01',
    model: 'x200u',
    model_id: 1,
    device_model: models[0] as any,
    is_accessory: false,
    status: 'online',
    lifecycle_status: 'active',
    created_at: '',
    updated_at: '',
  },
  {
    id: 12,
    name: 'VIVO X200 Ultra 02',
    serial_number: 'X200-02',
    model: 'x200u',
    model_id: 1,
    device_model: models[0] as any,
    is_accessory: false,
    status: 'online',
    lifecycle_status: 'sold',
    created_at: '',
    updated_at: '',
  },
  {
    id: 21,
    name: 'VIVO X300 Ultra 01',
    serial_number: 'X300-01',
    model: 'x300u',
    model_id: 2,
    device_model: models[1] as any,
    is_accessory: false,
    status: 'online',
    lifecycle_status: 'active',
    created_at: '',
    updated_at: '',
  },
]

const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

const SelectStub = defineComponent({
  props: ['modelValue'],
  emits: ['update:modelValue', 'change'],
  methods: {
    onChange(event: Event) {
      const rawValue = (event.target as HTMLSelectElement).value
      const value = rawValue === '' ? undefined : Number(rawValue)
      this.$emit('update:modelValue', value)
      this.$emit('change', value)
    },
  },
  template: `
    <select :value="modelValue ?? ''" @change="onChange">
      <option value="">请选择</option>
      <slot />
    </select>
  `,
})

const OptionStub = defineComponent({
  props: ['label', 'value', 'disabled'],
  template: '<option :value="value" :disabled="disabled">{{ label }}</option>',
})

const mountDialog = async (selectedDeviceModel?: string) => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useGanttStore()
  const findAvailableSlot = vi.spyOn(store, 'findAvailableSlot').mockResolvedValue({
    device: devices[2],
    shipOutDate: new Date('2026-07-30T00:00:00'),
    shipInDate: new Date('2026-08-05T00:00:00'),
  })

  const wrapper = shallowMount(BookingDialog, {
    props: {
      modelValue: true,
      selectedDeviceModel,
    },
    global: {
      plugins: [pinia],
      stubs: {
        ElDialog: {
          props: ['modelValue'],
          template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>',
        },
        ElForm: {
          methods: {
            validate: vi.fn().mockResolvedValue(true),
            resetFields: vi.fn(),
          },
          template: '<form><slot /></form>',
        },
        ElFormItem: { template: '<div><slot /></div>' },
        ElInputNumber: true,
        ElInput: true,
        ElButton: true,
        ElSelect: SelectStub,
        ElOption: OptionStub,
        ElCheckbox: true,
        ElCheckboxGroup: true,
        ElTag: true,
        ElIcon: true,
        VueDatePicker: true,
        LensComboSelector: true,
      },
    },
  })
  await flushPromises()

  return { findAvailableSlot, wrapper }
}

describe('BookingDialog device model selection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    testState.deviceManagement.devices.value = devices
    testState.deviceManagement.deviceModels.value = models
    testState.deviceManagement.accessories.value = []
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  it('defaults to the Gantt model and filters device choices', async () => {
    const { wrapper } = await mountDialog('VIVO X200 Ultra')
    const vm = wrapper.vm as any

    expect(vm.form.selectedModelId).toBe(1)
    expect(vm.filteredDevices.map((device: Device) => device.id)).toEqual([11, 12])
    expect(wrapper.find('option[value="11"]').text()).toBe('VIVO X200 Ultra 01')
    expect(wrapper.find('option[value="12"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('option[value="21"]').exists()).toBe(false)
  })

  it('changing the dialog model clears stale selection without updating the parent prop', async () => {
    const { wrapper } = await mountDialog('VIVO X200 Ultra')
    const vm = wrapper.vm as any
    vm.form.selectedDeviceId = 11
    vm.availableSlot = { device: devices[0] }

    await wrapper.findAll('select')[0].setValue('2')

    expect(vm.form.selectedDeviceId).toBeNull()
    expect(vm.availableSlot).toBeNull()
    expect(testState.availability.resetAll).toHaveBeenCalled()
    expect(wrapper.emitted('update:selectedDeviceModel')).toBeUndefined()
  })

  it('normalizes a cleared model and restores the Gantt default when reopened', async () => {
    const { wrapper } = await mountDialog('VIVO X200 Ultra')
    const vm = wrapper.vm as any

    await wrapper.findAll('select')[0].setValue('')

    expect(vm.form.selectedModelId).toBeNull()

    vm.handleClose()
    await wrapper.setProps({ modelValue: false })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    expect(vm.form.selectedModelId).toBe(1)
  })

  it('matches legacy devices through associated model names when IDs are missing', async () => {
    testState.deviceManagement.devices.value = [
      ...devices,
      {
        ...devices[2],
        id: 22,
        name: 'VIVO X300 Ultra legacy',
        model: 'legacy-code',
        model_id: undefined,
        device_model: {
          ...models[1],
          id: undefined,
        },
      },
    ]

    const { wrapper } = await mountDialog('VIVO X300 Ultra')
    const vm = wrapper.vm as any

    expect(vm.filteredDevices.map((device: Device) => device.id)).toEqual([21, 22])
  })

  it('searches availability with the model selected inside the dialog', async () => {
    const { findAvailableSlot, wrapper } = await mountDialog('VIVO X200 Ultra')
    const vm = wrapper.vm as any
    vm.form.startDate = new Date('2026-08-01T00:00:00')
    vm.form.endDate = new Date('2026-08-03T00:00:00')
    vm.form.selectedModelId = 2

    await vm.findAvailableSlot()

    expect(findAvailableSlot).toHaveBeenCalledWith(
      '2026-08-01',
      '2026-08-03',
      1,
      '2',
      false,
    )
  })

  it('ignores an old model search result that finishes after the model changes', async () => {
    const { findAvailableSlot, wrapper } = await mountDialog('VIVO X200 Ultra')
    const oldSearch = deferred<any>()
    findAvailableSlot.mockReset()
    findAvailableSlot.mockReturnValue(oldSearch.promise)
    const vm = wrapper.vm as any
    vm.form.startDate = new Date('2026-08-01T00:00:00')
    vm.form.endDate = new Date('2026-08-03T00:00:00')

    const pendingSearch = vm.findAvailableSlot()
    await wrapper.findAll('select')[0].setValue('2')
    oldSearch.resolve({
      device: devices[0],
      shipOutDate: new Date('2026-07-30T00:00:00'),
      shipInDate: new Date('2026-08-05T00:00:00'),
    })
    await pendingSearch

    expect(vm.form.selectedModelId).toBe(2)
    expect(vm.form.selectedDeviceId).toBeNull()
    expect(vm.availableSlot).toBeNull()
  })

  it('does not search without a dialog model', async () => {
    const { findAvailableSlot, wrapper } = await mountDialog()
    const vm = wrapper.vm as any
    vm.form.startDate = new Date('2026-08-01T00:00:00')
    vm.form.endDate = new Date('2026-08-03T00:00:00')

    await vm.findAvailableSlot()

    expect(findAvailableSlot).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalledWith('请先选择设备型号')
  })
})

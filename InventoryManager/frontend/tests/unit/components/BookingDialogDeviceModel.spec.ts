import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import { ElMessage, ElSelect, ElOption } from 'element-plus'
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
    allowed_lens_combos: ['lens_200mm', 'bare'],
    default_rental_package_id: 'legacy_bare',
    accessories: [],
    created_at: '',
    updated_at: '',
  },
  {
    id: 2,
    name: 'x300u',
    display_name: 'VIVO X300 Ultra',
    is_active: true,
    allowed_lens_combos: ['lens_400mm', 'lens_dual'],
    default_lens_combo: 'lens_dual',
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

const mountDialog = async (selectedDeviceModel?: string, realSelect = false) => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useGanttStore()
  const findAvailableSlot = vi.spyOn(store, 'findAvailableSlot').mockResolvedValue({
    device: devices[2],
    shipOutDate: new Date('2026-07-30T00:00:00'),
    shipInDate: new Date('2026-08-05T00:00:00'),
  })

  const wrapper = (realSelect ? mount : shallowMount)(BookingDialog, {
    props: {
      modelValue: true,
      selectedDeviceModel,
    },
    global: {
      plugins: [pinia],
      stubs: {
        BookingDeviceSelector: false,
        ElAlert: true,
        ElCard: { template: '<div><slot name="header" /><slot /></div>' },
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
        ElSelect: realSelect ? ElSelect : SelectStub,
        ElOption: realSelect ? ElOption : OptionStub,
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
    expect(wrapper.findComponent({ name: 'LensComboSelector' }).props('model')).toEqual(models[0])
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
  it('submits two independently configured devices together and reuses the key after failure', async () => {
    const { wrapper } = await mountDialog('VIVO X300 Ultra')
    const vm = wrapper.vm as any
    vm.form.startDate = new Date('2026-10-01')
    vm.form.endDate = new Date('2026-10-03')
    vm.form.customerName = '双机客户'
    vm.form.rentalPackageId = 'legacy_lens_400mm'
    vm.form.phoneHolderId = 91
    await flushPromises()
    vm.form.selectedDeviceId = 21
    vm.addDevice()
    expect(vm.additionalDevices[0].phoneHolderId).toBeNull()
    expect(vm.additionalDevices[0].device_id).toBeNull()
    vm.additionalDevices[0].device_id = 22
    vm.additionalDevices[0].rental_package_id = 'legacy_bare'
    vm.additionalDevices[0].tripodId = 92
    const create = vi.spyOn(useGanttStore(), 'createRental')
      .mockRejectedValueOnce(new Error('第 2 台档期冲突'))
      .mockResolvedValueOnce({ success: true, data: { main_rental: { id: 77 } } })
    await vm.handleSubmit()
    expect(vm.additionalDevices[0].rental_package_id).toBe('legacy_bare')
    await vm.handleSubmit()
    expect(create).toHaveBeenCalledTimes(2)
    const [first] = create.mock.calls[0]!
    const [retry] = create.mock.calls[1]!
    expect(first.rental_package_id).toBe('legacy_lens_400mm')
    expect(first.accessories).toEqual([91])
    expect(first.additional_devices[0]).toMatchObject({ device_id: 22, rental_package_id: 'legacy_bare', accessories: [92] })
    expect(first.booking_request_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(retry.booking_request_id).toBe(first.booking_request_id)
  })

  it('does not submit an unconfigured second device', async () => {
    const { wrapper } = await mountDialog('VIVO X300 Ultra')
    const vm = wrapper.vm as any
    const create = vi.spyOn(useGanttStore(), 'createRental')
    vm.addDevice()
    await vm.handleSubmit()
    expect(create).not.toHaveBeenCalled()
    expect(ElMessage.error).toHaveBeenCalledWith('请选择第 2 台设备')
  })

  it('adds any number of devices and removes only the chosen card', async () => {
    const { wrapper } = await mountDialog('VIVO X300 Ultra')
    const vm = wrapper.vm as any
    vm.addDevice()
    vm.addDevice()
    vm.addDevice()
    vm.additionalDevices[0].device_id = 22
    vm.additionalDevices[1].device_id = 23
    vm.additionalDevices[2].device_id = 24
    vm.additionalDevices[2].rental_package_id = 'legacy_bare'
    const lastKey = vm.additionalDevices[2].key
    vm.removeDevice(vm.additionalDevices[1])
    await flushPromises()
    expect(vm.additionalDevices.map((d: any) => d.device_id)).toEqual([22, 24])
    expect(vm.additionalDevices[1]).toMatchObject({ key: lastKey, rental_package_id: 'legacy_bare' })
    expect(wrapper.findAllComponents({ name: 'BookingDeviceSelector' })).toHaveLength(3)
    vm.removeDevice(vm.additionalDevices[0])
    vm.removeDevice(vm.additionalDevices[0])
    expect(vm.additionalDevices).toEqual([])
  })

  it('searches each additional device excluding devices already chosen', async () => {
    const { findAvailableSlot, wrapper } = await mountDialog('VIVO X300 Ultra')
    const vm = wrapper.vm as any
    vm.form.startDate = new Date('2026-10-01')
    vm.form.endDate = new Date('2026-10-03')
    await flushPromises()
    vm.form.selectedDeviceId = 21
    vm.addDevice()
    vm.addDevice()
    findAvailableSlot.mockResolvedValue({
      device: { ...devices[2], id: 21 },
      availableDevices: [21, 22, 23].map(id => ({ ...devices[2], id })),
      shipOutDate: new Date('2026-09-30'), shipInDate: new Date('2026-10-04'),
    })
    await vm.findAvailableSlot(vm.additionalDevices[0])
    await vm.findAvailableSlot(vm.additionalDevices[1])
    expect(vm.additionalDevices.map((d: any) => d.device_id)).toEqual([22, 23])
    const pending = deferred<any>()
    findAvailableSlot.mockReturnValue(pending.promise)
    const removed = vm.additionalDevices[0]
    const search = vm.findAvailableSlot(removed)
    vm.removeDevice(removed)
    pending.resolve({ device: { ...devices[2], id: 25 } })
    await search
    expect(vm.additionalDevices.map((d: any) => d.device_id)).toEqual([23])
    expect(removed.device_id).toBe(22)
  })

  it('renders names and dropdown options from slot results even when the initial list is empty', async () => {
    testState.deviceManagement.devices.value = []
    const { findAvailableSlot, wrapper } = await mountDialog('VIVO X300 Ultra', true)
    try {
      const vm = wrapper.vm as any
      vm.form.startDate = new Date('2026-10-01')
      vm.form.endDate = new Date('2026-10-03')
      await flushPromises()
      const candidates = [
        devices[2],
        { ...devices[2], id: 22, name: 'VIVO X300 Ultra 02' },
        { ...devices[2], id: 23, name: 'VIVO X300 Ultra 03' },
      ]
      findAvailableSlot.mockResolvedValue({ device: candidates[0], availableDevices: candidates,
        shipOutDate: new Date('2026-09-30'), shipInDate: new Date('2026-10-04') })
      await vm.findAvailableSlot()
      vm.addDevice()
      await vm.findAvailableSlot(vm.additionalDevices[0])
      await flushPromises()
      const selectors = wrapper.findAllComponents({ name: 'BookingDeviceSelector' })
      expect(selectors).toHaveLength(2)
      expect(selectors[0].find('.el-select__selection').text()).toBe('VIVO X300 Ultra 01')
      expect(selectors[1].find('.el-select__selection').text()).toBe('VIVO X300 Ultra 02')
      for (const selector of selectors) {
        await selector.find('.el-select__wrapper').trigger('click')
        await flushPromises()
        expect(selector.findAllComponents(ElOption).map(option => option.props('label'))).toEqual(candidates.map(d => d.name))
        expect(selector.findComponent(ElSelect).vm.expanded).toBe(true)
        await selector.find('.el-select__wrapper').trigger('click')
      }
      vm.form.selectedModelId = 1
      await flushPromises()
      expect(vm.filteredDevices).toEqual([])
    } finally {
      wrapper.unmount()
    }
  })

})

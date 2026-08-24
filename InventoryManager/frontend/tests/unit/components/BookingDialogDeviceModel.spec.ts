import { createPinia, setActivePinia } from 'pinia'
import { enableAutoUnmount, flushPromises, shallowMount } from '@vue/test-utils'
import { ElMessage } from 'element-plus'
import { ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import BookingDialog from '@/components/BookingDialog.vue'
import { useGanttStore } from '@/stores/gantt'

enableAutoUnmount(afterEach)

const testState = vi.hoisted(() => ({
  booking: {
    bootstrap: { value: null as any },
    availability: { value: null as any },
    bootstrapLoading: { value: false },
    availabilityLoading: { value: false },
    availabilityFailed: { value: false },
    loadBootstrap: vi.fn(),
    evaluateAvailability: vi.fn(),
    resetAvailability: vi.fn(),
  },
}))

vi.mock('@/composables/useRentalBooking', () => ({
  useRentalBooking: () => testState.booking,
}))

vi.mock('@/composables/useConflictDetection', () => ({
  useConflictDetection: () => ({
    checkDuplicateRental: vi.fn().mockResolvedValue({
      hasDuplicate: false,
      duplicates: [],
    }),
  }),
}))

const bootstrap = {
  request_id: 'bootstrap-1',
  evaluated_at: '2026-08-22T00:00:00Z',
  warehouses: [{
    id: 3,
    name: '华南仓',
    is_default: true,
    province: '广东省',
    city: '深圳市',
    district: '南山区',
    address_summary: '广东省深圳市南山区',
  }],
  recent_warehouse_id: null,
  default_warehouse_id: 3,
  device_models: [
    { id: 1, name: 'x200u', display_name: 'VIVO X200 Ultra' },
    { id: 2, name: 'x300u', display_name: 'VIVO X300 Ultra' },
  ],
  accessory_types: [{
    id: 8,
    name: 'tripod',
    display_name: '三脚架',
    tracking_mode: 'logical_unit',
    display_order: 1,
  }],
  form_policy: {},
}

const availability = (modelId = 1, manual = false) => ({
  request_id: `availability-${modelId}-${manual}`,
  evaluated_at: '2026-08-22T00:00:00Z',
  preferred_warehouse_id: 3,
  requested_accessory_type_ids: [],
  estimate_by_warehouse: {
    '3': {
      warehouse_id: 3,
      status: manual ? 'manual_confirmed' : 'unavailable',
      safe_failure_reason: manual ? null : 'SF_ESTIMATOR_NOT_INSTALLED',
      logistics_days: manual ? 1 : null,
      manual_confirmation_required: !manual,
      confirmation_context: 'a'.repeat(64),
    },
  },
  candidates: [{
    device: {
      id: modelId === 1 ? 11 : 21,
      name: modelId === 1 ? 'X200-01' : 'X300-01',
      model: modelId === 1 ? 'x200u' : 'x300u',
      model_id: modelId,
      warehouse_id: 3,
    },
    warehouse: bootstrap.warehouses[0],
    available: true,
    hard_conflicts: [],
    warnings: [],
    relay_candidate: false,
    logistics_days: manual ? 1 : null,
    planned_ship_out_date: manual ? '2026-07-30' : null,
    planned_return_date: manual ? '2026-08-05' : null,
    submission_ready: manual,
    accessories: [{
      accessory_type_id: 8,
      name: 'tripod',
      display_name: '三脚架',
      tracking_mode: 'logical_unit',
      requested: false,
      total: 2,
      reserved: 0,
      available: manual ? 2 : null,
      fulfilled: false,
      relay_confirmation_required: false,
      shortage: false,
      display_hint: manual
        ? 'not_requested'
        : 'logistics_confirmation_required',
    }],
  }],
})

const mountDialog = async (selectedDeviceModel?: string) => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = shallowMount(BookingDialog, {
    props: { modelValue: true, selectedDeviceModel },
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
        ElAlert: true,
        ElInputNumber: true,
        ElInput: true,
        ElButton: true,
        ElSelect: true,
        ElOption: true,
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
  return wrapper
}

const fillAvailabilityInput = (vm: any, modelId = 1) => {
  vm.form.startDate = new Date('2026-08-01T00:00:00')
  vm.form.endDate = new Date('2026-08-03T00:00:00')
  vm.form.selectedModelId = modelId
  vm.form.customerProvince = '广东省'
  vm.form.customerCity = '深圳市'
  vm.form.customerDistrict = '南山区'
  vm.form.customerAddressDetail = '测试路1号'
}

describe('BookingDialog SaaS booking contract', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    testState.booking.bootstrap = ref(bootstrap) as any
    testState.booking.availability = ref(null) as any
    testState.booking.loadBootstrap.mockResolvedValue(bootstrap)
    testState.booking.evaluateAvailability.mockImplementation(async payload => {
      const result = availability(
        payload.model_id,
        Boolean(payload.manual_logistics_by_warehouse),
      )
      testState.booking.availability.value = result
      return result
    })
    testState.booking.resetAvailability.mockImplementation(() => {
      testState.booking.availability.value = null
    })
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  it('loads one bootstrap and defaults to the Gantt model/default warehouse', async () => {
    const wrapper = await mountDialog('VIVO X200 Ultra')
    const vm = wrapper.vm as any

    expect(testState.booking.loadBootstrap).toHaveBeenCalledTimes(1)
    expect(vm.form.selectedModelId).toBe(1)
    expect(vm.form.preferredWarehouseId).toBe(3)
    expect(vm.availableDeviceModels.map((model: any) => model.id)).toEqual([1, 2])
  })

  it('uses one aggregate availability request with structured destination', async () => {
    const wrapper = await mountDialog('VIVO X200 Ultra')
    const vm = wrapper.vm as any
    fillAvailabilityInput(vm)

    await vm.checkAvailabilities()

    expect(testState.booking.evaluateAvailability).toHaveBeenCalledTimes(1)
    expect(testState.booking.evaluateAvailability).toHaveBeenCalledWith({
      start_date: '2026-08-01',
      end_date: '2026-08-03',
      model_id: 1,
      preferred_warehouse_id: 3,
      destination: {
        province: '广东省',
        city: '深圳市',
        district: '南山区',
        address_detail: '测试路1号',
      },
      requested_accessory_type_ids: [],
    })
    expect(vm.filteredDevices.map((device: any) => device.id)).toEqual([11])
  })

  it('clears stale device/accessory choices when the model changes', async () => {
    const wrapper = await mountDialog('VIVO X200 Ultra')
    const vm = wrapper.vm as any
    vm.form.selectedDeviceId = 11
    vm.form.requestedAccessoryTypeIds = [8]

    vm.handleModelChange(2)

    expect(vm.form.selectedModelId).toBe(2)
    expect(vm.form.selectedDeviceId).toBeNull()
    expect(vm.form.requestedAccessoryTypeIds).toEqual([])
    expect(wrapper.emitted('update:selectedDeviceModel')).toBeUndefined()
  })

  it('manual confirmation reuses server contexts in one explicit request', async () => {
    const wrapper = await mountDialog('VIVO X200 Ultra')
    const vm = wrapper.vm as any
    fillAvailabilityInput(vm)
    await vm.checkAvailabilities()
    testState.booking.evaluateAvailability.mockClear()

    await vm.confirmManualLogistics()

    expect(testState.booking.evaluateAvailability).toHaveBeenCalledTimes(1)
    expect(testState.booking.evaluateAvailability).toHaveBeenCalledWith(
      expect.objectContaining({
        manual_logistics_by_warehouse: {
          '3': { days: 1, context: 'a'.repeat(64) },
        },
      }),
    )
  })

  it('does not evaluate before structured inputs are complete', async () => {
    const wrapper = await mountDialog()
    const vm = wrapper.vm as any
    vm.form.startDate = new Date('2026-08-01T00:00:00')
    vm.form.endDate = new Date('2026-08-03T00:00:00')

    await vm.findAvailableSlot()

    expect(testState.booking.evaluateAvailability).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalledWith('请先选择设备型号')
  })

  it('submits the final structured tenant-runtime create contract', async () => {
    const wrapper = await mountDialog('VIVO X200 Ultra')
    const vm = wrapper.vm as any
    fillAvailabilityInput(vm)
    testState.booking.availability.value = availability(1, true)
    vm.form.selectedDeviceId = 11
    vm.form.customerName = '测试客户'
    vm.form.customerPhone = '13800138000'
    vm.form.requestedAccessoryTypeIds = [8]
    const createRental = vi.spyOn(useGanttStore(), 'createRental')
      .mockResolvedValue({
        success: true,
        data: { main_rental: { id: 42 } },
      })

    await vm.handleSubmit()

    expect(createRental).toHaveBeenCalledWith(expect.objectContaining({
      device_id: 11,
      model_id: 1,
      expected_origin_warehouse_id: 3,
      preferred_warehouse_id: 3,
      destination: {
        province: '广东省',
        city: '深圳市',
        district: '南山区',
        address_detail: '测试路1号',
      },
      requested_accessory_type_ids: [8],
      accessories: [],
    }))
  })
})

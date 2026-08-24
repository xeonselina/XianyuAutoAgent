import { createPinia, setActivePinia } from 'pinia'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { ElMessage } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import EditRentalDialogNew from '@/components/rental/EditRentalDialogNew.vue'
import { useGanttStore, type Rental } from '@/stores/gantt'

vi.mock('vue-router', () => ({
  useRouter: () => ({ resolve: vi.fn(() => ({ href: '/' })) }),
}))

vi.mock('@/composables/useDeviceManagement', () => ({
  useDeviceManagement: () => ({
    loading: { value: false },
    devices: { value: [] },
    accessories: { value: [] },
    loadDevices: vi.fn().mockResolvedValue(undefined),
    loadAccessories: vi.fn().mockResolvedValue(undefined),
  }),
}))

vi.mock('@/composables/useAvailabilityCheck', () => ({
  useAvailabilityCheck: () => ({
    checkDevicesAvailability: vi.fn().mockResolvedValue(undefined),
  }),
}))

vi.mock('@/composables/useConflictDetection', () => ({
  useConflictDetection: () => ({
    checkDeviceConflict: vi.fn().mockResolvedValue(false),
  }),
}))

vi.mock('@/composables/useRentalBooking', () => ({
  useRentalBooking: () => {
    const result = {
      request_id: 'edit-availability',
      evaluated_at: '2026-08-22T00:00:00Z',
      preferred_warehouse_id: 3,
      requested_accessory_type_ids: [],
      estimate_by_warehouse: {
        '3': {
          warehouse_id: 3,
          status: 'manual_confirmed',
          safe_failure_reason: null,
          logistics_days: 1,
          manual_confirmation_required: false,
          confirmation_context: 'c'.repeat(64),
        },
      },
      candidates: [{
        device: {
          id: 9,
          name: '测试设备',
          serial_number: 'TEST-9',
          model: 'x200u',
          model_id: 1,
          warehouse_id: 3,
        },
        warehouse: {
          id: 3,
          name: '测试仓',
          is_default: true,
          province: '广东省',
          city: '深圳市',
          district: '南山区',
          address_summary: '广东省深圳市南山区',
        },
        available: true,
        hard_conflicts: [],
        warnings: [],
        relay_candidate: false,
        logistics_days: 1,
        planned_ship_out_date: '2026-07-30',
        planned_return_date: '2026-08-07',
        submission_ready: true,
        accessories: [],
      }],
    }
    return {
      availability: { value: result },
      availabilityFailed: { value: false },
      availabilityLoading: { value: false },
      evaluateAvailability: vi.fn().mockResolvedValue(result),
      resetAvailability: vi.fn(),
    }
  },
}))

vi.mock('@/composables/useRentalFormValidation', () => ({
  getEditRentalRules: () => ({}),
}))

vi.mock('@/utils/logisticsWarning', () => ({
  getLogisticsMismatch: vi.fn().mockResolvedValue(null),
  formatLogisticsWarning: vi.fn(() => ''),
}))

const DialogStub = defineComponent({
  props: ['modelValue'],
  template: '<section v-if="modelValue"><slot /><slot name="footer" /></section>',
})

const FormStub = defineComponent({
  methods: { validate: vi.fn().mockResolvedValue(true) },
  template: '<form><slot /></form>',
})

const InputStub = defineComponent({
  props: ['modelValue', 'type', 'maxlength', 'showWordLimit'],
  emits: ['update:modelValue'],
  methods: {
    onInput(event: Event) {
      this.$emit('update:modelValue', (event.target as HTMLTextAreaElement).value)
    },
  },
  template: `
    <textarea
      v-if="type === 'textarea'"
      class="damage-note-input"
      :value="modelValue"
      :maxlength="maxlength"
      @input="onInput"
    />
  `,
})

const ButtonStub = defineComponent({
  emits: ['click'],
  template: '<button type="button" @click="$emit(\'click\')"><slot /></button>',
})

const rental = {
  id: 77,
  device_id: 9,
  start_date: '2026-08-01',
  end_date: '2026-08-05',
  customer_name: '测试客户',
  customer_phone: '13800138000',
  destination: '测试地址',
  status: 'returned',
  includes_handle: false,
  includes_lens_mount: false,
  photo_transfer: false,
  accessories: [],
  damage_note: '屏幕右下角碎裂',
  customer_province: '广东省',
  customer_city: '深圳市',
  customer_district: '南山区',
  customer_address_detail: '测试路1号',
  preferred_warehouse_id: 3,
  logistics_days: 1,
  logistics_estimate_origin_warehouse_id: 3,
  requested_accessory_type_ids: [],
  device: {
    id: 9,
    name: '测试设备',
    serial_number: 'TEST-9',
    model: 'x200u',
    model_id: 1,
  },
} as Rental & { damage_note?: string | null }

describe('desktop rental damage note editing', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  it('loads, warns, edits, and submits the current damage note', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useGanttStore()
    const getEditContext = vi.spyOn(
      store,
      'getRentalEditContext'
    ).mockResolvedValue({
      request_id: 'test-edit-context',
      evaluated_at: '2026-08-22T00:00:00Z',
      rental: { ...rental },
      devices: [{
        id: 9,
        name: '测试设备',
        serial_number: 'TEST-9',
        model: 'x200u',
        model_id: 1,
        warehouse_id: 3,
        is_accessory: false,
        lifecycle_status: 'active',
        created_at: '2026-08-01T00:00:00',
        updated_at: '2026-08-01T00:00:00',
      }],
      legacy_device_bound_accessories: [],
      warehouses: [{
        id: 3,
        name: '测试仓',
        is_default: true,
        province: '广东省',
        city: '深圳市',
        district: '南山区',
        address_summary: '广东省深圳市南山区',
      }],
      device_models: [{ id: 1, name: 'x200u', display_name: 'X200U' }],
      accessory_types: [],
      form_policy: {},
    })
    const update = vi.spyOn(store, 'updateRental').mockResolvedValue({ success: true })
    const wrapper = mount(EditRentalDialogNew, {
      props: { modelValue: true, rental: { ...rental } },
      global: {
        plugins: [pinia],
        stubs: {
          ElDialog: DialogStub,
          ElForm: FormStub,
          ElButton: ButtonStub,
          ElDivider: { template: '<div><slot /></div>' },
          ElFormItem: { template: '<label><slot /></label>' },
          ElInput: InputStub,
          ElAlert: {
            props: ['title'],
            template: '<aside class="damage-note-warning">{{ title }}</aside>',
          },
          RentalActionButtons: true,
          RentalBasicForm: true,
          RentalShippingForm: true,
          RentalAccessorySelector: true,
        },
      },
    })
    await flushPromises()

    expect(getEditContext).toHaveBeenCalledTimes(1)
    expect(getEditContext).toHaveBeenCalledWith(rental.id)
    const textareas = wrapper.findAll('textarea.damage-note-input')
    const textarea = textareas[textareas.length - 1]
    if (!textarea) throw new Error('未找到损坏备注输入框')
    expect(textarea.element.value).toBe('屏幕右下角碎裂')
    expect(textarea.attributes('maxlength')).toBe('1000')
    expect(
      wrapper.findAll('.damage-note-warning').some(
        warning => warning.text().includes('已记录用户损坏反馈'),
      ),
    ).toBe(true)

    await textarea.setValue('镜头卡口松动')
    const saveButton = wrapper.findAll('button').find(button => button.text() === '保存')
    if (!saveButton) throw new Error('未找到保存按钮')
    await saveButton.trigger('click')
    await flushPromises()

    expect(update).toHaveBeenCalledWith(
      rental.id,
      expect.objectContaining({ damage_note: '镜头卡口松动' }),
    )
  })
})

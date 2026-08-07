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
    vi.spyOn(store, 'getRentalById').mockResolvedValue({ ...rental })
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

    const textarea = wrapper.get('textarea.damage-note-input')
    expect(textarea.element.value).toBe('屏幕右下角碎裂')
    expect(textarea.attributes('maxlength')).toBe('1000')
    expect(wrapper.get('.damage-note-warning').text()).toContain('已记录用户损坏反馈')

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

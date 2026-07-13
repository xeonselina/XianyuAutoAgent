import { defineComponent } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import { ElMessage, ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import BookingDialog from '@/components/BookingDialog.vue'
import EditRentalDialogNew from '@/components/rental/EditRentalDialogNew.vue'
import { useGanttStore, type Rental } from '@/stores/gantt'

vi.mock('vue-router', () => ({
  useRouter: () => ({
    resolve: vi.fn(() => ({ href: '/' })),
  }),
}))

vi.mock('@/composables/useDeviceManagement', () => ({
  useDeviceManagement: () => ({
    loading: { value: false },
    devices: { value: [] },
    accessories: { value: [] },
    deviceModels: { value: [] },
    loadDevices: vi.fn().mockResolvedValue(undefined),
    loadAccessories: vi.fn().mockResolvedValue(undefined),
    loadDeviceModels: vi.fn().mockResolvedValue(undefined),
  }),
}))

vi.mock('@/composables/useAvailabilityCheck', () => ({
  useAvailabilityCheck: () => ({
    deviceAvailability: { value: { checked: false, availableItems: [], unavailableItems: [] } },
    accessoryAvailability: { value: { checked: false, availableItems: [], unavailableItems: [] } },
    resetAll: vi.fn(),
    checkDevicesAvailability: vi.fn().mockResolvedValue(undefined),
    checkAccessoriesAvailability: vi.fn().mockResolvedValue(undefined),
    isDeviceAvailable: vi.fn(() => true),
    isAccessoryAvailable: vi.fn(() => true),
  }),
}))

vi.mock('@/composables/useConflictDetection', () => ({
  useConflictDetection: () => ({
    checkDuplicateRental: vi.fn().mockResolvedValue({
      hasDuplicate: false,
      duplicates: [],
    }),
    checkDeviceConflict: vi.fn().mockResolvedValue(false),
  }),
}))

vi.mock('@/composables/useRentalFormValidation', () => ({
  getCreateRentalRules: () => ({}),
  getEditRentalRules: () => ({}),
}))

const DialogStub = defineComponent({
  props: ['modelValue', 'showClose', 'closeOnPressEscape'],
  emits: ['closed'],
  template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>',
})

const FormStub = defineComponent({
  emits: ['submit'],
  methods: {
    validate: vi.fn().mockResolvedValue(true),
    resetFields: vi.fn(),
  },
  template: '<form @submit.prevent="$emit(\'submit\')"><slot /></form>',
})

const ButtonStub = defineComponent({
  props: ['disabled'],
  emits: ['click'],
  template: '<button type="button" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
})

const RentalActionButtonsStub = defineComponent({
  emits: ['delete'],
  template: '<button type="button" @click="$emit(\'delete\')">删除</button>',
})

const globalStubs = {
  ElDialog: DialogStub,
  ElForm: FormStub,
  ElButton: ButtonStub,
  ElFormItem: { template: '<div><slot /></div>' },
  ElDivider: { template: '<div><slot /></div>' },
  ElInputNumber: true,
  ElInput: true,
  ElTag: true,
  ElOption: true,
  ElSelect: true,
  ElCheckbox: true,
  ElCheckboxGroup: true,
  ElIcon: true,
  VueDatePicker: true,
  LensComboSelector: true,
  RentalActionButtons: RentalActionButtonsStub,
  RentalBasicForm: true,
  RentalShippingForm: true,
  RentalAccessorySelector: true,
}

const rental77: Rental = {
  id: 77,
  device_id: 9,
  start_date: '2026-07-20',
  end_date: '2026-07-22',
  customer_name: '测试客户',
  customer_phone: '13800138000',
  destination: '测试地址',
  status: 'not_shipped',
  includes_handle: false,
  includes_lens_mount: false,
  photo_transfer: false,
  accessories: [],
}

const findButton = (wrapper: VueWrapper, label: string) => {
  const button = wrapper.findAll('button').find(candidate => candidate.text() === label)
  if (!button) throw new Error(`未找到按钮：${label}`)
  return button
}

const clickButton = async (wrapper: VueWrapper, label: string) => {
  const button = findButton(wrapper, label)
  await button.trigger('click')
  await flushPromises()
}

const emitDialogClosed = async (wrapper: VueWrapper) => {
  wrapper.findComponent(DialogStub).vm.$emit('closed')
  await flushPromises()
}

const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

const mountBookingDialog = () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useGanttStore()
  const wrapper = shallowMount(BookingDialog, {
    props: { modelValue: true },
    global: {
      plugins: [pinia],
      stubs: globalStubs,
    },
  })

  const form = (wrapper.vm as any).form
  form.startDate = new Date('2026-07-20T00:00:00')
  form.endDate = new Date('2026-07-22T00:00:00')
  form.selectedDeviceId = 9
  form.customerName = '测试客户'
  form.destination = '测试地址'

  return { store, wrapper }
}

const mountEditDialog = async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useGanttStore()
  vi.spyOn(store, 'getRentalById').mockResolvedValue({ ...rental77 })
  const wrapper = shallowMount(EditRentalDialogNew, {
    props: { modelValue: true, rental: { ...rental77 } },
    global: {
      plugins: [pinia],
      stubs: globalStubs,
    },
  })
  await flushPromises()

  return { store, wrapper }
}

describe('rental save success events', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  it('新建成功时通过 success 事件携带创建后的 rental ID', async () => {
    const { store, wrapper } = mountBookingDialog()
    vi.spyOn(store, 'createRental').mockResolvedValue({
      success: true,
      data: { main_rental: { id: 42 } },
    })

    await clickButton(wrapper, '提交预定')

    expect(wrapper.emitted('success')).toBeUndefined()
    await emitDialogClosed(wrapper)
    expect(wrapper.emitted('success')).toEqual([[42]])
  })

  it('编辑成功时通过 success 事件携带当前 rental ID', async () => {
    const { store, wrapper } = await mountEditDialog()
    vi.spyOn(store, 'updateRental').mockResolvedValue({ success: true })

    await clickButton(wrapper, '保存')

    expect(wrapper.emitted('success')).toBeUndefined()
    await emitDialogClosed(wrapper)
    expect(wrapper.emitted('success')).toEqual([[77]])
  })

  it('删除成功时保留无参数 success 刷新信号', async () => {
    const { store, wrapper } = await mountEditDialog()
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(undefined as never)
    vi.spyOn(store, 'deleteRental').mockResolvedValue({ success: true })

    await clickButton(wrapper, '删除')

    expect(wrapper.emitted('success')).toBeUndefined()
    await emitDialogClosed(wrapper)
    expect(wrapper.emitted('success')).toEqual([[]])
  })

  it('新建已保存但响应缺少 rental ID 时关闭表单并提示确认信息加载失败', async () => {
    const { store, wrapper } = mountBookingDialog()
    vi.spyOn(store, 'createRental').mockResolvedValue({ success: true, data: {} })

    await clickButton(wrapper, '提交预定')

    expect(wrapper.emitted('success')).toBeUndefined()
    expect(wrapper.emitted('update:modelValue')).toContainEqual([false])
    expect(ElMessage.error).toHaveBeenCalledWith('保存成功，但确认信息加载失败')
    expect(ElMessage.error).not.toHaveBeenCalledWith(expect.stringContaining('创建失败'))

    await emitDialogClosed(wrapper)
    expect(wrapper.emitted('success')).toBeUndefined()
  })

  it('取消关闭新建或编辑表单后不误发 success', async () => {
    const { wrapper: createWrapper } = mountBookingDialog()

    await clickButton(createWrapper, '取消')
    await emitDialogClosed(createWrapper)

    expect(createWrapper.emitted('success')).toBeUndefined()

    const { wrapper: editWrapper } = await mountEditDialog()

    await clickButton(editWrapper, '取消')
    await emitDialogClosed(editWrapper)

    expect(editWrapper.emitted('success')).toBeUndefined()
  })

  it('新建请求 pending 时先 closed，响应后仍立即且只发一次 success', async () => {
    const { store, wrapper } = mountBookingDialog()
    const request = deferred<{ success: boolean; data: { main_rental: { id: number } } }>()
    vi.spyOn(store, 'createRental').mockReturnValue(request.promise)

    await clickButton(wrapper, '提交预定')
    expect(store.createRental).toHaveBeenCalledTimes(1)

    await wrapper.setProps({ modelValue: false })
    await emitDialogClosed(wrapper)
    request.resolve({ success: true, data: { main_rental: { id: 42 } } })
    await flushPromises()

    expect(wrapper.emitted('success')).toEqual([[42]])

    await wrapper.setProps({ modelValue: true })
    await clickButton(wrapper, '取消')
    await wrapper.setProps({ modelValue: false })
    await emitDialogClosed(wrapper)

    expect(wrapper.emitted('success')).toEqual([[42]])
  })

  it('编辑请求 pending 时先 closed，响应后仍立即且只发一次 success', async () => {
    const { store, wrapper } = await mountEditDialog()
    const request = deferred<{ success: boolean }>()
    vi.spyOn(store, 'updateRental').mockReturnValue(request.promise)

    await clickButton(wrapper, '保存')
    expect(store.updateRental).toHaveBeenCalledTimes(1)

    await wrapper.setProps({ modelValue: false })
    await emitDialogClosed(wrapper)
    request.resolve({ success: true })
    await flushPromises()

    expect(wrapper.emitted('success')).toEqual([[77]])

    await wrapper.setProps({ modelValue: true })
    await clickButton(wrapper, '取消')
    await wrapper.setProps({ modelValue: false })
    await emitDialogClosed(wrapper)

    expect(wrapper.emitted('success')).toEqual([[77]])
  })

  it('新建或编辑请求 pending 时禁用正常关闭入口', async () => {
    const { store: createStore, wrapper: createWrapper } = mountBookingDialog()
    vi.spyOn(createStore, 'createRental').mockReturnValue(deferred<any>().promise)

    await clickButton(createWrapper, '提交预定')

    expect(findButton(createWrapper, '取消').attributes('disabled')).toBeDefined()
    expect(createWrapper.findComponent(DialogStub).props('showClose')).toBe(false)
    expect(createWrapper.findComponent(DialogStub).props('closeOnPressEscape')).toBe(false)

    const { store: updateStore, wrapper: updateWrapper } = await mountEditDialog()
    vi.spyOn(updateStore, 'updateRental').mockReturnValue(deferred<any>().promise)

    await clickButton(updateWrapper, '保存')

    expect(findButton(updateWrapper, '取消').attributes('disabled')).toBeDefined()
    expect(updateWrapper.findComponent(DialogStub).props('showClose')).toBe(false)
    expect(updateWrapper.findComponent(DialogStub).props('closeOnPressEscape')).toBe(false)
  })

  it('新建或编辑保存被拒绝时不发 success 并保留现有失败提示', async () => {
    const { store: createStore, wrapper: createWrapper } = mountBookingDialog()
    vi.spyOn(createStore, 'createRental').mockRejectedValue(new Error('网络异常'))

    await clickButton(createWrapper, '提交预定')

    expect(createWrapper.emitted('success')).toBeUndefined()
    expect(ElMessage.error).toHaveBeenCalledWith('创建失败：网络异常')

    const { store: updateStore, wrapper: updateWrapper } = await mountEditDialog()
    vi.spyOn(updateStore, 'updateRental').mockRejectedValue(new Error('保存被拒绝'))

    await clickButton(updateWrapper, '保存')

    expect(updateWrapper.emitted('success')).toBeUndefined()
    expect(ElMessage.error).toHaveBeenCalledWith('更新失败：保存被拒绝')
  })
})

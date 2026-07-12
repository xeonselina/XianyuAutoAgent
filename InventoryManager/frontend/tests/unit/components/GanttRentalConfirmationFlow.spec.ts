import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import BookingDialog from '@/components/BookingDialog.vue'
import EditRentalDialogNew from '@/components/rental/EditRentalDialogNew.vue'
import GanttChart from '@/components/GanttChart.vue'
import RentalConfirmationDialog from '@/components/RentalConfirmationDialog.vue'
import { useGanttStore, type Rental } from '@/stores/gantt'

const { axiosGet } = vi.hoisted(() => ({
  axiosGet: vi.fn(),
}))

vi.mock('axios', () => ({
  default: {
    get: axiosGet,
  },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: vi.fn(),
  }),
}))

const savedRental = (id: number): Rental => ({
  id,
  device_id: 8,
  start_date: '2026-07-14',
  end_date: '2026-07-20',
  customer_name: '流程测试客户',
  customer_phone: '13800138000',
  destination: '广东省广州市天河区一号路',
  status: 'not_shipped',
  includes_handle: true,
  includes_lens_mount: false,
  photo_transfer: false,
  accessories: [],
})

let wrapper: VueWrapper | undefined

const mountGantt = async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useGanttStore()
  const loadData = vi.spyOn(store, 'loadData').mockResolvedValue(undefined)
  const getRentalById = vi.spyOn(store, 'getRentalById').mockResolvedValue(null)

  wrapper = shallowMount(GanttChart, {
    global: {
      plugins: [pinia],
      stubs: {
        GanttRow: true,
        BatchPrintDialog: true,
        CustomerHistoryDialog: true,
        ScheduleReorderDialog: true,
        ElIcon: true,
        ElRow: true,
        ElCol: true,
        ElButton: true,
        ElButtonGroup: true,
        ElDatePicker: true,
        ElInput: true,
        ElSelect: true,
        ElOption: true,
        ElDropdown: true,
        ElDropdownMenu: true,
        ElDropdownItem: true,
        ElDialog: true,
        ElForm: true,
        ElFormItem: true,
        ElCheckbox: true,
      },
      directives: {
        loading: () => undefined,
      },
    },
  })
  await flushPromises()

  loadData.mockClear()
  getRentalById.mockClear()
  vi.mocked(ElMessage.error).mockClear()

  return { store, wrapper }
}

describe('GanttChart rental confirmation flow', () => {
  beforeEach(() => {
    axiosGet.mockResolvedValue({ data: { success: true, data: [] } })
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
    vi.restoreAllMocks()
    axiosGet.mockReset()
  })

  it('新建保存后按返回 ID 重新查询并打开确认弹窗', async () => {
    const { store, wrapper } = await mountGantt()
    const latestRental = savedRental(42)
    vi.mocked(store.getRentalById).mockResolvedValue(latestRental)

    wrapper.findComponent(BookingDialog).vm.$emit('success', 42)
    await flushPromises()

    expect(store.loadData).toHaveBeenCalled()
    expect(store.getRentalById).toHaveBeenCalledWith(42)
    const confirmation = wrapper.findComponent(RentalConfirmationDialog)
    expect(confirmation.props('modelValue')).toBe(true)
    expect(confirmation.props('rental')).toEqual(latestRental)
  })

  it('编辑保存后按当前 ID 重新查询并打开确认弹窗', async () => {
    const { store, wrapper } = await mountGantt()
    const latestRental = savedRental(77)
    vi.mocked(store.getRentalById).mockResolvedValue(latestRental)

    wrapper.findComponent(EditRentalDialogNew).vm.$emit('success', 77)
    await flushPromises()

    expect(store.loadData).toHaveBeenCalled()
    expect(store.getRentalById).toHaveBeenCalledWith(77)
    const confirmation = wrapper.findComponent(RentalConfirmationDialog)
    expect(confirmation.props('modelValue')).toBe(true)
    expect(confirmation.props('rental')).toEqual(latestRental)
  })

  it('保存成功但重新查询为空时关闭确认弹窗并显示固定提示', async () => {
    const { store, wrapper } = await mountGantt()
    ;(wrapper.vm as unknown as { selectedRental: Rental | null }).selectedRental = savedRental(9)
    vi.mocked(store.getRentalById).mockResolvedValue(null)

    wrapper.findComponent(BookingDialog).vm.$emit('success', 42)
    await flushPromises()

    const confirmation = wrapper.findComponent(RentalConfirmationDialog)
    expect(confirmation.props('modelValue')).toBe(false)
    expect(confirmation.props('rental')).toBeNull()
    expect(ElMessage.error).toHaveBeenCalledTimes(1)
    expect(ElMessage.error).toHaveBeenCalledWith('保存成功，但确认信息加载失败')
  })

  it('刷新完成后查询拒绝时清空旧确认、关闭弹窗且只提示一次', async () => {
    const { store, wrapper } = await mountGantt()
    const oldRental = savedRental(41)
    vi.mocked(store.getRentalById).mockResolvedValueOnce(oldRental)

    wrapper.findComponent(BookingDialog).vm.$emit('success', 41)
    await flushPromises()

    expect(wrapper.findComponent(RentalConfirmationDialog).props('modelValue')).toBe(true)
    expect(wrapper.findComponent(RentalConfirmationDialog).props('rental')).toEqual(oldRental)

    const callOrder: string[] = []
    let completeRefresh!: () => void
    const refreshPending = new Promise<void>((resolve) => {
      completeRefresh = resolve
    })
    vi.mocked(store.loadData).mockImplementationOnce(async () => {
      await refreshPending
      callOrder.push('loadData complete')
    })
    let rejectQuery!: (reason: Error) => void
    const rejectedQuery = new Promise<Rental | null>((_resolve, reject) => {
      rejectQuery = reject
    })
    vi.mocked(store.getRentalById).mockImplementationOnce(() => {
      callOrder.push('getRentalById')
      return rejectedQuery
    })

    wrapper.findComponent(BookingDialog).vm.$emit('success', 42)
    await flushPromises()

    expect(callOrder).toEqual([])
    expect(store.getRentalById).toHaveBeenCalledTimes(1)

    completeRefresh()
    await flushPromises()

    expect(callOrder).toEqual(['loadData complete', 'getRentalById'])
    expect(store.getRentalById).toHaveBeenLastCalledWith(42)
    expect(wrapper.findComponent(RentalConfirmationDialog).props('modelValue')).toBe(false)
    expect(wrapper.findComponent(RentalConfirmationDialog).props('rental')).toBeNull()

    rejectQuery(new Error('network failure'))
    await flushPromises()

    expect(wrapper.findComponent(RentalConfirmationDialog).props('modelValue')).toBe(false)
    expect(wrapper.findComponent(RentalConfirmationDialog).props('rental')).toBeNull()
    expect(ElMessage.error).toHaveBeenCalledTimes(1)
    expect(ElMessage.error).toHaveBeenCalledWith('保存成功，但确认信息加载失败')
  })

  it('删除发出无 ID 成功信号时只刷新且不查询、不弹窗、不报确认加载失败', async () => {
    const { store, wrapper } = await mountGantt()

    wrapper.findComponent(EditRentalDialogNew).vm.$emit('success')
    await flushPromises()

    expect(store.loadData).toHaveBeenCalled()
    expect(store.getRentalById).not.toHaveBeenCalled()
    expect(wrapper.findComponent(RentalConfirmationDialog).props('modelValue')).toBe(false)
    expect(ElMessage.error).not.toHaveBeenCalledWith('保存成功，但确认信息加载失败')
  })
})

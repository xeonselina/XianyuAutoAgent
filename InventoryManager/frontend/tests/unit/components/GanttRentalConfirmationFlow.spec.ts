import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import { ElMessage, ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import BookingDialog from '@/components/BookingDialog.vue'
import EditRentalDialogNew from '@/components/rental/EditRentalDialogNew.vue'
import GanttChart from '@/components/GanttChart.vue'
import RentalConfirmationDialog from '@/components/RentalConfirmationDialog.vue'
import XianyuOrderAlertBar from '@/components/XianyuOrderAlertBar.vue'
import { useGanttStore, type Rental } from '@/stores/gantt'
import { useTenantStore } from '@/stores/tenant'

const { axiosGet, axiosPost } = vi.hoisted(() => ({
  axiosGet: vi.fn(),
  axiosPost: vi.fn(),
}))

vi.mock('axios', () => ({
  default: {
    get: axiosGet,
    post: axiosPost,
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
    const alertSnapshot = {
      alerts: [],
      count: 0,
      refreshing: false,
      sync: {
        last_attempt_at: '2026-07-24T10:00:00',
        last_success_at: '2026-07-24T10:00:00',
        last_error: null,
      },
    }
    axiosGet.mockImplementation((url: string) => Promise.resolve({
      data: {
        success: true,
        data: url === '/api/xianyu-order-alerts'
          ? alertSnapshot
          : url === '/api/gantt/daily-stats'
            ? { stats: {} }
            : [],
      },
    }))
    axiosPost.mockResolvedValue({
      data: { success: true, data: alertSnapshot },
    })
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
    vi.useRealTimers()
    vi.restoreAllMocks()
    axiosGet.mockReset()
    axiosPost.mockReset()
  })

  it('每次统计加载只请求一次可见日期范围', async () => {
    vi.useFakeTimers()
    await mountGantt()

    await vi.advanceTimersByTimeAsync(301)
    await flushPromises()

    const statsCalls = axiosGet.mock.calls.filter(
      ([url]) => url === '/api/gantt/daily-stats',
    )
    expect(statsCalls).toHaveLength(1)
    expect(statsCalls[0][1]).toEqual({
      params: expect.objectContaining({
        start_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
        end_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      }),
    })
    expect(statsCalls[0][1].params).not.toHaveProperty('date')
  })

  it('漏录告警打开同一个预定弹框并传入订单号', async () => {
    const { wrapper } = await mountGantt()
    const alertBar = wrapper.findComponent(XianyuOrderAlertBar)

    expect(alertBar.exists()).toBe(true)
    alertBar.vm.$emit('book', {
      orderNo: 'XY-MISSING', shopId: 7, shopName: '深圳店',
    })
    await flushPromises()

    const bookingDialog = wrapper.findComponent(BookingDialog)
    expect(bookingDialog.props('modelValue')).toBe(true)
    expect(bookingDialog.props('initialXianyuOrderNo')).toBe(
      'XY-MISSING',
    )
    expect(bookingDialog.props('initialXianyuShopId')).toBe(7)
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

  it('退款提醒切换至档期仓库并确认客户设备日期后，只删除所选档期和刷新提醒', async () => {
    const { store, wrapper } = await mountGantt()
    const tenant = useTenantStore()
    tenant.setWarehousesForSession([
      { id: 1, name: '广州仓', province: '广东', city: '广州' },
      { id: 2, name: '深圳仓', province: '广东', city: '深圳' },
    ])
    const rental = {
      ...savedRental(42), warehouse_id: 2, xianyu_shop_id: 7, xianyu_order_no: 'XY-CLOSED',
      device: { id: 8, name: '相机A', serial_number: 'A', model: 'A' },
    }
    vi.mocked(store.getRentalById).mockResolvedValue(rental)
    const deleteRental = vi.spyOn(store, 'deleteRental').mockResolvedValue({ success: true })
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm')
    axiosGet.mockClear()

    wrapper.findComponent(XianyuOrderAlertBar).vm.$emit('rental-action', {
      orderNo: 'XY-CLOSED', shopId: 7, rentalId: 42, action: 'delete',
    })
    await flushPromises()

    expect(tenant.currentWarehouseId).toBe(2)
    expect(confirm).toHaveBeenCalledWith(
      expect.stringContaining('流程测试客户 的 相机A 档期（2026-07-14 至 2026-07-20）'),
      '确认删除', expect.any(Object),
    )
    expect(deleteRental).toHaveBeenCalledExactlyOnceWith(42)
    expect(axiosGet).toHaveBeenCalledWith('/api/xianyu-order-alerts')
  })

  it('取消退款档期删除确认时不删除，提醒保持原样', async () => {
    const { store, wrapper } = await mountGantt()
    useTenantStore().setWarehousesForSession([{ id: 1, name: '测试仓', province: '广东', city: '深圳' }])
    vi.mocked(store.getRentalById).mockResolvedValue({
      ...savedRental(42), warehouse_id: 1, xianyu_shop_id: 7, xianyu_order_no: 'XY-CLOSED',
    })
    const deleteRental = vi.spyOn(store, 'deleteRental')
    vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
    wrapper.findComponent(XianyuOrderAlertBar).vm.$emit('rental-action', {
      orderNo: 'XY-CLOSED', shopId: 7, rentalId: 42, action: 'delete',
    })
    await flushPromises()
    expect(deleteRental).not.toHaveBeenCalled()
    expect(wrapper.findComponent(XianyuOrderAlertBar).props('busyRentalId')).toBeUndefined()
  })

  it('点击提醒时档期已发货，改为查看档期并保留设备回收跟进', async () => {
    const { store, wrapper } = await mountGantt()
    useTenantStore().setWarehousesForSession([{ id: 1, name: '测试仓', province: '广东', city: '深圳' }])
    const rental = {
      ...savedRental(42), warehouse_id: 1, xianyu_shop_id: 7, xianyu_order_no: 'XY-CLOSED', status: 'shipped',
    }
    vi.mocked(store.getRentalById).mockResolvedValue(rental)
    const deleteRental = vi.spyOn(store, 'deleteRental')
    wrapper.findComponent(XianyuOrderAlertBar).vm.$emit('rental-action', {
      orderNo: 'XY-CLOSED', shopId: 7, rentalId: 42, action: 'delete',
    })
    await flushPromises()
    expect(deleteRental).not.toHaveBeenCalled()
    expect(wrapper.findComponent(EditRentalDialogNew).props('modelValue')).toBe(true)
    expect(wrapper.findComponent(EditRentalDialogNew).props('rental')).toEqual(rental)
  })

  it('提醒中的档期已经换绑订单时拒绝删除', async () => {
    const { store, wrapper } = await mountGantt()
    vi.mocked(store.getRentalById).mockResolvedValue({ ...savedRental(42), xianyu_shop_id: 7, xianyu_order_no: 'NEW' })
    const deleteRental = vi.spyOn(store, 'deleteRental')
    wrapper.findComponent(XianyuOrderAlertBar).vm.$emit('rental-action', {
      orderNo: 'OLD', shopId: 7, rentalId: 42, action: 'delete',
    })
    await flushPromises()
    expect(deleteRental).not.toHaveBeenCalled()
    expect(wrapper.findComponent(EditRentalDialogNew).props('modelValue')).toBe(false)
  })
})

import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import PendingReturnsDrawer from '@/components/PendingReturnsDrawer.vue'
import GanttChart from '@/components/GanttChart.vue'
import { useGanttStore } from '@/stores/gantt'

const { axiosGet, axiosPost, axiosPut } = vi.hoisted(() => ({
  axiosGet: vi.fn(),
  axiosPost: vi.fn(),
  axiosPut: vi.fn(),
}))

vi.mock('axios', () => ({
  default: {
    get: axiosGet,
    post: axiosPost,
    put: axiosPut,
  },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

const pendingReturn = {
  id: 21,
  device_model: 'iPhone 15 Pro',
  start_date: '2026-07-20',
  end_date: '2026-07-28',
  due_date: '2026-07-29',
  overdue_days: 3,
  destination: '上海市浦东新区',
  customer_phone: '13800138000',
  status: 'shipped' as const,
}

const pendingResponse = (rentals = [pendingReturn]) => ({
  data: {
    success: true,
    data: { rentals, count: rentals.length },
  },
})

const alertSnapshot = {
  alerts: [],
  count: 0,
  refreshing: false,
  sync: {
    last_attempt_at: '2026-07-29T10:00:00',
    last_success_at: '2026-07-29T10:00:00',
    last_error: null,
  },
}

const mountGantt = async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useGanttStore()
  const loadData = vi.spyOn(store, 'loadData').mockResolvedValue(undefined)
  const wrapper = shallowMount(GanttChart, {
    global: {
      plugins: [pinia],
      stubs: {
        GanttRow: true,
        BookingDialog: true,
        EditRentalDialogNew: true,
        RentalConfirmationDialog: true,
        XianyuOrderAlertBar: true,
        BatchPrintDialog: true,
        CustomerHistoryDialog: true,
        ScheduleReorderDialog: true,
        ElIcon: true,
        ElRow: { template: '<div><slot /></div>' },
        ElCol: { template: '<div><slot /></div>' },
        ElButton: {
          emits: ['click'],
          template: '<button @click="$emit(\'click\')"><slot /></button>',
        },
        ElButtonGroup: true,
        ElBadge: {
          props: ['value', 'hidden'],
          template: '<div :data-value="value"><slot /></div>',
        },
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
  return { wrapper, store, loadData }
}

describe('GanttChart pending-returns flow', () => {
  beforeEach(() => {
    axiosGet.mockReset()
    axiosPost.mockReset()
    axiosPut.mockReset()
    axiosGet.mockImplementation((url: string) => {
      if (url === '/api/rentals/pending-returns') {
        return Promise.resolve(pendingResponse())
      }
      if (url === '/api/xianyu-order-alerts') {
        return Promise.resolve({
          data: { success: true, data: alertSnapshot },
        })
      }
      return Promise.resolve({
        data: { success: true, data: [] },
      })
    })
    axiosPost.mockResolvedValue({
      data: { success: true, data: alertSnapshot },
    })
    axiosPut.mockResolvedValue({
      data: {
        success: true,
        data: { id: pendingReturn.id, status: 'returned' },
      },
    })
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('loads the total and refreshes the list when opening the drawer', async () => {
    const { wrapper } = await mountGantt()

    expect(wrapper.get('.pending-returns-badge').attributes('data-value')).toBe('1')
    expect(axiosGet).toHaveBeenCalledWith('/api/rentals/pending-returns')
    expect(wrapper.get('[data-testid="pending-returns-button"]').text()).toContain(
      '待归还',
    )

    await wrapper.get('[data-testid="pending-returns-button"]').trigger('click')
    await flushPromises()

    const pendingCalls = axiosGet.mock.calls.filter(
      ([url]) => url === '/api/rentals/pending-returns',
    )
    expect(pendingCalls).toHaveLength(2)
    expect(
      wrapper.findComponent(PendingReturnsDrawer).props('modelValue'),
    ).toBe(true)
  })

  it('marks a row returned and refreshes the gantt data', async () => {
    const { wrapper, loadData } = await mountGantt()

    wrapper.findComponent(PendingReturnsDrawer).vm.$emit(
      'mark-returned',
      pendingReturn.id,
    )
    await flushPromises()

    expect(axiosPut).toHaveBeenCalledWith(
      `/api/rentals/${pendingReturn.id}/status`,
      { status: 'returned' },
    )
    expect(loadData).toHaveBeenCalledTimes(1)
    expect(ElMessage.success).toHaveBeenCalledWith('已标记为已寄回')
  })
})

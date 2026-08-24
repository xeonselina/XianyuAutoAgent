import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import PendingReturnsDrawer from '@/components/PendingReturnsDrawer.vue'
import GanttChart from '@/components/GanttChart.vue'
import { useGanttStore, type Device } from '@/stores/gantt'

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

let resizeCallback: ResizeObserverCallback | undefined
const observeGanttBody = vi.fn()
const disconnectGanttBody = vi.fn()

class ResizeObserverStub {
  constructor(callback: ResizeObserverCallback) {
    resizeCallback = callback
  }

  observe = observeGanttBody
  unobserve = vi.fn()
  disconnect = disconnectGanttBody
}

const makeDevices = (): Device[] => Array.from({ length: 20 }, (_, index) => ({
  id: index + 1,
  name: `测试设备 ${index + 1}`,
  serial_number: `SN-${index + 1}`,
  model: '测试型号',
  is_accessory: false,
  lifecycle_status: 'active',
  created_at: '2026-08-03T00:00:00',
  updated_at: '2026-08-03T00:00:00',
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

const mountGantt = async (devices: Device[] = [], pendingCount = 0) => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useGanttStore()
  store.devices = devices
  store.summaries = {
    pending_returns: { count: pendingCount, revision: `test:${pendingCount}` },
  }
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
    resizeCallback = undefined
    observeGanttBody.mockClear()
    disconnectGanttBody.mockClear()
    vi.stubGlobal('ResizeObserver', ResizeObserverStub)
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
    vi.unstubAllGlobals()
  })

  it('keeps the final rows rendered when the alert changes the viewport height', async () => {
    const { wrapper } = await mountGantt(makeDevices())
    const body = wrapper.get('.gantt-body').element as HTMLElement

    Object.defineProperty(body, 'clientHeight', {
      configurable: true,
      value: 188,
    })
    Object.defineProperty(body, 'scrollTop', {
      configurable: true,
      writable: true,
      value: 0,
    })

    expect(resizeCallback).toBeTypeOf('function')
    resizeCallback?.([], {} as ResizeObserver)
    await wrapper.vm.$nextTick()

    expect(wrapper.findAllComponents({ name: 'GanttRow' })).toHaveLength(4)
    expect(wrapper.get('.virtual-container').attributes('style')).toContain(
      'height: 1881px',
    )

    body.scrollTop = (20 * 94) - 188
    body.dispatchEvent(new Event('scroll'))
    await wrapper.vm.$nextTick()

    Object.defineProperty(body, 'clientHeight', {
      configurable: true,
      value: 940,
    })
    body.scrollTop = (20 * 94) - 940
    resizeCallback?.([], {} as ResizeObserver)
    await wrapper.vm.$nextTick()

    const renderedRows = wrapper.findAllComponents({ name: 'GanttRow' })
    expect(renderedRows).toHaveLength(12)
    expect(renderedRows[0].attributes('style')).toContain('height: 94px')
    expect(renderedRows.at(-1)?.props('device').id).toBe(20)
  })

  it('disconnects the Gantt viewport observer when unmounted', async () => {
    const { wrapper } = await mountGantt(makeDevices())

    expect(observeGanttBody).toHaveBeenCalledWith(
      wrapper.get('.gantt-body').element,
    )

    wrapper.unmount()

    expect(disconnectGanttBody).toHaveBeenCalledTimes(1)
  })

  it('uses the range summary and loads the list only when opening the drawer', async () => {
    const { wrapper } = await mountGantt([], 1)

    expect(wrapper.get('.pending-returns-badge').attributes('data-value')).toBe('1')
    expect(axiosGet).not.toHaveBeenCalledWith('/api/rentals/pending-returns')
    expect(wrapper.get('[data-testid="pending-returns-button"]').text()).toContain(
      '待归还',
    )

    await wrapper.get('[data-testid="pending-returns-button"]').trigger('click')
    await flushPromises()

    const pendingCalls = axiosGet.mock.calls.filter(
      ([url]) => url === '/api/rentals/pending-returns',
    )
    expect(pendingCalls).toHaveLength(1)
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

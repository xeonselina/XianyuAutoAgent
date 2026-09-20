import ElementPlus, { ElTag, ElTooltip } from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import {
  computed,
  defineComponent,
  h,
  inject,
  markRaw,
  nextTick,
  provide,
  type InjectionKey,
  type Ref,
} from 'vue'
import { beforeAll, afterAll, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import axios from 'axios'

import BatchShippingView from '@/views/BatchShippingView.vue'
import { useTenantStore } from '@/stores/tenant'


vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('axios')


type PreviousRentalState = {
  has_previous_rental: boolean
  previous_rental_status: string | null
  previous_rental_completed: boolean | null
}

type RentalRow = PreviousRentalState & {
  id: number
  warehouse_id: number
  status: string
  customer_name: string
  destination: string
  device: {
    name: string
    device_model: { name: string }
  }
  ship_out_tracking_no: null
  scheduled_ship_time: null
  express_type_id: number
  is_relay_shipping: boolean
  relay_predecessor_rental_id: number | null
}

const rowKey: InjectionKey<Ref<RentalRow>> = Symbol('batch-shipping-row')

const TableRowProvider = defineComponent({
  props: {
    row: {
      type: Object,
      required: true,
    },
  },
  setup(props, { slots }) {
    provide(rowKey, computed(() => props.row as RentalRow))
    return () => slots.default?.()
  },
})

const ElTableStub = defineComponent({
  props: {
    data: {
      type: Array,
      default: () => [],
    },
  },
  setup(props, { slots }) {
    return () => h(
      'div',
      (props.data as RentalRow[]).map((row) => h(
        TableRowProvider,
        { key: row.id, row },
        { default: () => slots.default?.() },
      )),
    )
  },
})

const ElTableColumnStub = defineComponent({
  props: {
    label: {
      type: String,
      default: '',
    },
  },
  setup(props, { slots }) {
    const row = inject(rowKey)
    return () => h(
      'section',
      { 'data-column': props.label },
      row && slots.default ? slots.default({ row: row.value }) : [],
    )
  },
})

const baseRental: RentalRow = {
  id: 101,
  warehouse_id: 1,
  status: 'not_shipped',
  customer_name: '测试客户',
  destination: '上海市测试路 1 号',
  device: {
    name: 'X300U-01',
    device_model: { name: 'X300U' },
  },
  ship_out_tracking_no: null,
  scheduled_ship_time: null,
  express_type_id: 2,
  has_previous_rental: true,
  previous_rental_status: 'completed',
  previous_rental_completed: true,
  is_relay_shipping: false,
  relay_predecessor_rental_id: null,
}

const mountWithRental = async (
  previousState: PreviousRentalState,
  overrides: Partial<RentalRow> = {},
) => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(BatchShippingView, {
    global: {
      plugins: [pinia, ElementPlus],
      stubs: {
        ElTable: ElTableStub,
        ElTableColumn: ElTableColumnStub,
        teleport: true,
        transition: false,
      },
    },
  })

  wrapper.vm.$.setupState.rentals = [{
    ...baseRental,
    ...previousState,
    ...overrides,
  }]
  await nextTick()
  return wrapper
}


describe('BatchShippingView device status', () => {
  it('blocks scheduling, express changes and printing when all warehouses is selected', async () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const wrapper = await mountWithRental({
      has_previous_rental: true,
      previous_rental_status: 'completed',
      previous_rental_completed: true,
    }, {
      status: 'scheduled_for_shipping',
      ship_out_tracking_no: 'SF123' as never,
      scheduled_ship_time: '2026-08-26T10:00:00' as never,
    })
    const tenant = useTenantStore()
    tenant.setWarehousesForSession([
      { id: 1, name: 'A 仓', province: '广东省', city: '深圳市' },
      { id: 2, name: 'B 仓', province: '浙江省', city: '杭州市' },
    ])
    tenant.selectWarehouse('all')
    const setup = wrapper.vm.$.setupState as any
    setup.dateRange = [new Date('2026-08-25'), new Date('2026-08-26')]
    setup.selectedRentals = [{ id: 101 }]

    await setup.confirmSchedule()
    await setup.updateExpressType(101, 2)
    await setup.showWaybillPrintDialog()
    await setup.printSingle(101)
    setup.printAll()

    expect(axios.post).not.toHaveBeenCalled()
    expect(axios.patch).not.toHaveBeenCalled()
    expect(open).not.toHaveBeenCalled()
    open.mockRestore()
  })

  it('clears old rows and selection immediately when a new warehouse load starts', async () => {
    let rejectB!: (reason?: any) => void
    vi.mocked(axios.get).mockReturnValueOnce(
      new Promise((_resolve, reject) => { rejectB = reject }) as never,
    )
    const wrapper = await mountWithRental({
      has_previous_rental: true,
      previous_rental_status: 'completed',
      previous_rental_completed: true,
    })
    const tenant = useTenantStore()
    tenant.setWarehousesForSession([
      { id: 1, name: 'A 仓', province: '广东省', city: '深圳市' },
      { id: 2, name: 'B 仓', province: '浙江省', city: '杭州市' },
    ])
    const setup = wrapper.vm.$.setupState as any
    setup.selectedRentals = [baseRental]
    setup.dateRange = [new Date('2026-08-25'), new Date('2026-08-26')]
    tenant.selectWarehouse(2)
    await nextTick()

    expect(setup.rentals).toEqual([])
    expect(setup.selectedRentals).toEqual([])
    rejectB(new Error('B 仓加载失败'))
    await vi.waitFor(() => expect(setup.loading).toBe(false))
    expect(setup.rentals).toEqual([])
  })

  it('blocks schedule, express and print actions for stale rows from another warehouse', async () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const wrapper = await mountWithRental({
      has_previous_rental: true,
      previous_rental_status: 'completed',
      previous_rental_completed: true,
    }, {
      status: 'scheduled_for_shipping',
      ship_out_tracking_no: 'SF123' as never,
      scheduled_ship_time: '2026-08-26T10:00:00' as never,
    })
    const tenant = useTenantStore()
    tenant.setWarehousesForSession([
      { id: 1, name: 'A 仓', province: '广东省', city: '深圳市' },
      { id: 2, name: 'B 仓', province: '浙江省', city: '杭州市' },
    ])
    tenant.selectWarehouse(2)
    const setup = wrapper.vm.$.setupState as any
    setup.selectedRentals = [baseRental]
    setup.dateRange = [new Date('2026-08-25'), new Date('2026-08-26')]

    await setup.confirmSchedule()
    await setup.updateExpressType(101, 2)
    await setup.showWaybillPrintDialog()
    await setup.printSingle(101)
    setup.printAll()

    expect(axios.post).not.toHaveBeenCalled()
    expect(axios.patch).not.toHaveBeenCalled()
    expect(open).not.toHaveBeenCalled()
    open.mockRestore()
  })

  it('shows a returned previous rental as purple return-in-transit', async () => {
    const wrapper = await mountWithRental({
      has_previous_rental: true,
      previous_rental_status: 'returned',
      previous_rental_completed: true,
    })

    const deviceStatus = wrapper.get('[data-column="设备状态"]')
    const tag = deviceStatus.findComponent(ElTag)

    expect(tag.text()).toContain('寄回在途')
    expect(tag.props('color')).toBe('#7232dd')
    expect(deviceStatus.text()).not.toContain('设备在库')
  })

  it.each([
    {
      status: 'completed',
      completed: true,
      expectedText: '设备在库',
      expectedType: 'success',
    },
    {
      status: 'cancelled',
      completed: true,
      expectedText: '设备在库',
      expectedType: 'success',
    },
    {
      status: 'shipped',
      completed: false,
      expectedText: '上一单未结束',
      expectedType: 'danger',
    },
  ])('keeps the $status previous-rental display unchanged', async ({
    status,
    completed,
    expectedText,
    expectedType,
  }) => {
    const wrapper = await mountWithRental({
      has_previous_rental: true,
      previous_rental_status: status,
      previous_rental_completed: completed,
    })

    const tag = wrapper
      .get('[data-column="设备状态"]')
      .findComponent(ElTag)

    expect(tag.text()).toContain(expectedText)
    expect(tag.props('type')).toBe(expectedType)
  })

  it('keeps a dash when the device has no previous rental', async () => {
    const wrapper = await mountWithRental({
      has_previous_rental: false,
      previous_rental_status: null,
      previous_rental_completed: null,
    })

    const deviceStatus = wrapper.get('[data-column="设备状态"]')

    expect(deviceStatus.text().trim()).toBe('-')
    expect(deviceStatus.findComponent(ElTag).exists()).toBe(false)
  })

  it('marks relay shipping, disables selection, and adds a hover reason', async () => {
    const wrapper = await mountWithRental({
      has_previous_rental: true,
      previous_rental_status: 'completed',
      previous_rental_completed: true,
    }, {
      is_relay_shipping: true,
      relay_predecessor_rental_id: 100,
    })

    const customerColumn = wrapper.get('[data-column="客户"]')
    expect(customerColumn.get('[data-testid="relay-shipping-tag"]').text()).toBe('接力寄出')
    expect(customerColumn.findComponent(ElTooltip).props('content')).toContain('无需在批量发货中处理')

    const setup = wrapper.vm.$.setupState as {
      isSelectableRow: (row: RentalRow) => boolean
      handleCellMouseEnter: (row: RentalRow, column: unknown, cell: HTMLElement) => void
      handleCellMouseLeave: (row: RentalRow, column: unknown, cell: HTMLElement) => void
    }
    const relayRow = { ...baseRental, is_relay_shipping: true }
    expect(setup.isSelectableRow(relayRow)).toBe(false)

    const selectionCell = document.createElement('td')
    setup.handleCellMouseEnter(relayRow, { type: 'selection' }, selectionCell)
    expect(selectionCell.title).toContain('接力订单')
    setup.handleCellMouseLeave(relayRow, { type: 'selection' }, selectionCell)
    expect(selectionCell.hasAttribute('title')).toBe(false)
  })
})

// Use the real Element Plus table: a stub cannot verify merged customer cells.
describe('BatchShippingView grouped customers', () => {
  beforeAll(() => {
    // Browser observers are opaque to Vue; preserve that behavior in happy-dom.
    const Observer = globalThis.MutationObserver
    vi.stubGlobal('MutationObserver', class extends Observer {
      constructor(callback: MutationCallback) { super(callback); markRaw(this) }
    })
  })
  afterAll(() => vi.unstubAllGlobals())
  const mountTable = async (rows: any[]) => {
    const pinia = createPinia()
    setActivePinia(pinia)
    useTenantStore().setWarehousesForSession([
      { id: 1, name: 'A 仓', province: '广东省', city: '深圳市' },
    ])
    const wrapper = mount(BatchShippingView, {
      attachTo: document.body,
      global: { plugins: [pinia, ElementPlus], stubs: { teleport: true, transition: false } },
    })
    ;(wrapper.vm.$.setupState as any).rentals = rows
    await flushPromises()
    await nextTick()
    return wrapper
  }
  const row = (id: number, group?: string, overrides: any = {}) => ({
    ...baseRental, id, shipping_group_id: group,
    device: { name: `设备-${id}`, device_model: { name: 'X300 Ultra' } },
    ...overrides,
  })

  it('places scattered members together and merges only their customer cells', async () => {
    const wrapper = await mountTable([
      row(101, 'parcel-101'), row(201), row(102, 'parcel-101'), row(103, 'parcel-101'),
    ])
    try {
      const setup = wrapper.vm.$.setupState as any
      expect(setup.groupedRentals.map((r: any) => r.id)).toEqual([101, 102, 103, 201])
      expect(setup.rentals.map((r: any) => r.id)).toEqual([101, 201, 102, 103])
      const rows = wrapper.findAll('.el-table__body tbody tr')
      expect(rows).toHaveLength(4)
      expect(rows.map(r => r.text().match(/设备-\d+/)?.[0])).toEqual(['设备-101', '设备-102', '设备-103', '设备-201'])
      const merged = rows[0].get('td[rowspan="3"]')
      expect(merged.get('.customer-name').text()).toBe('测试客户')
      expect(merged.get('.multi-device-tag').text()).toBe('一单多台')
      expect(rows[1].find('.customer-name').exists()).toBe(false)
      expect(rows[2].find('.customer-name').exists()).toBe(false)
      expect(rows[3].find('.multi-device-tag').exists()).toBe(false)
      expect(wrapper.findAll('.el-table__body .el-checkbox')).toHaveLength(4)
      expect(wrapper.text()).not.toContain('发货分组')
      expect(wrapper.text()).not.toContain('parcel-')
      setup.handleSelectionChange([setup.groupedRentals[0], setup.groupedRentals[1]])
      expect(setup.selectedRentals.map((r: any) => r.id)).toEqual([101, 102])
    } finally { wrapper.unmount() }
  })

  it('does not merge different warehouses or unrelated orders with the same customer', async () => {
    const wrapper = await mountTable([
      row(101, 'parcel-101'), row(102, 'parcel-101', { warehouse_id: 2 }), row(103), row(104),
    ])
    try {
      expect(wrapper.findAll('.el-table__body .customer-name')).toHaveLength(4)
      expect(wrapper.findAll('.el-table__body .multi-device-tag')).toHaveLength(0)
    } finally { wrapper.unmount() }
  })

  it('keeps all customer names visible if a parcel contains different customers', async () => {
    const wrapper = await mountTable([
      row(101, 'parcel-101', { customer_name: '客户甲' }),
      row(102, 'parcel-101', { customer_name: '客户乙' }),
    ])
    try {
      const merged = wrapper.get('.el-table__body td[rowspan="2"]')
      expect(merged.findAll('.customer-name').map(name => name.text())).toEqual(['客户甲', '客户乙'])
    } finally { wrapper.unmount() }
  })
})

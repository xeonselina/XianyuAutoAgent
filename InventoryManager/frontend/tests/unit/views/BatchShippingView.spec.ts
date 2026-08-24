import axios from 'axios'
import ElementPlus, {
  ElMessage,
  ElSelect,
  ElTag,
  ElTooltip,
} from 'element-plus'
import { mount } from '@vue/test-utils'
import {
  computed,
  defineComponent,
  h,
  inject,
  nextTick,
  provide,
  type InjectionKey,
  type Ref,
} from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import BatchShippingView from '@/views/BatchShippingView.vue'


vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))


type PreviousRentalState = {
  has_previous_rental: boolean
  previous_rental_status: string | null
  previous_rental_completed: boolean | null
}

type RentalRow = PreviousRentalState & {
  id: number
  status: string
  customer_name: string
  destination: string
  device: {
    name: string
    device_model: { name: string }
  }
  ship_out_tracking_no: string | null
  scheduled_ship_time: string | null
  express_type_id: number
  persisted_express_type_id?: number
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
  const wrapper = mount(BatchShippingView, {
    global: {
      plugins: [ElementPlus],
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

afterEach(() => {
  vi.restoreAllMocks()
})


describe('BatchShippingView device status', () => {
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

describe('BatchShippingView express type', () => {
  it('renders the supported 1/2/263 products', async () => {
    const wrapper = await mountWithRental({
      has_previous_rental: false,
      previous_rental_status: null,
      previous_rental_completed: null,
    })

    const setup = wrapper.vm.$.setupState as {
      EXPRESS_TYPE_OPTIONS: Array<{ value: number; label: string }>
    }

    expect(setup.EXPRESS_TYPE_OPTIONS).toEqual([
      { value: 1, label: '特快' },
      { value: 2, label: '标快' },
      { value: 263, label: '半日达' },
    ])
  })

  it.each([
    { status: 'not_shipped', tracking: 'SF-LOCKED' },
    { status: 'scheduled_for_shipping', tracking: null },
    { status: 'shipped', tracking: null },
  ])('disables selection after waybill creation: $status', async ({
    status,
    tracking,
  }) => {
    const wrapper = await mountWithRental({
      has_previous_rental: false,
      previous_rental_status: null,
      previous_rental_completed: null,
    }, {
      status,
      ship_out_tracking_no: tracking,
    })

    const select = wrapper
      .get('[data-column="快递类型"]')
      .findComponent(ElSelect)
    expect(select.props('disabled')).toBe(true)
  })

  it('keeps selection enabled before waybill creation', async () => {
    const wrapper = await mountWithRental({
      has_previous_rental: false,
      previous_rental_status: null,
      previous_rental_completed: null,
    })

    const select = wrapper
      .get('[data-column="快递类型"]')
      .findComponent(ElSelect)
    expect(select.props('disabled')).toBe(false)
  })

  it('persists a successful selection', async () => {
    vi.spyOn(axios, 'patch').mockResolvedValue({
      data: { success: true },
    })
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    const wrapper = await mountWithRental({
      has_previous_rental: false,
      previous_rental_status: null,
      previous_rental_completed: null,
    }, {
      express_type_id: 263,
      persisted_express_type_id: 2,
    })
    const setup = wrapper.vm.$.setupState as {
      rentals: RentalRow[]
      updateExpressType: (rentalId: number, expressTypeId: number) => Promise<void>
    }

    await setup.updateExpressType(baseRental.id, 263)

    expect(axios.patch).toHaveBeenCalledWith(
      '/api/shipping-batch/express-type',
      { rental_id: baseRental.id, express_type_id: 263 },
    )
    expect(setup.rentals[0].express_type_id).toBe(263)
    expect(setup.rentals[0].persisted_express_type_id).toBe(263)
  })

  it('rolls back the displayed selection when persistence fails', async () => {
    vi.spyOn(axios, 'patch').mockRejectedValue(new Error('network failure'))
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const wrapper = await mountWithRental({
      has_previous_rental: false,
      previous_rental_status: null,
      previous_rental_completed: null,
    }, {
      express_type_id: 263,
      persisted_express_type_id: 2,
    })
    const setup = wrapper.vm.$.setupState as {
      rentals: RentalRow[]
      updateExpressType: (rentalId: number, expressTypeId: number) => Promise<void>
    }

    await setup.updateExpressType(baseRental.id, 263)

    expect(setup.rentals[0].express_type_id).toBe(2)
    expect(setup.rentals[0].persisted_express_type_id).toBe(2)
    expect(ElMessage.error).toHaveBeenCalledWith('更新快递类型失败')
  })
})

import ElementPlus, { ElTag } from 'element-plus'
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
import { describe, expect, it, vi } from 'vitest'

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
  ship_out_tracking_no: null
  scheduled_ship_time: null
  express_type_id: number
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
}

const mountWithRental = async (previousState: PreviousRentalState) => {
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

  wrapper.vm.$.setupState.rentals = [{ ...baseRental, ...previousState }]
  await nextTick()
  return wrapper
}


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
})

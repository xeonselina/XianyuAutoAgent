import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'

import WarehouseMovementDialog from '@/components/WarehouseMovementDialog.vue'
import InspectionView from '@/views/InspectionView.vue'
import { useTenantStore } from '@/stores/tenant'
import { useInspectionStore } from '@/stores/inspection'


const { axiosPost } = vi.hoisted(() => ({ axiosPost: vi.fn() }))

vi.mock('axios', () => ({
  default: { post: axiosPost },
  isAxiosError: (error: unknown) => Boolean(
    error && typeof error === 'object' && 'response' in error,
  ),
}))

const publicWarehouses = [
  { id: 1, name: '深圳仓库', province: '广东', city: '深圳' },
  { id: 2, name: '杭州仓库', province: '浙江', city: '杭州' },
]

const preview = (token = 'preview-token') => ({
  source_device_id: 9,
  old_warehouse_id: 1,
  target_warehouse_id: 2,
  auto_fixable: [{ rental_id: 101, replacements: [] }],
  shortages: [{ rental_id: 102, code: 'NO_AVAILABLE_REPLACEMENT', missing: [] }],
  manual: [{ rental_id: 103, reason: 'TRACKING_EXISTS' }],
  blocked: [{ rental_id: 104, reason: 'SOURCE_ROLE_MISMATCH' }],
  token,
})

const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

const mountDialog = async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const tenant = useTenantStore()
  tenant.setWarehousesForSession(publicWarehouses)
  const wrapper = mount(WarehouseMovementDialog, {
    props: {
      modelValue: true,
      deviceId: 9,
      currentWarehouseId: 1,
    },
    global: {
      plugins: [pinia],
      stubs: {
        ElDialog: {
          props: ['modelValue'],
          template: '<section><slot /><slot name="footer" /></section>',
        },
        ElSelect: {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template: '<select data-testid="movement-target" />',
        },
        ElOption: true,
        ElAlert: { template: '<div><slot /></div>' },
        ElButton: {
          emits: ['click'],
          template: '<button @click="$emit(\'click\')"><slot /></button>',
        },
      },
    },
  })
  await wrapper.setProps({ modelValue: false })
  await wrapper.setProps({ modelValue: true })
  await wrapper.vm.$nextTick()
  return wrapper
}

describe('warehouse movement confirmation', () => {
  beforeEach(() => {
    axiosPost.mockReset()
  })

  it('previews automatic, shortage, manual and blocked impacts before executing the signed token', async () => {
    axiosPost
      .mockResolvedValueOnce({ data: { success: true, data: preview() } })
      .mockResolvedValueOnce({ data: { success: true, data: preview() } })
    const wrapper = await mountDialog()

    await wrapper.find('[data-testid="preview-movement"]').trigger('click')
    await flushPromises()

    expect(axiosPost).toHaveBeenNthCalledWith(
      1,
      '/api/devices/9/movement-preview',
      { target_warehouse_id: 2 },
    )
    expect(wrapper.text()).toContain('可自动修正')
    expect(wrapper.text()).toContain('缺货')
    expect(wrapper.text()).toContain('人工处理')
    expect(wrapper.text()).toContain('已阻止')

    await wrapper.find('[data-testid="confirm-movement"]').trigger('click')
    await flushPromises()

    expect(axiosPost).toHaveBeenNthCalledWith(
      2,
      '/api/devices/9/move',
      { token: 'preview-token' },
    )
  })

  it('re-previews one stale normal movement and executes the replacement token once', async () => {
    const stale = Object.assign(new Error('stale'), {
      response: { status: 409, data: { message: '请重新预览' } },
    })
    axiosPost
      .mockResolvedValueOnce({ data: { success: true, data: preview('first') } })
      .mockRejectedValueOnce(stale)
      .mockResolvedValueOnce({ data: { success: true, data: preview('fresh') } })
      .mockResolvedValueOnce({ data: { success: true, data: preview('fresh') } })
    const wrapper = await mountDialog()

    await wrapper.find('[data-testid="preview-movement"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="confirm-movement"]').trigger('click')
    await flushPromises()

    expect(axiosPost.mock.calls).toEqual([
      ['/api/devices/9/movement-preview', { target_warehouse_id: 2 }],
      ['/api/devices/9/move', { token: 'first' }],
      ['/api/devices/9/movement-preview', { target_warehouse_id: 2 }],
      ['/api/devices/9/move', { token: 'fresh' }],
    ])
  })

  it('submits the chosen receipt warehouse and executes returned aggregate impacts directly', async () => {
    axiosPost
      .mockResolvedValueOnce({
        data: {
          success: true,
          data: {
            id: 77,
            rental_id: 101,
            device_id: 9,
            status: 'normal',
            check_items: [],
            created_at: '2026-08-25T00:00:00Z',
            updated_at: '2026-08-25T00:00:00Z',
            warehouse_impacts: {
              ...preview('receipt-token'),
              primary_device_id: 9,
              moved_device_ids: [9, 10],
              target_warehouse_id: 2,
            },
          },
        },
      })
      .mockResolvedValueOnce({ data: { success: true, data: {} } })
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useInspectionStore()
    store.currentRental = {
      id: 101,
      device_id: 9,
      warehouse_id: 1,
      accessories: [{ id: 10, name: '三脚架', type: 'tripod', is_bundled: false }],
    } as never
    store.checkItems = [{ item_name: '外观', is_checked: true, item_order: 1 }]
    store.receivingWarehouseId = 2
    store.receivedDeviceIds = [10]

    expect(await store.submitInspection()).toBe(true)
    expect(axiosPost).toHaveBeenNthCalledWith(
      1,
      '/api/inspections',
      expect.objectContaining({
        receiving_warehouse_id: 2,
        received_device_ids: [10],
      }),
      expect.any(Object),
    )

    expect(await store.repairWarehouseImpacts()).toBe(true)
    expect(axiosPost).toHaveBeenNthCalledWith(
      2,
      '/api/devices/9/move',
      { token: 'receipt-token' },
    )
    expect(axiosPost.mock.calls.some(
      ([url]) => String(url).includes('movement-preview'),
    )).toBe(false)
  })

  it('locks an inspection immediately after one successful submission until reset', async () => {
    const response = deferred<any>()
    axiosPost.mockReturnValue(response.promise)
    setActivePinia(createPinia())
    const store = useInspectionStore()
    store.currentRental = { id: 101, device_id: 9, warehouse_id: 1 } as never
    store.checkItems = [{ item_name: '外观', is_checked: true, item_order: 1 }]
    store.receivingWarehouseId = 1

    const first = store.submitInspection()
    const duplicateWhileLoading = store.submitInspection()
    expect(axiosPost).toHaveBeenCalledOnce()

    response.resolve({
      data: {
        success: true,
        data: {
          id: 77,
          rental_id: 101,
          device_id: 9,
          status: 'normal',
          check_items: [],
          created_at: '2026-08-25T00:00:00Z',
          updated_at: '2026-08-25T00:00:00Z',
        },
      },
    })
    expect(await first).toBe(true)
    expect(await duplicateWhileLoading).toBe(false)
    expect(store.submitted).toBe(true)
    expect(await store.submitInspection()).toBe(false)
    expect(axiosPost).toHaveBeenCalledOnce()

    store.reset()
    expect(store.submitted).toBe(false)
  })

  it('hides the receipt checklist after success even when there are no warehouse impacts', async () => {
    axiosPost.mockResolvedValue({
      data: {
        success: true,
        data: {
          id: 77,
          rental_id: 101,
          device_id: 9,
          status: 'normal',
          check_items: [],
          created_at: '2026-08-25T00:00:00Z',
          updated_at: '2026-08-25T00:00:00Z',
        },
      },
    })
    const pinia = createPinia()
    setActivePinia(pinia)
    useTenantStore().setWarehousesForSession(publicWarehouses)
    const store = useInspectionStore()
    store.currentRental = { id: 101, device_id: 9, warehouse_id: 1 } as never
    store.checkItems = [{ item_name: '外观', is_checked: true, item_order: 1 }]
    store.receivingWarehouseId = 1
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/inspection', component: InspectionView }],
    })
    await router.push('/inspection')
    await router.isReady()
    const wrapper = mount(InspectionView, {
      global: {
        plugins: [pinia, router],
        stubs: {
          DeviceSearchInput: true,
          RentalInfoCard: true,
          ChecklistForm: defineComponent({
            emits: ['submit'],
            template: '<button data-testid="submit-inspection" @click="$emit(\'submit\')">提交</button>',
          }),
          ElCard: { template: '<section><slot name="header"/><slot/></section>' },
          ElForm: { template: '<form><slot/></form>' },
          ElFormItem: { template: '<div><slot/></div>' },
          ElSelect: true,
          ElOption: true,
          ElCheckboxGroup: true,
          ElCheckbox: true,
          ElResult: { template: '<section data-testid="success-result"><slot name="extra"/></section>' },
          ElButton: { emits: ['click'], template: '<button @click="$emit(\'click\')"><slot/></button>' },
        },
      },
    })

    await wrapper.get('[data-testid="submit-inspection"]').trigger('click')
    await flushPromises()

    expect(store.submitted).toBe(true)
    expect(wrapper.find('[data-testid="submit-inspection"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="success-result"]').text()).toContain('继续验货')
    expect(axiosPost).toHaveBeenCalledOnce()
  })
})

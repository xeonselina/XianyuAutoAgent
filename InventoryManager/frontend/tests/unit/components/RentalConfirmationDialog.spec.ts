import { flushPromises, mount } from '@vue/test-utils'
import { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import RentalConfirmationDialog from '@/components/RentalConfirmationDialog.vue'
import type { Rental } from '@/stores/gantt'
import { buildRentalConfirmation } from '@/utils/rentalConfirmation'

const savedRental: Rental = {
  id: 42,
  device_id: 8,
  device: {
    id: 8,
    name: '3618',
    serial_number: 'SN-PRIVATE',
    model: 'x300u',
    device_model: {
      id: 3,
      name: 'x300u',
      display_name: 'VIVO X300 Ultra',
      is_active: true,
      created_at: '2026-01-01',
      updated_at: '2026-01-01',
      accessories: [],
    },
  },
  start_date: '2026-07-14',
  end_date: '2026-07-20',
  ship_out_time: '2026-07-12T19:30:00',
  ship_in_time: '2026-07-22T12:00:00',
  customer_name: '闲鱼用户ABC',
  customer_phone: '13800138000',
  destination: '张三，广东省广州市天河区一号路',
  status: 'not_shipped',
  includes_handle: true,
  includes_lens_mount: true,
  photo_transfer: true,
  lens_combo: 'lens_dual',
  accessories: [
    { name: '手机支架 12', model: '手机支架', type: 'phone_holder', is_bundled: false },
    { name: '备用手机支架', model: 'phone holder', type: 'phone_holder', is_bundled: false },
    { name: '三脚架 03', model: '三脚架', type: 'tripod', is_bundled: false },
  ],
}

const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
const execCommandDescriptor = Object.getOwnPropertyDescriptor(document, 'execCommand')

const restoreProperty = (
  target: object,
  key: PropertyKey,
  descriptor: PropertyDescriptor | undefined,
) => {
  if (descriptor) Object.defineProperty(target, key, descriptor)
  else Reflect.deleteProperty(target, key)
}

const mountDialog = (rental: Rental) => mount(RentalConfirmationDialog, {
  props: { modelValue: true, rental },
  global: {
    stubs: {
      ElDialog: {
        props: ['modelValue'],
        template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>',
      },
      ElButton: {
        emits: ['click'],
        template: '<button @click="$emit(\'click\')"><slot /></button>',
      },
    },
  },
})

describe('RentalConfirmationDialog', () => {
  beforeEach(() => {
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  afterEach(() => {
    restoreProperty(navigator, 'clipboard', clipboardDescriptor)
    restoreProperty(document, 'execCommand', execCommandDescriptor)
    vi.restoreAllMocks()
  })

  it('展示五行并通过 Clipboard API 复制全部文本', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    const wrapper = mountDialog(savedRental)
    const text = wrapper.get('[data-test="confirmation-text"]').text()

    expect(text.split('\n')).toHaveLength(5)
    await wrapper.get('[data-test="copy-confirmation"]').trigger('click')
    await flushPromises()

    expect(writeText).toHaveBeenCalledWith(buildRentalConfirmation(savedRental).text)
    expect(ElMessage.success).toHaveBeenCalledWith('确认信息已复制')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('Clipboard API 失败时使用 textarea 兼容复制', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    })
    const execCommand = vi.fn().mockReturnValue(true)
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: execCommand,
    })
    const wrapper = mountDialog(savedRental)

    await wrapper.get('[data-test="copy-confirmation"]').trigger('click')
    await flushPromises()

    expect(execCommand).toHaveBeenCalledWith('copy')
    expect(ElMessage.success).toHaveBeenCalledWith('确认信息已复制')
  })

  it('两种复制方式都失败时提示手动复制', async () => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined })
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: vi.fn().mockReturnValue(false),
    })
    const wrapper = mountDialog(savedRental)

    await wrapper.get('[data-test="copy-confirmation"]').trigger('click')
    await flushPromises()

    expect(ElMessage.error).toHaveBeenCalledWith('自动复制失败，请手动选择文本复制')
    expect(wrapper.get('[data-test="confirmation-text"]').text()).toContain('收货地址：')
  })
})

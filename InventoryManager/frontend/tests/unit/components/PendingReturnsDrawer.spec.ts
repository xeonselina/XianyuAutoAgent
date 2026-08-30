import { flushPromises, mount } from '@vue/test-utils'
import { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import PendingReturnsDrawer from '@/components/PendingReturnsDrawer.vue'
import type { PendingReturn } from '@/types/pendingReturn'

const pendingReturn: PendingReturn = {
  id: 12,
  warehouse_id: 1,
  device_model: 'iPhone 15 Pro Max',
  device_name: '手机-12',
  customer_name: '张三',
  start_date: '2026-07-20',
  end_date: '2026-07-28',
  due_date: '2026-07-29',
  overdue_days: 0,
  destination: '浙江省杭州市西湖区测试路 88 号',
  customer_phone: '13900139000',
  status: 'shipped',
}

const withOverdueDays = (id: number, overdueDays: number): PendingReturn => ({
  ...pendingReturn,
  id,
  overdue_days: overdueDays,
  due_date: `2026-07-${String(29 - overdueDays).padStart(2, '0')}`,
})

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

const mountDrawer = (
  rentals: PendingReturn[],
  updatingIds = new Set<number>(),
) => mount(PendingReturnsDrawer, {
  props: {
    modelValue: true,
    rentals,
    loading: false,
    updatingIds,
  },
  global: {
    stubs: {
      ElDrawer: {
        props: ['modelValue', 'title', 'size'],
        template: '<section :data-size="size"><h2>{{ title }}</h2><slot /></section>',
      },
      ElButton: {
        props: ['loading', 'disabled'],
        emits: ['click'],
        template: `
          <button
            :disabled="disabled || loading"
            @click="$emit('click')"
          ><slot /></button>
        `,
      },
      ElEmpty: {
        props: ['description'],
        template: '<div class="empty">{{ description }}</div>',
      },
    },
    directives: {
      loading: () => undefined,
    },
  },
})

describe('PendingReturnsDrawer', () => {
  beforeEach(() => {
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  afterEach(() => {
    restoreProperty(navigator, 'clipboard', clipboardDescriptor)
    restoreProperty(document, 'execCommand', execCommandDescriptor)
    vi.restoreAllMocks()
  })

  it('groups every overdue boundary in the fixed display order', () => {
    const wrapper = mountDrawer([
      withOverdueDays(18, 8),
      withOverdueDays(17, 7),
      withOverdueDays(14, 4),
      withOverdueDays(13, 3),
      withOverdueDays(11, 1),
      withOverdueDays(10, 0),
    ])

    expect(wrapper.findAll('[data-testid="pending-return-group"]')).toHaveLength(4)
    expect(wrapper.findAll('.group-title').map((item) => item.text())).toEqual([
      '今日（1）',
      '逾期 1–3 天（2）',
      '逾期 4–7 天（2）',
      '逾期超过 7 天（1）',
    ])
  })

  it('shows the exact due date and all existing rental fields', () => {
    const wrapper = mountDrawer([pendingReturn])

    expect(wrapper.text()).toContain('iPhone 15 Pro Max')
    expect(wrapper.text()).toContain('机器编号：手机-12')
    expect(wrapper.text()).toContain('2026-07-20 至 2026-07-28')
    expect(wrapper.text()).toContain('应归还：2026-07-29')
    expect(wrapper.text()).toContain('浙江省杭州市西湖区测试路 88 号')
    expect(wrapper.text()).toContain('张三')
    expect(wrapper.text()).toContain('13900139000')
    expect(wrapper.text()).toContain('标记为已寄回')
  })

  it('hides empty groups', () => {
    const wrapper = mountDrawer([withOverdueDays(14, 4)])

    expect(wrapper.findAll('.group-title').map((item) => item.text())).toEqual([
      '逾期 4–7 天（1）',
    ])
  })

  it('emits the selected row action', async () => {
    const wrapper = mountDrawer([pendingReturn])

    await wrapper.get('[data-test="mark-returned"]').trigger('click')

    expect(wrapper.emitted('mark-returned')).toEqual([[pendingReturn.id]])
  })

  it('disables only the row currently being updated', () => {
    const second = { ...pendingReturn, id: 13, device_model: 'iPhone 16 Pro' }
    const wrapper = mountDrawer(
      [pendingReturn, second],
      new Set([pendingReturn.id]),
    )
    const buttons = wrapper.findAll('[data-test="mark-returned"]')

    expect(buttons[0].attributes('disabled')).toBeDefined()
    expect(buttons[1].attributes('disabled')).toBeUndefined()
  })

  it('copies only the selected phone number with an icon action', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    const wrapper = mountDrawer([pendingReturn])
    const copyButton = wrapper.get('[data-test="copy-phone"]')

    expect(copyButton.attributes('aria-label')).toBe(
      '复制电话号码 13900139000',
    )
    expect(copyButton.text()).toBe('')
    await copyButton.trigger('click')
    await flushPromises()

    expect(writeText).toHaveBeenCalledWith('13900139000')
    expect(ElMessage.success).toHaveBeenCalledWith('电话号码已复制')
  })

  it('falls back to compatible copying on HTTP', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: undefined,
    })
    const execCommand = vi.fn().mockReturnValue(true)
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: execCommand,
    })
    const wrapper = mountDrawer([pendingReturn])

    await wrapper.get('[data-test="copy-phone"]').trigger('click')
    await flushPromises()

    expect(execCommand).toHaveBeenCalledWith('copy')
    expect(ElMessage.success).toHaveBeenCalledWith('电话号码已复制')
  })

  it('shows a clear message when both copy methods fail', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: undefined,
    })
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: vi.fn().mockReturnValue(false),
    })
    const wrapper = mountDrawer([pendingReturn])

    await wrapper.get('[data-test="copy-phone"]').trigger('click')
    await flushPromises()

    expect(ElMessage.error).toHaveBeenCalledWith(
      '复制失败，请手动复制电话号码',
    )
  })

  it('does not show a copy icon when the phone number is missing', () => {
    const wrapper = mountDrawer([{ ...pendingReturn, customer_phone: null }])

    expect(wrapper.find('[data-test="copy-phone"]').exists()).toBe(false)
  })

  it('shows a clear empty state', () => {
    const wrapper = mountDrawer([])

    expect(wrapper.text()).toContain('暂无待归还订单')
  })

  it('passes a splitter-compatible size to Element Plus', () => {
    const wrapper = mountDrawer([pendingReturn])

    expect(wrapper.get('section').attributes('data-size')).toMatch(
      /^\d+(?:\.\d+)?(?:px|%)$/,
    )
  })
})

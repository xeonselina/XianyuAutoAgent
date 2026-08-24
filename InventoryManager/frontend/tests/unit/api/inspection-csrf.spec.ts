import axios, {
  type AxiosAdapter,
  type InternalAxiosRequestConfig,
} from 'axios'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setTenantCsrfHeader } from '@/api/auth'
import {
  createInspection,
  updateInspection,
} from '@/api/inspection'
import InspectionRecordCard from '@/components/inspection/InspectionRecordCard.vue'
import type { InspectionRecord } from '@/types/inspection'


const elementMocks = vi.hoisted(() => ({
  confirm: vi.fn().mockResolvedValue(undefined),
  error: vi.fn(),
  success: vi.fn(),
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    error: elementMocks.error,
    success: elementMocks.success,
  },
  ElMessageBox: { confirm: elementMocks.confirm },
}))


describe('inspection mutation CSRF', () => {
  const requests: InternalAxiosRequestConfig[] = []
  let originalAdapter: typeof axios.defaults.adapter

  beforeEach(() => {
    requests.length = 0
    vi.clearAllMocks()
    originalAdapter = axios.defaults.adapter
    axios.defaults.adapter = (async (config) => {
      requests.push(config)
      return {
        config,
        data: { success: true, data: { id: 1 } },
        headers: {},
        status: 200,
        statusText: 'OK',
      }
    }) as AxiosAdapter
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: async () => ({ success: true, data: { id: 1 } }),
    }))
  })

  afterEach(() => {
    axios.defaults.adapter = originalAdapter
    setTenantCsrfHeader(null)
    vi.unstubAllGlobals()
  })

  it('dispatches create with the initial token and update with the rotated token', async () => {
    setTenantCsrfHeader('csrf-initial')
    await createInspection({
      rental_id: 7,
      device_id: 11,
      check_items: [{ name: '机身外观', is_checked: true, order: 1 }],
    })

    setTenantCsrfHeader('csrf-rotated')
    await updateInspection(19, {
      check_items: [{ id: 23, is_checked: false }],
    })

    expect(requests).toHaveLength(2)
    expect(requests[0]).toMatchObject({ method: 'post', url: '/api/inspections' })
    expect(requests[0].headers?.get('X-CSRF-Token')).toBe('csrf-initial')
    expect(requests[1]).toMatchObject({ method: 'put', url: '/api/inspections/19' })
    expect(requests[1].headers?.get('X-CSRF-Token')).toBe('csrf-rotated')
  })

  it('dispatches deposit completion with the current rotated token', async () => {
    setTenantCsrfHeader('csrf-before-rotation')
    setTenantCsrfHeader('csrf-after-rotation')
    const wrapper = mount(InspectionRecordCard, {
      props: {
        record: {
          id: 31,
          rental_id: 17,
          device_id: 8,
          status: 'normal',
          created_at: '2026-08-24T08:00:00Z',
          updated_at: '2026-08-24T08:00:00Z',
          check_items: [],
          device: { name: '2001' },
          rental: { status: 'returned' },
        } as InspectionRecord,
      },
      global: {
        stubs: {
          Close: true,
          ElButton: {
            emits: ['click'],
            template: '<button @click="$emit(\'click\')"><slot /></button>',
          },
          ElCard: { template: '<section><slot /></section>' },
          ElIcon: { template: '<i><slot /></i>' },
          ElTag: { template: '<span><slot /></span>' },
          WarningFilled: true,
        },
      },
    })

    await wrapper.get('button').trigger('click')

    await vi.waitFor(() => expect(requests).toHaveLength(1))
    expect(requests[0]).toMatchObject({
      method: 'put',
      url: '/api/rentals/17/status',
    })
    expect(requests[0].headers?.get('X-CSRF-Token')).toBe(
      'csrf-after-rotation',
    )
  })
})

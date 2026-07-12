import { describe, expect, it } from 'vitest'
import type { Rental } from '@/stores/gantt'
import { buildRentalConfirmation } from '@/utils/rentalConfirmation'

const rental = (overrides: Partial<Rental> = {}): Rental => ({
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
  ...overrides,
})

describe('buildRentalConfirmation', () => {
  it('生成严格五行并补充地址中的缺失电话', () => {
    const result = buildRentalConfirmation(rental())
    expect(result.lines).toEqual([
      '收货地址：张三，广东省广州市天河区一号路，13800138000',
      '寄出时间：2026-07-12',
      '预计收货：2026-07-14',
      '客户归还：2026-07-20',
      '寄出型号：VIVO X300 Ultra + 双镜头 + 镜头支架 + 手柄 + 手机支架 + 三脚架',
    ])
    expect(result.text).toBe(result.lines.join('\n'))
    expect(result.text).not.toContain('2026-07-22')
    expect(result.text).not.toContain('闲鱼用户ABC')
    expect(result.text).not.toContain('SN-PRIVATE')
  })

  it('地址已经包含格式化电话时不重复追加', () => {
    const result = buildRentalConfirmation(rental({
      destination: '张三 138-0013-8000 广东省广州市',
    }))
    expect(result.lines[0]).toBe('收货地址：张三 138-0013-8000 广东省广州市')
  })

  it('无附件和缺失值使用固定兜底文案', () => {
    const result = buildRentalConfirmation(rental({
      destination: '',
      customer_phone: '',
      ship_out_time: undefined,
      start_date: '',
      end_date: '',
      device: undefined,
      lens_combo: undefined,
      includes_handle: false,
      includes_lens_mount: false,
      accessories: [],
    }))
    expect(result.lines).toEqual([
      '收货地址：未填写',
      '寄出时间：未填写',
      '预计收货：未填写',
      '客户归还：未填写',
      '寄出型号：未识别型号 + 未填写镜头组合 + 无附件',
    ])
  })

  it('其他附件使用名称并去重', () => {
    const result = buildRentalConfirmation(rental({
      includes_handle: false,
      includes_lens_mount: false,
      accessories: [
        { name: '补光灯', type: 'other', is_bundled: false },
        { name: '补光灯', type: 'other', is_bundled: false },
      ],
    }))
    expect(result.lines[4]).toBe('寄出型号：VIVO X300 Ultra + 双镜头 + 补光灯')
  })
})

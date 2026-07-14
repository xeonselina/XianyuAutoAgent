import { beforeEach, describe, expect, it, vi } from 'vitest'
import axios from 'axios'

import {
  formatLogisticsWarning,
  getLogisticsMismatch
} from '@/utils/logisticsWarning'

vi.mock('axios', () => ({
  default: { get: vi.fn() }
}))

const mockedGet = vi.mocked(axios.get)

describe('物流时效警告判断', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('地址为空时跳过预估', async () => {
    expect(await getLogisticsMismatch('  ', 1)).toBeNull()
    expect(mockedGet).not.toHaveBeenCalled()
  })

  it('所选天数少于预估时返回不匹配信息', async () => {
    mockedGet.mockResolvedValue({
      data: {
        success: true,
        data: {
          logistics_days: 2,
          matched_location: '浙江',
          message: '从深圳寄往 浙江 预计 2 天送达（顺丰标快）'
        }
      }
    } as any)

    const mismatch = await getLogisticsMismatch('浙江省杭州市', 1)

    expect(mismatch).toMatchObject({
      selectedDays: 1,
      estimatedDays: 2,
      matchedLocation: '浙江'
    })
    expect(formatLogisticsWarning(mismatch!)).toContain('预计需要 2 天')
    expect(formatLogisticsWarning(mismatch!)).toContain('仅预留 1 天')
  })

  it('所选天数等于或大于预估时不警告', async () => {
    mockedGet.mockResolvedValue({
      data: {
        success: true,
        data: { logistics_days: 2 }
      }
    } as any)

    expect(await getLogisticsMismatch('江苏南京', 2)).toBeNull()
    expect(await getLogisticsMismatch('江苏南京', 3)).toBeNull()
  })

  it('接口失败时返回可读错误', async () => {
    mockedGet.mockRejectedValue({
      response: { data: { message: '预估服务不可用' } }
    })

    await expect(getLogisticsMismatch('北京朝阳', 1)).rejects.toThrow(
      '预估服务不可用'
    )
  })
})


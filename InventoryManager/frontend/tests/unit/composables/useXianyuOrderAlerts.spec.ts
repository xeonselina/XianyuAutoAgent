import { beforeEach, describe, expect, it, vi } from 'vitest'
import axios from 'axios'

import { useXianyuOrderAlerts } from '@/composables/useXianyuOrderAlerts'
import type { XianyuOrderAlertSnapshot } from '@/types/xianyuOrderAlert'


vi.mock('axios', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

const makeSnapshot = (
  orderNo?: string,
): XianyuOrderAlertSnapshot => ({
  alerts: orderNo
    ? [{
        order_no: orderNo,
        pay_amount: 8000,
        buyer_nick: '测试买家',
      }]
    : [],
  count: orderNo ? 1 : 0,
  refreshing: false,
  sync: {
    last_attempt_at: '2026-07-24T02:00:00Z',
    last_success_at: '2026-07-24T02:00:00Z',
    last_error: null,
  },
})

const response = (snapshot: XianyuOrderAlertSnapshot) => ({
  data: {
    success: true,
    data: snapshot,
  },
})

const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('useXianyuOrderAlerts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does not let an older GET restore an alert after ignore succeeds', async () => {
    const oldGet = deferred<any>()
    vi.mocked(axios.get).mockReturnValueOnce(oldGet.promise)
    vi.mocked(axios.post).mockResolvedValueOnce(response(makeSnapshot()))
    const alerts = useXianyuOrderAlerts()

    const pendingGet = alerts.load()
    await alerts.ignore('XY-1', '非租赁商品')
    oldGet.resolve(response(makeSnapshot('XY-1')))
    await pendingGet

    expect(alerts.snapshot.value.count).toBe(0)
  })

  it('skips polling reads while a mutation is in flight', async () => {
    const pendingPost = deferred<any>()
    vi.mocked(axios.post).mockReturnValueOnce(pendingPost.promise)
    const alerts = useXianyuOrderAlerts()

    const mutation = alerts.ignore('XY-1', '非租赁商品')
    await alerts.load()

    expect(axios.get).not.toHaveBeenCalled()
    pendingPost.resolve(response(makeSnapshot()))
    await mutation
  })
})

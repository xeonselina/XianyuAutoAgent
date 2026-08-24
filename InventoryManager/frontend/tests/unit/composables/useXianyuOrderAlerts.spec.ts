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

  it('serializes refresh behind an in-flight ignore', async () => {
    const pendingIgnore = deferred<any>()
    vi.mocked(axios.post)
      .mockReturnValueOnce(pendingIgnore.promise)
      .mockResolvedValueOnce(response(makeSnapshot()))
    const alerts = useXianyuOrderAlerts()

    const ignoreRequest = alerts.ignore('XY-1', '非租赁商品')
    const refreshRequest = alerts.refresh()
    await Promise.resolve()

    expect(axios.post).toHaveBeenCalledTimes(1)
    pendingIgnore.resolve(response(makeSnapshot()))
    await ignoreRequest
    await refreshRequest

    expect(axios.post).toHaveBeenCalledTimes(2)
    expect(alerts.snapshot.value.count).toBe(0)
  })

  it('treats refresh as a durable 202 job instead of a provider response', async () => {
    vi.mocked(axios.post).mockResolvedValueOnce({
      data: {
        success: true,
        data: {
          job_id: 'job-1',
          snapshot_revision: 9,
          job_status: 'pending',
          reused: false,
        },
      },
    })
    const alerts = useXianyuOrderAlerts()

    await alerts.refresh()

    expect(alerts.snapshot.value.refreshing).toBe(true)
    expect(alerts.snapshot.value.snapshot_revision).toBe(9)
    expect(alerts.snapshot.value.sync.current_job_uuid).toBe('job-1')
    expect(alerts.snapshot.value.sync.sync_status).toBe('syncing')
    expect(axios.get).not.toHaveBeenCalled()
  })

  it('polls only the local summary every three minutes while visible', async () => {
    vi.useFakeTimers()
    vi.mocked(axios.get).mockResolvedValue(response(makeSnapshot()))
    const visibility = vi.spyOn(document, 'visibilityState', 'get')
    visibility.mockReturnValue('hidden')
    const alerts = useXianyuOrderAlerts()
    alerts.startPolling()

    await vi.advanceTimersByTimeAsync(180_000)
    expect(axios.get).not.toHaveBeenCalled()

    visibility.mockReturnValue('visible')
    document.dispatchEvent(new Event('visibilitychange'))
    await Promise.resolve()
    expect(axios.get).toHaveBeenCalledTimes(1)

    alerts.stopPolling()
    visibility.mockRestore()
    vi.useRealTimers()
  })
})

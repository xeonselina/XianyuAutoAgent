import { onUnmounted, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

import type { XianyuOrderAlertSnapshot } from '@/types/xianyuOrderAlert'


const emptySnapshot = (): XianyuOrderAlertSnapshot => ({
  alerts: [],
  count: 0,
  refreshing: false,
  sync: {
    last_attempt_at: null,
    last_success_at: null,
    last_error: null,
  },
})


export function useXianyuOrderAlerts() {
  const snapshot = ref<XianyuOrderAlertSnapshot>(emptySnapshot())
  const loading = ref(false)
  let pollingTimer: ReturnType<typeof setInterval> | undefined
  let latestReadId = 0
  let mutationVersion = 0
  let mutationCount = 0
  let mutationQueue: Promise<void> = Promise.resolve()

  const applyResponse = (response: any) => {
    if (response?.data?.success && response.data.data) {
      snapshot.value = response.data.data
    }
  }

  const load = async (force = false) => {
    if (mutationCount > 0) {
      if (!force) return
      await mutationQueue
    }

    const readId = ++latestReadId
    const startedMutationVersion = mutationVersion
    try {
      const response = await axios.get('/api/xianyu-order-alerts')
      if (
        readId === latestReadId
        && startedMutationVersion === mutationVersion
        && mutationCount === 0
      ) {
        applyResponse(response)
      }
    } catch (error) {
      console.error('读取闲鱼漏录订单告警失败:', error)
    }
  }

  const enqueueMutation = async <T>(
    operation: () => Promise<T>,
  ): Promise<T> => {
    mutationCount += 1
    mutationVersion += 1
    loading.value = true

    const task = mutationQueue.then(operation)
    mutationQueue = task.then(
      () => undefined,
      () => undefined,
    )

    try {
      return await task
    } finally {
      mutationCount -= 1
      loading.value = mutationCount > 0
    }
  }

  const refresh = async () => {
    try {
      await enqueueMutation(async () => {
        applyResponse(
          await axios.post('/api/xianyu-order-alerts/refresh'),
        )
      })
    } catch (error: any) {
      console.error('刷新闲鱼漏录订单告警失败:', error)
      ElMessage.error(
        error.response?.data?.message || '漏录订单检查失败',
      )
    }
  }

  const ignore = async (orderNo: string, reason: string) => {
    try {
      await enqueueMutation(async () => {
        applyResponse(
          await axios.post(
            `/api/xianyu-order-alerts/${encodeURIComponent(orderNo)}/ignore`,
            { reason },
          ),
        )
      })
      ElMessage.success('订单已永久忽略')
    } catch (error: any) {
      ElMessage.error(
        error.response?.data?.message || '忽略订单失败',
      )
    }
  }

  const startPolling = (intervalMs = 60_000) => {
    if (pollingTimer) return
    pollingTimer = setInterval(() => {
      void load()
    }, intervalMs)
  }

  const stopPolling = () => {
    if (!pollingTimer) return
    clearInterval(pollingTimer)
    pollingTimer = undefined
  }

  onUnmounted(stopPolling)

  return {
    snapshot,
    loading,
    load,
    refresh,
    ignore,
    startPolling,
    stopPolling,
  }
}

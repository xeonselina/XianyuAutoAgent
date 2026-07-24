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
  let latestRequestId = 0
  let mutationCount = 0
  let refreshCount = 0

  const applyResponse = (response: any, requestId: number) => {
    if (
      requestId === latestRequestId
      && response?.data?.success
      && response.data.data
    ) {
      snapshot.value = response.data.data
    }
  }

  const load = async (force = false) => {
    if (!force && mutationCount > 0) return
    const requestId = ++latestRequestId
    try {
      applyResponse(
        await axios.get('/api/xianyu-order-alerts'),
        requestId,
      )
    } catch (error) {
      console.error('读取闲鱼漏录订单告警失败:', error)
    }
  }

  const refresh = async () => {
    mutationCount += 1
    refreshCount += 1
    loading.value = true
    const requestId = ++latestRequestId
    try {
      applyResponse(
        await axios.post('/api/xianyu-order-alerts/refresh'),
        requestId,
      )
    } catch (error: any) {
      console.error('刷新闲鱼漏录订单告警失败:', error)
      ElMessage.error(
        error.response?.data?.message || '漏录订单检查失败',
      )
    } finally {
      mutationCount -= 1
      refreshCount -= 1
      loading.value = refreshCount > 0
    }
  }

  const ignore = async (orderNo: string, reason: string) => {
    mutationCount += 1
    const requestId = ++latestRequestId
    try {
      applyResponse(
        await axios.post(
          `/api/xianyu-order-alerts/${encodeURIComponent(orderNo)}/ignore`,
          { reason },
        ),
        requestId,
      )
      ElMessage.success('订单已永久忽略')
    } catch (error: any) {
      ElMessage.error(
        error.response?.data?.message || '忽略订单失败',
      )
    } finally {
      mutationCount -= 1
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

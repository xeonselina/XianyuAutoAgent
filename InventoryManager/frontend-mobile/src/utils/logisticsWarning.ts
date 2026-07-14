import axios from 'axios'

export interface LogisticsMismatch {
  selectedDays: number
  estimatedDays: number
  matchedLocation: string | null
  estimateMessage: string
}

export async function getLogisticsMismatch(
  destination: string,
  selectedDays: number | null | undefined
): Promise<LogisticsMismatch | null> {
  const normalizedDestination = destination?.trim()
  if (!normalizedDestination || selectedDays == null) return null

  const normalizedSelectedDays = Number(selectedDays)
  if (!Number.isFinite(normalizedSelectedDays) || normalizedSelectedDays < 0) {
    return null
  }

  try {
    const response = await axios.get('/api/rentals/estimate-logistics', {
      params: { destination: normalizedDestination }
    })
    if (!response.data?.success || !response.data?.data) {
      throw new Error(response.data?.message || '顺丰时效预估失败')
    }

    const estimate = response.data.data
    const estimatedDays = Number(estimate.logistics_days)
    if (!Number.isFinite(estimatedDays) || normalizedSelectedDays >= estimatedDays) {
      return null
    }

    return {
      selectedDays: normalizedSelectedDays,
      estimatedDays,
      matchedLocation: estimate.matched_location || null,
      estimateMessage: estimate.message || ''
    }
  } catch (error: any) {
    throw new Error(
      error.response?.data?.message || error.message || '顺丰时效预估失败'
    )
  }
}

export function formatLogisticsWarning(mismatch: LogisticsMismatch): string {
  const destinationHint = mismatch.matchedLocation
    ? `寄往${mismatch.matchedLocation}`
    : '当前收货地址'
  return `${destinationHint}的顺丰标快预计需要 ${mismatch.estimatedDays} 天，当前仅预留 ${mismatch.selectedDays} 天，可能无法按时送达。`
}


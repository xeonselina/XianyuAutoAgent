/**
 * Eval Replay API Wrapper
 */

const API_BASE = '/eval'

export const evalAPI = {
  /**
   * List all eval runs with summary stats
   */
  async listRuns(offset = 0, limit = 50) {
    const params = new URLSearchParams({ offset, limit })
    const res = await fetch(`${API_BASE}/runs?${params}`)
    if (!res.ok) throw new Error(`API error: ${res.status}`)
    return res.json()
  },

  /**
   * Get eval run detail (all items)
   */
  async getRunDetail(runId, { statusFilter, chatIdFilter, limit, offset } = {}) {
    const params = new URLSearchParams()
    if (statusFilter) params.set('status_filter', statusFilter)
    if (chatIdFilter) params.set('chat_id_filter', chatIdFilter)
    if (limit) params.set('limit', limit)
    if (offset) params.set('offset', offset)
    const res = await fetch(`${API_BASE}/runs/${encodeURIComponent(runId)}?${params}`)
    if (!res.ok) throw new Error(`API error: ${res.status}`)
    return res.json()
  },

  /**
   * Get distinct chat_ids within a run
   */
  async getRunChats(runId) {
    const res = await fetch(`${API_BASE}/runs/${encodeURIComponent(runId)}/chats`)
    if (!res.ok) throw new Error(`API error: ${res.status}`)
    return res.json()
  }
}

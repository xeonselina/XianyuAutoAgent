/**
 * Conversations API client
 */

const BASE_URL = '/conversations'

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    },
    ...options
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }

  return response.json()
}

export default {
  /**
   * Get recent conversations list
   */
  getRecent(limit = 20, offset = 0) {
    return request(`${BASE_URL}/recent?limit=${limit}&offset=${offset}`)
  },

  /**
   * Get conversation detail by chat_id
   */
  getDetail(chatId, limit = 200, offset = 0) {
    return request(`${BASE_URL}/${encodeURIComponent(chatId)}?limit=${limit}&offset=${offset}`)
  },

  /**
   * Search messages
   */
  search(params = {}) {
    const searchParams = new URLSearchParams()
    if (params.keyword) searchParams.set('keyword', params.keyword)
    if (params.start_time) searchParams.set('start_time', params.start_time)
    if (params.end_time) searchParams.set('end_time', params.end_time)
    if (params.message_type) searchParams.set('message_type', params.message_type)
    if (params.has_agent_response !== undefined && params.has_agent_response !== null) {
      searchParams.set('has_agent_response', params.has_agent_response)
    }
    if (params.debug_only) searchParams.set('debug_only', 'true')
    if (params.limit) searchParams.set('limit', params.limit)
    if (params.offset) searchParams.set('offset', params.offset)

    return request(`${BASE_URL}/search?${searchParams.toString()}`)
  },

  /**
   * Get conversation statistics
   */
  getStats() {
    return request(`${BASE_URL}/stats`)
  },

  /**
   * Get turns for a specific session
   */
  getSessionTurns(sessionId, limit = 100, offset = 0) {
    return request(`${BASE_URL}/turns/${encodeURIComponent(sessionId)}?limit=${limit}&offset=${offset}`)
  },

  /**
   * Get recent turns across all sessions
   */
  getRecentTurns(limit = 50, offset = 0) {
    return request(`${BASE_URL}/turns/recent?limit=${limit}&offset=${offset}`)
  }
}

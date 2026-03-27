/**
 * System Prompt Management API Wrapper
 */

const API_BASE = '/prompts'

export const promptAPI = {
  /**
   * List all system prompts
   */
  async list(promptKey = null, offset = 0, limit = 50) {
    const params = new URLSearchParams({ offset, limit })
    if (promptKey) params.set('prompt_key', promptKey)
    const res = await fetch(`${API_BASE}/?${params}`)
    if (!res.ok) throw new Error(`API error: ${res.status}`)
    return res.json()
  },

  /**
   * Get single prompt by ID
   */
  async get(id) {
    const res = await fetch(`${API_BASE}/${id}`)
    if (!res.ok) throw new Error(`API error: ${res.status}`)
    return res.json()
  },

  /**
   * Get active prompt for a key
   */
  async getActive(promptKey) {
    const res = await fetch(`${API_BASE}/active/${promptKey}`)
    if (!res.ok) {
      if (res.status === 404) return null
      throw new Error(`API error: ${res.status}`)
    }
    return res.json()
  },

  /**
   * Create new prompt
   */
  async create(data) {
    const res = await fetch(`${API_BASE}/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    })
    if (!res.ok) throw new Error(`API error: ${res.status}`)
    return res.json()
  },

  /**
   * Update prompt
   */
  async update(id, data) {
    const res = await fetch(`${API_BASE}/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    })
    if (!res.ok) throw new Error(`API error: ${res.status}`)
    return res.json()
  },

  /**
   * Delete prompt
   */
  async delete(id) {
    const res = await fetch(`${API_BASE}/${id}`, {
      method: 'DELETE'
    })
    if (!res.ok) throw new Error(`API error: ${res.status}`)
    return res.json()
  },

  /**
   * Activate a prompt version
   */
  async activate(id) {
    const res = await fetch(`${API_BASE}/${id}/activate`, {
      method: 'POST'
    })
    if (!res.ok) throw new Error(`API error: ${res.status}`)
    return res.json()
  },

  /**
   * Initialize default prompts
   */
  async initDefaults() {
    const res = await fetch(`${API_BASE}/init-defaults`, {
      method: 'POST'
    })
    if (!res.ok) throw new Error(`API error: ${res.status}`)
    return res.json()
  }
}

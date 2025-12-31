/**
 * Knowledge Management API Wrapper
 */

const API_BASE = '/knowledge'

export const knowledgeAPI = {
  /**
   * List knowledge entries with pagination
   */
  async list(offset = 0, limit = 20, activeOnly = true) {
    const params = new URLSearchParams({ offset, limit, active_only: activeOnly })
    const res = await fetch(`${API_BASE}/?${params}`)
    if (!res.ok) throw new Error(`API error: ${res.status}`)
    return res.json()
  },

  /**
   * Get single knowledge entry by ID
   */
  async get(id) {
    const res = await fetch(`${API_BASE}/${id}`)
    if (!res.ok) throw new Error(`API error: ${res.status}`)
    return res.json()
  },

  /**
   * Create new knowledge entry
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
   * Update existing knowledge entry
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
   * Delete knowledge entry
   */
  async delete(id) {
    const res = await fetch(`${API_BASE}/${id}`, {
      method: 'DELETE'
    })
    if (!res.ok) throw new Error(`API error: ${res.status}`)
    return res.json()
  },

  /**
   * Search knowledge base
   */
  async search(query, topK = 5, category = null) {
    const body = { query, top_k: topK }
    if (category) body.category = category

    const res = await fetch(`${API_BASE}/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
    if (!res.ok) throw new Error(`API error: ${res.status}`)
    return res.json()
  },

  /**
   * Bulk import knowledge entries
   */
  async bulkImport(entries, overwrite = false) {
    const res = await fetch(`${API_BASE}/bulk`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entries, overwrite_existing: overwrite })
    })
    if (!res.ok) throw new Error(`API error: ${res.status}`)
    return res.json()
  },

  /**
   * Initialize default knowledge entries
   */
  async initDefaults() {
    const res = await fetch(`${API_BASE}/init-defaults`, {
      method: 'POST'
    })
    if (!res.ok) throw new Error(`API error: ${res.status}`)
    return res.json()
  },

  /**
   * Export all knowledge entries as JSON
   */
  async export(activeOnly = true) {
    const params = new URLSearchParams({ active_only: activeOnly })
    const res = await fetch(`${API_BASE}/export?${params}`)
    if (!res.ok) throw new Error(`API error: ${res.status}`)

    const blob = await res.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `knowledge_export_${new Date().toISOString()}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
  }
}

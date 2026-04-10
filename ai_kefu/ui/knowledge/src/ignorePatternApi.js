/**
 * Ignore Pattern API client.
 * Manages message patterns that should be skipped by AI agent.
 */

const API_BASE = '/ignore-patterns'

export async function listIgnorePatterns(activeOnly = false, offset = 0, limit = 100) {
  const params = new URLSearchParams({ offset, limit })
  if (activeOnly) params.set('active_only', 'true')
  const res = await fetch(`${API_BASE}?${params}`)
  if (!res.ok) throw new Error(`Failed to list patterns: ${res.statusText}`)
  return res.json()
}

export async function getIgnorePattern(id) {
  const res = await fetch(`${API_BASE}/${id}`)
  if (!res.ok) throw new Error(`Failed to get pattern: ${res.statusText}`)
  return res.json()
}

export async function createIgnorePattern(data) {
  const res = await fetch(API_BASE + '/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Failed to create pattern: ${res.statusText}`)
  }
  return res.json()
}

export async function updateIgnorePattern(id, data) {
  const res = await fetch(`${API_BASE}/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Failed to update pattern: ${res.statusText}`)
  }
  return res.json()
}

export async function deleteIgnorePattern(id) {
  const res = await fetch(`${API_BASE}/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Failed to delete pattern: ${res.statusText}`)
  return res.json()
}

export async function toggleIgnorePattern(id) {
  const res = await fetch(`${API_BASE}/${id}/toggle`, { method: 'POST' })
  if (!res.ok) throw new Error(`Failed to toggle pattern: ${res.statusText}`)
  return res.json()
}

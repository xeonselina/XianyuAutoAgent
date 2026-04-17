/**
 * API helpers for the 历史对话 (Conversation History) feature.
 * All requests go through the Vite proxy to http://localhost:8000/conversations/...
 */

const BASE = '/conversations'

/**
 * Fetch paginated list of recent conversations.
 * @param {number} limit
 * @param {number} offset
 */
export async function fetchRecentConversations(limit = 30, offset = 0) {
  const res = await fetch(`${BASE}/recent?limit=${limit}&offset=${offset}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

/**
 * Fetch full message history for a chat_id.
 * @param {string} chatId
 */
export async function fetchConversation(chatId) {
  const res = await fetch(`${BASE}/${encodeURIComponent(chatId)}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

/**
 * Fetch existing review for a chat_id.
 * @param {string} chatId
 */
export async function fetchReviews(chatId) {
  const res = await fetch(`${BASE}/${encodeURIComponent(chatId)}/reviews`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

/**
 * Save (upsert) a review for a chat_id.
 * @param {string} chatId
 * @param {1|-1}  rating    1 = 👍, -1 = 👎
 * @param {string} comment  Free-text comment
 * @param {string|null} sessionId
 */
export async function saveReview(chatId, rating, comment = '', sessionId = null) {
  const res = await fetch(`${BASE}/${encodeURIComponent(chatId)}/reviews`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rating, comment, session_id: sessionId }),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`HTTP ${res.status}: ${text}`)
  }
  return res.json()
}

/**
 * Get AI comparison analysis for a conversation.
 * Compares human replies with AI replies using similarity metrics.
 * @param {string} chatId
 */
export async function compareReplies(chatId) {
  const res = await fetch(`${BASE}/${encodeURIComponent(chatId)}/compare`, {
    method: 'POST'
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

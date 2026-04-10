<template>
  <div class="conv-history">

    <!-- ─── Session List ──────────────────────────────── -->
    <div v-if="!selectedChatId" class="card">
      <div class="card-header">
        <h2>历史对话</h2>
        <p class="subtitle">选择一条对话，查看详情并对 AI 回复质量进行评价</p>
      </div>

      <div v-if="loadingList" class="loading"><div class="spinner"></div></div>
      <div v-else-if="sessions.length === 0" class="empty-state">暂无对话记录</div>

      <div v-else>
        <div class="session-list">
          <div
            v-for="s in sessions"
            :key="s.chat_id"
            class="session-card"
            @click="openSession(s.chat_id)"
          >
            <div class="session-card-top">
              <span class="session-chat-id">💬 {{ s.chat_id }}</span>
              <span v-if="reviewMap[s.chat_id]" class="review-badge"
                :class="reviewMap[s.chat_id].rating === 1 ? 'badge-up' : 'badge-down'">
                {{ reviewMap[s.chat_id].rating === 1 ? '👍 已评价' : '👎 已评价' }}
              </span>
            </div>
            <div class="session-card-meta">
              <span v-if="s.user_id">买家: {{ s.user_id }}</span>
              <span v-if="s.item_id">商品: {{ s.item_id }}</span>
              <span>消息数: {{ s.message_count }}</span>
              <span>AI 回复: {{ s.ai_replies }}</span>
            </div>
            <div class="session-card-snippet">
              <span class="snippet-label">最新:</span>
              {{ s.latest_message || '—' }}
            </div>
            <div class="session-card-time">{{ formatTime(s.last_message_at) }}</div>
          </div>
        </div>

        <!-- Pagination -->
        <div class="pagination">
          <button class="btn btn-secondary" :disabled="offset === 0" @click="prevPage">上一页</button>
          <span class="page-info">第 {{ Math.floor(offset / pageSize) + 1 }} 页 / 共 {{ totalSessions }} 条</span>
          <button class="btn btn-secondary" :disabled="offset + pageSize >= totalSessions" @click="nextPage">下一页</button>
        </div>
      </div>
    </div>

    <!-- ─── Session Detail ────────────────────────────── -->
    <div v-else class="detail-view">
      <!-- Header -->
      <div class="detail-header card">
        <button class="btn btn-secondary" @click="closeSession">← 返回列表</button>
        <h2>对话详情：{{ selectedChatId }}</h2>
      </div>

      <div v-if="loadingDetail" class="loading"><div class="spinner"></div></div>

      <template v-else>
        <!-- Chat bubbles -->
        <div class="chat-window card">
          <div
            v-for="msg in messages"
            :key="msg.id"
            class="msg"
            :class="msgClass(msg)"
          >
            <!-- Left side: user -->
            <template v-if="msg.message_type === 'user'">
              <div class="msg-avatar">👤</div>
              <div class="msg-body">
                <div class="msg-meta">买家 · {{ formatTime(msg.created_at) }}</div>
                <div class="msg-bubble">{{ msg.message_content }}</div>
              </div>
            </template>

            <!-- Right side: seller (human manual reply) -->
            <template v-else-if="msg.message_type === 'seller' && !msg.agent_response">
              <div class="msg-body">
                <div class="msg-meta">人工回复 · {{ formatTime(msg.created_at) }}</div>
                <div class="msg-bubble">{{ msg.message_content }}</div>
              </div>
              <div class="msg-avatar">🧑‍💼</div>
            </template>

            <!-- Right side: AI reply -->
            <template v-else-if="msg.message_type === 'seller' && msg.agent_response">
              <div class="msg-body">
                <div class="msg-meta">AI 回复 · {{ formatTime(msg.created_at) }}</div>
                <div class="msg-bubble">{{ msg.message_content }}</div>
                <!-- AI Context Panel -->
                <div class="ai-context-toggle" @click="toggleContext(msg.id)">
                  {{ contextVisible[msg.id] ? '▲ 收起 AI 上下文' : '▼ 查看 AI 上下文' }}
                </div>
                <div v-if="contextVisible[msg.id]" class="ai-context-panel">
                  <template v-if="getContextForMsg(msg, index).length > 0">
                    <!-- Tool Calls -->
                    <div v-if="hasToolCalls(getContextForMsg(msg, index))" class="ctx-section">
                      <div class="ctx-section-title">🔧 工具调用</div>
                      <div v-for="(turn, ti) in getContextForMsg(msg, index)" :key="ti">
                        <div v-if="turn.tool_calls && turn.tool_calls.length" class="tool-call-list">
                          <div v-for="(tc, tci) in turn.tool_calls" :key="tci" class="tool-call-item">
                            <span class="tool-name">{{ tc.function ? tc.function.name : tc.name }}</span>
                            <span class="tool-args">{{ formatToolArgs(tc) }}</span>
                            <div v-if="getToolResult(turn, tci)" class="tool-result">
                              ↳ {{ formatToolResult(getToolResult(turn, tci)) }}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                    <!-- LLM Context Messages -->
                    <div v-if="getContextForMsg(msg, index)[0] && getContextForMsg(msg, index)[0].llm_input" class="ctx-section">
                      <div class="ctx-section-title">
                        📋 LLM 上下文
                        <span class="ctx-count">({{ getLlmInputMessages(getContextForMsg(msg, index)[0]).length }} 条)</span>
                        <button class="btn-link ctx-expand-btn" @click.stop="toggleLlmExpand(msg.id)">
                          {{ llmExpanded[msg.id] ? '收起' : '展开' }}
                        </button>
                      </div>
                      <div v-if="llmExpanded[msg.id]" class="llm-messages">
                        <div
                          v-for="(lmsg, li) in getLlmInputMessages(getContextForMsg(msg, index)[0])"
                          :key="li"
                          class="llm-msg-row"
                          :class="'llm-role-' + lmsg.role"
                        >
                          <span class="llm-role-badge">{{ lmsg.role }}</span>
                          <span class="llm-content">{{ formatLlmContent(lmsg) }}</span>
                        </div>
                      </div>
                    </div>
                  </template>
                  <div v-else class="ctx-empty">暂无上下文记录（该会话无 agent_turns 数据）</div>
                </div>
              </div>
              <div class="msg-avatar">🤖</div>
            </template>

            <!-- System messages -->
            <template v-else>
              <div class="msg-system">{{ msg.message_content }}</div>
            </template>
          </div>

          <div v-if="messages.length === 0" class="empty-state">暂无消息记录</div>
        </div>

        <!-- Legend -->
        <div class="legend card">
          <span class="legend-item legend-user">👤 买家消息</span>
          <span class="legend-item legend-human">🧑‍💼 人工回复</span>
          <span class="legend-item legend-ai">🤖 AI 回复</span>
        </div>

        <!-- Review Form -->
        <div class="review-form card">
          <h3>对话评价</h3>
          <p class="review-hint">对本对话中 AI 回复质量进行整体评价</p>

          <!-- Persisted review display -->
          <div v-if="savedReview" class="saved-review-display">
            <span class="saved-rating" :class="savedReview.rating === 1 ? 'rating-up' : 'rating-down'">
              {{ savedReview.rating === 1 ? '👍 好评' : '👎 差评' }}
            </span>
            <span v-if="savedReview.comment" class="saved-comment">{{ savedReview.comment }}</span>
            <span class="saved-time">已于 {{ formatTime(savedReview.updated_at) }} 保存</span>
            <button class="btn-link" @click="savedReview = null">修改评价</button>
          </div>

          <template v-if="!savedReview">
            <div v-if="reviewSaved" class="alert alert-success">评价已保存 ✓</div>
            <div v-if="reviewError" class="alert alert-error">{{ reviewError }}</div>

            <div class="rating-row">
              <button
                class="btn-rating"
                :class="{ active: reviewRating === 1 }"
                @click="reviewRating = 1"
                title="AI 回复质量好"
              >👍 好评</button>
              <button
                class="btn-rating btn-rating-down"
                :class="{ active: reviewRating === -1 }"
                @click="reviewRating = -1"
                title="AI 回复质量差"
              >👎 差评</button>
            </div>

            <div class="form-group">
              <label class="form-label">补充说明（可选）</label>
              <textarea
                v-model="reviewComment"
                class="form-textarea"
                rows="3"
                placeholder="描述 AI 哪里回复得好或不好…"
              ></textarea>
            </div>

            <button
              class="btn btn-primary"
              :disabled="reviewRating === 0 || savingReview"
              @click="submitReview"
            >
              {{ savingReview ? '保存中…' : '提交评价' }}
            </button>
          </template>
        </div>
      </template>
    </div>
  </div>
</template>

<script>
import {
  fetchRecentConversations,
  fetchConversation,
  fetchReviews,
  saveReview,
} from '../conversationHistoryApi.js'

export default {
  name: 'ConversationHistory',

  props: {
    chatId: { type: String, default: null },
  },

  data() {
    return {
      // Session list
      sessions: [],
      totalSessions: 0,
      loadingList: false,
      pageSize: 30,
      offset: 0,
      // Review badge map: { [chat_id]: { rating, comment } }
      reviewMap: {},

      // Session detail
      selectedChatId: this.chatId || null,
      messages: [],
      loadingDetail: false,

      // Review form
      reviewRating: 0,   // 0 = not selected
      reviewComment: '',
      savingReview: false,
      reviewSaved: false,
      reviewError: '',
      savedReview: null,  // persisted review loaded from DB / just submitted

      // AI context panel
      turnsBySession: {},   // { session_id: [turn, ...] }
      contextVisible: {},   // { msg_id: bool }
      llmExpanded: {},      // { msg_id: bool }
    }
  },

  watch: {
    chatId(val) {
      if (val) {
        this.selectedChatId = val
        this.loadDetail(val)
      } else {
        this.selectedChatId = null
      }
    },
  },

  mounted() {
    if (this.selectedChatId) {
      this.loadDetail(this.selectedChatId)
    } else {
      this.loadList()
    }
  },

  methods: {
    async loadList() {
      this.loadingList = true
      try {
        const data = await fetchRecentConversations(this.pageSize, this.offset)
        this.sessions = data.items || []
        this.totalSessions = data.total || 0
        // Fetch reviews for all visible sessions
        await this.loadBadges()
      } catch (e) {
        console.error('Failed to load sessions', e)
      } finally {
        this.loadingList = false
      }
    },

    async loadBadges() {
      const chatIds = this.sessions.map(s => s.chat_id)
      await Promise.all(chatIds.map(async (id) => {
        try {
          const data = await fetchReviews(id)
          if (data.reviews && data.reviews.length > 0) {
            this.$set ? this.$set(this.reviewMap, id, data.reviews[0])
              : (this.reviewMap[id] = data.reviews[0])
          }
        } catch (_) { /* ignore per-item errors */ }
      }))
    },

    async openSession(chatId) {
      this.selectedChatId = chatId
      this.$router.push({ name: 'history-detail', params: { chatId } }).catch(() => {})
      await this.loadDetail(chatId)
    },

    async loadDetail(chatId) {
      this.loadingDetail = true
      this.messages = []
      this.reviewRating = 0
      this.reviewComment = ''
      this.reviewSaved = false
      this.reviewError = ''
      this.savedReview = null
      this.turnsBySession = {}
      this.contextVisible = {}
      this.llmExpanded = {}
      try {
        const [convData, reviewData] = await Promise.all([
          fetchConversation(chatId),
          fetchReviews(chatId),
        ])
        this.messages = convData.messages || []
        this.turnsBySession = convData.turns_by_session || {}
        if (reviewData.reviews && reviewData.reviews.length > 0) {
          const r = reviewData.reviews[0]
          this.reviewRating = r.rating || 0
          this.reviewComment = r.comment || ''
          this.savedReview = r
        }
      } catch (e) {
        console.error('Failed to load conversation', e)
      } finally {
        this.loadingDetail = false
      }
    },

    closeSession() {
      this.selectedChatId = null
      this.$router.push({ name: 'history-list' }).catch(() => {})
      this.loadList()
    },

    prevPage() {
      this.offset = Math.max(0, this.offset - this.pageSize)
      this.loadList()
    },

    nextPage() {
      this.offset += this.pageSize
      this.loadList()
    },

    async submitReview() {
      if (!this.reviewRating) return
      this.savingReview = true
      this.reviewSaved = false
      this.reviewError = ''
      try {
        // Find primary session_id from messages (first AI reply)
        const aiMsg = this.messages.find(m => m.session_id)
        const sessionId = aiMsg ? aiMsg.session_id : null
        await saveReview(this.selectedChatId, this.reviewRating, this.reviewComment, sessionId)
        this.savedReview = {
          rating: this.reviewRating,
          comment: this.reviewComment,
          updated_at: new Date().toISOString(),
        }
        this.reviewSaved = true
        setTimeout(() => { this.reviewSaved = false }, 3000)
      } catch (e) {
        this.reviewError = `保存失败: ${e.message}`
      } finally {
        this.savingReview = false
      }
    },

    msgClass(msg) {
      if (msg.message_type === 'user') return 'msg-user'
      if (msg.message_type === 'seller' && msg.agent_response) return 'msg-ai'
      if (msg.message_type === 'seller') return 'msg-human'
      return 'msg-system-wrap'
    },

    // ── AI Context helpers ──────────────────────────────────────────

    toggleContext(msgId) {
      this.contextVisible = {
        ...this.contextVisible,
        [msgId]: !this.contextVisible[msgId],
      }
    },

    toggleLlmExpand(msgId) {
      this.llmExpanded = {
        ...this.llmExpanded,
        [msgId]: !this.llmExpanded[msgId],
      }
    },

    // Return the turns array that belong to this AI message.
    // Strategy: match by session_id on the message, falling back to the
    // turns whose user_query equals the preceding user message.
    getContextForMsg(msg, index) {
      if (!msg.session_id) return []
      const turns = this.turnsBySession[msg.session_id]
      if (!turns || !turns.length) return []

      // Find the user message just before this seller/AI message
      let prevUserMsg = null
      for (let i = index - 1; i >= 0; i--) {
        if (this.messages[i].message_type === 'user') {
          prevUserMsg = this.messages[i]
          break
        }
      }

      // If we have an interaction_id on the turns, group by the turn whose
      // user_query matches the preceding user message
      if (prevUserMsg) {
        const matchingTurns = turns.filter(
          t => t.user_query && t.user_query.trim() === prevUserMsg.message_content.trim()
        )
        if (matchingTurns.length) return matchingTurns
      }

      // Fallback: return the turn whose response_text matches the AI reply
      const byResponse = turns.filter(
        t => t.response_text && msg.message_content &&
             t.response_text.trim() === msg.message_content.trim()
      )
      if (byResponse.length) return byResponse

      // Last resort: return all turns for this session
      return turns
    },

    hasToolCalls(ctx) {
      return ctx.some(t => t.tool_calls && t.tool_calls.length > 0)
    },

    getLlmInputMessages(turn) {
      if (!turn || !turn.llm_input) return []
      try {
        const inp = typeof turn.llm_input === 'string'
          ? JSON.parse(turn.llm_input)
          : turn.llm_input
        return Array.isArray(inp) ? inp : (inp.messages || [])
      } catch { return [] }
    },

    getToolResult(turn, toolCallIndex) {
      if (!turn.tool_results) return null
      const results = typeof turn.tool_results === 'string'
        ? (() => { try { return JSON.parse(turn.tool_results) } catch { return [] } })()
        : turn.tool_results
      return Array.isArray(results) ? (results[toolCallIndex] || null) : null
    },

    formatToolArgs(tc) {
      try {
        const args = tc.function ? tc.function.arguments : tc.arguments
        if (!args) return ''
        const parsed = typeof args === 'string' ? JSON.parse(args) : args
        return JSON.stringify(parsed, null, 0).slice(0, 200)
      } catch {
        return String(tc.function ? tc.function.arguments : tc.arguments || '').slice(0, 200)
      }
    },

    formatToolResult(result) {
      if (!result) return ''
      const content = result.content || result.output || result
      const str = typeof content === 'string' ? content : JSON.stringify(content)
      return str.length > 300 ? str.slice(0, 300) + '…' : str
    },

    formatLlmContent(msg) {
      if (!msg) return ''
      const c = msg.content
      if (typeof c === 'string') return c.length > 400 ? c.slice(0, 400) + '…' : c
      if (Array.isArray(c)) {
        return c.map(p => p.text || JSON.stringify(p)).join(' ').slice(0, 400)
      }
      return JSON.stringify(c).slice(0, 400)
    },

    formatTime(ts) {
      if (!ts) return '—'
      const d = new Date(ts)
      return d.toLocaleString('zh-CN', {
        month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit',
      })
    },
  },
}
</script>

<style scoped>
/* ── Layout ── */
.conv-history { width: 100%; }

.card-header { margin-bottom: 1.5rem; }
.card-header h2 { margin-bottom: 0.25rem; }
.subtitle { color: #888; font-size: 0.875rem; }

/* ── Session list ── */
.session-list { display: flex; flex-direction: column; gap: 0.75rem; }

.session-card {
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 1rem 1.25rem;
  cursor: pointer;
  transition: box-shadow 0.2s, border-color 0.2s;
  background: #fafafa;
}
.session-card:hover {
  border-color: #1890ff;
  box-shadow: 0 2px 8px rgba(24,144,255,0.15);
  background: #fff;
}

.session-card-top {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.4rem;
}
.session-chat-id { font-weight: 600; font-size: 0.95rem; color: #333; }
.review-badge {
  font-size: 0.75rem;
  padding: 2px 8px;
  border-radius: 12px;
  font-weight: 500;
}
.badge-up { background: #f6ffed; color: #52c41a; border: 1px solid #b7eb8f; }
.badge-down { background: #fff2f0; color: #ff4d4f; border: 1px solid #ffccc7; }

.session-card-meta {
  display: flex;
  gap: 1rem;
  font-size: 0.8rem;
  color: #888;
  margin-bottom: 0.35rem;
}
.session-card-snippet {
  font-size: 0.85rem;
  color: #555;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 600px;
}
.snippet-label { color: #aaa; margin-right: 0.25rem; }
.session-card-time { font-size: 0.75rem; color: #bbb; margin-top: 0.3rem; text-align: right; }

/* ── Pagination ── */
.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  margin-top: 1.5rem;
}
.page-info { color: #888; font-size: 0.875rem; }

/* ── Detail header ── */
.detail-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1rem;
}
.detail-header h2 { font-size: 1rem; color: #555; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ── Chat window ── */
.chat-window {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1.5rem;
  margin-bottom: 1rem;
  max-height: 65vh;
  overflow-y: auto;
}

/* Base message row */
.msg {
  display: flex;
  align-items: flex-end;
  gap: 0.5rem;
  max-width: 85%;
}

/* User message — left aligned */
.msg-user { align-self: flex-start; flex-direction: row; }
.msg-user .msg-bubble {
  background: #e6f7ff;
  color: #003a8c;
  border-radius: 12px 12px 12px 2px;
}

/* Human seller reply — right aligned */
.msg-human { align-self: flex-end; flex-direction: row-reverse; }
.msg-human .msg-bubble {
  background: #f6ffed;
  color: #135200;
  border-radius: 12px 12px 2px 12px;
}

/* AI reply — right aligned */
.msg-ai { align-self: flex-end; flex-direction: row-reverse; }
.msg-ai .msg-bubble {
  background: #f9f0ff;
  color: #391085;
  border-radius: 12px 12px 2px 12px;
}

.msg-avatar {
  font-size: 1.5rem;
  flex-shrink: 0;
  width: 2rem;
  text-align: center;
}

.msg-body { display: flex; flex-direction: column; gap: 0.2rem; }

.msg-meta { font-size: 0.72rem; color: #aaa; }
.msg-human .msg-meta,
.msg-ai .msg-meta { text-align: right; }

.msg-bubble {
  padding: 0.6rem 0.9rem;
  font-size: 0.9rem;
  line-height: 1.5;
  word-break: break-word;
  white-space: pre-wrap;
}

/* System message */
.msg-system-wrap { align-self: center; }
.msg-system {
  font-size: 0.78rem;
  color: #aaa;
  background: #f5f5f5;
  border-radius: 12px;
  padding: 0.3rem 0.8rem;
}

/* ── Legend ── */
.legend {
  display: flex;
  gap: 1.5rem;
  padding: 0.75rem 1.25rem;
  margin-bottom: 1rem;
  background: #fafafa;
}
.legend-item { font-size: 0.82rem; color: #666; }
.legend-user::before  { content: ''; display: inline-block; width: 12px; height: 12px; border-radius: 3px; background: #e6f7ff; margin-right: 4px; vertical-align: middle; }
.legend-human::before { content: ''; display: inline-block; width: 12px; height: 12px; border-radius: 3px; background: #f6ffed; margin-right: 4px; vertical-align: middle; }
.legend-ai::before    { content: ''; display: inline-block; width: 12px; height: 12px; border-radius: 3px; background: #f9f0ff; margin-right: 4px; vertical-align: middle; }

/* ── Review form ── */
.review-form h3 { margin-bottom: 0.25rem; }
.review-hint { font-size: 0.85rem; color: #888; margin-bottom: 1rem; }

.rating-row {
  display: flex;
  gap: 1rem;
  margin-bottom: 1rem;
}
.btn-rating {
  padding: 0.5rem 1.5rem;
  font-size: 1rem;
  border: 2px solid #d9d9d9;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-rating:hover { border-color: #52c41a; background: #f6ffed; }
.btn-rating.active { border-color: #52c41a; background: #f6ffed; font-weight: 600; }
.btn-rating-down:hover { border-color: #ff4d4f; background: #fff2f0; }
.btn-rating-down.active { border-color: #ff4d4f; background: #fff2f0; font-weight: 600; }

.empty-state {
  text-align: center;
  padding: 3rem;
  color: #bbb;
  font-size: 0.95rem;
}

/* ── Saved review display ── */
.saved-review-display {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  padding: 0.85rem 1.1rem;
  background: #f0f5ff;
  border: 1px solid #adc6ff;
  border-radius: 8px;
  margin-bottom: 1rem;
}
.saved-rating {
  font-size: 1rem;
  font-weight: 600;
  padding: 3px 12px;
  border-radius: 12px;
}
.rating-up   { background: #f6ffed; color: #389e0d; border: 1px solid #b7eb8f; }
.rating-down { background: #fff2f0; color: #cf1322; border: 1px solid #ffccc7; }
.saved-comment {
  flex: 1;
  font-size: 0.9rem;
  color: #333;
  font-style: italic;
}
.saved-time {
  font-size: 0.78rem;
  color: #8c8c8c;
}
.btn-link {
  background: none;
  border: none;
  color: #1890ff;
  cursor: pointer;
  font-size: 0.82rem;
  padding: 0;
  text-decoration: underline;
}
.btn-link:hover { color: #40a9ff; }

/* ── AI Context Panel ── */
.ai-context-toggle {
  font-size: 0.72rem;
  color: #1890ff;
  cursor: pointer;
  margin-top: 0.3rem;
  user-select: none;
  text-align: right;
}
.ai-context-toggle:hover { text-decoration: underline; }

.ai-context-panel {
  margin-top: 0.5rem;
  background: #fafafa;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 0.75rem 1rem;
  font-size: 0.82rem;
  max-width: 520px;
}

.ctx-section { margin-bottom: 0.75rem; }
.ctx-section:last-child { margin-bottom: 0; }

.ctx-section-title {
  font-weight: 600;
  color: #555;
  margin-bottom: 0.4rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.ctx-count { font-weight: 400; color: #aaa; font-size: 0.78rem; }
.ctx-expand-btn { font-size: 0.75rem; }

/* Tool calls */
.tool-call-list { display: flex; flex-direction: column; gap: 0.4rem; }
.tool-call-item {
  background: #fff;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  padding: 0.4rem 0.7rem;
}
.tool-name {
  display: inline-block;
  background: #e6f7ff;
  color: #0050b3;
  border-radius: 4px;
  padding: 1px 7px;
  font-size: 0.78rem;
  font-weight: 600;
  margin-right: 0.4rem;
}
.tool-args {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 0.75rem;
  color: #666;
  word-break: break-all;
}
.tool-result {
  margin-top: 0.25rem;
  font-size: 0.75rem;
  color: #52c41a;
  font-family: 'SFMono-Regular', Consolas, monospace;
  word-break: break-all;
  white-space: pre-wrap;
  background: #f6ffed;
  border-radius: 4px;
  padding: 0.25rem 0.5rem;
}

/* LLM messages */
.llm-messages { display: flex; flex-direction: column; gap: 0.3rem; margin-top: 0.35rem; }
.llm-msg-row {
  display: flex;
  gap: 0.5rem;
  align-items: flex-start;
  padding: 0.3rem 0.5rem;
  border-radius: 5px;
  font-size: 0.78rem;
}
.llm-role-system   { background: #fff7e6; }
.llm-role-user     { background: #e6f7ff; }
.llm-role-assistant { background: #f9f0ff; }
.llm-role-tool     { background: #f6ffed; }

.llm-role-badge {
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(0,0,0,0.06);
  flex-shrink: 0;
  color: #555;
  white-space: nowrap;
}
.llm-content {
  color: #333;
  word-break: break-word;
  white-space: pre-wrap;
  line-height: 1.45;
}

.ctx-empty {
  font-size: 0.78rem;
  color: #bbb;
  text-align: center;
  padding: 0.5rem 0;
}
</style>

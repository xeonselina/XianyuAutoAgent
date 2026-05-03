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
              <span
                v-if="reviewMap[s.chat_id]"
                class="review-icon"
                :class="reviewMap[s.chat_id].rating === 1 ? 'review-icon-up' : 'review-icon-down'"
                :title="reviewMap[s.chat_id].rating === 1 ? '已好评' : '已差评'"
              >{{ reviewMap[s.chat_id].rating === 1 ? '👍' : '👎' }}</span>
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
            v-for="msg in mergedTimeline"
            :key="msg._key || msg.id"
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
                <div v-if="hasAiContext(msg)" class="ai-context-toggle" @click="toggleContext(msg.id)">
                  {{ contextVisible[msg.id] ? '▲ 收起 AI 上下文' : '▼ 查看 AI 上下文' }}
                </div>
                <div v-if="contextVisible[msg.id] && hasAiContext(msg)" class="ai-context-panel">
                  <!-- 商品信息 -->
                  <div v-if="msg.context && (msg.context.item_title || msg.context.item_price)" class="ctx-section">
                    <div class="ctx-section-title">🛍️ 商品信息</div>
                    <div class="ctx-kv-list">
                      <div v-if="msg.context.item_title" class="ctx-kv-row">
                        <span class="ctx-kv-key">标题</span>
                        <span class="ctx-kv-val">{{ msg.context.item_title }}</span>
                      </div>
                      <div v-if="msg.context.item_price" class="ctx-kv-row">
                        <span class="ctx-kv-key">价格</span>
                        <span class="ctx-kv-val">¥{{ msg.context.item_price }}</span>
                      </div>
                    </div>
                  </div>

                  <!-- 买家身份 -->
                  <div v-if="msg.context && msg.context.is_returning_customer !== undefined" class="ctx-section">
                    <div class="ctx-section-title">👤 买家身份</div>
                    <div class="ctx-kv-list">
                      <div class="ctx-kv-row">
                        <span class="ctx-kv-key">类型</span>
                        <span class="ctx-kv-val">
                          <span v-if="msg.context.is_returning_customer" class="badge-returning">🔁 老客户（有付款记录）</span>
                          <span v-else class="badge-new">🆕 新客户</span>
                        </span>
                      </div>
                    </div>
                  </div>

                  <!-- 租赁信息 -->
                  <div v-if="msg.context && (msg.context.receive_date || msg.context.return_date || msg.context.destination)" class="ctx-section">
                    <div class="ctx-section-title">🗓️ 租赁信息</div>
                    <div class="ctx-kv-list">
                      <div v-if="msg.context.receive_date" class="ctx-kv-row">
                        <span class="ctx-kv-key ctx-kv-key-wide">收货日期</span>
                        <span class="ctx-kv-val">{{ msg.context.receive_date }}</span>
                      </div>
                      <div v-if="msg.context.return_date" class="ctx-kv-row">
                        <span class="ctx-kv-key ctx-kv-key-wide">归还日期</span>
                        <span class="ctx-kv-val">{{ msg.context.return_date }}</span>
                      </div>
                      <div v-if="msg.context.destination" class="ctx-kv-row">
                        <span class="ctx-kv-key ctx-kv-key-wide">收货地</span>
                        <span class="ctx-kv-val">{{ msg.context.destination }}</span>
                      </div>
                    </div>
                  </div>

                  <!-- 历史对话摘要 -->
                  <div v-if="msg.context && msg.context.context_summary" class="ctx-section">
                    <div class="ctx-section-title">📝 历史对话摘要</div>
                    <div class="ctx-summary">{{ msg.context.context_summary }}</div>
                  </div>
                </div>

                <!-- Agent Turns Panel -->
                <div v-if="hasAgentTurns(msg)" class="ai-context-toggle turns-toggle" @click="toggleTurns(msg.id)">
                  {{ turnsVisible[msg.id] ? '▲ 收起 AI 推理过程' : '▼ 查看 AI 推理过程 (' + getAgentTurns(msg).length + ' 轮)' }}
                </div>
                <div v-if="turnsVisible[msg.id] && hasAgentTurns(msg)" class="agent-turns-panel">
                  <div
                    v-for="(turn, tidx) in getAgentTurns(msg)"
                    :key="tidx"
                    class="agent-turn-item"
                  >
                    <div class="agent-turn-header">
                      <span class="turn-index">Turn {{ turn.turn_number != null ? turn.turn_number : (tidx + 1) }}</span>
                      <span v-if="turn.confidence_percent != null" class="turn-confidence" :class="confidenceClass(turn.confidence_percent)">
                        置信度 {{ turn.confidence_percent }}%
                      </span>
                      <span v-if="turn.response_suppressed" class="badge-suppressed">🔇 已抑制</span>
                      <span v-else-if="turn.response_text" class="badge-sent">✅ 已发送</span>
                      <span v-if="turn.duration_ms" class="turn-duration">{{ turn.duration_ms }}ms</span>
                    </div>

                    <!-- Tool Calls -->
                    <div v-if="turn.tool_calls && formatToolCalls(turn.tool_calls).length > 0" class="ctx-section">
                      <div class="ctx-section-title">🔧 工具调用</div>
                      <div class="tool-call-list">
                        <div
                          v-for="(tc, tcidx) in formatToolCalls(turn.tool_calls)"
                          :key="tcidx"
                          class="tool-call-item"
                        >
                          <span class="tool-name">{{ tc.name }}</span>
                          <div v-if="tc.args" class="tool-args">{{ argsDisplay(tc.args) }}</div>
                        </div>
                      </div>
                    </div>

                    <!-- Tool Results -->
                    <div v-if="turn.tool_results && formatToolResults(turn.tool_results).length > 0" class="ctx-section">
                      <div class="ctx-section-title">📤 工具结果</div>
                      <div class="tool-call-list">
                        <div
                          v-for="(tr, tridx) in formatToolResults(turn.tool_results)"
                          :key="tridx"
                          class="tool-call-item"
                        >
                          <div class="tool-result">{{ tr.content }}</div>
                        </div>
                      </div>
                    </div>

                    <!-- AI Response -->
                    <div v-if="turn.response_text" class="ctx-section">
                      <div class="ctx-section-title">
                        💬 AI 回复
                        <span v-if="turn.response_suppressed" class="suppressed-label">（因置信度不足未发送）</span>
                      </div>
                      <div class="turn-response-text" :class="{ 'response-suppressed': turn.response_suppressed }">{{ turn.response_text }}</div>
                    </div>
                  </div>
                </div>
              </div>
              <div class="msg-avatar">🤖</div>
            </template>

            <!-- Suppressed AI turn bubble -->
            <template v-else-if="msg._type === 'suppressed'">
              <div class="msg-body suppressed-bubble-body">
                <div class="msg-meta">AI 客服 · {{ formatTime(msg._time) }}</div>
                <div class="msg-bubble suppressed-bubble">
                  🔇 AI 客服置信度抑制
                  <span class="suppressed-turn-count">（{{ msg._turns.length }} 轮推理）</span>
                </div>
                <!-- Toggle to expand turns -->
                <div class="ai-context-toggle turns-toggle" @click="toggleTurns(msg._key)">
                  {{ turnsVisible[msg._key] ? '▲ 收起 AI 推理过程' : '▼ 查看 AI 推理过程 (' + msg._turns.length + ' 轮)' }}
                </div>
                <div v-if="turnsVisible[msg._key]" class="agent-turns-panel suppressed-turns-panel">
                  <div
                    v-for="(turn, tidx) in msg._turns"
                    :key="turn.id || tidx"
                    class="agent-turn-item"
                  >
                    <div class="agent-turn-header">
                      <span class="turn-index">Turn {{ turn.turn_number != null ? turn.turn_number : (tidx + 1) }}</span>
                      <span v-if="turn.confidence_percent != null" class="turn-confidence" :class="confidenceClass(turn.confidence_percent)">
                        置信度 {{ turn.confidence_percent }}%
                      </span>
                      <span v-if="turn.response_suppressed" class="badge-suppressed">🔇 已抑制</span>
                      <span v-else-if="turn.response_text" class="badge-sent">✅ 已发送</span>
                      <span v-if="turn.duration_ms" class="turn-duration">{{ turn.duration_ms }}ms</span>
                    </div>

                    <!-- Tool Calls -->
                    <div v-if="turn.tool_calls && formatToolCalls(turn.tool_calls).length > 0" class="ctx-section">
                      <div class="ctx-section-title">🔧 工具调用</div>
                      <div class="tool-call-list">
                        <div v-for="(tc, tcidx) in formatToolCalls(turn.tool_calls)" :key="tcidx" class="tool-call-item">
                          <span class="tool-name">{{ tc.name }}</span>
                          <div v-if="tc.args" class="tool-args">{{ argsDisplay(tc.args) }}</div>
                        </div>
                      </div>
                    </div>

                    <!-- Tool Results -->
                    <div v-if="turn.tool_results && formatToolResults(turn.tool_results).length > 0" class="ctx-section">
                      <div class="ctx-section-title">📤 工具结果</div>
                      <div class="tool-call-list">
                        <div v-for="(tr, tridx) in formatToolResults(turn.tool_results)" :key="tridx" class="tool-call-item">
                          <div class="tool-result">{{ tr.content }}</div>
                        </div>
                      </div>
                    </div>

                    <!-- AI Response -->
                    <div v-if="turn.response_text" class="ctx-section">
                      <div class="ctx-section-title">
                        💬 AI 回复
                        <span v-if="turn.response_suppressed" class="suppressed-label">（因置信度不足未发送）</span>
                      </div>
                      <div class="turn-response-text" :class="{ 'response-suppressed': turn.response_suppressed }">{{ turn.response_text }}</div>
                    </div>

                    <!-- Inline rating -->
                    <div class="turn-inline-rating">
                      <div v-if="getTurnReview(msg._sessionId, turn.id)" class="turn-saved-rating">
                        <span class="saved-rating" :class="getTurnReview(msg._sessionId, turn.id).rating === 1 ? 'rating-up' : 'rating-down'">
                          {{ getTurnReview(msg._sessionId, turn.id).rating === 1 ? '👍 好评' : '👎 差评' }}
                        </span>
                        <span v-if="getTurnReview(msg._sessionId, turn.id).comment" class="saved-comment">「{{ getTurnReview(msg._sessionId, turn.id).comment }}」</span>
                        <span class="saved-time">{{ formatTime(getTurnReview(msg._sessionId, turn.id).updated_at) }}</span>
                        <button class="btn-link" @click="clearTurnReview(msg._sessionId, turn.id)">修改</button>
                      </div>
                      <div v-else-if="pendingRating[turn.id] !== undefined" class="turn-pending-rating">
                        <div class="pending-rating-header">
                          <span class="pending-emoji">{{ pendingRating[turn.id] === 1 ? '👍' : '👎' }}</span>
                          <span class="pending-label">{{ pendingRating[turn.id] === 1 ? '好评' : '差评' }}</span>
                          <button class="btn-link pending-switch" @click="pendingRating = { ...pendingRating, [turn.id]: pendingRating[turn.id] === 1 ? -1 : 1 }">切换</button>
                        </div>
                        <textarea
                          class="turn-comment-input"
                          :value="pendingComment[turn.id]"
                          @input="pendingComment = { ...pendingComment, [turn.id]: $event.target.value }"
                          placeholder="可选：填写文字点评"
                          rows="2"
                        ></textarea>
                        <div class="pending-actions">
                          <button class="btn btn-primary btn-sm" :disabled="savingTurnReview[turn.id]" @click="submitTurnReview(turn, msg._sessionId)">{{ savingTurnReview[turn.id] ? '保存中…' : '确认' }}</button>
                          <button class="btn btn-secondary btn-sm" @click="cancelTurnRating(turn.id)">取消</button>
                          <span v-if="turnReviewError[turn.id]" class="turn-review-error">{{ turnReviewError[turn.id] }}</span>
                        </div>
                      </div>
                      <div v-else class="turn-rating-buttons">
                        <button class="btn-turn-rate btn-turn-up" :disabled="savingTurnReview[turn.id]" @click="selectTurnRating(turn.id, 1)" title="这轮回复质量好">👍</button>
                        <button class="btn-turn-rate btn-turn-down" :disabled="savingTurnReview[turn.id]" @click="selectTurnRating(turn.id, -1)" title="这轮回复质量差">👎</button>
                        <span v-if="turnReviewError[turn.id]" class="turn-review-error">{{ turnReviewError[turn.id] }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <div class="msg-avatar">🔇</div>
            </template>

            <!-- System messages -->
            <template v-else>
              <div class="msg-system">{{ msg.message_content }}</div>
            </template>
          </div>

          <div v-if="mergedTimeline.length === 0" class="empty-state">暂无消息记录</div>
        </div>

        <!-- Legend -->
        <div class="legend card">
          <span class="legend-item legend-user">👤 买家消息</span>
          <span class="legend-item legend-human">🧑‍💼 人工回复</span>
          <span class="legend-item legend-ai">🤖 AI 回复</span>
        </div>

        <!-- AI Evaluation / Comparison Section -->
        <div class="ai-eval-form card">
          <h3>🤖 AI 对比评估</h3>
          <p class="review-hint">AI 自动对比人工回复和 AI 回复的相似度</p>

          <div v-if="loadingComparison" class="loading"><div class="spinner"></div></div>
          <div v-else-if="comparisonError" class="alert alert-error">{{ comparisonError }}</div>
          
          <template v-else-if="aiComparisons && aiComparisons.comparisons && aiComparisons.comparisons.length > 0">
            <button
              class="btn btn-secondary"
              @click="comparisonVisible = !comparisonVisible"
              style="margin-bottom: 1rem; width: 100%;"
            >
              {{ comparisonVisible ? '▲ 隐藏对比结果' : '▼ 展开对比结果' }} ({{ aiComparisons.comparisons.length }} 条对话)
            </button>

            <div v-if="comparisonVisible" class="ai-comparison-results">
              <div v-for="(comp, idx) in aiComparisons.comparisons" :key="idx" class="comparison-item">
                <div class="comparison-header">
                  <span class="comp-index">第 {{ idx + 1 }} 条对话</span>
                  <span class="comp-similarity" :class="getSimilarityClass(comp.similarity)">
                    📊 相似度: {{ (comp.similarity * 100).toFixed(1) }}%
                  </span>
                  <span class="comp-length-ratio">
                    📏 长度比: {{ (comp.length_ratio * 100).toFixed(1) }}%
                  </span>
                </div>

                <div class="comparison-messages">
                  <div class="comp-msg-group">
                    <div class="comp-msg-label">📝 用户问题</div>
                    <div class="comp-msg-content">{{ comp.user_message }}</div>
                  </div>

                  <div class="comp-msg-group">
                    <div class="comp-msg-label">🧑‍💼 人工回复 ({{ comp.length_human }} 字)</div>
                    <div class="comp-msg-content human-reply">{{ comp.human_reply }}</div>
                  </div>

                  <div class="comp-msg-group">
                    <div class="comp-msg-label">🤖 AI 回复 ({{ comp.length_ai }} 字)</div>
                    <div class="comp-msg-content ai-reply">{{ comp.ai_reply }}</div>
                  </div>
                </div>

                <div class="comparison-metrics">
                  <div class="metric-bar">
                    <span class="metric-label">相似度</span>
                    <div class="progress-bar">
                      <div class="progress-fill" :style="{ width: (comp.similarity * 100) + '%', backgroundColor: getSimilarityColor(comp.similarity) }"></div>
                    </div>
                    <span class="metric-value">{{ (comp.similarity * 100).toFixed(1) }}%</span>
                  </div>
                  <div class="metric-bar">
                    <span class="metric-label">长度比</span>
                    <div class="progress-bar">
                      <div class="progress-fill" :style="{ width: (comp.length_ratio * 100) + '%', backgroundColor: getSimilarityColor(comp.length_ratio) }"></div>
                    </div>
                    <span class="metric-value">{{ (comp.length_ratio * 100).toFixed(1) }}%</span>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <template v-else-if="aiComparisons && aiComparisons.status === 'no_data'">
            <div class="alert alert-info">
              ℹ️ 该对话中没有找到对应的人工回复和 AI 回复对进行对比。
            </div>
          </template>

          <template v-else>
            <button class="btn btn-secondary" @click="loadComparison" style="width: 100%;">
              加载 AI 对比结果
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
  compareReplies,
  saveTurnReview,
  fetchTurnReviews,
} from '../conversationHistoryApi.js'

export default {
  name: 'ConversationHistory',

  props: {
    chatId: { type: String, default: null },
  },

  data() {
    return {
      // AI Comparison
      aiComparisons: null,
      loadingComparison: false,
      comparisonError: '',
      comparisonVisible: false,

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

      // Per-turn reviews: { [sessionId]: { [turnId]: reviewObj } }
      turnReviewsBySession: {},
      // Saving state per turn: { [turnId]: bool }
      savingTurnReview: {},
      // Error per turn: { [turnId]: string }
      turnReviewError: {},
      // Pending state: rating selected but comment not yet submitted
      // { [turnId]: 1 | -1 }
      pendingRating: {},
      // Pending comment text: { [turnId]: string }
      pendingComment: {},

      // AI context panel
      contextVisible: {},   // { msg_id: bool }
      // Agent turns panel
      turnsBySession: {},
      turnsVisible: {},
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

  computed: {
    /**
     * Merge real messages with synthetic "suppressed" entries derived from
     * turnsBySession.  A suppressed entry is inserted when a session's turns
     * are ALL suppressed AND no message in conversations carries that session_id
     * (i.e. nothing was ever sent for that session).
     *
     * The synthetic entry gets:
     *   _type: 'suppressed'
     *   _key:  'suppressed-<sessionId>'
     *   _sessionId: sessionId
     *   _turns: [...all turns for that session]
     *   _time:  created_at of the first turn (for display)
     */
    mergedTimeline() {
      const msgs = this.messages || []
      const bySession = this.turnsBySession || {}

      // Collect session_ids that are already represented in real messages
      const representedSessions = new Set(msgs.map(m => m.session_id).filter(Boolean))

      // Build synthetic suppressed entries for sessions NOT in messages
      const suppressedEntries = []
      for (const [sessionId, turns] of Object.entries(bySession)) {
        if (representedSessions.has(sessionId)) continue
        if (!turns || turns.length === 0) continue
        suppressedEntries.push({
          _type: 'suppressed',
          _key: `suppressed-${sessionId}`,
          _sessionId: sessionId,
          _turns: turns,
          _time: turns[0] && turns[0].created_at ? turns[0].created_at : null,
        })
      }

      if (suppressedEntries.length === 0) return msgs

      // Merge: sort all items by time
      const combined = [
        ...msgs.map(m => ({ ...m, _sortTime: m.created_at || '' })),
        ...suppressedEntries.map(e => ({ ...e, _sortTime: e._time || '' })),
      ]
      combined.sort((a, b) => {
        if (a._sortTime < b._sortTime) return -1
        if (a._sortTime > b._sortTime) return 1
        return 0
      })
      return combined
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
      const resolved = this.$router.resolve({ name: 'history-detail', params: { chatId } })
      window.open(resolved.href, '_blank')
    },

    async loadDetail(chatId) {
      this.loadingDetail = true
      this.messages = []
      this.turnsBySession = {}
      this.turnsVisible = {}
      this.turnReviewsBySession = {}
      this.savingTurnReview = {}
      this.turnReviewError = {}
      this.pendingRating = {}
      this.pendingComment = {}
      this.contextVisible = {}
      this.aiComparisons = null
      this.comparisonError = ''
      this.comparisonVisible = false
      try {
        const convData = await fetchConversation(chatId)
        this.messages = convData.messages || []
        this.turnsBySession = convData.turns_by_session || {}

        // Load per-turn reviews for every session
        const sessionIds = Object.keys(this.turnsBySession)
        await Promise.all(sessionIds.map(async (sid) => {
          try {
            const data = await fetchTurnReviews(sid)
            this.turnReviewsBySession[sid] = data.reviews || {}
          } catch (_) { /* ignore */ }
        }))

        // Auto-load AI comparison
        try {
          this.aiComparisons = await compareReplies(chatId)
        } catch (e) {
          console.debug('Could not load AI comparison', e)
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

    // ── Per-turn review helpers ────────────────────────────────────

    getTurnReview(sessionId, turnId) {
      const bySession = this.turnReviewsBySession[sessionId]
      if (!bySession) return null
      return bySession[turnId] || null
    },

    clearTurnReview(sessionId, turnId) {
      if (this.turnReviewsBySession[sessionId]) {
        const updated = { ...this.turnReviewsBySession[sessionId] }
        delete updated[turnId]
        this.turnReviewsBySession = {
          ...this.turnReviewsBySession,
          [sessionId]: updated,
        }
      }
    },

    selectTurnRating(turnId, rating) {
      this.pendingRating = { ...this.pendingRating, [turnId]: rating }
      if (this.pendingComment[turnId] === undefined) {
        this.pendingComment = { ...this.pendingComment, [turnId]: '' }
      }
      this.turnReviewError = { ...this.turnReviewError, [turnId]: '' }
    },

    cancelTurnRating(turnId) {
      const pr = { ...this.pendingRating }
      const pc = { ...this.pendingComment }
      delete pr[turnId]
      delete pc[turnId]
      this.pendingRating = pr
      this.pendingComment = pc
    },

    async submitTurnReview(turn, sessionId) {
      const turnId = turn.id
      const rating = this.pendingRating[turnId]
      const comment = (this.pendingComment[turnId] || '').trim()
      if (rating === undefined) return
      this.savingTurnReview = { ...this.savingTurnReview, [turnId]: true }
      this.turnReviewError = { ...this.turnReviewError, [turnId]: '' }
      try {
        await saveTurnReview(turnId, rating, sessionId, comment)
        const reviewObj = {
          agent_turn_id: turnId,
          session_id: sessionId,
          rating,
          comment,
          updated_at: new Date().toISOString(),
        }
        const existing = this.turnReviewsBySession[sessionId] || {}
        this.turnReviewsBySession = {
          ...this.turnReviewsBySession,
          [sessionId]: { ...existing, [turnId]: reviewObj },
        }
        // Clear pending state
        this.cancelTurnRating(turnId)
      } catch (e) {
        this.turnReviewError = { ...this.turnReviewError, [turnId]: `保存失败: ${e.message}` }
      } finally {
        this.savingTurnReview = { ...this.savingTurnReview, [turnId]: false }
      }
    },

    msgClass(msg) {
      if (msg._type === 'suppressed') return 'msg-suppressed'
      if (msg.message_type === 'user') return 'msg-user'
      if (msg.message_type === 'seller' && msg.agent_response) return 'msg-ai'
      if (msg.message_type === 'seller') return 'msg-human'
      return 'msg-system-wrap'
    },

    // ── AI Context helpers ──────────────────────────────────────────

    hasAiContext(msg) {
      if (!msg.context) return false
      const c = msg.context
      return !!(c.item_title || c.item_price || c.context_summary || c.is_returning_customer !== undefined
        || c.receive_date || c.return_date || c.destination)
    },

    toggleContext(msgId) {
      this.contextVisible = {
        ...this.contextVisible,
        [msgId]: !this.contextVisible[msgId],
      }
    },

    // ── Agent turns helpers ─────────────────────────────────────────

    getAgentTurns(msg) {
      const sid = msg.session_id
      if (!sid || !this.turnsBySession) return []
      return this.turnsBySession[sid] || []
    },

    hasAgentTurns(msg) {
      return this.getAgentTurns(msg).length > 0
    },

    toggleTurns(msgId) {
      this.turnsVisible = {
        ...this.turnsVisible,
        [msgId]: !this.turnsVisible[msgId],
      }
    },

    parseJsonField(val) {
      if (!val) return null
      if (typeof val === 'object') return val
      try { return JSON.parse(val) } catch (_) { return val }
    },

    formatToolCalls(rawCalls) {
      const parsed = this.parseJsonField(rawCalls)
      if (!parsed) return []
      const arr = Array.isArray(parsed) ? parsed : [parsed]
      return arr.map(tc => {
        // Handle OpenAI tool-call schema: { function: { name, arguments }, id }
        if (tc.function) {
          const args = this.parseJsonField(tc.function.arguments)
          return { name: tc.function.name, args }
        }
        // Handle flat schema: { tool_name, tool_input }
        if (tc.tool_name || tc.name) {
          return { name: tc.tool_name || tc.name, args: tc.tool_input || tc.input || tc.args }
        }
        return { name: '(unknown)', args: tc }
      })
    },

    formatToolResults(rawResults) {
      const parsed = this.parseJsonField(rawResults)
      if (!parsed) return []
      const arr = Array.isArray(parsed) ? parsed : [parsed]
      return arr.map(tr => {
        // OpenAI tool_result schema: { tool_use_id, content }
        if (tr.content !== undefined) {
          const content = Array.isArray(tr.content)
            ? tr.content.map(c => (typeof c === 'object' ? (c.text || JSON.stringify(c)) : c)).join('\n')
            : (typeof tr.content === 'string' ? tr.content : JSON.stringify(tr.content))
          return { id: tr.tool_use_id || '', content }
        }
        // Flat result string
        return { id: '', content: typeof tr === 'string' ? tr : JSON.stringify(tr) }
      })
    },

    argsDisplay(args) {
      if (!args) return ''
      return typeof args === 'string' ? args : JSON.stringify(args, null, 2)
    },

    confidenceClass(pct) {
      if (pct >= 70) return 'confidence-high'
      if (pct >= 40) return 'confidence-medium'
      return 'confidence-low'
    },


    async loadComparison() {
      this.loadingComparison = true
      this.comparisonError = ''
      try {
        this.aiComparisons = await compareReplies(this.selectedChatId)
      } catch (e) {
        this.comparisonError = `加载失败: ${e.message}`
      } finally {
        this.loadingComparison = false
      }
    },

    getSimilarityClass(similarity) {
      if (similarity >= 0.7) return 'similarity-high'
      if (similarity >= 0.4) return 'similarity-medium'
      return 'similarity-low'
    },

    getSimilarityColor(value) {
      if (value >= 0.7) return '#52c41a'  // green
      if (value >= 0.4) return '#faad14'  // orange
      return '#ff4d4f'  // red
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
.review-icon {
  font-size: 1rem;
  line-height: 1;
  cursor: default;
  opacity: 0.85;
  transition: opacity 0.15s;
}
.review-icon:hover { opacity: 1; }
.review-icon-up  { filter: none; }
.review-icon-down { filter: none; }

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

/* KV list */
.ctx-kv-list { display: flex; flex-direction: column; gap: 0.25rem; }
.ctx-kv-row { display: flex; gap: 0.5rem; align-items: baseline; font-size: 0.82rem; }
.ctx-kv-key {
  flex-shrink: 0;
  color: #999;
  width: 3em;
}
.ctx-kv-key-wide {
  width: 4.5em;
}
.ctx-kv-val { color: #333; word-break: break-word; }

/* Returning / new customer badges */
.badge-returning {
  background: #fff7e6;
  color: #d46b08;
  border: 1px solid #ffd591;
  border-radius: 10px;
  padding: 1px 8px;
  font-size: 0.78rem;
}
.badge-new {
  background: #f6ffed;
  color: #389e0d;
  border: 1px solid #b7eb8f;
  border-radius: 10px;
  padding: 1px 8px;
  font-size: 0.78rem;
}

/* History summary */
.ctx-summary {
  background: #fff;
  border-left: 3px solid #722ed1;
  padding: 0.5rem 0.75rem;
  font-size: 0.83rem;
  color: #333;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  border-radius: 0 4px 4px 0;
}

.ctx-empty {
  font-size: 0.78rem;
  color: #bbb;
  text-align: center;
  padding: 0.5rem 0;
}

/* ── AI Evaluation Section ── */
.ai-eval-form h3 { margin-bottom: 0.25rem; }
.ai-eval-form { background: #f0f8ff; border: 1px solid #b3d8ff; }

.ai-comparison-results {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.comparison-item {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 1rem;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.comparison-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 0.75rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid #f0f0f0;
  flex-wrap: wrap;
}

.comp-index {
  font-size: 0.85rem;
  font-weight: 600;
  color: #666;
}

.comp-similarity {
  font-size: 0.9rem;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 6px;
}

.similarity-high {
  background: #f6ffed;
  color: #389e0d;
  border: 1px solid #b7eb8f;
}

.similarity-medium {
  background: #fffbe6;
  color: #ad6800;
  border: 1px solid #ffd591;
}

.similarity-low {
  background: #fff2f0;
  color: #cf1322;
  border: 1px solid #ffccc7;
}

.comp-length-ratio {
  font-size: 0.85rem;
  color: #666;
}

.comparison-messages {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.comp-msg-group {
  background: #fafafa;
  border-radius: 6px;
  padding: 0.75rem;
}

.comp-msg-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #999;
  margin-bottom: 0.3rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.comp-msg-content {
  font-size: 0.9rem;
  color: #333;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  background: #fff;
  border-radius: 4px;
  padding: 0.6rem;
  border-left: 3px solid #d9d9d9;
}

.comp-msg-content.human-reply {
  border-left-color: #52c41a;
  background: #f6ffed;
}

.comp-msg-content.ai-reply {
  border-left-color: #722ed1;
  background: #f9f0ff;
}

.comparison-metrics {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.metric-bar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.85rem;
}

.metric-label {
  flex-shrink: 0;
  width: 4rem;
  color: #666;
  font-weight: 500;
}

.progress-bar {
  flex: 1;
  height: 24px;
  background: #f0f0f0;
  border-radius: 4px;
  overflow: hidden;
  border: 1px solid #d9d9d9;
}

.progress-fill {
  height: 100%;
  transition: width 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
  color: #fff;
  font-weight: 600;
}

.metric-value {
  flex-shrink: 0;
  width: 3.5rem;
  text-align: right;
  font-weight: 600;
  color: #333;
}

.alert-info {
  background: #e6f7ff;
  border: 1px solid #91d5ff;
  color: #0050b3;
  border-radius: 6px;
  padding: 0.85rem 1.1rem;
  font-size: 0.9rem;
  margin-top: 0.5rem;
}

/* ── Agent Turns Panel ── */
.turns-toggle {
  color: #722ed1;
  margin-top: 0.3rem;
}

.agent-turns-panel {
  margin-top: 0.5rem;
  background: #faf5ff;
  border: 1px solid #d3adf7;
  border-radius: 8px;
  padding: 0.75rem 1rem;
  font-size: 0.82rem;
  max-width: 560px;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.agent-turn-item {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  padding: 0.6rem 0.9rem;
}

.agent-turn-header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
  padding-bottom: 0.4rem;
  border-bottom: 1px solid #f0f0f0;
}

.turn-index {
  font-weight: 600;
  color: #722ed1;
  font-size: 0.8rem;
}

.turn-confidence {
  font-size: 0.75rem;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 10px;
}

.confidence-high {
  background: #f6ffed;
  color: #389e0d;
  border: 1px solid #b7eb8f;
}

.confidence-medium {
  background: #fffbe6;
  color: #ad6800;
  border: 1px solid #ffd591;
}

.confidence-low {
  background: #fff2f0;
  color: #cf1322;
  border: 1px solid #ffccc7;
}

.badge-suppressed {
  background: #fff2f0;
  color: #cf1322;
  border: 1px solid #ffccc7;
  border-radius: 10px;
  padding: 1px 8px;
  font-size: 0.75rem;
  font-weight: 600;
}

.badge-sent {
  background: #f6ffed;
  color: #389e0d;
  border: 1px solid #b7eb8f;
  border-radius: 10px;
  padding: 1px 8px;
  font-size: 0.75rem;
  font-weight: 600;
}

.turn-duration {
  font-size: 0.72rem;
  color: #aaa;
  margin-left: auto;
}

.turn-response-text {
  background: #f9f0ff;
  border-left: 3px solid #722ed1;
  padding: 0.5rem 0.75rem;
  font-size: 0.83rem;
  color: #333;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  border-radius: 0 4px 4px 0;
}

.turn-response-text.response-suppressed {
  background: #fff2f0;
  border-left-color: #ff4d4f;
  color: #666;
  opacity: 0.85;
}

.suppressed-label {
  font-weight: 400;
  color: #cf1322;
  font-size: 0.75rem;
}

/* ── Suppressed AI bubble ── */
.msg-suppressed { align-self: flex-end; flex-direction: row-reverse; }

.suppressed-bubble-body { display: flex; flex-direction: column; gap: 0.2rem; }

.suppressed-bubble {
  background: #fff2f0;
  color: #cf1322;
  border: 1px solid #ffccc7;
  border-radius: 12px 12px 2px 12px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}
.suppressed-turn-count {
  font-weight: 400;
  font-size: 0.78rem;
  color: #ff7875;
}
.suppressed-turns-panel {
  max-width: 560px;
  align-self: flex-end;
}

.turn-ratings-section h3 { margin-bottom: 0.25rem; }



.turn-rating-sessions {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.turn-rating-session {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.session-label {
  font-size: 0.78rem;
  color: #888;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.session-label code {
  background: #f0f0f0;
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 0.76rem;
  color: #555;
}
.turn-count-badge {
  background: #f0f0f0;
  color: #888;
  border-radius: 10px;
  padding: 0px 7px;
  font-size: 0.72rem;
}

.turn-rating-item {
  background: #faf5ff;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 0.65rem 0.9rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.turn-inline-rating {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  margin-top: 0.15rem;
  width: 100%;
}

.turn-rating-buttons {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.btn-turn-rate {
  background: #fff;
  border: 1.5px solid #d9d9d9;
  border-radius: 6px;
  padding: 2px 10px;
  font-size: 1rem;
  cursor: pointer;
  line-height: 1.6;
  transition: all 0.15s;
}
.btn-turn-up:hover  { border-color: #52c41a; background: #f6ffed; }
.btn-turn-down:hover { border-color: #ff4d4f; background: #fff2f0; }
.btn-turn-rate:disabled { opacity: 0.5; cursor: not-allowed; }

.turn-saved-rating {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.saved-comment {
  font-size: 0.78rem;
  color: #595959;
  font-style: italic;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.turn-pending-rating {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  width: 100%;
}
.pending-rating-header {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.pending-emoji {
  font-size: 1.1rem;
}
.pending-label {
  font-size: 0.82rem;
  font-weight: 600;
  color: #444;
}
.pending-switch {
  font-size: 0.75rem;
  margin-left: 0.2rem;
}
.turn-comment-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  padding: 0.4rem 0.6rem;
  font-size: 0.82rem;
  resize: vertical;
  outline: none;
  transition: border-color 0.15s;
  color: #333;
  background: #fff;
}
.turn-comment-input:focus {
  border-color: #a78bfa;
}
.pending-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.btn-sm {
  padding: 3px 14px;
  font-size: 0.8rem;
}

.turn-saving {
  font-size: 0.78rem;
  color: #888;
}
.turn-review-error {
  font-size: 0.78rem;
  color: #cf1322;
}
</style>
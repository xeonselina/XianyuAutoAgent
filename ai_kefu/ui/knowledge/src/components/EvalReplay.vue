<template>
  <div class="eval-replay">
    <!-- Run 选择列表 -->
    <div v-if="!selectedRunId" class="card">
      <div class="card-header">
        <h2>Eval 回放结果</h2>
        <p class="subtitle">选择一次评测运行，查看对话回放</p>
      </div>

      <div v-if="loadingRuns" class="loading"><div class="spinner"></div></div>
      <div v-else-if="runs.length === 0" class="empty-state">暂无评测记录</div>

      <div v-else class="runs-list">
        <div
          v-for="run in runs"
          :key="run.run_id"
          class="run-card"
          @click="selectRun(run.run_id)"
        >
          <div class="run-card-header">
            <span class="run-id">{{ run.run_id }}</span>
            <span v-if="run.tag" class="run-tag">{{ run.tag }}</span>
          </div>
          <div class="run-card-meta">
            <span>模型: {{ run.ai_model || '—' }}</span>
            <span>开始: {{ formatTime(run.started_at) }}</span>
          </div>
          <div class="run-card-stats">
            <span class="stat stat-total">共 {{ run.total_items }} 条</span>
            <span class="stat stat-success">✓ {{ run.success_count || 0 }}</span>
            <span class="stat stat-error">✗ {{ run.error_count || 0 }}</span>
            <span v-if="run.avg_duration_ms" class="stat stat-time">
              ⏱ {{ run.avg_duration_ms }}ms
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 对话回放视图 -->
    <div v-else class="replay-view">
      <!-- 顶部导航 -->
      <div class="replay-header card">
        <div class="replay-header-top">
          <button class="btn btn-secondary" @click="goBack">← 返回列表</button>
          <h2>{{ selectedRunId }}</h2>
        </div>

        <!-- Summary -->
        <div v-if="summary" class="replay-summary">
          <span>模型: {{ summary.ai_model || '—' }}</span>
          <span>共 {{ summary.total_items }} 条</span>
          <span class="stat-success">成功 {{ summary.success_count || 0 }}</span>
          <span class="stat-error">失败 {{ summary.error_count || 0 }}</span>
        </div>

        <!-- 过滤器 -->
        <div class="replay-filters">
          <select v-model="statusFilter" class="form-select filter-select" @change="loadRunDetail">
            <option value="">全部状态</option>
            <option value="success">✓ 成功</option>
            <option value="error">✗ 失败</option>
            <option value="skipped">— 跳过</option>
          </select>
          <select v-model="chatFilter" class="form-select filter-select" @change="loadRunDetail">
            <option value="">全部对话</option>
            <option v-for="c in chatIds" :key="c.chat_id" :value="c.chat_id">
              {{ c.chat_id }} ({{ c.message_count }}条)
            </option>
          </select>
          <span class="filter-info">
            显示 {{ items.length }} / {{ totalItems }} 条
          </span>
        </div>
      </div>

      <!-- 加载中 -->
      <div v-if="loadingDetail" class="loading"><div class="spinner"></div></div>

      <!-- 对话列表 -->
      <div v-else class="conversations-container">
        <div
          v-for="(group, idx) in groupedItems"
          :key="group.chat_id"
          class="chat-group card"
        >
          <div class="chat-group-header" @click="toggleGroup(idx)">
            <span class="chat-id">💬 {{ group.chat_id }}</span>
            <span class="chat-count">{{ group.items.length }} 条消息</span>
            <span class="expand-icon">{{ expandedGroups[idx] ? '▼' : '▶' }}</span>
          </div>

          <div v-if="expandedGroups[idx]" class="chat-messages">
            <div
              v-for="item in group.items"
              :key="item.id"
              class="message-pair"
              :class="{ 'message-error': item.status === 'error' }"
            >
              <!-- 上下文消息 (折叠) -->
              <div v-if="item.context_messages && item.context_messages.length > 0" class="context-toggle">
                <button class="btn-link" @click="item._showContext = !item._showContext">
                  {{ item._showContext ? '收起上下文' : `查看上下文 (${item.context_messages.length}条)` }}
                </button>
                <div v-if="item._showContext" class="context-messages">
                  <div
                    v-for="(ctx, ci) in item.context_messages"
                    :key="ci"
                    class="context-msg"
                    :class="'ctx-' + (ctx.role || ctx.message_type || 'unknown')"
                  >
                    <span class="ctx-role">{{ ctx.role || ctx.message_type || '?' }}</span>
                    <span class="ctx-content">{{ ctx.content || ctx.message_content || '' }}</span>
                  </div>
                </div>
              </div>

              <!-- 用户消息 -->
              <div class="msg msg-user">
                <div class="msg-avatar">👤</div>
                <div class="msg-body">
                  <div class="msg-label">买家</div>
                  <div class="msg-content">{{ item.user_message }}</div>
                </div>
              </div>

              <!-- 人类客服回复 -->
              <div v-if="item.human_reply" class="msg msg-human">
                <div class="msg-avatar">🧑‍💼</div>
                <div class="msg-body">
                  <div class="msg-label">人类客服 (实际回复)</div>
                  <div class="msg-content">{{ item.human_reply }}</div>
                </div>
              </div>

              <!-- AI 回复 -->
              <div class="msg msg-ai" :class="{ 'msg-ai-error': item.status === 'error' }">
                <div class="msg-avatar">🤖</div>
                <div class="msg-body">
                  <div class="msg-label">
                    AI Agent
                    <span v-if="item.ai_duration_ms" class="msg-meta">{{ item.ai_duration_ms }}ms</span>
                    <span v-if="item.ai_turn_count" class="msg-meta">{{ item.ai_turn_count }}轮</span>
                    <span
                      class="msg-status"
                      :class="'status-' + item.status"
                    >{{ item.status }}</span>
                  </div>
                  <div v-if="item.status === 'error'" class="msg-content msg-content-error">
                    ❌ {{ item.error_message || '未知错误' }}
                  </div>
                  <div v-else-if="item.ai_reply" class="msg-content">{{ item.ai_reply }}</div>
                  <div v-else class="msg-content msg-content-empty">（无回复）</div>

                  <!-- 工具调用 -->
                  <div v-if="item.ai_tool_calls && item.ai_tool_calls.length > 0" class="tool-calls">
                    <button class="btn-link" @click="item._showTools = !item._showTools">
                      {{ item._showTools ? '收起工具调用' : `🔧 ${item.ai_tool_calls.length} 次工具调用` }}
                    </button>
                    <div v-if="item._showTools" class="tool-calls-list">
                      <div v-for="(tc, ti) in item.ai_tool_calls" :key="ti" class="tool-call-item">
                        <span class="tool-name">{{ tc.function?.name || tc.name || '?' }}</span>
                        <pre class="tool-args">{{ formatToolArgs(tc) }}</pre>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <hr class="msg-divider" />
            </div>
          </div>
        </div>

        <!-- 加载更多 -->
        <div v-if="items.length < totalItems" class="load-more">
          <button class="btn btn-primary" @click="loadMore" :disabled="loadingMore">
            {{ loadingMore ? '加载中...' : `加载更多 (还有 ${totalItems - items.length} 条)` }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { evalAPI } from '../evalApi.js'

export default {
  name: 'EvalReplay',
  data() {
    return {
      // Runs list
      runs: [],
      loadingRuns: false,

      // Selected run
      selectedRunId: null,
      summary: null,
      items: [],
      totalItems: 0,
      chatIds: [],
      loadingDetail: false,
      loadingMore: false,

      // Filters
      statusFilter: '',
      chatFilter: '',

      // UI state
      expandedGroups: {},
      currentOffset: 0,
      pageSize: 200,
    }
  },

  computed: {
    groupedItems() {
      const groups = []
      const map = {}
      for (const item of this.items) {
        if (!map[item.chat_id]) {
          map[item.chat_id] = { chat_id: item.chat_id, items: [] }
          groups.push(map[item.chat_id])
        }
        map[item.chat_id].items.push(item)
      }
      return groups
    }
  },

  async mounted() {
    // Check if route has a run_id param
    const runId = this.$route.params.runId
    if (runId) {
      this.selectedRunId = runId
      await this.loadRunDetail()
      await this.loadChatIds()
    } else {
      await this.loadRuns()
    }
  },

  watch: {
    '$route.params.runId'(val) {
      if (val) {
        this.selectedRunId = val
        this.loadRunDetail()
        this.loadChatIds()
      } else {
        this.selectedRunId = null
        this.loadRuns()
      }
    }
  },

  methods: {
    async loadRuns() {
      this.loadingRuns = true
      try {
        const data = await evalAPI.listRuns(0, 100)
        this.runs = data.items || []
      } catch (e) {
        console.error('Failed to load runs:', e)
      } finally {
        this.loadingRuns = false
      }
    },

    selectRun(runId) {
      this.$router.push({ name: 'eval-detail', params: { runId } })
    },

    goBack() {
      this.selectedRunId = null
      this.items = []
      this.chatIds = []
      this.summary = null
      this.statusFilter = ''
      this.chatFilter = ''
      this.expandedGroups = {}
      this.$router.push({ name: 'eval-list' })
      this.loadRuns()
    },

    async loadChatIds() {
      try {
        const data = await evalAPI.getRunChats(this.selectedRunId)
        this.chatIds = data.chats || []
      } catch (e) {
        console.error('Failed to load chat ids:', e)
      }
    },

    async loadRunDetail() {
      this.loadingDetail = true
      this.currentOffset = 0
      this.items = []
      this.expandedGroups = {}
      try {
        const data = await evalAPI.getRunDetail(this.selectedRunId, {
          statusFilter: this.statusFilter || undefined,
          chatIdFilter: this.chatFilter || undefined,
          limit: this.pageSize,
          offset: 0,
        })
        this.items = (data.items || []).map(it => ({
          ...it,
          _showContext: false,
          _showTools: false,
        }))
        this.totalItems = data.total
        this.summary = data.summary
        this.currentOffset = this.items.length

        // Auto-expand first group
        if (this.groupedItems.length > 0) {
          this.expandedGroups = { 0: true }
        }
      } catch (e) {
        console.error('Failed to load run detail:', e)
      } finally {
        this.loadingDetail = false
      }
    },

    async loadMore() {
      this.loadingMore = true
      try {
        const data = await evalAPI.getRunDetail(this.selectedRunId, {
          statusFilter: this.statusFilter || undefined,
          chatIdFilter: this.chatFilter || undefined,
          limit: this.pageSize,
          offset: this.currentOffset,
        })
        const newItems = (data.items || []).map(it => ({
          ...it,
          _showContext: false,
          _showTools: false,
        }))
        this.items.push(...newItems)
        this.currentOffset += newItems.length
      } catch (e) {
        console.error('Failed to load more:', e)
      } finally {
        this.loadingMore = false
      }
    },

    toggleGroup(idx) {
      this.expandedGroups = {
        ...this.expandedGroups,
        [idx]: !this.expandedGroups[idx]
      }
    },

    formatTime(iso) {
      if (!iso) return '—'
      try {
        const d = new Date(iso)
        return d.toLocaleString('zh-CN', {
          month: '2-digit', day: '2-digit',
          hour: '2-digit', minute: '2-digit'
        })
      } catch {
        return iso
      }
    },

    formatToolArgs(tc) {
      try {
        const args = tc.function?.arguments || tc.arguments || tc.args || '{}'
        if (typeof args === 'string') {
          return JSON.stringify(JSON.parse(args), null, 2)
        }
        return JSON.stringify(args, null, 2)
      } catch {
        return String(tc.function?.arguments || tc.arguments || '')
      }
    },
  }
}
</script>

<style scoped>
.eval-replay {
  max-width: 960px;
  margin: 0 auto;
}

.card-header {
  margin-bottom: 1rem;
}

.card-header h2 {
  font-size: 1.25rem;
  color: #333;
}

.subtitle {
  color: #888;
  font-size: 0.875rem;
  margin-top: 0.25rem;
}

.empty-state {
  text-align: center;
  padding: 3rem;
  color: #999;
  font-size: 1rem;
}

/* ── Runs List ── */
.runs-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.run-card {
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 1rem;
  cursor: pointer;
  transition: all 0.2s;
  background: #fafafa;
}

.run-card:hover {
  border-color: #1890ff;
  box-shadow: 0 2px 8px rgba(24, 144, 255, 0.15);
}

.run-card-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.run-id {
  font-family: monospace;
  font-size: 0.875rem;
  font-weight: 600;
  color: #1890ff;
}

.run-tag {
  background: #e6f7ff;
  color: #1890ff;
  padding: 0.125rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
}

.run-card-meta {
  display: flex;
  gap: 1.5rem;
  font-size: 0.8rem;
  color: #888;
  margin-bottom: 0.5rem;
}

.run-card-stats {
  display: flex;
  gap: 1rem;
}

.stat {
  font-size: 0.8rem;
  padding: 0.125rem 0.5rem;
  border-radius: 4px;
}

.stat-total {
  background: #f0f0f0;
  color: #666;
}

.stat-success {
  color: #52c41a;
}

.stat-error {
  color: #ff4d4f;
}

.stat-time {
  color: #888;
}

/* ── Replay View ── */
.replay-header {
  margin-bottom: 1rem;
}

.replay-header-top {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 0.75rem;
}

.replay-header-top h2 {
  font-size: 1rem;
  font-family: monospace;
  color: #333;
}

.replay-summary {
  display: flex;
  gap: 1.5rem;
  font-size: 0.85rem;
  color: #666;
  margin-bottom: 0.75rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid #f0f0f0;
}

.replay-filters {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  flex-wrap: wrap;
}

.filter-select {
  width: auto;
  min-width: 140px;
  padding: 0.375rem 0.5rem;
  font-size: 0.85rem;
}

.filter-info {
  font-size: 0.8rem;
  color: #999;
}

/* ── Chat Groups ── */
.conversations-container {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.chat-group {
  padding: 0;
  overflow: hidden;
}

.chat-group-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  background: #fafafa;
  cursor: pointer;
  user-select: none;
  border-bottom: 1px solid #f0f0f0;
}

.chat-group-header:hover {
  background: #f0f5ff;
}

.chat-id {
  font-family: monospace;
  font-size: 0.85rem;
  font-weight: 600;
  color: #333;
}

.chat-count {
  font-size: 0.8rem;
  color: #888;
}

.expand-icon {
  margin-left: auto;
  font-size: 0.75rem;
  color: #999;
}

.chat-messages {
  padding: 1rem;
}

/* ── Messages ── */
.message-pair {
  margin-bottom: 0.5rem;
}

.message-error {
  background: #fff8f8;
  border-radius: 8px;
  padding: 0.5rem;
}

.msg {
  display: flex;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
  max-width: 85%;
}

.msg-user {
  margin-right: auto;
}

.msg-human {
  margin-left: auto;
  flex-direction: row-reverse;
}

.msg-ai {
  margin-left: auto;
  flex-direction: row-reverse;
}

.msg-avatar {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #f0f0f0;
  font-size: 1.1rem;
  flex-shrink: 0;
}

.msg-body {
  max-width: calc(100% - 48px);
}

.msg-label {
  font-size: 0.75rem;
  color: #999;
  margin-bottom: 0.25rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.msg-human .msg-label,
.msg-ai .msg-label {
  justify-content: flex-end;
}

.msg-meta {
  background: #f5f5f5;
  padding: 0.0625rem 0.375rem;
  border-radius: 3px;
  font-size: 0.7rem;
  color: #999;
}

.msg-status {
  padding: 0.0625rem 0.375rem;
  border-radius: 3px;
  font-size: 0.7rem;
  font-weight: 600;
}

.status-success {
  background: #f6ffed;
  color: #52c41a;
}

.status-error {
  background: #fff2f0;
  color: #ff4d4f;
}

.status-skipped {
  background: #fffbe6;
  color: #faad14;
}

.msg-content {
  display: inline-block;
  padding: 0.625rem 0.875rem;
  border-radius: 12px;
  font-size: 0.9rem;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.msg-user .msg-content {
  background: #e6f7ff;
  color: #333;
  border-top-left-radius: 4px;
}

.msg-human .msg-content {
  background: #f6ffed;
  color: #333;
  border-top-right-radius: 4px;
}

.msg-ai .msg-content {
  background: #f9f0ff;
  color: #333;
  border-top-right-radius: 4px;
}

.msg-ai-error .msg-content {
  background: #fff2f0;
}

.msg-content-error {
  color: #ff4d4f;
}

.msg-content-empty {
  color: #ccc;
  font-style: italic;
}

/* ── Context ── */
.context-toggle {
  margin-bottom: 0.5rem;
}

.btn-link {
  background: none;
  border: none;
  color: #1890ff;
  cursor: pointer;
  font-size: 0.8rem;
  padding: 0.25rem 0;
}

.btn-link:hover {
  text-decoration: underline;
}

.context-messages {
  background: #fafafa;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  padding: 0.75rem;
  margin-top: 0.5rem;
  max-height: 300px;
  overflow-y: auto;
}

.context-msg {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.375rem;
  font-size: 0.8rem;
  line-height: 1.4;
}

.ctx-role {
  flex-shrink: 0;
  font-weight: 600;
  color: #888;
  min-width: 48px;
}

.ctx-content {
  color: #666;
  white-space: pre-wrap;
  word-break: break-word;
}

.ctx-user .ctx-role { color: #1890ff; }
.ctx-seller .ctx-role { color: #52c41a; }
.ctx-system .ctx-role { color: #faad14; }

/* ── Tool Calls ── */
.tool-calls {
  margin-top: 0.5rem;
}

.tool-calls-list {
  margin-top: 0.375rem;
  background: #f5f5f5;
  border-radius: 6px;
  padding: 0.5rem;
}

.tool-call-item {
  margin-bottom: 0.375rem;
}

.tool-name {
  font-family: monospace;
  font-size: 0.8rem;
  font-weight: 600;
  color: #722ed1;
}

.tool-args {
  font-size: 0.75rem;
  color: #666;
  margin: 0.25rem 0 0;
  padding: 0.375rem;
  background: white;
  border-radius: 4px;
  overflow-x: auto;
  max-height: 120px;
  overflow-y: auto;
}

/* ── Divider ── */
.msg-divider {
  border: none;
  border-top: 1px dashed #e8e8e8;
  margin: 1rem 0;
}

/* ── Load More ── */
.load-more {
  text-align: center;
  padding: 1rem;
}
</style>

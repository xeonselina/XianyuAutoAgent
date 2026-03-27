<template>
  <div class="conversation-list">
    <!-- Stats Overview -->
    <div class="stats-grid" v-if="stats">
      <div class="stat-card">
        <div class="stat-value">{{ stats.total_conversations || 0 }}</div>
        <div class="stat-label">总会话数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ stats.total_messages || 0 }}</div>
        <div class="stat-label">总消息数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ stats.ai_replies || 0 }}</div>
        <div class="stat-label">AI 回复数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" :style="{ color: stats.debug_replies > 0 ? '#fa8c16' : '#1890ff' }">
          {{ stats.debug_replies || 0 }}
        </div>
        <div class="stat-label">调试回复数</div>
      </div>
    </div>

    <!-- Conversation Table -->
    <div class="card">
      <div class="card-header">
        <h2 class="card-title">会话列表</h2>
        <button class="btn btn-secondary btn-sm" @click="loadData" :disabled="loading">
          🔄 刷新
        </button>
      </div>

      <!-- Loading -->
      <div class="loading" v-if="loading">
        <div class="spinner"></div>
        <span>加载中...</span>
      </div>

      <!-- Error -->
      <div class="alert alert-error" v-else-if="error">
        ⚠️ {{ error }}
        <button class="btn btn-sm btn-secondary" @click="loadData" style="margin-left: 12px;">重试</button>
      </div>

      <!-- Empty -->
      <div class="empty-state" v-else-if="conversations.length === 0">
        <div class="empty-icon">📭</div>
        <p>暂无聊天记录</p>
      </div>

      <!-- Table -->
      <div class="table-wrapper" v-else>
        <table class="data-table">
          <thead>
            <tr>
              <th>会话 ID</th>
              <th>用户</th>
              <th>消息数</th>
              <th>AI 回复</th>
              <th>调试</th>
              <th>最新消息</th>
              <th>最后活跃</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="conv in conversations"
              :key="conv.chat_id"
              class="clickable-row"
              @click="viewDetail(conv.chat_id)"
            >
              <td>
                <span class="chat-id" :title="conv.chat_id">
                  {{ truncateId(conv.chat_id) }}
                </span>
              </td>
              <td>
                <span class="user-id" :title="conv.user_id">
                  {{ truncateId(conv.user_id) }}
                </span>
              </td>
              <td>
                <span class="badge badge-blue">{{ conv.message_count }}</span>
              </td>
              <td>
                <span class="badge badge-green" v-if="conv.ai_replies > 0">{{ conv.ai_replies }}</span>
                <span class="text-muted" v-else>-</span>
              </td>
              <td>
                <span class="badge badge-orange" v-if="conv.debug_replies > 0">
                  {{ conv.debug_replies }}
                </span>
                <span class="text-muted" v-else>-</span>
              </td>
              <td>
                <div class="latest-message" :title="conv.latest_message">
                  {{ conv.latest_message || '-' }}
                </div>
              </td>
              <td>
                <span class="time-ago">{{ formatTime(conv.last_message_at) }}</span>
              </td>
              <td>
                <button class="btn btn-primary btn-sm" @click.stop="viewDetail(conv.chat_id)">
                  查看
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="pagination" v-if="total > pageSize">
        <button
          class="btn btn-secondary btn-sm"
          :disabled="currentPage <= 1"
          @click="goToPage(currentPage - 1)"
        >
          ◀ 上一页
        </button>
        <span class="page-info">
          第 {{ currentPage }} / {{ totalPages }} 页（共 {{ total }} 条）
        </span>
        <button
          class="btn btn-secondary btn-sm"
          :disabled="currentPage >= totalPages"
          @click="goToPage(currentPage + 1)"
        >
          下一页 ▶
        </button>
      </div>
    </div>
  </div>
</template>

<script>
import api from '../api'

export default {
  name: 'ConversationList',
  data() {
    return {
      conversations: [],
      stats: null,
      loading: false,
      error: null,
      total: 0,
      currentPage: 1,
      pageSize: 20
    }
  },
  computed: {
    totalPages() {
      return Math.ceil(this.total / this.pageSize)
    }
  },
  mounted() {
    this.loadData()
  },
  methods: {
    async loadData() {
      this.loading = true
      this.error = null
      try {
        const [convResult, statsResult] = await Promise.all([
          api.getRecent(this.pageSize, (this.currentPage - 1) * this.pageSize),
          api.getStats()
        ])
        this.conversations = convResult.items || []
        this.total = convResult.total || 0
        this.stats = statsResult
      } catch (e) {
        this.error = e.message || '加载失败'
      } finally {
        this.loading = false
      }
    },
    goToPage(page) {
      this.currentPage = page
      this.loadData()
    },
    viewDetail(chatId) {
      this.$router.push(`/chat/${encodeURIComponent(chatId)}`)
    },
    truncateId(id) {
      if (!id) return '-'
      if (id.length <= 16) return id
      return id.substring(0, 8) + '...' + id.substring(id.length - 6)
    },
    formatTime(timeStr) {
      if (!timeStr) return '-'
      try {
        const date = new Date(timeStr)
        const now = new Date()
        const diff = now - date

        if (diff < 60000) return '刚刚'
        if (diff < 3600000) return Math.floor(diff / 60000) + ' 分钟前'
        if (diff < 86400000) return Math.floor(diff / 3600000) + ' 小时前'
        if (diff < 604800000) return Math.floor(diff / 86400000) + ' 天前'

        return date.toLocaleDateString('zh-CN', {
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit'
        })
      } catch {
        return timeStr
      }
    }
  }
}
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.table-wrapper {
  overflow-x: auto;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.data-table th {
  background: #fafafa;
  padding: 12px 16px;
  text-align: left;
  font-weight: 600;
  color: #666;
  border-bottom: 2px solid #f0f0f0;
  white-space: nowrap;
}

.data-table td {
  padding: 12px 16px;
  border-bottom: 1px solid #f0f0f0;
  vertical-align: middle;
}

.clickable-row {
  cursor: pointer;
  transition: background 0.15s;
}

.clickable-row:hover {
  background: #f5f7fa;
}

.chat-id, .user-id {
  font-family: 'SF Mono', 'Menlo', 'Monaco', monospace;
  font-size: 13px;
  color: #555;
  background: #f5f5f5;
  padding: 2px 6px;
  border-radius: 4px;
}

.latest-message {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #666;
  font-size: 13px;
}

.time-ago {
  font-size: 13px;
  color: #999;
  white-space: nowrap;
}

.text-muted {
  color: #ccc;
}
</style>

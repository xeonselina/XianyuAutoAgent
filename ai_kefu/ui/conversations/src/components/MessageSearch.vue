<template>
  <div class="message-search">
    <!-- Search Form -->
    <div class="card">
      <h2 class="card-title">🔍 搜索聊天记录</h2>

      <div class="search-form">
        <div class="form-row">
          <div class="form-group flex-2">
            <label>关键词</label>
            <input
              type="text"
              v-model="filters.keyword"
              placeholder="搜索消息内容或 AI 回复..."
              @keyup.enter="doSearch"
            />
          </div>
          <div class="form-group">
            <label>消息类型</label>
            <select v-model="filters.message_type">
              <option value="">全部</option>
              <option value="user">用户消息</option>
              <option value="seller">卖家消息</option>
              <option value="system">系统消息</option>
            </select>
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label>开始时间</label>
            <input type="datetime-local" v-model="filters.start_time" />
          </div>
          <div class="form-group">
            <label>结束时间</label>
            <input type="datetime-local" v-model="filters.end_time" />
          </div>
          <div class="form-group">
            <label>AI 回复筛选</label>
            <select v-model="filters.has_agent_response">
              <option :value="null">全部</option>
              <option :value="true">有 AI 回复</option>
              <option :value="false">无 AI 回复</option>
            </select>
          </div>
        </div>

        <div class="form-row form-actions">
          <label class="toggle-label">
            <input type="checkbox" v-model="filters.debug_only" />
            <span>🐛 仅调试回复</span>
          </label>
          <div class="action-buttons">
            <button class="btn btn-secondary" @click="resetFilters">重置</button>
            <button class="btn btn-primary" @click="doSearch" :disabled="searching">
              {{ searching ? '搜索中...' : '搜索' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Results -->
    <div class="card" v-if="hasSearched">
      <div class="card-header">
        <h3 class="card-title">
          搜索结果
          <span class="result-count" v-if="total > 0">（{{ total }} 条）</span>
        </h3>
      </div>

      <!-- Loading -->
      <div class="loading" v-if="searching">
        <div class="spinner"></div>
        <span>搜索中...</span>
      </div>

      <!-- Error -->
      <div class="alert alert-error" v-else-if="error">
        ⚠️ {{ error }}
      </div>

      <!-- Empty -->
      <div class="empty-state" v-else-if="results.length === 0">
        <div class="empty-icon">🔍</div>
        <p>未找到匹配的记录</p>
      </div>

      <!-- Result List -->
      <div class="result-list" v-else>
        <div
          v-for="msg in results"
          :key="msg.id"
          class="result-item"
          @click="viewConversation(msg.chat_id)"
        >
          <div class="result-header">
            <div class="result-tags">
              <span
                class="badge"
                :class="{
                  'badge-blue': msg.message_type === 'user',
                  'badge-green': msg.message_type === 'seller',
                  'badge-purple': msg.message_type === 'system'
                }"
              >
                {{ typeLabel(msg.message_type) }}
              </span>
              <span class="badge badge-orange" v-if="msg.agent_response && msg.agent_response.startsWith('【调试】')">
                🐛 调试
              </span>
              <span class="badge badge-green" v-else-if="msg.agent_response">
                🤖 AI
              </span>
            </div>
            <span class="result-time">{{ formatTime(msg.created_at) }}</span>
          </div>

          <div class="result-body">
            <div class="result-content">
              <strong>消息：</strong>{{ msg.message_content }}
            </div>
            <div class="result-ai" v-if="msg.agent_response">
              <strong>AI 回复：</strong>{{ truncate(msg.agent_response, 150) }}
            </div>
          </div>

          <div class="result-footer">
            <span class="result-chat-id" :title="msg.chat_id">
              会话: {{ truncateId(msg.chat_id) }}
            </span>
            <span class="result-link">查看完整会话 →</span>
          </div>
        </div>
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
  name: 'MessageSearch',
  data() {
    return {
      filters: {
        keyword: '',
        start_time: '',
        end_time: '',
        message_type: '',
        has_agent_response: null,
        debug_only: false
      },
      results: [],
      total: 0,
      currentPage: 1,
      pageSize: 30,
      searching: false,
      error: null,
      hasSearched: false
    }
  },
  computed: {
    totalPages() {
      return Math.ceil(this.total / this.pageSize)
    }
  },
  methods: {
    async doSearch() {
      this.searching = true
      this.error = null
      this.hasSearched = true
      try {
        const params = {
          limit: this.pageSize,
          offset: (this.currentPage - 1) * this.pageSize
        }

        if (this.filters.keyword) params.keyword = this.filters.keyword
        if (this.filters.start_time) params.start_time = this.filters.start_time
        if (this.filters.end_time) params.end_time = this.filters.end_time
        if (this.filters.message_type) params.message_type = this.filters.message_type
        if (this.filters.has_agent_response !== null) params.has_agent_response = this.filters.has_agent_response
        if (this.filters.debug_only) params.debug_only = true

        const result = await api.search(params)
        this.results = result.items || []
        this.total = result.total || 0
      } catch (e) {
        this.error = e.message || '搜索失败'
      } finally {
        this.searching = false
      }
    },
    resetFilters() {
      this.filters = {
        keyword: '',
        start_time: '',
        end_time: '',
        message_type: '',
        has_agent_response: null,
        debug_only: false
      }
      this.results = []
      this.total = 0
      this.currentPage = 1
      this.hasSearched = false
      this.error = null
    },
    goToPage(page) {
      this.currentPage = page
      this.doSearch()
    },
    viewConversation(chatId) {
      this.$router.push(`/chat/${encodeURIComponent(chatId)}`)
    },
    typeLabel(type) {
      const labels = { user: '用户', seller: '卖家', system: '系统' }
      return labels[type] || type
    },
    truncate(text, maxLen) {
      if (!text) return ''
      if (text.length <= maxLen) return text
      return text.substring(0, maxLen) + '...'
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
        return date.toLocaleString('zh-CN', {
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit'
        })
      } catch {
        return timeStr
      }
    }
  }
}
</script>

<style scoped>
/* Search Form */
.search-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.form-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-width: 180px;
}

.form-group.flex-2 {
  flex: 2;
}

.form-group label {
  font-size: 13px;
  font-weight: 500;
  color: #666;
}

.form-actions {
  justify-content: space-between;
  align-items: center;
  padding-top: 8px;
  border-top: 1px solid #f0f0f0;
}

.toggle-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  color: #666;
  cursor: pointer;
  user-select: none;
}

.toggle-label input[type="checkbox"] {
  width: 16px;
  height: 16px;
  accent-color: #fa8c16;
}

.action-buttons {
  display: flex;
  gap: 8px;
}

/* Card header */
.card-header {
  margin-bottom: 16px;
}

.result-count {
  font-size: 14px;
  color: #999;
  font-weight: 400;
}

/* Result List */
.result-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.result-item {
  background: #fafafa;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  padding: 14px 16px;
  cursor: pointer;
  transition: all 0.2s;
}

.result-item:hover {
  background: #f0f7ff;
  border-color: #91d5ff;
  box-shadow: 0 2px 6px rgba(24, 144, 255, 0.1);
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.result-tags {
  display: flex;
  gap: 6px;
}

.result-time {
  font-size: 12px;
  color: #999;
}

.result-body {
  margin-bottom: 8px;
}

.result-content {
  font-size: 14px;
  line-height: 1.5;
  color: #333;
  margin-bottom: 4px;
  word-break: break-word;
}

.result-ai {
  font-size: 13px;
  line-height: 1.5;
  color: #666;
  padding: 6px 10px;
  background: rgba(24, 144, 255, 0.05);
  border-radius: 4px;
  border-left: 3px solid #1890ff;
  margin-top: 6px;
  word-break: break-word;
}

.result-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 8px;
  border-top: 1px solid #f0f0f0;
}

.result-chat-id {
  font-family: 'SF Mono', 'Menlo', monospace;
  font-size: 12px;
  color: #999;
}

.result-link {
  font-size: 13px;
  color: #1890ff;
  font-weight: 500;
}

@media (max-width: 768px) {
  .form-group {
    min-width: 100%;
  }
}
</style>

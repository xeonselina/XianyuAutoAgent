<template>
  <div class="prompt-list">
    <div class="card">
      <div class="list-header">
        <h2>System Prompt 管理</h2>
        <div class="actions">
          <button @click="initDefaults" class="btn btn-secondary" :disabled="loading">
            从代码初始化
          </button>
          <router-link to="/prompts/new" class="btn btn-primary">
            新建版本
          </router-link>
        </div>
      </div>

      <div v-if="alert.show" :class="['alert', `alert-${alert.type}`]">
        {{ alert.message }}
      </div>

      <div class="info-banner">
        <strong>💡 说明：</strong>
        每个 prompt_key 只有一个活跃版本（绿色标签），Agent 运行时使用活跃版本。
        修改后实时生效，无需重启服务。支持模板变量：
        <code>{today_str}</code> <code>{today_date}</code> <code>{current_year}</code> <code>{current_month}</code>
      </div>

      <div v-if="loading" class="loading">
        <div class="spinner"></div>
      </div>

      <div v-else-if="items.length === 0" class="empty-state">
        <p>暂无 System Prompt</p>
        <button @click="initDefaults" class="btn btn-primary">
          从代码初始化默认 Prompt
        </button>
      </div>

      <div v-else class="prompt-cards">
        <div
          v-for="item in items"
          :key="item.id"
          :class="['prompt-card', { active: item.active }]"
        >
          <div class="prompt-card-header">
            <div class="prompt-title-row">
              <h3>{{ item.title }}</h3>
              <span :class="['status-badge', item.active ? 'active' : 'inactive']">
                {{ item.active ? '✅ 活跃' : '未激活' }}
              </span>
            </div>
            <div class="prompt-meta">
              <span class="prompt-key">{{ item.prompt_key }}</span>
              <span class="prompt-date">更新于 {{ formatDate(item.updated_at) }}</span>
            </div>
            <p v-if="item.description" class="prompt-desc">{{ item.description }}</p>
          </div>

          <div class="prompt-preview">
            <pre>{{ truncate(item.content, 300) }}</pre>
          </div>

          <div class="prompt-card-actions">
            <button
              v-if="!item.active"
              @click="activatePrompt(item)"
              class="btn btn-primary btn-sm"
            >
              设为活跃
            </button>
            <router-link
              :to="`/prompts/edit/${item.id}`"
              class="btn btn-secondary btn-sm"
            >
              编辑
            </router-link>
            <button
              @click="confirmDelete(item)"
              class="btn btn-danger btn-sm"
              :disabled="item.active"
              :title="item.active ? '不能删除活跃版本' : ''"
            >
              删除
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Delete Confirmation Modal -->
    <div v-if="deleteModal.show" class="modal-overlay" @click="deleteModal.show = false">
      <div class="modal" @click.stop>
        <h3>确认删除</h3>
        <p>确定要删除 "{{ deleteModal.item?.title }}" 吗？</p>
        <div class="modal-actions">
          <button @click="deleteModal.show = false" class="btn btn-secondary">
            取消
          </button>
          <button @click="deleteItem" class="btn btn-danger">
            删除
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { promptAPI } from '../promptApi'

export default {
  name: 'PromptList',
  data() {
    return {
      items: [],
      loading: false,
      alert: {
        show: false,
        type: 'success',
        message: ''
      },
      deleteModal: {
        show: false,
        item: null
      }
    }
  },
  mounted() {
    this.loadItems()
  },
  methods: {
    async loadItems() {
      this.loading = true
      try {
        const response = await promptAPI.list()
        this.items = response.items
      } catch (error) {
        this.showAlert('error', '加载失败: ' + error.message)
      } finally {
        this.loading = false
      }
    },
    async initDefaults() {
      this.loading = true
      try {
        const response = await promptAPI.initDefaults()
        this.showAlert('success', response.message)
        await this.loadItems()
      } catch (error) {
        this.showAlert('error', '初始化失败: ' + error.message)
      } finally {
        this.loading = false
      }
    },
    async activatePrompt(item) {
      try {
        await promptAPI.activate(item.id)
        this.showAlert('success', `已将 "${item.title}" 设为活跃版本`)
        await this.loadItems()
      } catch (error) {
        this.showAlert('error', '激活失败: ' + error.message)
      }
    },
    confirmDelete(item) {
      this.deleteModal = { show: true, item }
    },
    async deleteItem() {
      try {
        await promptAPI.delete(this.deleteModal.item.id)
        this.showAlert('success', '删除成功')
        this.deleteModal.show = false
        await this.loadItems()
      } catch (error) {
        this.showAlert('error', '删除失败: ' + error.message)
      }
    },
    truncate(text, maxLen) {
      if (!text) return ''
      return text.length > maxLen ? text.substring(0, maxLen) + '...' : text
    },
    formatDate(dateString) {
      if (!dateString) return '-'
      const date = new Date(dateString)
      return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
      })
    },
    showAlert(type, message) {
      this.alert = { show: true, type, message }
      setTimeout(() => { this.alert.show = false }, 5000)
    }
  }
}
</script>

<style scoped>
.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}

.list-header h2 {
  margin: 0;
  color: #333;
}

.actions {
  display: flex;
  gap: 0.5rem;
}

.info-banner {
  background-color: #e6f7ff;
  border: 1px solid #91d5ff;
  border-radius: 4px;
  padding: 0.75rem 1rem;
  margin-bottom: 1.5rem;
  font-size: 0.875rem;
  color: #333;
  line-height: 1.6;
}

.info-banner code {
  background: #f0f0f0;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  font-size: 0.8rem;
}

.prompt-cards {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.prompt-card {
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 1.25rem;
  transition: all 0.3s;
}

.prompt-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.prompt-card.active {
  border-color: #52c41a;
  background-color: #f6ffed;
}

.prompt-card-header {
  margin-bottom: 0.75rem;
}

.prompt-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.25rem;
}

.prompt-title-row h3 {
  margin: 0;
  font-size: 1.1rem;
  color: #333;
}

.prompt-meta {
  display: flex;
  gap: 1rem;
  font-size: 0.8rem;
  color: #999;
  margin-bottom: 0.25rem;
}

.prompt-key {
  background: #f0f0f0;
  padding: 0.1rem 0.5rem;
  border-radius: 3px;
  font-family: monospace;
}

.prompt-desc {
  font-size: 0.875rem;
  color: #666;
  margin: 0.25rem 0 0 0;
}

.prompt-preview {
  background: #fafafa;
  border-radius: 4px;
  padding: 0.75rem;
  margin-bottom: 0.75rem;
  max-height: 200px;
  overflow: hidden;
}

.prompt-preview pre {
  margin: 0;
  white-space: pre-wrap;
  word-wrap: break-word;
  font-size: 0.8rem;
  color: #555;
  font-family: 'SF Mono', 'Fira Code', monospace;
  line-height: 1.5;
}

.prompt-card-actions {
  display: flex;
  gap: 0.5rem;
}

.btn-sm {
  padding: 0.25rem 0.75rem;
  font-size: 0.75rem;
}

.status-badge {
  display: inline-block;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 500;
}

.status-badge.active {
  background-color: #f6ffed;
  color: #52c41a;
  border: 1px solid #b7eb8f;
}

.status-badge.inactive {
  background-color: #f0f0f0;
  color: #999;
}

.empty-state {
  text-align: center;
  padding: 3rem 1rem;
  color: #999;
}

.empty-state p {
  margin-bottom: 1rem;
  font-size: 1.125rem;
}

/* Modal styles */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
}

.modal {
  background: white;
  border-radius: 8px;
  padding: 2rem;
  max-width: 500px;
  width: 90%;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.modal h3 {
  margin-bottom: 1rem;
  color: #333;
}

.modal p {
  margin-bottom: 1.5rem;
  color: #666;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}
</style>

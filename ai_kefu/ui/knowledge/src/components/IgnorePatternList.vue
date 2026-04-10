<template>
  <div class="ignore-patterns">
    <div class="page-header">
      <h2>消息过滤白名单</h2>
      <p class="subtitle">配置不需要 AI 处理的消息（如系统通知、图片、视频等）</p>
    </div>

    <!-- Alert messages -->
    <div v-if="successMessage" class="alert alert-success">
      {{ successMessage }}
    </div>
    <div v-if="errorMessage" class="alert alert-error">
      {{ errorMessage }}
    </div>

    <!-- Add new pattern -->
    <div class="card add-section">
      <h3>添加新规则</h3>
      <div class="add-form">
        <div class="form-row">
          <div class="form-group flex-2">
            <label class="form-label">消息内容（精确匹配）</label>
            <input
              v-model="newPattern.pattern"
              class="form-input"
              placeholder="例如：[图片]、[视频]、[买家已确认退回金额，交易成功]"
              @keyup.enter="addPattern"
            />
          </div>
          <div class="form-group flex-1">
            <label class="form-label">描述（可选）</label>
            <input
              v-model="newPattern.description"
              class="form-input"
              placeholder="例如：图片消息"
              @keyup.enter="addPattern"
            />
          </div>
          <div class="form-group btn-group">
            <button class="btn btn-primary" @click="addPattern" :disabled="!newPattern.pattern.trim() || adding">
              {{ adding ? '添加中...' : '添加' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Pattern list -->
    <div class="card">
      <div class="list-header">
        <h3>已配置的规则 ({{ total }})</h3>
        <div class="filter-group">
          <label>
            <input type="checkbox" v-model="showActiveOnly" @change="loadPatterns" />
            仅显示启用
          </label>
        </div>
      </div>

      <div v-if="loading" class="loading">
        <div class="spinner"></div>
      </div>

      <div v-else-if="patterns.length === 0" class="empty-state">
        <p>暂无过滤规则</p>
      </div>

      <table v-else class="pattern-table">
        <thead>
          <tr>
            <th class="col-pattern">消息内容</th>
            <th class="col-desc">描述</th>
            <th class="col-status">状态</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in patterns" :key="p.id" :class="{ inactive: !p.active }">
            <td class="col-pattern">
              <template v-if="editingId === p.id">
                <input v-model="editForm.pattern" class="form-input inline-edit" />
              </template>
              <template v-else>
                <code>{{ p.pattern }}</code>
              </template>
            </td>
            <td class="col-desc">
              <template v-if="editingId === p.id">
                <input v-model="editForm.description" class="form-input inline-edit" placeholder="描述" />
              </template>
              <template v-else>
                {{ p.description || '-' }}
              </template>
            </td>
            <td class="col-status">
              <span class="status-badge" :class="p.active ? 'active' : 'disabled'" @click="togglePattern(p)">
                {{ p.active ? '启用' : '禁用' }}
              </span>
            </td>
            <td class="col-actions">
              <template v-if="editingId === p.id">
                <button class="btn btn-primary btn-sm" @click="saveEdit(p.id)">保存</button>
                <button class="btn btn-secondary btn-sm" @click="cancelEdit">取消</button>
              </template>
              <template v-else>
                <button class="btn btn-secondary btn-sm" @click="startEdit(p)">编辑</button>
                <button class="btn btn-danger btn-sm" @click="deletePattern(p)">删除</button>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script>
import {
  listIgnorePatterns,
  createIgnorePattern,
  updateIgnorePattern,
  deleteIgnorePattern,
  toggleIgnorePattern
} from '../ignorePatternApi.js'

export default {
  name: 'IgnorePatternList',
  data() {
    return {
      patterns: [],
      total: 0,
      loading: true,
      adding: false,
      showActiveOnly: false,
      successMessage: '',
      errorMessage: '',
      newPattern: {
        pattern: '',
        description: ''
      },
      editingId: null,
      editForm: {
        pattern: '',
        description: ''
      }
    }
  },
  async mounted() {
    await this.loadPatterns()
  },
  methods: {
    async loadPatterns() {
      this.loading = true
      this.clearMessages()
      try {
        const data = await listIgnorePatterns(this.showActiveOnly)
        this.patterns = data.items
        this.total = data.total
      } catch (e) {
        this.errorMessage = `加载失败: ${e.message}`
      } finally {
        this.loading = false
      }
    },

    async addPattern() {
      const pattern = this.newPattern.pattern.trim()
      if (!pattern) return

      this.adding = true
      this.clearMessages()
      try {
        await createIgnorePattern({
          pattern,
          description: this.newPattern.description.trim() || null,
          active: true
        })
        this.successMessage = `已添加: ${pattern}`
        this.newPattern.pattern = ''
        this.newPattern.description = ''
        await this.loadPatterns()
      } catch (e) {
        this.errorMessage = `添加失败: ${e.message}`
      } finally {
        this.adding = false
      }
    },

    async togglePattern(p) {
      this.clearMessages()
      try {
        const result = await toggleIgnorePattern(p.id)
        p.active = result.active
        this.successMessage = result.message
      } catch (e) {
        this.errorMessage = `切换失败: ${e.message}`
      }
    },

    startEdit(p) {
      this.editingId = p.id
      this.editForm.pattern = p.pattern
      this.editForm.description = p.description || ''
    },

    cancelEdit() {
      this.editingId = null
    },

    async saveEdit(id) {
      this.clearMessages()
      try {
        await updateIgnorePattern(id, {
          pattern: this.editForm.pattern.trim(),
          description: this.editForm.description.trim() || null
        })
        this.editingId = null
        this.successMessage = '已更新'
        await this.loadPatterns()
      } catch (e) {
        this.errorMessage = `更新失败: ${e.message}`
      }
    },

    async deletePattern(p) {
      if (!confirm(`确认删除规则 "${p.pattern}" ？`)) return

      this.clearMessages()
      try {
        await deleteIgnorePattern(p.id)
        this.successMessage = `已删除: ${p.pattern}`
        await this.loadPatterns()
      } catch (e) {
        this.errorMessage = `删除失败: ${e.message}`
      }
    },

    clearMessages() {
      this.successMessage = ''
      this.errorMessage = ''
    }
  }
}
</script>

<style scoped>
.ignore-patterns {
  max-width: 960px;
}

.page-header {
  margin-bottom: 1.5rem;
}

.page-header h2 {
  margin-bottom: 0.25rem;
  color: #333;
}

.subtitle {
  color: #888;
  font-size: 0.875rem;
}

.add-section {
  margin-bottom: 1.5rem;
}

.add-section h3 {
  margin-bottom: 1rem;
  font-size: 1rem;
  color: #555;
}

.form-row {
  display: flex;
  gap: 1rem;
  align-items: flex-end;
}

.flex-2 {
  flex: 2;
}

.flex-1 {
  flex: 1;
}

.btn-group {
  display: flex;
  align-items: flex-end;
  padding-bottom: 0;
}

.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.list-header h3 {
  font-size: 1rem;
  color: #555;
}

.filter-group label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
  color: #666;
  cursor: pointer;
}

.pattern-table {
  width: 100%;
  border-collapse: collapse;
}

.pattern-table th,
.pattern-table td {
  padding: 0.75rem;
  text-align: left;
  border-bottom: 1px solid #f0f0f0;
}

.pattern-table th {
  font-weight: 500;
  color: #999;
  font-size: 0.8rem;
  text-transform: uppercase;
}

.pattern-table tr.inactive {
  opacity: 0.5;
}

.pattern-table code {
  background: #f5f5f5;
  padding: 0.2rem 0.5rem;
  border-radius: 3px;
  font-size: 0.875rem;
  color: #d63384;
}

.col-pattern {
  width: 40%;
}

.col-desc {
  width: 25%;
}

.col-status {
  width: 10%;
}

.col-actions {
  width: 25%;
  white-space: nowrap;
}

.col-actions .btn {
  margin-right: 0.5rem;
}

.status-badge {
  display: inline-block;
  padding: 0.2rem 0.6rem;
  border-radius: 12px;
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.2s;
}

.status-badge.active {
  background: #f6ffed;
  color: #52c41a;
  border: 1px solid #b7eb8f;
}

.status-badge.disabled {
  background: #fff2f0;
  color: #ff4d4f;
  border: 1px solid #ffccc7;
}

.status-badge:hover {
  opacity: 0.8;
}

.btn-sm {
  padding: 0.25rem 0.75rem;
  font-size: 0.8rem;
}

.inline-edit {
  padding: 0.25rem 0.5rem;
  font-size: 0.875rem;
}

.empty-state {
  text-align: center;
  padding: 2rem;
  color: #999;
}
</style>

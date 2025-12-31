<template>
  <div class="knowledge-list">
    <div class="card">
      <div class="list-header">
        <h2>知识库列表</h2>
        <div class="actions">
          <button @click="initDefaults" class="btn btn-secondary" :disabled="loading">
            初始化默认数据
          </button>
          <button @click="exportKnowledge" class="btn btn-secondary" :disabled="loading">
            导出知识库
          </button>
          <button @click="showImportModal = true" class="btn btn-secondary">
            批量导入
          </button>
          <router-link to="/new" class="btn btn-primary">
            新建知识
          </router-link>
        </div>
      </div>

      <div v-if="alert.show" :class="['alert', `alert-${alert.type}`]">
        {{ alert.message }}
      </div>

      <div class="search-bar">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索标题或内容..."
          class="form-input"
          @input="onSearch"
        />
      </div>

      <div v-if="loading" class="loading">
        <div class="spinner"></div>
      </div>

      <div v-else-if="filteredItems.length === 0" class="empty-state">
        <p>暂无知识条目</p>
        <button @click="initDefaults" class="btn btn-primary">
          初始化默认知识
        </button>
      </div>

      <div v-else class="table-container">
        <table class="knowledge-table">
          <thead>
            <tr>
              <th>标题</th>
              <th>分类</th>
              <th>标签</th>
              <th>优先级</th>
              <th>状态</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in filteredItems" :key="item.id">
              <td>
                <div class="title-cell">{{ item.title }}</div>
              </td>
              <td>
                <span v-if="item.category" class="category-badge">
                  {{ item.category }}
                </span>
              </td>
              <td>
                <div class="tags">
                  <span v-for="tag in item.tags" :key="tag" class="tag">
                    {{ tag }}
                  </span>
                </div>
              </td>
              <td>
                <span :class="['priority-badge', `priority-${item.priority}`]">
                  {{ item.priority }}
                </span>
              </td>
              <td>
                <span :class="['status-badge', item.active ? 'active' : 'inactive']">
                  {{ item.active ? '启用' : '禁用' }}
                </span>
              </td>
              <td>{{ formatDate(item.created_at) }}</td>
              <td>
                <div class="action-buttons">
                  <router-link
                    :to="`/edit/${item.id}`"
                    class="btn btn-sm btn-secondary"
                  >
                    编辑
                  </router-link>
                  <button
                    @click="confirmDelete(item)"
                    class="btn btn-sm btn-danger"
                  >
                    删除
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="total > limit" class="pagination">
        <button
          @click="previousPage"
          :disabled="offset === 0"
          class="btn btn-secondary"
        >
          上一页
        </button>
        <span class="page-info">
          第 {{ currentPage }} / {{ totalPages }} 页 (共 {{ total }} 条)
        </span>
        <button
          @click="nextPage"
          :disabled="offset + limit >= total"
          class="btn btn-secondary"
        >
          下一页
        </button>
      </div>
    </div>

    <!-- Delete Confirmation Modal -->
    <div v-if="deleteModal.show" class="modal-overlay" @click="deleteModal.show = false">
      <div class="modal" @click.stop>
        <h3>确认删除</h3>
        <p>确定要删除知识条目 "{{ deleteModal.item?.title }}" 吗？</p>
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

    <!-- Bulk Import Modal -->
    <div v-if="showImportModal" class="modal-overlay" @click="showImportModal = false">
      <div class="modal large" @click.stop>
        <BulkImport @close="showImportModal = false" @imported="onImported" />
      </div>
    </div>
  </div>
</template>

<script>
import { knowledgeAPI } from '../api'
import BulkImport from './BulkImport.vue'

export default {
  name: 'KnowledgeList',
  components: {
    BulkImport
  },
  data() {
    return {
      items: [],
      total: 0,
      offset: 0,
      limit: 20,
      loading: false,
      searchQuery: '',
      alert: {
        show: false,
        type: 'success',
        message: ''
      },
      deleteModal: {
        show: false,
        item: null
      },
      showImportModal: false
    }
  },
  computed: {
    filteredItems() {
      if (!this.searchQuery) return this.items

      const query = this.searchQuery.toLowerCase()
      return this.items.filter(item =>
        item.title.toLowerCase().includes(query) ||
        item.content.toLowerCase().includes(query) ||
        (item.category && item.category.toLowerCase().includes(query))
      )
    },
    currentPage() {
      return Math.floor(this.offset / this.limit) + 1
    },
    totalPages() {
      return Math.ceil(this.total / this.limit)
    }
  },
  mounted() {
    this.loadItems()
  },
  methods: {
    async loadItems() {
      this.loading = true
      try {
        const response = await knowledgeAPI.list(this.offset, this.limit, true)
        this.items = response.items
        this.total = response.total
      } catch (error) {
        this.showAlert('error', '加载失败: ' + error.message)
      } finally {
        this.loading = false
      }
    },
    async initDefaults() {
      this.loading = true
      try {
        const response = await knowledgeAPI.initDefaults()
        this.showAlert('success', response.message)
        await this.loadItems()
      } catch (error) {
        this.showAlert('error', '初始化失败: ' + error.message)
      } finally {
        this.loading = false
      }
    },
    async exportKnowledge() {
      try {
        await knowledgeAPI.export(true)
        this.showAlert('success', '导出成功')
      } catch (error) {
        this.showAlert('error', '导出失败: ' + error.message)
      }
    },
    confirmDelete(item) {
      this.deleteModal = {
        show: true,
        item
      }
    },
    async deleteItem() {
      try {
        await knowledgeAPI.delete(this.deleteModal.item.id)
        this.showAlert('success', '删除成功')
        this.deleteModal.show = false
        await this.loadItems()
      } catch (error) {
        this.showAlert('error', '删除失败: ' + error.message)
      }
    },
    onImported() {
      this.showImportModal = false
      this.showAlert('success', '导入成功')
      this.loadItems()
    },
    previousPage() {
      if (this.offset > 0) {
        this.offset -= this.limit
        this.loadItems()
      }
    },
    nextPage() {
      if (this.offset + this.limit < this.total) {
        this.offset += this.limit
        this.loadItems()
      }
    },
    onSearch() {
      // Client-side filtering in computed property
    },
    formatDate(dateString) {
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
      setTimeout(() => {
        this.alert.show = false
      }, 5000)
    }
  }
}
</script>

<style scoped>
.knowledge-list {
  width: 100%;
}

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

.search-bar {
  margin-bottom: 1.5rem;
}

.search-bar input {
  max-width: 400px;
}

.table-container {
  overflow-x: auto;
}

.knowledge-table {
  width: 100%;
  border-collapse: collapse;
}

.knowledge-table th,
.knowledge-table td {
  padding: 0.75rem;
  text-align: left;
  border-bottom: 1px solid #f0f0f0;
}

.knowledge-table th {
  background-color: #fafafa;
  font-weight: 600;
  color: #666;
}

.knowledge-table tr:hover {
  background-color: #f5f5f5;
}

.title-cell {
  font-weight: 500;
  color: #333;
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.category-badge {
  display: inline-block;
  padding: 0.25rem 0.5rem;
  background-color: #e6f7ff;
  color: #1890ff;
  border-radius: 4px;
  font-size: 0.75rem;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}

.tag {
  display: inline-block;
  padding: 0.25rem 0.5rem;
  background-color: #f0f0f0;
  color: #666;
  border-radius: 4px;
  font-size: 0.75rem;
}

.priority-badge {
  display: inline-block;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
}

.priority-0,
.priority-1,
.priority-2,
.priority-3,
.priority-4,
.priority-5 {
  background-color: #f0f0f0;
  color: #666;
}

.priority-6,
.priority-7,
.priority-8 {
  background-color: #fff7e6;
  color: #fa8c16;
}

.priority-9,
.priority-10 {
  background-color: #fff2f0;
  color: #ff4d4f;
}

.status-badge {
  display: inline-block;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
}

.status-badge.active {
  background-color: #f6ffed;
  color: #52c41a;
}

.status-badge.inactive {
  background-color: #f0f0f0;
  color: #999;
}

.action-buttons {
  display: flex;
  gap: 0.5rem;
}

.btn-sm {
  padding: 0.25rem 0.75rem;
  font-size: 0.75rem;
}

.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 1rem;
  margin-top: 1.5rem;
}

.page-info {
  color: #666;
  font-size: 0.875rem;
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

.modal.large {
  max-width: 800px;
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

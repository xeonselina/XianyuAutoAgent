<template>
  <div class="knowledge-form">
    <div class="card">
      <h2>{{ isEdit ? '编辑知识条目' : '新建知识条目' }}</h2>

      <div v-if="alert.show" :class="['alert', `alert-${alert.type}`]">
        {{ alert.message }}
      </div>

      <div v-if="loading" class="loading">
        <div class="spinner"></div>
      </div>

      <form v-else @submit.prevent="handleSubmit">
        <div class="form-group">
          <label class="form-label">
            标题 <span class="required">*</span>
          </label>
          <input
            v-model="form.title"
            type="text"
            class="form-input"
            placeholder="请输入知识标题"
            required
            maxlength="200"
          />
        </div>

        <div class="form-group">
          <label class="form-label">
            内容 <span class="required">*</span>
          </label>
          <textarea
            v-model="form.content"
            class="form-textarea"
            placeholder="请输入知识内容"
            required
            rows="10"
            maxlength="10000"
          ></textarea>
          <div class="char-count">
            {{ form.content.length }} / 10000
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label class="form-label">分类</label>
            <select v-model="form.category" class="form-select">
              <option value="">请选择分类</option>
              <option value="售后服务">售后服务</option>
              <option value="物流配送">物流配送</option>
              <option value="会员服务">会员服务</option>
              <option value="支付相关">支付相关</option>
              <option value="优惠活动">优惠活动</option>
              <option value="其他">其他</option>
            </select>
          </div>

          <div class="form-group">
            <label class="form-label">优先级 (0-100)</label>
            <input
              v-model.number="form.priority"
              type="number"
              class="form-input"
              min="0"
              max="100"
            />
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">标签 (逗号分隔)</label>
          <input
            v-model="tagsInput"
            type="text"
            class="form-input"
            placeholder="例如: 退款, 售后, 政策"
          />
          <div v-if="form.tags.length" class="tags-preview">
            <span v-for="tag in form.tags" :key="tag" class="tag">
              {{ tag }}
              <button
                type="button"
                @click="removeTag(tag)"
                class="tag-remove"
              >
                ×
              </button>
            </span>
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">来源</label>
          <input
            v-model="form.source"
            type="text"
            class="form-input"
            placeholder="例如: 官方文档, 客服整理"
            maxlength="200"
          />
        </div>

        <div class="form-group">
          <label class="form-checkbox">
            <input v-model="form.active" type="checkbox" />
            <span>启用此知识条目</span>
          </label>
        </div>

        <div class="form-actions">
          <button
            type="button"
            @click="goBack"
            class="btn btn-secondary"
          >
            取消
          </button>
          <button
            type="submit"
            class="btn btn-primary"
            :disabled="submitting"
          >
            {{ submitting ? '保存中...' : (isEdit ? '更新' : '创建') }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script>
import { knowledgeAPI } from '../api'

export default {
  name: 'KnowledgeForm',
  props: {
    id: {
      type: String,
      default: null
    }
  },
  data() {
    return {
      form: {
        title: '',
        content: '',
        category: '',
        tags: [],
        source: '',
        priority: 0,
        active: true
      },
      tagsInput: '',
      loading: false,
      submitting: false,
      alert: {
        show: false,
        type: 'success',
        message: ''
      }
    }
  },
  computed: {
    isEdit() {
      return !!this.id
    }
  },
  watch: {
    tagsInput(newValue) {
      if (newValue) {
        this.form.tags = newValue
          .split(',')
          .map(tag => tag.trim())
          .filter(tag => tag.length > 0)
      } else {
        this.form.tags = []
      }
    }
  },
  mounted() {
    if (this.isEdit) {
      this.loadItem()
    }
  },
  methods: {
    async loadItem() {
      this.loading = true
      try {
        const item = await knowledgeAPI.get(this.id)
        this.form = {
          title: item.title,
          content: item.content,
          category: item.category || '',
          tags: item.tags || [],
          source: item.source || '',
          priority: item.priority,
          active: item.active
        }
        this.tagsInput = this.form.tags.join(', ')
      } catch (error) {
        this.showAlert('error', '加载失败: ' + error.message)
      } finally {
        this.loading = false
      }
    },
    async handleSubmit() {
      if (!this.validateForm()) {
        return
      }

      this.submitting = true
      try {
        const data = {
          title: this.form.title,
          content: this.form.content,
          category: this.form.category || null,
          tags: this.form.tags,
          source: this.form.source || null,
          priority: this.form.priority,
          active: this.form.active
        }

        if (this.isEdit) {
          await knowledgeAPI.update(this.id, data)
          this.showAlert('success', '更新成功')
        } else {
          await knowledgeAPI.create(data)
          this.showAlert('success', '创建成功')
        }

        setTimeout(() => {
          this.$router.push('/')
        }, 1000)
      } catch (error) {
        this.showAlert('error', '保存失败: ' + error.message)
      } finally {
        this.submitting = false
      }
    },
    validateForm() {
      if (!this.form.title.trim()) {
        this.showAlert('error', '请输入标题')
        return false
      }

      if (!this.form.content.trim()) {
        this.showAlert('error', '请输入内容')
        return false
      }

      if (this.form.content.length < 10) {
        this.showAlert('error', '内容至少需要10个字符')
        return false
      }

      if (this.form.priority < 0 || this.form.priority > 100) {
        this.showAlert('error', '优先级必须在0-100之间')
        return false
      }

      return true
    },
    removeTag(tag) {
      this.form.tags = this.form.tags.filter(t => t !== tag)
      this.tagsInput = this.form.tags.join(', ')
    },
    goBack() {
      this.$router.push('/')
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
.knowledge-form {
  max-width: 800px;
}

.knowledge-form h2 {
  margin-bottom: 1.5rem;
  color: #333;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

.required {
  color: #ff4d4f;
}

.char-count {
  text-align: right;
  font-size: 0.75rem;
  color: #999;
  margin-top: 0.25rem;
}

.tags-preview {
  margin-top: 0.5rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.5rem;
  background-color: #f0f0f0;
  color: #666;
  border-radius: 4px;
  font-size: 0.75rem;
}

.tag-remove {
  background: none;
  border: none;
  color: #999;
  cursor: pointer;
  font-size: 1.25rem;
  line-height: 1;
  padding: 0;
  margin-left: 0.25rem;
}

.tag-remove:hover {
  color: #ff4d4f;
}

.form-checkbox {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
}

.form-checkbox input[type="checkbox"] {
  width: auto;
  cursor: pointer;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 2rem;
  padding-top: 1.5rem;
  border-top: 1px solid #f0f0f0;
}

@media (max-width: 768px) {
  .form-row {
    grid-template-columns: 1fr;
  }
}
</style>

<template>
  <div class="prompt-editor">
    <div class="card">
      <h2>{{ isEdit ? '编辑 System Prompt' : '新建 System Prompt' }}</h2>

      <div v-if="alert.show" :class="['alert', `alert-${alert.type}`]">
        {{ alert.message }}
      </div>

      <div v-if="loading" class="loading">
        <div class="spinner"></div>
      </div>

      <form v-else @submit.prevent="handleSubmit">
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">
              Prompt Key <span class="required">*</span>
            </label>
            <input
              v-model="form.prompt_key"
              type="text"
              class="form-input"
              placeholder="例如: rental_system"
              required
              maxlength="100"
              :disabled="isEdit"
            />
            <div class="form-hint">用于标识此 Prompt，同一 key 可有多个版本</div>
          </div>

          <div class="form-group">
            <label class="form-label">
              标题 <span class="required">*</span>
            </label>
            <input
              v-model="form.title"
              type="text"
              class="form-input"
              placeholder="例如: 手机租赁客服 System Prompt"
              required
              maxlength="200"
            />
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">描述</label>
          <input
            v-model="form.description"
            type="text"
            class="form-input"
            placeholder="描述此 Prompt 的用途和特点"
            maxlength="500"
          />
        </div>

        <div class="form-group">
          <label class="form-label">
            Prompt 内容 <span class="required">*</span>
          </label>
          <div class="editor-toolbar">
            <span class="char-count">{{ form.content.length }} 字符</span>
            <div class="toolbar-actions">
              <button type="button" @click="insertVariable('{today_str}')" class="btn-toolbar" title="插入今日日期(中文)">
                {today_str}
              </button>
              <button type="button" @click="insertVariable('{today_date}')" class="btn-toolbar" title="插入今日日期(ISO)">
                {today_date}
              </button>
              <button type="button" @click="insertVariable('{current_year}')" class="btn-toolbar" title="插入当前年份">
                {current_year}
              </button>
              <button type="button" @click="insertVariable('{current_month}')" class="btn-toolbar" title="插入当前月份">
                {current_month}
              </button>
            </div>
          </div>
          <textarea
            ref="contentEditor"
            v-model="form.content"
            class="form-textarea prompt-textarea"
            placeholder="在此编写 System Prompt 内容...

支持模板变量：
{today_str} → 2026年03月25日
{today_date} → 2026-03-25
{current_year} → 2026
{current_month} → 3"
            required
            rows="25"
          ></textarea>
        </div>

        <div class="form-group">
          <label class="form-checkbox">
            <input v-model="form.active" type="checkbox" />
            <span>设为活跃版本（会自动停用同 key 的其他版本）</span>
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
import { promptAPI } from '../promptApi'

export default {
  name: 'PromptEditor',
  props: {
    id: {
      type: String,
      default: null
    }
  },
  data() {
    return {
      form: {
        prompt_key: 'rental_system',
        title: '',
        content: '',
        description: '',
        active: false
      },
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
  mounted() {
    if (this.isEdit) {
      this.loadItem()
    }
  },
  methods: {
    async loadItem() {
      this.loading = true
      try {
        const item = await promptAPI.get(this.id)
        this.form = {
          prompt_key: item.prompt_key,
          title: item.title,
          content: item.content,
          description: item.description || '',
          active: item.active
        }
      } catch (error) {
        this.showAlert('error', '加载失败: ' + error.message)
      } finally {
        this.loading = false
      }
    },
    async handleSubmit() {
      if (!this.validateForm()) return

      this.submitting = true
      try {
        const data = {
          prompt_key: this.form.prompt_key,
          title: this.form.title,
          content: this.form.content,
          description: this.form.description || null,
          active: this.form.active
        }

        if (this.isEdit) {
          // Don't send prompt_key in update
          delete data.prompt_key
          await promptAPI.update(this.id, data)
          this.showAlert('success', '更新成功，已实时生效！')
        } else {
          await promptAPI.create(data)
          this.showAlert('success', '创建成功')
        }

        setTimeout(() => {
          this.$router.push('/prompts')
        }, 1000)
      } catch (error) {
        this.showAlert('error', '保存失败: ' + error.message)
      } finally {
        this.submitting = false
      }
    },
    validateForm() {
      if (!this.form.prompt_key.trim()) {
        this.showAlert('error', '请输入 Prompt Key')
        return false
      }
      if (!this.form.title.trim()) {
        this.showAlert('error', '请输入标题')
        return false
      }
      if (!this.form.content.trim()) {
        this.showAlert('error', '请输入 Prompt 内容')
        return false
      }
      return true
    },
    insertVariable(variable) {
      const textarea = this.$refs.contentEditor
      const start = textarea.selectionStart
      const end = textarea.selectionEnd
      const text = this.form.content
      this.form.content = text.substring(0, start) + variable + text.substring(end)
      // Restore cursor position
      this.$nextTick(() => {
        textarea.focus()
        textarea.selectionStart = textarea.selectionEnd = start + variable.length
      })
    },
    goBack() {
      this.$router.push('/prompts')
    },
    showAlert(type, message) {
      this.alert = { show: true, type, message }
      setTimeout(() => { this.alert.show = false }, 5000)
    }
  }
}
</script>

<style scoped>
.prompt-editor {
  max-width: 960px;
}

.prompt-editor h2 {
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

.form-hint {
  font-size: 0.75rem;
  color: #999;
  margin-top: 0.25rem;
}

.editor-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.char-count {
  font-size: 0.8rem;
  color: #999;
}

.toolbar-actions {
  display: flex;
  gap: 0.25rem;
}

.btn-toolbar {
  padding: 0.2rem 0.5rem;
  border: 1px solid #d9d9d9;
  background: #fafafa;
  border-radius: 3px;
  font-size: 0.7rem;
  font-family: monospace;
  cursor: pointer;
  color: #666;
  transition: all 0.2s;
}

.btn-toolbar:hover {
  background: #e6f7ff;
  border-color: #1890ff;
  color: #1890ff;
}

.prompt-textarea {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 0.875rem;
  line-height: 1.6;
  min-height: 500px;
  resize: vertical;
  tab-size: 2;
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

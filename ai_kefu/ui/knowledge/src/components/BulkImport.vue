<template>
  <div class="bulk-import">
    <h3>批量导入知识条目</h3>

    <div v-if="alert.show" :class="['alert', `alert-${alert.type}`]">
      {{ alert.message }}
    </div>

    <div class="import-steps">
      <div class="step" :class="{ active: step === 1 }">
        <div class="step-number">1</div>
        <div class="step-label">选择文件</div>
      </div>
      <div class="step" :class="{ active: step === 2 }">
        <div class="step-number">2</div>
        <div class="step-label">预览数据</div>
      </div>
      <div class="step" :class="{ active: step === 3 }">
        <div class="step-number">3</div>
        <div class="step-label">导入结果</div>
      </div>
    </div>

    <!-- Step 1: File Upload -->
    <div v-if="step === 1" class="upload-section">
      <div class="file-upload">
        <input
          ref="fileInput"
          type="file"
          accept=".json"
          @change="handleFileSelect"
          style="display: none"
        />
        <button
          @click="$refs.fileInput.click()"
          class="btn btn-primary btn-large"
        >
          选择 JSON 文件
        </button>
        <p class="help-text">
          请选择包含知识条目的 JSON 文件
        </p>
      </div>

      <div class="format-info">
        <h4>文件格式要求</h4>
        <pre><code>{
  "entries": [
    {
      "kb_id": "kb_custom_001",
      "title": "知识标题",
      "content": "知识内容...",
      "category": "分类名称",
      "tags": ["标签1", "标签2"],
      "source": "来源",
      "priority": 5,
      "active": true
    }
  ]
}</code></pre>
      </div>
    </div>

    <!-- Step 2: Preview -->
    <div v-if="step === 2" class="preview-section">
      <div class="preview-summary">
        <p>共 <strong>{{ entries.length }}</strong> 条知识条目待导入</p>
      </div>

      <div class="preview-options">
        <label class="form-checkbox">
          <input v-model="overwriteExisting" type="checkbox" />
          <span>覆盖已存在的条目</span>
        </label>
      </div>

      <div class="preview-list">
        <div
          v-for="(entry, index) in entries.slice(0, 10)"
          :key="index"
          class="preview-item"
        >
          <div class="preview-item-header">
            <strong>{{ entry.title }}</strong>
            <span class="badge">{{ entry.kb_id }}</span>
          </div>
          <div class="preview-item-content">
            {{ entry.content.substring(0, 100) }}...
          </div>
          <div class="preview-item-meta">
            <span v-if="entry.category" class="meta-item">
              分类: {{ entry.category }}
            </span>
            <span class="meta-item">
              优先级: {{ entry.priority }}
            </span>
          </div>
        </div>
        <p v-if="entries.length > 10" class="more-items">
          还有 {{ entries.length - 10 }} 条未显示...
        </p>
      </div>

      <div class="preview-actions">
        <button @click="step = 1" class="btn btn-secondary">
          重新选择
        </button>
        <button
          @click="performImport"
          class="btn btn-primary"
          :disabled="importing"
        >
          {{ importing ? '导入中...' : '开始导入' }}
        </button>
      </div>
    </div>

    <!-- Step 3: Results -->
    <div v-if="step === 3" class="results-section">
      <div class="result-summary">
        <div class="result-stat success">
          <div class="stat-number">{{ importResult.imported }}</div>
          <div class="stat-label">成功导入</div>
        </div>
        <div class="result-stat skipped">
          <div class="stat-number">{{ importResult.skipped }}</div>
          <div class="stat-label">已跳过</div>
        </div>
        <div class="result-stat error">
          <div class="stat-number">{{ importResult.errors.length }}</div>
          <div class="stat-label">失败</div>
        </div>
      </div>

      <div v-if="importResult.errors.length > 0" class="error-list">
        <h4>错误详情</h4>
        <div
          v-for="(error, index) in importResult.errors"
          :key="index"
          class="error-item"
        >
          {{ error }}
        </div>
      </div>

      <div class="result-actions">
        <button @click="reset" class="btn btn-secondary">
          继续导入
        </button>
        <button @click="$emit('close')" class="btn btn-primary">
          完成
        </button>
      </div>
    </div>
  </div>
</template>

<script>
import { knowledgeAPI } from '../api'

export default {
  name: 'BulkImport',
  emits: ['close', 'imported'],
  data() {
    return {
      step: 1,
      entries: [],
      overwriteExisting: false,
      importing: false,
      importResult: {
        imported: 0,
        skipped: 0,
        errors: []
      },
      alert: {
        show: false,
        type: 'success',
        message: ''
      }
    }
  },
  methods: {
    handleFileSelect(event) {
      const file = event.target.files[0]
      if (!file) return

      const reader = new FileReader()
      reader.onload = (e) => {
        try {
          const data = JSON.parse(e.target.result)

          // Support both formats: {entries: [...]} and direct array [...]
          if (Array.isArray(data)) {
            this.entries = data
          } else if (data.entries && Array.isArray(data.entries)) {
            this.entries = data.entries
          } else {
            throw new Error('Invalid JSON format')
          }

          if (this.entries.length === 0) {
            this.showAlert('error', '文件中没有找到知识条目')
            return
          }

          // Validate entries
          const isValid = this.validateEntries()
          if (!isValid) {
            return
          }

          this.step = 2
        } catch (error) {
          this.showAlert('error', '文件解析失败: ' + error.message)
        }
      }
      reader.readAsText(file)
    },
    validateEntries() {
      for (let i = 0; i < this.entries.length; i++) {
        const entry = this.entries[i]

        if (!entry.kb_id) {
          this.showAlert('error', `第 ${i + 1} 条记录缺少 kb_id`)
          return false
        }

        if (!entry.title || entry.title.length < 1) {
          this.showAlert('error', `第 ${i + 1} 条记录的标题无效`)
          return false
        }

        if (!entry.content || entry.content.length < 10) {
          this.showAlert('error', `第 ${i + 1} 条记录的内容至少需要10个字符`)
          return false
        }
      }

      return true
    },
    async performImport() {
      this.importing = true
      try {
        const result = await knowledgeAPI.bulkImport(
          this.entries,
          this.overwriteExisting
        )

        this.importResult = result
        this.step = 3

        if (result.imported > 0) {
          this.$emit('imported')
        }
      } catch (error) {
        this.showAlert('error', '导入失败: ' + error.message)
      } finally {
        this.importing = false
      }
    },
    reset() {
      this.step = 1
      this.entries = []
      this.overwriteExisting = false
      this.importResult = {
        imported: 0,
        skipped: 0,
        errors: []
      }
      if (this.$refs.fileInput) {
        this.$refs.fileInput.value = ''
      }
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
.bulk-import {
  min-height: 400px;
}

.bulk-import h3 {
  margin-bottom: 1.5rem;
  color: #333;
}

.import-steps {
  display: flex;
  justify-content: center;
  gap: 2rem;
  margin-bottom: 2rem;
}

.step {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  opacity: 0.5;
}

.step.active {
  opacity: 1;
}

.step-number {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background-color: #f0f0f0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  color: #666;
}

.step.active .step-number {
  background-color: #1890ff;
  color: white;
}

.step-label {
  font-size: 0.875rem;
  color: #666;
}

/* Upload Section */
.upload-section {
  text-align: center;
}

.file-upload {
  margin-bottom: 2rem;
}

.btn-large {
  padding: 1rem 2rem;
  font-size: 1rem;
}

.help-text {
  margin-top: 0.5rem;
  color: #999;
  font-size: 0.875rem;
}

.format-info {
  text-align: left;
  background-color: #fafafa;
  padding: 1rem;
  border-radius: 4px;
  margin-top: 2rem;
}

.format-info h4 {
  margin-bottom: 0.5rem;
  color: #333;
}

.format-info pre {
  background-color: #f5f5f5;
  padding: 1rem;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 0.75rem;
}

/* Preview Section */
.preview-summary {
  text-align: center;
  margin-bottom: 1rem;
  font-size: 1.125rem;
}

.preview-options {
  margin-bottom: 1.5rem;
  text-align: center;
}

.preview-list {
  max-height: 400px;
  overflow-y: auto;
  margin-bottom: 1.5rem;
}

.preview-item {
  background-color: #fafafa;
  padding: 1rem;
  border-radius: 4px;
  margin-bottom: 0.5rem;
}

.preview-item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.badge {
  padding: 0.25rem 0.5rem;
  background-color: #e6f7ff;
  color: #1890ff;
  border-radius: 4px;
  font-size: 0.75rem;
  font-family: monospace;
}

.preview-item-content {
  color: #666;
  font-size: 0.875rem;
  margin-bottom: 0.5rem;
}

.preview-item-meta {
  display: flex;
  gap: 1rem;
}

.meta-item {
  font-size: 0.75rem;
  color: #999;
}

.more-items {
  text-align: center;
  color: #999;
  font-size: 0.875rem;
  margin-top: 1rem;
}

.preview-actions {
  display: flex;
  justify-content: center;
  gap: 0.5rem;
}

/* Results Section */
.result-summary {
  display: flex;
  justify-content: center;
  gap: 2rem;
  margin-bottom: 2rem;
}

.result-stat {
  text-align: center;
  padding: 1.5rem;
  border-radius: 8px;
  min-width: 120px;
}

.result-stat.success {
  background-color: #f6ffed;
  border: 1px solid #b7eb8f;
}

.result-stat.skipped {
  background-color: #fff7e6;
  border: 1px solid #ffd591;
}

.result-stat.error {
  background-color: #fff2f0;
  border: 1px solid #ffccc7;
}

.stat-number {
  font-size: 2rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
}

.result-stat.success .stat-number {
  color: #52c41a;
}

.result-stat.skipped .stat-number {
  color: #fa8c16;
}

.result-stat.error .stat-number {
  color: #ff4d4f;
}

.stat-label {
  font-size: 0.875rem;
  color: #666;
}

.error-list {
  margin-bottom: 1.5rem;
  max-height: 300px;
  overflow-y: auto;
}

.error-list h4 {
  margin-bottom: 0.5rem;
  color: #ff4d4f;
}

.error-item {
  background-color: #fff2f0;
  padding: 0.75rem;
  border-radius: 4px;
  border-left: 3px solid #ff4d4f;
  margin-bottom: 0.5rem;
  font-size: 0.875rem;
  color: #666;
}

.result-actions {
  display: flex;
  justify-content: center;
  gap: 0.5rem;
}
</style>

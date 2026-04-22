<template>
  <div class="settings-page">
    <div class="page-header">
      <h2>系统设置</h2>
      <p class="subtitle">管理 AI 客服的运行时配置，修改立即生效，重启服务后恢复 .env 中的默认值</p>
    </div>

    <div v-if="errorMessage" class="alert alert-error">{{ errorMessage }}</div>

    <div v-if="loading" class="loading-state">
      <div class="loading-spinner"></div>
      <span>加载中...</span>
    </div>

    <div v-else class="card settings-card">
      <div class="setting-row">
        <div class="setting-info">
          <div class="setting-title">AI 自动回复</div>
          <div class="setting-desc">
            <span v-if="enableAiReply" class="status-on">🟢 开启 — AI 会真实发送消息给买家</span>
            <span v-else class="status-off">⚫ 关闭 — 仅记录 AI 回复内容，不实际发送（调试模式）</span>
          </div>
        </div>
        <button
          class="toggle-btn"
          :class="{ 'toggle-on': enableAiReply, 'toggle-off': !enableAiReply }"
          :disabled="saving"
          @click="toggleAiReply"
        >
          <span class="toggle-knob"></span>
        </button>
      </div>

      <div v-if="lastSaved" class="save-hint">✓ 已保存（{{ lastSaved }}）</div>
    </div>

    <div class="card info-card">
      <h3>说明</h3>
      <ul>
        <li>此开关对应 <code>.env</code> 中的 <code>ENABLE_AI_REPLY</code> 配置项</li>
        <li>运行时修改只影响当前进程，<strong>重启服务后恢复 .env 中的值</strong></li>
        <li>如需永久生效，请同步修改 <code>.env</code> 文件</li>
      </ul>
    </div>
  </div>
</template>

<script>
export default {
  name: 'Settings',
  data() {
    return {
      loading: true,
      saving: false,
      enableAiReply: false,
      errorMessage: '',
      lastSaved: '',
    }
  },
  async mounted() {
    await this.fetchSettings()
  },
  methods: {
    async fetchSettings() {
      this.loading = true
      this.errorMessage = ''
      try {
        const res = await fetch('/settings')
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        this.enableAiReply = data.enable_ai_reply
      } catch (e) {
        this.errorMessage = `加载设置失败：${e.message}`
      } finally {
        this.loading = false
      }
    },
    async toggleAiReply() {
      this.saving = true
      this.errorMessage = ''
      try {
        const newValue = !this.enableAiReply
        const res = await fetch('/settings', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enable_ai_reply: newValue }),
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        this.enableAiReply = data.enable_ai_reply
        const now = new Date()
        this.lastSaved = `${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}:${now.getSeconds().toString().padStart(2,'0')}`
      } catch (e) {
        this.errorMessage = `保存失败：${e.message}`
      } finally {
        this.saving = false
      }
    },
  },
}
</script>

<style scoped>
.settings-page {
  max-width: 700px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 1.5rem;
}

.page-header h2 {
  font-size: 1.4rem;
  color: #333;
  margin-bottom: 0.3rem;
}

.subtitle {
  color: #888;
  font-size: 0.9rem;
}

.settings-card {
  margin-bottom: 1rem;
}

.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.setting-info {
  flex: 1;
}

.setting-title {
  font-size: 1rem;
  font-weight: 600;
  color: #333;
  margin-bottom: 0.25rem;
}

.setting-desc {
  font-size: 0.875rem;
  color: #666;
}

.status-on { color: #52c41a; }
.status-off { color: #999; }

/* Toggle switch */
.toggle-btn {
  position: relative;
  width: 52px;
  height: 28px;
  border-radius: 14px;
  border: none;
  cursor: pointer;
  transition: background 0.2s;
  flex-shrink: 0;
  padding: 0;
}
.toggle-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.toggle-on {
  background: #52c41a;
}
.toggle-off {
  background: #ccc;
}
.toggle-knob {
  position: absolute;
  top: 3px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: white;
  box-shadow: 0 1px 3px rgba(0,0,0,0.2);
  transition: left 0.2s;
}
.toggle-on .toggle-knob {
  left: 27px;
}
.toggle-off .toggle-knob {
  left: 3px;
}

.save-hint {
  margin-top: 0.75rem;
  font-size: 0.8rem;
  color: #52c41a;
}

.info-card h3 {
  font-size: 0.95rem;
  margin-bottom: 0.5rem;
  color: #555;
}
.info-card ul {
  padding-left: 1.2rem;
  font-size: 0.875rem;
  color: #666;
  line-height: 1.8;
}
.info-card code {
  background: #f0f0f0;
  padding: 0.1em 0.35em;
  border-radius: 3px;
  font-size: 0.85em;
}

.loading-state {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1.5rem;
  color: #888;
}
</style>

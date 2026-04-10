<template>
  <div class="conversation-detail">
    <!-- Header -->
    <div class="detail-header">
      <button class="btn btn-secondary btn-sm" @click="goBack">
        ← 返回列表
      </button>
      <div class="header-info">
        <h2>会话详情</h2>
        <span class="chat-id-badge" :title="chatId">{{ truncateId(chatId) }}</span>
      </div>
      <div class="header-actions">
        <label class="toggle-label">
          <input type="checkbox" v-model="showDebugOnly" @change="filterMessages" />
          <span>仅显示调试回复</span>
        </label>
        <label class="toggle-label" style="margin-left: 16px;">
          <input type="checkbox" v-model="showTurns" />
          <span>🔧 显示 Turns 详情</span>
        </label>
      </div>
    </div>

    <!-- Loading -->
    <div class="loading" v-if="loading">
      <div class="spinner"></div>
      <span>加载聊天记录...</span>
    </div>

    <!-- Error -->
    <div class="alert alert-error" v-else-if="error">
      ⚠️ {{ error }}
      <button class="btn btn-sm btn-secondary" @click="loadDetail" style="margin-left: 12px;">重试</button>
    </div>

    <!-- Content -->
    <div v-else>
      <!-- Chat Messages -->
      <div class="chat-container">
        <div class="chat-stats" v-if="allMessages.length > 0">
          <span>共 {{ allMessages.length }} 条消息</span>
          <span v-if="debugCount > 0" class="debug-count">🐛 {{ debugCount }} 条调试回复</span>
          <span v-if="aiCount > 0" class="ai-count">🤖 {{ aiCount }} 条 AI 回复</span>
          <span v-if="totalTurns > 0" class="turns-count">🔧 {{ totalTurns }} 个 Agent Turns</span>
        </div>

        <div class="empty-state" v-if="displayMessages.length === 0">
          <div class="empty-icon">🔍</div>
          <p>没有符合筛选条件的消息</p>
        </div>

        <div class="messages-list" v-else>
          <div
            v-for="(msg, index) in displayMessages"
            :key="msg.id || index"
            class="message-group"
          >
            <!-- Date Separator -->
            <div class="date-separator" v-if="index === 0 || !isSameDay(msg.created_at, displayMessages[index - 1].created_at)">
              <span>{{ formatDate(msg.created_at) }}</span>
            </div>

            <!-- User Message -->
            <div class="message-row message-left" v-if="msg.message_type === 'user'">
              <div class="avatar avatar-user">👤</div>
              <div class="message-bubble bubble-user">
                <div class="message-meta">
                  <span class="sender-name">用户</span>
                  <span class="message-time">{{ formatTime(msg.created_at) }}</span>
                </div>
                <div class="message-text">{{ msg.message_content }}</div>
              </div>
            </div>

            <!-- Seller/AI Message -->
            <div class="message-row message-right" v-else-if="msg.message_type === 'seller'">
              <div class="message-bubble bubble-seller">
                <div class="message-meta">
                  <span class="sender-name">卖家</span>
                  <span class="message-time">{{ formatTime(msg.created_at) }}</span>
                </div>
                <div class="message-text">{{ msg.message_content }}</div>
                <div v-if="msg.agent_response" class="ai-response" :class="{ 'debug-response': isDebugResponse(msg.agent_response) }">
                  <div class="ai-response-header">
                    <span v-if="isDebugResponse(msg.agent_response)">🐛 调试模式 AI 回复</span>
                    <span v-else>🤖 AI 回复</span>
                  </div>
                  <div class="ai-response-text">{{ msg.agent_response }}</div>
                </div>
              </div>
              <div class="avatar avatar-seller">🏪</div>
            </div>

            <!-- System Message -->
            <div class="message-row message-center" v-else>
              <div class="system-message">
                <span class="badge badge-purple">系统</span>
                {{ msg.message_content }}
                <span class="message-time">{{ formatTime(msg.created_at) }}</span>
              </div>
            </div>

            <!-- Standalone AI Response -->
            <div class="message-row message-right" v-if="msg.message_type === 'user' && msg.agent_response">
              <div class="message-bubble bubble-ai" :class="{ 'bubble-debug': isDebugResponse(msg.agent_response) }">
                <div class="message-meta">
                  <span class="sender-name" v-if="isDebugResponse(msg.agent_response)">🐛 AI 调试回复</span>
                  <span class="sender-name" v-else>🤖 AI 回复</span>
                  <span class="message-time">{{ formatTime(msg.created_at) }}</span>
                </div>
                <div class="message-text">{{ msg.agent_response }}</div>
              </div>
              <div class="avatar avatar-ai">🤖</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Agent Turns Panel -->
      <div class="turns-panel" v-if="showTurns && Object.keys(turnsBySession).length > 0">
        <div class="card" v-for="(turns, sessionId) in turnsBySession" :key="sessionId">
          <div class="card-header-row">
            <h3 class="card-title">🔧 Agent Turns — Session: <code>{{ truncateId(sessionId) }}</code></h3>
            <span class="badge badge-blue">{{ turns.length }} turns</span>
          </div>

          <!-- Group turns by interaction_id -->
          <div v-for="(group, groupIdx) in groupTurnsByInteraction(turns)" :key="group.interaction_id || groupIdx" class="interaction-group">
            <div class="interaction-header" v-if="group.interaction_id">
              <span class="interaction-label">💬 Interaction #{{ groupIdx + 1 }}</span>
              <code class="interaction-id">{{ truncateId(group.interaction_id) }}</code>
              <span class="badge badge-purple">{{ group.turns.length }} turns</span>
            </div>

            <div class="turn-timeline">
              <div
                v-for="turn in group.turns"
                :key="turn.id"
                class="turn-card"
                :class="{ 'turn-error': !turn.success }"
              >
                <div class="turn-header" @click="toggleTurn(turn.id)">
                  <div class="turn-header-left">
                    <span class="turn-number" v-if="turn.local_turn_number">
                      Turn {{ turn.local_turn_number }}/{{ group.turns.length }}
                    </span>
                    <span class="turn-number" v-else>Turn #{{ turn.turn_number }}</span>
                    <span class="badge" :class="turn.success ? 'badge-green' : 'badge-red'">
                      {{ turn.success ? '✓ 成功' : '✗ 失败' }}
                    </span>
                    <span class="badge badge-blue" v-if="turn.tool_calls && turn.tool_calls.length">
                      🔨 {{ turn.tool_calls.length }} tool calls
                    </span>
                    <span class="turn-duration" v-if="turn.duration_ms">
                      ⏱ {{ turn.duration_ms }}ms
                    </span>
                  </div>
                  <span class="turn-toggle">{{ expandedTurns[turn.id] ? '▼' : '▶' }}</span>
                </div>

                <!-- Turn Details (collapsible) -->
                <div class="turn-details" v-if="expandedTurns[turn.id]">

                  <!-- User Query -->
                  <div class="turn-section" v-if="turn.user_query">
                    <div class="section-label">💬 用户查询</div>
                    <div class="section-content content-text">{{ turn.user_query }}</div>
                  </div>

                  <!-- LLM Response Text -->
                  <div class="turn-section" v-if="turn.response_text">
                    <div class="section-label">💡 LLM 回复文本</div>
                    <div class="section-content content-text">{{ turn.response_text }}</div>
                  </div>

                  <!-- Tool Calls -->
                  <div class="turn-section" v-if="turn.tool_calls && turn.tool_calls.length">
                    <div class="section-label">🔨 Tool Calls</div>
                    <div class="tool-call-list">
                      <div v-for="(tc, idx) in turn.tool_calls" :key="idx" class="tool-call-item">
                        <div class="tool-call-header">
                          <span class="tool-name">{{ tc.name || 'unknown' }}</span>
                          <code class="tool-id">{{ tc.id }}</code>
                        </div>
                        <div class="tool-call-body" v-if="tc.args">
                          <div class="sub-label">参数:</div>
                          <pre class="json-block">{{ formatJson(tc.args) }}</pre>
                        </div>
                        <div class="tool-call-body" v-if="tc.result !== undefined && tc.result !== null">
                          <div class="sub-label">结果:</div>
                          <pre class="json-block json-result">{{ formatJson(tc.result) }}</pre>
                        </div>
                      </div>
                    </div>
                  </div>

                  <!-- LLM Input (Messages Array) -->
                  <div class="turn-section">
                    <div class="section-label">
                      📥 LLM 输入 (Messages)
                      <button class="btn btn-sm btn-secondary" @click="toggleLlmInput(turn.id)" style="margin-left: 8px;">
                        {{ expandedLlmInput[turn.id] ? '收起' : '展开' }}
                      </button>
                    </div>
                    <div v-if="expandedLlmInput[turn.id]" class="section-content">
                      <div v-if="turn.llm_input && turn.llm_input.length" class="llm-messages">
                        <div
                          v-for="(m, mi) in turn.llm_input"
                          :key="mi"
                          class="llm-msg"
                          :class="'llm-msg-' + m.role"
                        >
                          <div class="llm-msg-header">
                            <span class="llm-msg-role">{{ m.role }}</span>
                            <span class="llm-msg-idx">[{{ mi }}]</span>
                            <span v-if="m.tool_call_id" class="llm-msg-tcid">tool_call_id: {{ m.tool_call_id }}</span>
                          </div>
                          <div class="llm-msg-content">
                            <template v-if="m.content && m.content.length > 500">
                              {{ m.content.substring(0, 500) }}...
                              <button class="btn btn-sm btn-secondary" @click="showFullContent(m.content)">
                                查看完整内容 ({{ m.content.length }} chars)
                              </button>
                            </template>
                            <template v-else>
                              {{ m.content || '(empty)' }}
                            </template>
                          </div>
                          <div v-if="m.tool_calls" class="llm-msg-tc">
                            <pre class="json-block">{{ formatJson(m.tool_calls) }}</pre>
                          </div>
                        </div>
                      </div>
                      <span v-else class="text-muted">无输入数据</span>
                    </div>
                  </div>

                  <!-- LLM Output (Raw Response) -->
                  <div class="turn-section">
                    <div class="section-label">
                      📤 LLM 输出 (Raw)
                      <button class="btn btn-sm btn-secondary" @click="toggleLlmOutput(turn.id)" style="margin-left: 8px;">
                        {{ expandedLlmOutput[turn.id] ? '收起' : '展开' }}
                      </button>
                    </div>
                    <div v-if="expandedLlmOutput[turn.id]" class="section-content">
                      <pre class="json-block" v-if="turn.llm_output">{{ formatJson(turn.llm_output) }}</pre>
                      <span v-else class="text-muted">无输出数据</span>
                    </div>
                  </div>

                  <!-- Error -->
                  <div class="turn-section" v-if="turn.error_message">
                    <div class="section-label">❌ 错误信息</div>
                    <div class="section-content error-text">{{ turn.error_message }}</div>
                  </div>

                  <!-- Timestamp -->
                  <div class="turn-footer">
                    <span class="turn-time">{{ formatDateTime(turn.created_at) }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- No turns message -->
      <div class="alert alert-info" v-if="showTurns && Object.keys(turnsBySession).length === 0" style="margin-top: 16px;">
        📋 当前会话暂无关联的 Agent Turn 记录。Turn 数据在 Agent 处理消息时自动记录。
      </div>
    </div>

    <!-- Full content modal -->
    <div class="modal-overlay" v-if="fullContentModal" @click="fullContentModal = null">
      <div class="modal-content" @click.stop>
        <div class="modal-header">
          <h3>完整内容</h3>
          <button class="btn btn-sm btn-secondary" @click="fullContentModal = null">关闭</button>
        </div>
        <pre class="modal-body">{{ fullContentModal }}</pre>
      </div>
    </div>
  </div>
</template>

<script>
import api from '../api'

export default {
  name: 'ConversationDetail',
  props: {
    chatId: {
      type: String,
      required: true
    }
  },
  data() {
    return {
      allMessages: [],
      displayMessages: [],
      turnsBySession: {},
      loading: false,
      error: null,
      showDebugOnly: false,
      showTurns: false,
      expandedTurns: {},
      expandedLlmInput: {},
      expandedLlmOutput: {},
      fullContentModal: null
    }
  },
  computed: {
    debugCount() {
      return this.allMessages.filter(m => this.isDebugResponse(m.agent_response)).length
    },
    aiCount() {
      return this.allMessages.filter(m => m.agent_response && !this.isDebugResponse(m.agent_response)).length
    },
    totalTurns() {
      let count = 0
      for (const turns of Object.values(this.turnsBySession)) {
        count += turns.length
      }
      return count
    }
  },
  mounted() {
    this.loadDetail()
  },
  methods: {
    async loadDetail() {
      this.loading = true
      this.error = null
      try {
        const result = await api.getDetail(this.chatId)
        this.allMessages = result.messages || []
        this.turnsBySession = result.turns_by_session || {}
        this.filterMessages()
      } catch (e) {
        this.error = e.message || '加载失败'
      } finally {
        this.loading = false
      }
    },
    filterMessages() {
      if (this.showDebugOnly) {
        this.displayMessages = this.allMessages.filter(m => this.isDebugResponse(m.agent_response))
      } else {
        this.displayMessages = [...this.allMessages]
      }
    },
    isDebugResponse(response) {
      return response && response.startsWith('【调试】')
    },
    goBack() {
      this.$router.push('/')
    },
    groupTurnsByInteraction(turns) {
      // Group turns by interaction_id
      // Turns without interaction_id go into a single "legacy" group
      const groups = []
      const groupMap = {}
      for (const turn of turns) {
        const key = turn.interaction_id || '__legacy__'
        if (!groupMap[key]) {
          groupMap[key] = {
            interaction_id: turn.interaction_id || null,
            turns: []
          }
          groups.push(groupMap[key])
        }
        groupMap[key].turns.push(turn)
      }
      // Sort turns within each group by local_turn_number (fallback to id)
      for (const group of groups) {
        group.turns.sort((a, b) => {
          if (a.local_turn_number && b.local_turn_number) {
            return a.local_turn_number - b.local_turn_number
          }
          return (a.id || 0) - (b.id || 0)
        })
      }
      return groups
    },
    toggleTurn(id) {
      this.expandedTurns = { ...this.expandedTurns, [id]: !this.expandedTurns[id] }
    },
    toggleLlmInput(id) {
      this.expandedLlmInput = { ...this.expandedLlmInput, [id]: !this.expandedLlmInput[id] }
    },
    toggleLlmOutput(id) {
      this.expandedLlmOutput = { ...this.expandedLlmOutput, [id]: !this.expandedLlmOutput[id] }
    },
    showFullContent(content) {
      this.fullContentModal = content
    },
    formatJson(obj) {
      if (!obj) return ''
      if (typeof obj === 'string') {
        try { obj = JSON.parse(obj) } catch { return obj }
      }
      try {
        return JSON.stringify(obj, null, 2)
      } catch {
        return String(obj)
      }
    },
    truncateId(id) {
      if (!id) return '-'
      if (id.length <= 20) return id
      return id.substring(0, 10) + '...' + id.substring(id.length - 8)
    },
    formatDate(timeStr) {
      if (!timeStr) return ''
      try {
        return new Date(timeStr).toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })
      } catch { return timeStr }
    },
    formatTime(timeStr) {
      if (!timeStr) return ''
      try {
        return new Date(timeStr).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      } catch { return timeStr }
    },
    formatDateTime(timeStr) {
      if (!timeStr) return ''
      try {
        return new Date(timeStr).toLocaleString('zh-CN')
      } catch { return timeStr }
    },
    isSameDay(time1, time2) {
      if (!time1 || !time2) return false
      try {
        return new Date(time1).toDateString() === new Date(time2).toDateString()
      } catch { return false }
    }
  }
}
</script>

<style scoped>
/* Header */
.detail-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  background: white;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.header-info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-info h2 {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
}
.chat-id-badge {
  font-family: 'SF Mono', 'Menlo', monospace;
  font-size: 12px;
  background: #f0f0f0;
  padding: 4px 10px;
  border-radius: 12px;
  color: #666;
}
.header-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
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

/* Chat Container */
.chat-container {
  background: #f0f2f5;
  border-radius: 8px;
  padding: 16px;
}
.chat-stats {
  display: flex;
  gap: 16px;
  padding: 10px 16px;
  background: white;
  border-radius: 6px;
  margin-bottom: 16px;
  font-size: 13px;
  color: #666;
  flex-wrap: wrap;
}
.debug-count { color: #fa8c16; font-weight: 500; }
.ai-count { color: #52c41a; font-weight: 500; }
.turns-count { color: #722ed1; font-weight: 500; }
.messages-list { display: flex; flex-direction: column; gap: 4px; }

/* Date Separator */
.date-separator { text-align: center; padding: 16px 0 8px; }
.date-separator span {
  background: rgba(0, 0, 0, 0.06);
  padding: 4px 16px;
  border-radius: 12px;
  font-size: 12px;
  color: #999;
}

/* Messages */
.message-row { display: flex; align-items: flex-start; gap: 10px; padding: 6px 0; }
.message-left { justify-content: flex-start; }
.message-right { justify-content: flex-end; }
.message-center { justify-content: center; }
.avatar {
  width: 36px; height: 36px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px; flex-shrink: 0;
}
.avatar-user { background: #e6f7ff; }
.avatar-seller { background: #f6ffed; }
.avatar-ai { background: #fff7e6; }
.message-bubble { max-width: 70%; padding: 10px 14px; border-radius: 12px; }
.bubble-user { background: white; border: 1px solid #e8e8e8; border-top-left-radius: 4px; }
.bubble-seller { background: #d4f8d4; border-top-right-radius: 4px; }
.bubble-ai { background: #e6f7ff; border: 1px solid #91d5ff; border-top-right-radius: 4px; }
.bubble-debug { background: #fff7e6; border: 2px solid #ffc069; }
.message-meta { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 4px; }
.sender-name { font-size: 12px; font-weight: 600; color: #666; }
.message-time { font-size: 11px; color: #bbb; white-space: nowrap; }
.message-text { font-size: 14px; line-height: 1.6; word-break: break-word; white-space: pre-wrap; }
.ai-response { margin-top: 10px; padding: 10px 12px; background: rgba(24,144,255,0.08); border-radius: 8px; border-left: 3px solid #1890ff; }
.ai-response.debug-response { background: rgba(250,140,22,0.08); border-left-color: #fa8c16; }
.ai-response-header { font-size: 12px; font-weight: 600; color: #1890ff; margin-bottom: 6px; }
.debug-response .ai-response-header { color: #fa8c16; }
.ai-response-text { font-size: 13px; line-height: 1.5; color: #444; white-space: pre-wrap; word-break: break-word; }
.system-message {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 16px; background: rgba(0,0,0,0.03); border-radius: 16px; font-size: 13px; color: #999;
}

/* ─── Turns Panel ──────────────────────────────────────────── */
.turns-panel { margin-top: 20px; }
.card-header-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.card-header-row code { font-size: 12px; background: #f0f0f0; padding: 2px 8px; border-radius: 4px; }

/* Interaction Group */
.interaction-group {
  margin-bottom: 16px;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  overflow: hidden;
}
.interaction-group:last-child { margin-bottom: 0; }
.interaction-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  background: #f6f0ff;
  border-bottom: 1px solid #e8e8e8;
}
.interaction-label {
  font-weight: 600;
  font-size: 13px;
  color: #722ed1;
}
.interaction-id {
  font-size: 11px;
  color: #999;
  background: rgba(0,0,0,0.04);
  padding: 2px 8px;
  border-radius: 4px;
}

.turn-timeline { display: flex; flex-direction: column; gap: 0; }

.turn-card {
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  overflow: hidden;
  transition: box-shadow 0.2s;
}
.turn-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
.turn-card.turn-error { border-color: #ffa39e; }

.turn-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: #fafafa;
  cursor: pointer;
  user-select: none;
}
.turn-header:hover { background: #f0f0f0; }
.turn-error .turn-header { background: #fff2f0; }

.turn-header-left { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.turn-number { font-weight: 700; font-size: 14px; color: #333; }
.turn-duration { font-size: 12px; color: #999; }
.turn-toggle { font-size: 12px; color: #999; }

.turn-details { padding: 16px; border-top: 1px solid #f0f0f0; }

.turn-section { margin-bottom: 16px; }
.turn-section:last-child { margin-bottom: 0; }
.section-label {
  font-size: 13px; font-weight: 600; color: #555;
  margin-bottom: 8px;
  display: flex; align-items: center;
}
.section-content { font-size: 13px; color: #333; }
.content-text {
  background: #fafafa;
  padding: 10px 14px;
  border-radius: 6px;
  border: 1px solid #f0f0f0;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
}
.error-text {
  background: #fff2f0;
  border: 1px solid #ffccc7;
  padding: 10px 14px;
  border-radius: 6px;
  color: #cf1322;
}

/* Tool Calls */
.tool-call-list { display: flex; flex-direction: column; gap: 8px; }
.tool-call-item {
  background: #f9f0ff;
  border: 1px solid #d3adf7;
  border-radius: 6px;
  padding: 10px 14px;
}
.tool-call-header { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.tool-name { font-weight: 600; font-size: 13px; color: #722ed1; }
.tool-id { font-size: 11px; color: #999; background: rgba(0,0,0,0.04); padding: 1px 6px; border-radius: 3px; }
.tool-call-body { margin-top: 6px; }
.sub-label { font-size: 12px; font-weight: 500; color: #888; margin-bottom: 4px; }

/* JSON Block */
.json-block {
  background: #1e1e2e;
  color: #cdd6f4;
  padding: 12px 16px;
  border-radius: 6px;
  font-family: 'SF Mono', 'Menlo', 'Monaco', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  max-height: 400px;
  overflow-y: auto;
  white-space: pre;
  margin: 0;
}
.json-result { background: #1a2332; color: #89b4fa; }

/* LLM Messages */
.llm-messages { display: flex; flex-direction: column; gap: 6px; }
.llm-msg {
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 13px;
}
.llm-msg-system { background: #f6ffed; border-left: 3px solid #52c41a; }
.llm-msg-user { background: #e6f7ff; border-left: 3px solid #1890ff; }
.llm-msg-assistant { background: #fff7e6; border-left: 3px solid #fa8c16; }
.llm-msg-tool { background: #f9f0ff; border-left: 3px solid #722ed1; }

.llm-msg-header {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 4px; font-size: 11px; font-weight: 600;
}
.llm-msg-role {
  text-transform: uppercase;
  padding: 1px 6px;
  border-radius: 3px;
  background: rgba(0,0,0,0.06);
}
.llm-msg-idx { color: #bbb; }
.llm-msg-tcid { color: #722ed1; font-family: monospace; }
.llm-msg-content {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
  color: #333;
}
.llm-msg-tc { margin-top: 6px; }

.turn-footer {
  padding-top: 8px;
  border-top: 1px solid #f0f0f0;
  margin-top: 12px;
}
.turn-time { font-size: 12px; color: #999; }

.text-muted { color: #ccc; font-style: italic; }

/* Modal */
.modal-overlay {
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
.modal-content {
  background: white;
  border-radius: 8px;
  max-width: 80vw;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 4px 24px rgba(0,0,0,0.2);
}
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
}
.modal-header h3 { margin: 0; font-size: 16px; }
.modal-body {
  padding: 20px;
  overflow: auto;
  font-family: monospace;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
}

@media (max-width: 768px) {
  .message-bubble { max-width: 85%; }
  .detail-header { flex-direction: column; align-items: flex-start; }
}
</style>

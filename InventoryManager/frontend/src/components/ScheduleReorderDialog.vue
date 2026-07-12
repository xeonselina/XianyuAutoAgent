<template>
  <el-dialog
    v-model="visible"
    title="一键重排档期"
    width="min(1000px, 94vw)"
    :close-on-click-modal="false"
    destroy-on-close
  >
    <el-steps :active="step - 1" finish-status="success" align-center class="reorder-steps">
      <el-step title="确认接力关系" />
      <el-step title="预览并执行" />
    </el-steps>

    <div v-loading="loading" class="reorder-content">
      <template v-if="step === 1">
        <el-alert
          title="仅重排今天及以后、尚未预约发货的主设备档期；型号、日期、附件和父子 rental 关系均不会改变。"
          type="info"
          :closable="false"
          show-icon
        />

        <el-empty
          v-if="analysis && analysis.overlaps.length === 0"
          description="没有需要人工确认的重叠档期，可直接计算预览"
        />

        <section
          v-for="overlap in analysis?.overlaps || []"
          :key="overlap.pair_key"
          class="relay-card"
        >
          <header class="relay-card__header">
            <div>
              <strong>{{ overlap.device.name }}</strong>
              <el-tag v-if="overlap.status === 'bound'" type="success" size="small">
                已保存接力绑定
              </el-tag>
            </div>
            <el-tag type="warning">原档期重叠 {{ overlap.overlap_days }} 天</el-tag>
          </header>

          <div class="customer-pair">
            <div class="customer-card">
              <span class="customer-card__label">前一位租客</span>
              <strong>{{ overlap.predecessor.customer_name }}</strong>
              <span>{{ overlap.predecessor.customer_phone || '未填写电话' }}</span>
              <span>{{ overlap.predecessor.destination || '未填写地址' }}</span>
              <span>寄出 {{ formatDateTime(overlap.predecessor.ship_out_time) }}</span>
              <span>收回 {{ formatDateTime(overlap.predecessor.ship_in_time) }}</span>
            </div>
            <div class="relay-arrow">→</div>
            <div class="customer-card">
              <span class="customer-card__label">后一位租客</span>
              <strong>{{ overlap.successor.customer_name }}</strong>
              <span>{{ overlap.successor.customer_phone || '未填写电话' }}</span>
              <span>{{ overlap.successor.destination || '未填写地址' }}</span>
              <span>寄出 {{ formatDateTime(overlap.successor.ship_out_time) }}</span>
              <span>收回 {{ formatDateTime(overlap.successor.ship_in_time) }}</span>
            </div>
          </div>

          <el-radio-group v-model="relayActions[overlap.pair_key]" class="relay-actions">
            <el-radio-button
              value="keep"
              :data-test="`relay-keep-${testPairKey(overlap.pair_key)}`"
              @click="relayActions[overlap.pair_key] = 'keep'"
            >
              保持接力并永久绑定
            </el-radio-button>
            <el-radio-button
              value="separate"
              :disabled="!overlap.can_separate"
              @click="relayActions[overlap.pair_key] = 'separate'"
            >
              解除接力，允许重排
            </el-radio-button>
          </el-radio-group>
          <p v-if="!overlap.can_separate" class="fixed-hint">
            两笔档期都已固定，无法拆开，只能保持接力。
          </p>
        </section>
      </template>

      <template v-else>
        <el-alert
          title="这是最终执行前的预览。执行时会再次校验数据库快照，档期有变化则整批拒绝，不会部分写入。"
          type="warning"
          :closable="false"
          show-icon
        />

        <h3>型号优化结果</h3>
        <el-table v-if="preview?.models.length" :data="localizedModels" border>
          <el-table-column prop="model_id" label="型号 ID" width="100" />
          <el-table-column prop="status" label="求解状态" width="120" />
          <el-table-column label="使用设备数" min-width="140">
            <template #default="scope">
              {{ scope.row.before_devices }} → {{ scope.row.after_devices }}
            </template>
          </el-table-column>
          <el-table-column prop="movable_rentals" label="参与档期" width="100" />
          <el-table-column prop="changed_rentals" label="调整档期" width="100" />
          <el-table-column prop="total_gap_days" label="空隙天数" width="100" />
        </el-table>
        <el-empty v-else description="没有可优化的主设备档期" :image-size="80" />

        <h3>设备调整明细</h3>
        <el-table v-if="preview?.changes.length" :data="preview.changes" border>
          <el-table-column label="租客" min-width="210">
            <template #default="scope">
              <div class="contact-cell">
                <strong>{{ scope.row.customer_name }}</strong>
                <span>{{ scope.row.customer_phone || '未填写电话' }}</span>
                <span>{{ scope.row.destination || '未填写地址' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="档期" min-width="190">
            <template #default="scope">
              <div>{{ formatDateTime(scope.row.ship_out_time) }}</div>
              <div>至 {{ formatDateTime(scope.row.ship_in_time) }}</div>
            </template>
          </el-table-column>
          <el-table-column label="设备调整" min-width="210">
            <template #default="scope">
              {{ scope.row.from_device_name }} → {{ scope.row.to_device_name }}
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="预览无需更换设备" :image-size="80" />

        <template v-if="preview?.skipped.length">
          <h3>未参与重排</h3>
          <el-alert
            v-for="item in preview.skipped"
            :key="item.rental_id"
            :title="`Rental #${item.rental_id}：${item.reason}`"
            type="info"
            :closable="false"
            class="skipped-item"
          />
        </template>
      </template>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <template v-if="step === 1">
        <el-button
          type="primary"
          data-test="calculate-preview"
          :disabled="!analysis || !allRelayPairsDecided"
          :loading="loading"
          @click="calculatePreview"
        >
          计算重排预览
        </el-button>
      </template>
      <template v-else>
        <el-button :disabled="loading" @click="step = 1">返回修改接力关系</el-button>
        <el-button
          type="primary"
          data-test="execute-reorder"
          :disabled="!preview || hasUnsolvedModel"
          :loading="loading"
          @click="executeReorder"
        >
          执行重排
        </el-button>
      </template>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'

import {
  useGanttStore,
  type RelayDecision,
  type ReorderAnalysis,
  type ReorderPreview,
} from '@/stores/gantt'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'completed'): void
}>()

const ganttStore = useGanttStore()
const step = ref(1)
const loading = ref(false)
const analysis = ref<ReorderAnalysis | null>(null)
const preview = ref<ReorderPreview | null>(null)
const relayActions = ref<Record<string, 'keep' | 'separate'>>({})

const solverStatusLabels: Record<string, string> = {
  OPTIMAL: '最优方案',
  FEASIBLE: '可行方案',
  INFEASIBLE: '无可行方案',
  UNKNOWN: '未得出结果',
  MODEL_INVALID: '求解模型无效',
}

const formatSolverStatus = (status: string) => {
  return solverStatusLabels[status] || '未知状态'
}

const localizedModels = computed(() => {
  return (preview.value?.models || []).map(model => ({
    ...model,
    status: formatSolverStatus(model.status),
  }))
})

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const allRelayPairsDecided = computed(() => {
  return (analysis.value?.overlaps || []).every(
    overlap => relayActions.value[overlap.pair_key] !== undefined
  )
})

const hasUnsolvedModel = computed(() => {
  return (preview.value?.models || []).some(
    model => !['OPTIMAL', 'FEASIBLE'].includes(model.status)
  )
})

const testPairKey = (pairKey: string) => pairKey.replace(':', '-')

const formatDateTime = (value: string) => {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '-'
}

const loadAnalysis = async () => {
  loading.value = true
  step.value = 1
  preview.value = null
  try {
    const result = await ganttStore.analyzeScheduleReorder()
    analysis.value = result
    relayActions.value = Object.fromEntries(
      result.overlaps
        .filter(overlap => overlap.status === 'bound' || !overlap.can_separate)
        .map(overlap => [overlap.pair_key, 'keep' as const])
    )
  } catch (error) {
    analysis.value = null
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

const buildDecisions = (): RelayDecision[] => {
  return (analysis.value?.overlaps || []).map(overlap => ({
    predecessor_rental_id: overlap.predecessor.id,
    successor_rental_id: overlap.successor.id,
    action: relayActions.value[overlap.pair_key],
  }))
}

const calculatePreview = async () => {
  if (!analysis.value || !allRelayPairsDecided.value) return
  loading.value = true
  try {
    preview.value = await ganttStore.previewScheduleReorder(buildDecisions())
    step.value = 2
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

const executeReorder = async () => {
  if (!preview.value || hasUnsolvedModel.value) return
  loading.value = true
  try {
    const result = await ganttStore.executeScheduleReorder(preview.value.token)
    ElMessage.success(`档期重排完成，共调整 ${result.changes.length} 笔 rental`)
    emit('completed')
    visible.value = false
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

watch(
  () => props.modelValue,
  isOpen => {
    if (isOpen) loadAnalysis()
  },
  { immediate: true }
)
</script>

<style scoped>
.reorder-steps {
  margin: 0 auto 24px;
  max-width: 620px;
}

.reorder-content {
  min-height: 180px;
}

.relay-card {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  margin-top: 16px;
  padding: 16px;
}

.relay-card__header,
.customer-pair {
  align-items: center;
  display: flex;
  gap: 12px;
  justify-content: space-between;
}

.relay-card__header > div {
  align-items: center;
  display: flex;
  gap: 8px;
}

.customer-pair {
  margin: 16px 0;
}

.customer-card {
  background: var(--el-fill-color-light);
  border-radius: 6px;
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
  padding: 12px;
}

.customer-card__label,
.fixed-hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.relay-arrow {
  color: var(--el-color-primary);
  font-size: 24px;
}

.relay-actions {
  width: 100%;
}

.contact-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

h3 {
  font-size: 15px;
  margin: 20px 0 10px;
}

.skipped-item {
  margin-top: 8px;
}

@media (max-width: 700px) {
  .customer-pair {
    align-items: stretch;
    flex-direction: column;
  }

  .relay-arrow {
    text-align: center;
    transform: rotate(90deg);
  }
}
</style>

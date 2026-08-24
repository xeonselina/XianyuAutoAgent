<template>
  <main class="adjustment-page">
    <el-card shadow="never">
      <template #header>
        <div class="page-header">
          <div>
            <p class="eyebrow">D53 · action-scoped confirmation</p>
            <h1>调整租户服务期</h1>
            <p>先按服务端当前状态预览，再为这一笔动作现场验证第二因子。</p>
          </div>
          <el-button @click="router.push({ name: 'platform-tenants' })">返回租户目录</el-button>
        </div>
      </template>

      <el-skeleton v-if="tenantLoading" :rows="4" animated />
      <template v-else-if="tenant">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="租户">{{ tenant.name || tenant.tenant_id }}</el-descriptions-item>
          <el-descriptions-item label="租户状态">{{ tenant.status }}</el-descriptions-item>
          <el-descriptions-item label="当前到期">
            {{ formatTime(tenant.subscription?.expires_at || null) }}
          </el-descriptions-item>
        </el-descriptions>

        <el-alert
          class="warning"
          type="warning"
          :closable="false"
          title="减少服务期或立即到期只记录运营原因，不代表资金已经退款。"
        />

        <el-form class="form" label-position="top" @submit.prevent>
          <el-form-item label="动作">
            <el-radio-group v-model="operation" :disabled="submitting">
              <el-radio-button value="add_days">增加天数</el-radio-button>
              <el-radio-button value="subtract_days">减少天数</el-radio-button>
              <el-radio-button value="expire_now">立即到期</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="operation !== 'expire_now'" label="天数">
            <el-input-number v-model="days" :min="1" :step="1" :precision="0" />
          </el-form-item>
          <el-form-item label="原因代码">
            <el-input v-model="reasonCode" maxlength="64" autocomplete="off" />
          </el-form-item>
          <el-form-item label="安全备注（不要填写 Secret 或不必要的个人信息）">
            <el-input v-model="note" type="textarea" maxlength="500" show-word-limit />
          </el-form-item>
          <el-form-item label="线下参考号（可选）">
            <el-input v-model="offlineReference" maxlength="128" autocomplete="off" />
          </el-form-item>
          <el-button type="primary" :loading="previewing" :disabled="submitting" @click="loadPreview">
            生成预览
          </el-button>
        </el-form>

        <section v-if="preview" class="preview" data-testid="adjustment-preview">
          <h2>确认本次结果</h2>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="计算基准">{{ formatTime(preview.calculation_base_at) }}</el-descriptions-item>
            <el-descriptions-item label="调整前">{{ formatTime(preview.before_expires_at) }} / {{ preview.before_status }}</el-descriptions-item>
            <el-descriptions-item label="调整后">{{ formatTime(preview.after_expires_at) }} / {{ preview.after_status }}</el-descriptions-item>
            <el-descriptions-item label="预览有效至">{{ formatTime(preview.expires_at) }}</el-descriptions-item>
          </el-descriptions>

          <el-form class="factor-form" label-position="top" @submit.prevent>
            <el-form-item label="本次动作第二因子">
              <el-select v-model="factorMethod">
                <el-option label="TOTP" value="totp" />
                <el-option label="恢复码" value="recovery_code" />
              </el-select>
            </el-form-item>
            <el-form-item :label="factorMethod === 'totp' ? 'TOTP 验证码' : '未使用的恢复码'">
              <el-input
                v-model="factor"
                type="password"
                show-password
                autocomplete="one-time-code"
                data-testid="adjustment-factor"
              />
            </el-form-item>
            <el-button type="danger" :loading="submitting" @click="submitAdjustment">
              确认并提交
            </el-button>
          </el-form>
        </section>

        <el-result
          v-if="result"
          icon="success"
          title="服务期调整已记录"
          :sub-title="`${formatTime(result.before_expires_at)} → ${formatTime(result.after_expires_at)}`"
        >
          <template #extra>
            <p class="result-reference">事件：{{ result.event_id }}</p>
            <p>{{ result.refund_disclaimer }}</p>
          </template>
        </el-result>
      </template>
    </el-card>
  </main>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import {
  commitPlatformSubscriptionAdjustment,
  getPlatformTenant,
  previewPlatformSubscriptionAdjustment,
  type PlatformFactorMethod,
  type PlatformSubscriptionAdjustmentInput,
  type PlatformSubscriptionAdjustmentOperation,
  type PlatformSubscriptionAdjustmentPreview,
  type PlatformSubscriptionAdjustmentResult,
  type PlatformTenantDetail,
} from '@/api/platformIdentity'

const route = useRoute()
const router = useRouter()
const tenantId = String(route.params.tenantId || '')
const tenantLoading = ref(true)
const previewing = ref(false)
const submitting = ref(false)
const tenant = ref<PlatformTenantDetail | null>(null)
const operation = ref<PlatformSubscriptionAdjustmentOperation>('add_days')
const days = ref(1)
const reasonCode = ref('customer_compensation')
const note = ref('')
const offlineReference = ref('')
const factorMethod = ref<PlatformFactorMethod>('totp')
const factor = ref('')
const idempotencyKey = ref(newIdempotencyKey())
const preview = ref<PlatformSubscriptionAdjustmentPreview | null>(null)
const result = ref<PlatformSubscriptionAdjustmentResult | null>(null)

const formatTime = (value: string | null) => value
  ? new Intl.DateTimeFormat('zh-CN', {
      dateStyle: 'medium',
      timeStyle: 'medium',
      timeZone: 'Asia/Shanghai',
    }).format(new Date(value))
  : '-'

const currentInput = (): PlatformSubscriptionAdjustmentInput => ({
  operation: operation.value,
  days: operation.value === 'expire_now' ? null : days.value,
  reason_code: reasonCode.value,
  note: note.value || null,
  offline_reference: offlineReference.value || null,
  idempotency_key: idempotencyKey.value,
})

const clearConfirmation = () => {
  preview.value = null
  factor.value = ''
}

const clearSensitiveState = () => {
  clearConfirmation()
  result.value = null
}

const loadPreview = async () => {
  previewing.value = true
  clearConfirmation()
  result.value = null
  try {
    preview.value = await previewPlatformSubscriptionAdjustment(
      tenantId,
      currentInput(),
    )
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '无法生成服务期预览')
  } finally {
    previewing.value = false
  }
}

const submitAdjustment = async () => {
  const confirmed = preview.value
  if (!confirmed || !factor.value) {
    ElMessage.warning('请先生成预览并填写本次动作第二因子')
    return
  }
  submitting.value = true
  try {
    result.value = await commitPlatformSubscriptionAdjustment(
      tenantId,
      {
        ...currentInput(),
        action_id: confirmed.action_id,
        expected_subscription_row_version: confirmed.expected_subscription_row_version,
        confirmation_token: confirmed.confirmation_token,
        factor_method: factorMethod.value,
        factor: factor.value,
      },
    )
    clearConfirmation()
    idempotencyKey.value = newIdempotencyKey()
    tenant.value = await getPlatformTenant(tenantId)
    ElMessage.success('服务期调整已提交')
  } catch (error) {
    factor.value = ''
    ElMessage.error(error instanceof Error ? error.message : '服务期调整失败')
  } finally {
    submitting.value = false
  }
}

watch(
  [operation, days, reasonCode, note, offlineReference],
  () => {
    if (preview.value) clearConfirmation()
  },
)

watch(factorMethod, () => {
  factor.value = ''
})

onMounted(async () => {
  try {
    tenant.value = await getPlatformTenant(tenantId)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '无法读取租户')
  } finally {
    tenantLoading.value = false
  }
})

onBeforeUnmount(clearSensitiveState)

function newIdempotencyKey(): string {
  return `d53:${crypto.randomUUID()}`
}
</script>

<style scoped>
.adjustment-page { max-width: 920px; margin: 32px auto; padding: 0 20px; }
.page-header { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; }
.eyebrow { margin: 0 0 6px; color: #6b7280; font-size: 12px; letter-spacing: .08em; text-transform: uppercase; }
h1, h2 { margin: 0; }
.page-header p:last-child { margin-bottom: 0; color: #6b7280; }
.warning, .form, .preview { margin-top: 24px; }
.form, .factor-form { max-width: 620px; }
.preview { border-top: 1px solid #e5e7eb; padding-top: 24px; }
.preview h2 { margin-bottom: 16px; }
.factor-form { margin-top: 20px; }
.result-reference { font-family: ui-monospace, monospace; overflow-wrap: anywhere; }
@media (max-width: 640px) { .page-header { flex-direction: column; } }
</style>

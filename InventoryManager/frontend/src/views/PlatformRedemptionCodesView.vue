<template>
  <main class="codes-page">
    <el-card shadow="never">
      <template #header>
        <div class="page-header">
          <div>
            <p class="eyebrow">Control-plane bearer inventory</p>
            <h1>兑换码</h1>
            <p>列表始终脱敏；历史批次不能再次整批导出，单码查看逐次审计。</p>
          </div>
          <div class="header-actions">
            <el-button @click="router.push({ name: 'platform-tenants' })">租户目录</el-button>
            <el-button type="primary" @click="generationOpen = true">生成兑换码</el-button>
          </div>
        </div>
      </template>

      <div class="filters">
        <el-select v-model="status" placeholder="全部状态" clearable @change="resetAndLoad">
          <el-option
            v-for="option in statusOptions"
            :key="option"
            :label="option"
            :value="option"
          />
        </el-select>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>

      <el-table v-loading="loading" :data="items" empty-text="暂无兑换码">
        <el-table-column label="兑换码" min-width="210">
          <template #default="scope">
            <strong>{{ scope.row.masked_code }}</strong>
            <div class="secondary">{{ scope.row.code_id }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="150" />
        <el-table-column label="服务期" width="110">
          <template #default="scope">
            {{ durationDays(scope.row.service_duration_seconds) }} 天
          </template>
        </el-table-column>
        <el-table-column label="兑换截止" min-width="180">
          <template #default="scope">{{ formatTime(scope.row.redeem_before) }}</template>
        </el-table-column>
        <el-table-column prop="batch_name" label="批次" min-width="180" />
        <el-table-column prop="channel" label="渠道" min-width="120" />
        <el-table-column label="结果" min-width="220">
          <template #default="scope">{{ outcomeLabel(scope.row) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="170" align="right">
          <template #default="scope">
            <el-button link type="primary" @click="reveal(scope.row)">查看完整码</el-button>
            <el-button
              v-if="scope.row.status === 'active'"
              link
              type="danger"
              @click="revoke(scope.row)"
            >撤销</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-button :disabled="page <= 1 || loading" @click="movePage(-1)">上一页</el-button>
        <span>第 {{ page }} / {{ Math.max(1, pages) }} 页，共 {{ total }} 条</span>
        <el-button :disabled="page >= pages || loading" @click="movePage(1)">下一页</el-button>
      </div>
    </el-card>

    <el-dialog
      v-model="generationOpen"
      title="生成并下载一次性 CSV"
      width="min(560px, 92vw)"
      :close-on-click-modal="false"
    >
      <el-alert
        title="成功响应会立即下载唯一一次整批明文 CSV；后台不会提供历史批次重导出。"
        type="warning"
        :closable="false"
      />
      <el-form class="generation-form" label-position="top" @submit.prevent>
        <el-form-item label="批次名称">
          <el-input v-model="batchName" maxlength="160" autocomplete="off" />
        </el-form-item>
        <el-form-item label="渠道（可选，小写代码）">
          <el-input v-model="channel" maxlength="64" autocomplete="off" />
        </el-form-item>
        <el-form-item label="内部备注（可选，不要填写 Secret 或个人信息）">
          <el-input
            v-model="internalNote"
            type="textarea"
            maxlength="500"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="quantity" :min="1" :max="1000" :precision="0" />
        </el-form-item>
        <el-form-item label="兑换后服务天数">
          <el-input-number v-model="durationDaysInput" :min="1" :precision="0" />
        </el-form-item>
        <el-form-item label="兑换截止时间">
          <el-date-picker
            v-model="redeemBefore"
            type="datetime"
            placeholder="选择未来时间"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="generationOpen = false">取消</el-button>
        <el-button type="primary" :loading="generating" @click="generate">
          生成并下载
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="revealOpen"
      title="完整兑换码"
      width="min(520px, 92vw)"
      @closed="clearReveal"
    >
      <el-alert
        title="本次查看已写入平台审计。请仅发送给预期接收者，不要复制到日志或备注。"
        type="warning"
        :closable="false"
      />
      <p class="revealed-code" data-testid="revealed-redemption-code">
        {{ revealedCode || '读取中…' }}
      </p>
    </el-dialog>
  </main>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'

import {
  generatePlatformRedemptionCodeBatch,
  listPlatformRedemptionCodes,
  revealPlatformRedemptionCode,
  revokePlatformRedemptionCode,
  type PlatformRedemptionCodeItem,
  type PlatformRedemptionCodeStatus,
} from '@/api/platformIdentity'

const statusOptions: PlatformRedemptionCodeStatus[] = [
  'active', 'reserved', 'redeemed', 'revoked', 'expired', 'recovery_revoked',
]
const router = useRouter()
const items = ref<PlatformRedemptionCodeItem[]>([])
const status = ref<PlatformRedemptionCodeStatus | ''>('')
const loading = ref(false)
const page = ref(1)
const pageSize = 20
const pages = ref(0)
const total = ref(0)
const generationOpen = ref(false)
const generating = ref(false)
const batchName = ref('Core 兑换码')
const channel = ref('direct_sales')
const internalNote = ref('')
const quantity = ref(1)
const durationDaysInput = ref(365)
const redeemBefore = ref<Date | null>(null)
const generationRequestId = ref(crypto.randomUUID())
const revealOpen = ref(false)
const revealedCode = ref('')

const load = async () => {
  loading.value = true
  try {
    const result = await listPlatformRedemptionCodes({
      page: page.value,
      page_size: pageSize,
      ...(status.value ? { status: status.value } : {}),
    })
    items.value = result.items
    total.value = result.total
    pages.value = result.pages
  } catch (error) {
    items.value = []
    ElMessage.error(error instanceof Error ? error.message : '无法读取兑换码')
  } finally {
    loading.value = false
  }
}

const resetAndLoad = () => {
  page.value = 1
  void load()
}

const movePage = (delta: number) => {
  page.value += delta
  void load()
}

const generate = async () => {
  if (!batchName.value.trim() || !redeemBefore.value) {
    ElMessage.warning('请填写批次名称和未来兑换截止时间')
    return
  }
  generating.value = true
  try {
    const result = await generatePlatformRedemptionCodeBatch({
      generation_request_id: generationRequestId.value,
      name: batchName.value,
      quantity: quantity.value,
      service_duration_days: durationDaysInput.value,
      redeem_before: redeemBefore.value.toISOString(),
      channel: channel.value.trim() || null,
      internal_note: internalNote.value.trim() || null,
    })
    if (result.created && result.export_csv && result.export_filename) {
      downloadCsv(result.export_csv, result.export_filename)
      ElMessage.success('兑换码已生成；一次性 CSV 已下载')
    } else {
      ElMessage.info('该请求已提交过；历史批次不会再次导出明文')
    }
    generationRequestId.value = crypto.randomUUID()
    generationOpen.value = false
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '无法生成兑换码')
  } finally {
    generating.value = false
  }
}

const reveal = async (item: PlatformRedemptionCodeItem) => {
  clearReveal()
  revealOpen.value = true
  try {
    const result = await revealPlatformRedemptionCode(item.code_id)
    if (revealOpen.value) revealedCode.value = result.code
  } catch (error) {
    revealOpen.value = false
    clearReveal()
    ElMessage.error(error instanceof Error ? error.message : '无法查看兑换码')
  }
}

const revoke = async (item: PlatformRedemptionCodeItem) => {
  try {
    await ElMessageBox.confirm(
      `确定撤销 ${item.masked_code}？撤销后不能恢复。`,
      '撤销兑换码',
      { type: 'warning', confirmButtonText: '撤销', cancelButtonText: '取消' },
    )
    await revokePlatformRedemptionCode(item.code_id, {
      expected_row_version: item.row_version,
      reason_code: 'operator_revoked',
    })
    ElMessage.success('兑换码已撤销')
    await load()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error instanceof Error ? error.message : '无法撤销兑换码')
  }
}

const clearReveal = () => {
  revealedCode.value = ''
}

const durationDays = (seconds: number) => seconds / 86_400

const formatTime = (value: string) => new Intl.DateTimeFormat('zh-CN', {
  dateStyle: 'medium',
  timeStyle: 'medium',
  timeZone: 'Asia/Shanghai',
}).format(new Date(value))

const outcomeLabel = (item: PlatformRedemptionCodeItem) => {
  if (item.replacement_status === 'issued') return '已补发新兑换码'
  if (item.replacement_status === 'integrity_blocked') {
    return '一致性异常，未补发'
  }
  if (item.status === 'reserved') {
    return item.reserved_attempt_status
      ? `开户处理中：${item.reserved_attempt_status}`
      : '开户处理中'
  }
  if (item.status === 'redeemed') {
    return item.redeemed_tenant_id
      ? `已用于租户 ${item.redeemed_tenant_id}`
      : '已兑换'
  }
  if (item.status === 'revoked') return item.revocation_reason_code || '已撤销'
  if (item.status === 'recovery_revoked') return '灾备恢复后作废'
  return '-'
}

function downloadCsv(contents: string, filename: string): void {
  const blob = new Blob([contents], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

onMounted(load)
onBeforeUnmount(clearReveal)
</script>

<style scoped>
.codes-page { min-height: 100vh; padding: 24px; background: #f5f7fa; }
.page-header, .header-actions, .filters, .pager { display: flex; align-items: center; }
.page-header { justify-content: space-between; gap: 20px; }
.header-actions, .filters { gap: 12px; }
.filters { margin-bottom: 16px; }
.pager { justify-content: center; gap: 16px; margin-top: 18px; }
.eyebrow, .secondary { color: #909399; }
.eyebrow { margin: 0; font-size: 12px; text-transform: uppercase; }
h1 { margin: 4px 0; }
.secondary { margin-top: 4px; font-size: 12px; overflow-wrap: anywhere; }
.generation-form { margin-top: 18px; }
.revealed-code {
  margin: 18px 0 0;
  padding: 18px;
  overflow-wrap: anywhere;
  font: 600 20px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
  letter-spacing: .08em;
  text-align: center;
  background: #f5f7fa;
  border-radius: 8px;
  user-select: text;
}
@media (max-width: 700px) {
  .codes-page { padding: 12px; }
  .page-header { align-items: flex-start; flex-direction: column; }
}
</style>

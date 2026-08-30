<template>
  <el-drawer
    :model-value="modelValue"
    title="待归还"
    size="920px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="returns-content" v-loading="loading">
      <el-empty
        v-if="!loading && groups.length === 0"
        description="暂无待归还订单"
      />

      <div v-else class="return-groups">
        <section
          v-for="group in groups"
          :key="group.key"
          class="return-group"
          :class="`return-group--${group.key}`"
          data-testid="pending-return-group"
        >
          <h3 class="group-title">
            {{ group.label }}（{{ group.rentals.length }}）
          </h3>

          <div class="table-scroll">
            <table class="returns-table">
              <thead>
                <tr>
                  <th>设备</th>
                  <th>租赁时间</th>
                  <th>地址</th>
                  <th>租赁人 / 电话</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="rental in group.rentals" :key="rental.id">
                  <td class="model-cell">
                    <div>{{ rental.device_model }}</div>
                    <div class="device-name">
                      机器编号：{{ rental.device_name || '-' }}
                    </div>
                  </td>
                  <td class="date-cell">
                    <div>{{ rental.start_date }} 至 {{ rental.end_date }}</div>
                    <div class="due-date">应归还：{{ rental.due_date }}</div>
                  </td>
                  <td class="address-cell">{{ rental.destination || '-' }}</td>
                  <td class="phone-cell">
                    <div class="customer-name">
                      {{ rental.customer_name || '-' }}
                    </div>
                    <div v-if="rental.customer_phone" class="phone-line">
                      <a :href="`tel:${rental.customer_phone}`">
                        {{ rental.customer_phone }}
                      </a>
                      <el-button
                        link
                        type="primary"
                        :icon="CopyDocument"
                        class="copy-phone-button"
                        data-test="copy-phone"
                        title="复制电话号码"
                        :aria-label="`复制电话号码 ${rental.customer_phone}`"
                        @click="copyPhone(rental.customer_phone)"
                      />
                    </div>
                    <span v-else>-</span>
                  </td>
                  <td class="action-cell">
                    <el-button
                      type="success"
                      size="small"
                      :loading="updatingIds.has(rental.id)"
                      :disabled="readOnly || updatingIds.has(rental.id)"
                      data-test="mark-returned"
                      @click="emit('mark-returned', rental.id)"
                    >
                      标记为已寄回
                    </el-button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { CopyDocument } from '@element-plus/icons-vue'

import type { PendingReturn } from '@/types/pendingReturn'

const props = defineProps<{
  modelValue: boolean
  rentals: PendingReturn[]
  loading: boolean
  updatingIds: Set<number>
  readOnly?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'mark-returned': [rentalId: number]
}>()

const fallbackCopy = (text: string): boolean => {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    textarea.remove()
  }
}

const copyPhone = async (phone: string) => {
  let copied = false
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(phone)
      copied = true
    }
  } catch {
    copied = false
  }
  if (!copied) copied = fallbackCopy(phone)
  if (copied) ElMessage.success('电话号码已复制')
  else ElMessage.error('复制失败，请手动复制电话号码')
}

const groups = computed(() => [
  {
    key: 'today',
    label: '今日',
    rentals: props.rentals.filter((item) => item.overdue_days === 0),
  },
  {
    key: 'one-to-three',
    label: '逾期 1–3 天',
    rentals: props.rentals.filter(
      (item) => item.overdue_days >= 1 && item.overdue_days <= 3,
    ),
  },
  {
    key: 'four-to-seven',
    label: '逾期 4–7 天',
    rentals: props.rentals.filter(
      (item) => item.overdue_days >= 4 && item.overdue_days <= 7,
    ),
  },
  {
    key: 'over-seven',
    label: '逾期超过 7 天',
    rentals: props.rentals.filter((item) => item.overdue_days >= 8),
  },
].filter((group) => group.rentals.length > 0))
</script>

<style scoped>
.returns-content {
  min-height: 180px;
}

.return-groups {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.return-group {
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}

.group-title {
  margin: 0;
  padding: 11px 14px;
  border-left: 4px solid var(--el-color-primary);
  background: var(--el-fill-color-light);
  color: var(--el-text-color-primary);
  font-size: 15px;
  font-weight: 600;
}

.return-group--one-to-three .group-title {
  border-left-color: var(--el-color-warning);
}

.return-group--four-to-seven .group-title,
.return-group--over-seven .group-title {
  border-left-color: var(--el-color-danger);
}

.table-scroll {
  overflow-x: auto;
}

.returns-table {
  width: 100%;
  min-width: 780px;
  border-collapse: collapse;
  color: var(--el-text-color-primary);
}

.returns-table th,
.returns-table td {
  padding: 12px 10px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  text-align: left;
  vertical-align: middle;
}

.returns-table tbody tr:last-child td {
  border-bottom: 0;
}

.returns-table th {
  background: var(--el-fill-color-lighter);
  color: var(--el-text-color-regular);
  font-size: 13px;
  font-weight: 600;
}

.returns-table tbody tr:hover {
  background: var(--el-fill-color-lighter);
}

.model-cell {
  min-width: 140px;
  font-weight: 600;
}

.device-name {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 400;
}

.date-cell {
  min-width: 190px;
  white-space: nowrap;
}

.due-date {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.address-cell {
  min-width: 220px;
  max-width: 320px;
  line-height: 1.5;
}

.phone-cell {
  min-width: 120px;
  white-space: nowrap;
}

.customer-name {
  font-weight: 600;
}

.phone-line {
  display: flex;
  align-items: center;
  gap: 3px;
  margin-top: 4px;
}

.phone-cell a {
  color: var(--el-color-primary);
  text-decoration: none;
}

.copy-phone-button {
  min-height: 20px;
  padding: 2px;
}

.action-cell {
  min-width: 130px;
  white-space: nowrap;
}
</style>

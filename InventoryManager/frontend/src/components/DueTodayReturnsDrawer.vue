<template>
  <el-drawer
    :model-value="modelValue"
    title="今日应归还"
    size="min(920px, 96vw)"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="returns-content" v-loading="loading">
      <el-empty
        v-if="!loading && rentals.length === 0"
        description="今天暂无应归还订单"
      />

      <div v-else class="table-scroll">
        <table class="returns-table">
          <thead>
            <tr>
              <th>手机型号</th>
              <th>租赁时间</th>
              <th>地址</th>
              <th>电话</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="rental in rentals" :key="rental.id">
              <td class="model-cell">{{ rental.device_model }}</td>
              <td class="date-cell">
                {{ rental.start_date }} 至 {{ rental.end_date }}
              </td>
              <td class="address-cell">{{ rental.destination || '-' }}</td>
              <td class="phone-cell">
                <a
                  v-if="rental.customer_phone"
                  :href="`tel:${rental.customer_phone}`"
                >
                  {{ rental.customer_phone }}
                </a>
                <span v-else>-</span>
              </td>
              <td class="action-cell">
                <el-button
                  type="success"
                  size="small"
                  :loading="updatingIds.has(rental.id)"
                  :disabled="updatingIds.has(rental.id)"
                  @click="emit('mark-returned', rental.id)"
                >
                  标记为已寄回
                </el-button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import type { DueTodayRental } from '@/types/dueTodayRental'

defineProps<{
  modelValue: boolean
  rentals: DueTodayRental[]
  loading: boolean
  updatingIds: Set<number>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'mark-returned': [rentalId: number]
}>()
</script>

<style scoped>
.returns-content {
  min-height: 180px;
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

.returns-table th {
  background: var(--el-fill-color-light);
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

.date-cell {
  min-width: 190px;
  white-space: nowrap;
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

.phone-cell a {
  color: var(--el-color-primary);
  text-decoration: none;
}

.action-cell {
  min-width: 130px;
  white-space: nowrap;
}
</style>

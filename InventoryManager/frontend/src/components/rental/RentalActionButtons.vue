<template>
  <div class="rental-action-buttons">
    <!-- 顶部操作按钮 -->
    <div class="top-actions">
      <el-button
        type="success"
        size="small"
        @click="openContract"
        :disabled="!rental"
      >
        <el-icon><Document /></el-icon>
        租赁合同
      </el-button>
      <el-button
        type="warning"
        size="small"
        @click="openShippingOrder"
        :disabled="!rental"
      >
        <el-icon><Box /></el-icon>
        发货单
      </el-button>
      <el-tooltip
        :content="canShipToXianyu ? '' : '缺少闲鱼订单号或快递单号'"
        :disabled="canShipToXianyu"
        placement="top"
      >
        <el-button
          type="primary"
          size="small"
          @click="handleShipToXianyu"
          :disabled="!canShipToXianyu || shippingToXianyu"
          :loading="shippingToXianyu"
        >
          <el-icon><Van /></el-icon>
          发货到闲鱼
        </el-button>
      </el-tooltip>
      <el-button
        type="danger"
        size="small"
        @click="handleDelete"
        :disabled="!rental || submitting"
      >
        <el-icon><Delete /></el-icon>
        删除租赁
      </el-button>
    </div>

    <!-- 状态提示 -->
    <div v-if="loadingLatestData" class="loading-tip">
      <el-icon class="is-loading"><Loading /></el-icon>
      正在获取最新数据...
    </div>

    <div v-if="latestDataError" class="error-tip">
      <el-icon><Warning /></el-icon>
      {{ latestDataError }}
    </div>

  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Document, Box, Loading, Warning, Delete, Van } from '@element-plus/icons-vue'
import type { Rental } from '@/stores/gantt'

interface Props {
  rental: Rental | null
  loadingLatestData: boolean
  latestDataError: string | null
  submitting: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'open-contract': []
  'open-shipping-order': []
  'delete': []
  'close': []
  'submit': []
  'ship-to-xianyu': []
}>()

// State
const shippingToXianyu = ref(false)

// Computed
const canShipToXianyu = computed(() => {
  return !!(props.rental?.xianyu_order_no && props.rental?.ship_out_tracking_no)
})

const openContract = () => {
  emit('open-contract')
}

const openShippingOrder = () => {
  emit('open-shipping-order')
}

const handleClose = () => {
  emit('close')
}

const handleSubmit = () => {
  emit('submit')
}

const handleDelete = () => {
  emit('delete')
}

const handleShipToXianyu = () => {
  emit('ship-to-xianyu')
}
</script>

<style scoped>
.top-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.loading-tip, .error-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 14px;
}

.loading-tip {
  background: var(--el-color-info-light-9);
  color: var(--el-color-info);
  border: 1px solid var(--el-color-info-light-8);
}

.error-tip {
  background: var(--el-color-warning-light-9);
  color: var(--el-color-warning-dark-2);
  border: 1px solid var(--el-color-warning-light-8);
}

.dialog-footer {
  text-align: right;
}
</style>
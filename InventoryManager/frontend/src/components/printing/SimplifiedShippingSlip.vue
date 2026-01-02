<template>
  <div class="simplified-slip" :style="{ width: `${width}px` }">
    <!-- Order number section -->
    <div class="order-section">
      <div class="order-number">订单号: RNT-{{ rental.id }}</div>
    </div>

    <!-- Customer info section -->
    <div class="section customer-section">
      <div class="info-row">
        <span class="label">收货人:</span>
        <span class="value">{{ rental.customer_name }}</span>
      </div>
      <div class="info-row">
        <span class="label">电话:</span>
        <span class="value">{{ maskPhone(rental.customer_phone) }}</span>
      </div>
      <div class="info-row">
        <span class="label">地址:</span>
        <span class="value">{{ rental.destination || '未知' }}</span>
      </div>
    </div>

    <!-- Device info section -->
    <div class="section device-section">
      <div class="info-row">
        <span class="label">设备:</span>
        <span class="value">{{ rental.device.name }}</span>
      </div>
      <div class="info-row">
        <span class="label">序列号:</span>
        <span class="value">{{ rental.device.serial_number }}</span>
      </div>
      <div class="info-row" v-if="hasAccessories">
        <span class="label">附件:</span>
        <span class="value">{{ accessoriesSummary }}</span>
      </div>
    </div>

    <!-- Rental period section -->
    <div class="section period-section">
      <div class="info-row">
        <span class="label">租期:</span>
        <span class="value">{{ rental.start_date }} ~ {{ rental.end_date }}</span>
      </div>
      <div class="info-row">
        <span class="label">归还:</span>
        <span class="value highlight">{{ rental.end_date }} 16:00前</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  rental: {
    id: number
    customer_name: string
    customer_phone: string
    destination: string
    device: {
      name: string
      serial_number: string
      device_model?: { name: string }
    }
    accessories: Array<{
      name: string
      model: string
    }>
    start_date: string
    end_date: string
  }
  width?: number  // Default: 640px (80mm @ 203 DPI)
}

const props = withDefaults(defineProps<Props>(), {
  width: 640
})

// Phone masking function
const maskPhone = (phone: string) => {
  if (!phone || phone.length < 11) return phone
  return phone.slice(0, 3) + '****' + phone.slice(-4)
}

// Accessories summary
const hasAccessories = computed(() => {
  return props.rental.accessories && props.rental.accessories.length > 0
})

const accessoriesSummary = computed(() => {
  if (!hasAccessories.value) return ''
  return props.rental.accessories
    .map(acc => `${acc.name}${acc.model ? ` ${acc.model}` : ''}`)
    .join(', ')
})
</script>

<style scoped>
.simplified-slip {
  background: white;
  font-family: 'Arial', 'Helvetica', '微软雅黑', sans-serif;
  color: black;
  padding: 8px;
  box-sizing: border-box;
}

.order-section {
  text-align: center;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px dashed #000;
}

.order-number {
  font-size: 14px;
  font-weight: bold;
}

.section {
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px dashed #000;
}

.section:last-child {
  border-bottom: none;
}

.info-row {
  display: flex;
  margin-bottom: 4px;
  font-size: 12px;
  line-height: 1.4;
}

.label {
  min-width: 60px;
  font-weight: 500;
  flex-shrink: 0;
}

.value {
  flex: 1;
  word-break: break-all;
}

.value.highlight {
  font-weight: bold;
}

.period-section .value.highlight {
  color: #e74c3c;
}
</style>

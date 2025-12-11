<template>
  <div class="batch-shipping-order-page">
    <!-- 操作栏 (打印时隐藏) -->
    <div class="action-bar print-hide">
      <el-button @click="goBack" type="primary">
        <el-icon><ArrowLeft /></el-icon>
        返回甘特图
      </el-button>
      <span class="order-count">共 {{ rentals.length }} 个订单</span>
      <el-button @click="handlePrint" type="success" :disabled="rentals.length === 0">
        <el-icon><Printer /></el-icon>
        打印所有发货单
      </el-button>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="loading-container print-hide">
      <el-icon class="is-loading"><Loading /></el-icon>
      <p>正在加载订单...</p>
    </div>

    <!-- 错误提示 -->
    <el-alert
      v-if="error"
      type="error"
      :closable="false"
      class="print-hide"
      style="margin: 20px;"
    >
      {{ error }}
      <el-button @click="fetchRentals" type="primary" size="small" style="margin-left: 12px;">
        重试
      </el-button>
    </el-alert>

    <!-- 发货单列表 -->
    <div v-if="!loading && rentals.length > 0">
      <div
        v-for="(rental, index) in rentals"
        :key="rental.id"
        class="shipping-order-page-wrapper"
        :class="{ 'last-order': index === rentals.length - 1 }"
      >
        <!-- 发货单内容 (复用 ShippingOrderView 的结构) -->
        <div class="shipping-order-container">
          <div class="content-section">
            <!-- 页眉 -->
            <div class="header-section">
              <div class="header-content">
                <img src="/src/assets/logo.jpg" alt="光影租界" class="logo" />
                <h2><el-icon><Document /></el-icon> 出货单</h2>
              </div>
              <!-- Barcode for Rental ID -->
              <div class="barcode-container">
                <svg :id="`barcode${rental.id}`" class="barcode"></svg>
                <div class="barcode-label">订单识别码</div>
              </div>
            </div>

            <!-- 客户信息 -->
            <div class="info-card customer-info">
              <div class="info-grid">
                <div class="info-item">
                  <span class="info-label"><el-icon><User /></el-icon> 买家ID：</span>
                  <span class="info-value">{{ rental.customer_name || '-' }}</span>
                </div>
                <div class="info-item">
                  <span class="info-label"><el-icon><Phone /></el-icon> 电话：</span>
                  <span class="info-value">{{ rental.customer_phone || '-' }}</span>
                </div>
                <div class="info-item full-width">
                  <span class="info-label"><el-icon><Location /></el-icon> 收货地址：</span>
                  <span class="info-value">{{ rental.destination || '-' }}</span>
                </div>
              </div>
            </div>

            <!-- 产品信息表格 -->
            <table class="product-table">
              <thead>
                <tr>
                  <th style="width: 8%;">序号</th>
                  <th style="width: 40%;">品名</th>
                  <th style="width: 8%;">数量</th>
                  <th style="width: 20%;">资产编号/序列号</th>
                  <th style="width: 24%;">附件说明</th>
                </tr>
              </thead>
              <tbody>
                <!-- 主设备 -->
                <tr class="main-product">
                  <td class="serial-number">1</td>
                  <td class="device-name">{{ rental.device?.device_model?.name || rental.device?.name || '-' }}</td>
                  <td class="serial-number">1台</td>
                  <td class="serial-number">{{ rental.device?.name || '-' }}
                    <br />
                    {{ rental.device?.serial_number || '-' }}</td>
                  <td class="serial-number">{{ getDefaultAccessories(rental) }}</td>
                </tr>
                <!-- 个性化附件 -->
                <tr v-for="(accessory, accIndex) in getPersonalizedAccessories(rental)" :key="`personal-${accessory.id}`">
                  <td>{{ accIndex + 2 }}</td>
                  <td>{{ accessory.model || accessory.name }}</td>
                  <td>1个</td>
                  <td>{{ accessory.name || '-' }}</td>
                  <td>个性化附件</td>
                </tr>
              </tbody>
            </table>

            <!-- 时间和寄回信息 -->
            <div class="info-card combined-info">
              <div class="info-grid">
                <!-- 时间信息 -->
                <div class="time-section">
                  <h6><el-icon><Calendar /></el-icon> 租赁时间信息</h6>
                  <div class="info-row compact">
                    <span class="info-label">寄出时间：</span>
                    <span class="info-value">{{ formatDate(rental.ship_out_time) }}</span>
                  </div>
                  <div class="info-row compact">
                    <span class="info-label">租赁时间：</span>
                    <span class="info-value">{{ rental.start_date }} 至 {{ rental.end_date }}</span>
                  </div>
                  <div class="info-row compact">
                    <span class="info-label">归还时间：</span>
                    <span class="info-value return-date">{{ getReturnDate(rental) }} 下午 16:00 前</span>
                  </div>
                  <div class="info-row compact">
                    <span class="info-label">租赁天数：</span>
                    <span class="info-value">{{ getRentalDays(rental) }} 天</span>
                  </div>
                </div>

                <!-- 寄回信息 -->
                <div class="return-section">
                  <h6><el-icon><Box /></el-icon> 寄回信息</h6>
                  <div class="info-row compact">
                    <span class="info-label">寄回地址：</span>
                    <span class="info-value">广东省深圳市南山区西丽街道松坪村竹苑9栋4单元415</span>
                  </div>
                  <div class="info-row compact">
                    <span class="info-label">收件人：</span>
                    <span class="info-value">张女士</span>
                  </div>
                  <div class="info-row compact">
                    <span class="info-label">电话：</span>
                    <span class="info-value">13510224947</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 重要提醒 -->
            <div class="reminder-section">
              <div class="reminder-text">
                <el-icon><Warning /></el-icon>
                为避免器材损坏并尽快返还您押金，请在归还日下午16:00将此发货单随货发<span class="sf-express">顺丰</span>（寄付）寄回
              </div>
              <div class="contact-text">
                小二微信：vacuumdust，13510224947
              </div>
            </div>

            <!-- 底部二维码区域 -->
            <div class="qr-codes-section">
              <div class="qr-code-item">
                <img src="/src/assets/镜头安装教程.png" alt="镜头安装教程" class="qr-code" />
                <div class="qr-code-label">镜头安装教程</div>
              </div>
              <div class="qr-code-item">
                <img src="/src/assets/拍摄调试教程.png" alt="拍摄调试教程" class="qr-code" />
                <div class="qr-code-label">拍摄调试教程</div>
              </div>
              <div class="qr-code-item">
                <img src="/src/assets/照片传输教程.png" alt="照片传输教程" class="qr-code" />
                <div class="qr-code-label">照片传输教程</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft,
  Printer,
  Loading,
  Document,
  User,
  Phone,
  Location,
  Calendar,
  Box,
  Warning
} from '@element-plus/icons-vue'
import axios from 'axios'
import dayjs from 'dayjs'
// @ts-ignore
import JsBarcode from 'jsbarcode'

// Router
const route = useRoute()
const router = useRouter()

// State
const rentals = ref<any[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

// Mounted
onMounted(() => {
  fetchRentals()
})

// Methods
const fetchRentals = async () => {
  try {
    loading.value = true
    error.value = null

    const startDate = route.query.start_date as string
    const endDate = route.query.end_date as string

    if (!startDate || !endDate) {
      error.value = '缺少日期参数'
      return
    }

    const response = await axios.get('/api/rentals/by-ship-date', {
      params: {
        start_date: startDate,
        end_date: endDate
      }
    })

    if (response.data.success) {
      // 过滤掉已发货的订单，只打印未发货的发货单
      rentals.value = response.data.data.rentals.filter((r: any) => r.status !== 'shipped')
      if (rentals.value.length === 0) {
        ElMessage.warning('该日期范围内未找到未发货的发货单')
      } else {
        ElMessage.success(`找到 ${rentals.value.length} 个未发货订单`)
        // Generate barcodes after rentals are loaded
        await nextTick()
        // 添加小延迟确保DOM完全渲染
        setTimeout(() => {
          generateBarcodes()
        }, 100)
      }
    } else {
      error.value = response.data.message || '加载订单失败'
    }
  } catch (err: any) {
    console.error('获取租赁记录失败:', err)
    error.value = '加载订单失败,请检查网络连接'
  } finally {
    loading.value = false
  }
}

const generateBarcodes = () => {
  console.log('开始生成条形码，订单数量:', rentals.value.length)
  rentals.value.forEach(rental => {
    const barcodeId = `barcode${rental.id}`
    const svg = document.getElementById(barcodeId)
    console.log(`查找svg ${barcodeId}:`, svg ? '找到' : '未找到')
    if (svg) {
      try {
        JsBarcode(svg, String(rental.id), {
          format: 'CODE128',
          width: 2,
          height: 60,
          displayValue: false, // 不显示条形码下方的默认文字
          margin: 5
        })
        console.log(`Rental ${rental.id} 条形码生成成功`)
      } catch (error) {
        console.error(`Rental ${rental.id} 条形码生成失败:`, error)
      }
    } else {
      console.error(`SVG ${barcodeId} 未找到`)
    }
  })
}

const goBack = () => {
  router.push('/')
}

const handlePrint = () => {
  window.print()
}

const formatDate = (dateString: string | null) => {
  if (!dateString) return '未设置'
  return dayjs(dateString).format('YYYY-MM-DD HH:mm')
}

const getReturnDate = (rental: any) => {
  if (!rental.end_date) return '未设置'
  const endDate = dayjs(rental.end_date)
  return endDate.add(1, 'day').format('YYYY-MM-DD')
}

const getRentalDays = (rental: any) => {
  if (!rental.start_date || !rental.end_date) return 0
  const start = dayjs(rental.start_date)
  const end = dayjs(rental.end_date)
  return end.diff(start, 'day') + 1
}

// 获取默认附件列表
const getDefaultAccessories = (rental: any) => {
  if (!rental.device?.device_model?.default_accessories) {
    return ""
  }

  const accessories = rental.device.device_model.default_accessories

  // 如果是数组，转换为字符串
  if (Array.isArray(accessories)) {
    return accessories.join('、')
  }

  // 如果是字符串，直接返回
  return accessories
}

const getPersonalizedAccessories = (rental: any) => {
  if (!rental.child_rentals) return []
  return rental.child_rentals
    .map((childRental: any) => childRental.device)
    .filter((device: any) => device && device.model && device.model.includes('手柄'))
}
</script>

<style scoped>
/* 页面基础样式 */
.batch-shipping-order-page {
  background-color: #f5f5f5;
  min-height: 100vh;
  padding-bottom: 40px;
}

/* 操作栏样式 */
.action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px;
  background-color: white;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  position: sticky;
  top: 0;
  z-index: 100;
}

.order-count {
  font-size: 16px;
  font-weight: 500;
  color: var(--el-text-color-primary);
}

.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 100px 20px;
  color: var(--el-text-color-secondary);
}

.loading-container .el-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

/* 发货单包装器 */
.shipping-order-page-wrapper {
  page-break-after: always;
  page-break-inside: avoid;
  background-color: white;
  margin: 20px auto;
  max-width: 210mm;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.shipping-order-page-wrapper.last-order {
  page-break-after: auto;
}

/* 复用 ShippingOrderView 的样式 */
.shipping-order-container {
  padding: 20px;
}

.content-section {
  max-width: 100%;
}

.header-section {
  text-align: center;
  margin-bottom: 20px;
  border-bottom: 2px solid #409eff;
  padding-bottom: 15px;
  position: relative;
}

.header-content {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 20px;
}

.barcode-container {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  padding: 8px;
  background: white;
  border-radius: 4px;
  text-align: center;
}

.barcode {
  display: block;
}

.barcode-label {
  font-size: 12px;
  color: #333;
  margin-top: 4px;
  font-weight: bold;
}

.logo {
  width: 60px;
  height: 60px;
  border-radius: 8px;
}

.header-content h2 {
  margin: 0;
  color: #303133;
  font-size: 28px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.info-card {
  background-color: #f8f9fa;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.info-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.info-item.full-width {
  grid-column: 1 / -1;
}

.info-label {
  font-weight: 600;
  color: #202121;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 4px;
}

.info-value {
  color: #303133;
  word-break: break-all;
}

.product-table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 16px;
}

.product-table th,
.product-table td {
  border: 1px solid #dcdfe6;
  padding: 12px;
  text-align: left;
}

.product-table th {
  background-color: #f2f6fc;
  font-weight: 600;
  color: #2d2d2d;
}

.product-table .main-product {
  background-color: #ecf5ff;
}

.device-name {
  font-weight: 600;
  color: #303133;
}

.serial-number {
  color: #323333;
  font-size: 14px;
}

/* 附件行样式 - 加深颜色提高可读性 */
.product-table tbody tr:not(.main-product) td {
  color: #000;
  font-weight: 500;
}

.combined-info .info-grid {
  grid-template-columns: 1fr 1fr;
}

.time-section h6,
.return-section h6 {
  margin: 0 0 12px 0;
  color: #409eff;
  font-size: 16px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.info-row {
  display: flex;
  margin-bottom: 8px;
}

.info-row.compact {
  margin-bottom: 6px;
}

.info-row .info-label {
  min-width: 90px;
}

.return-date {
  color: #f56c6c;
  font-weight: 600;
}

.reminder-section {
  background-color: #fff3e0;
  border: 2px solid #ff9800;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}

.reminder-text {
  font-size: 15px;
  color: #e65100;
  font-weight: 500;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.sf-express {
  color: #f56c6c;
  font-weight: 700;
  font-size: 16px;
}

.contact-text {
  font-size: 14px;
  color: #2b2b2b;
}

.qr-codes-section {
  display: flex;
  justify-content: space-around;
  align-items: center;
  padding: 16px 0;
  border-top: 1px solid #e0e0e0;
}

.qr-code-item {
  text-align: center;
}

.qr-code {
  width: 120px;
  height: 120px;
  border: 1px solid #e0e0e0;
  border-radius: 4px;
}

.qr-code-label {
  margin-top: 8px;
  font-size: 13px;
  color: #353536;
}

/* 打印样式 */
@media print {
  .print-hide {
    display: none !important;
  }

  .shipping-order-page-wrapper {
    page-break-after: always;
    page-break-inside: avoid !important;
    margin: 0;
    box-shadow: none;
    max-width: 100%;
    height: 100%;
  }

  .shipping-order-page-wrapper.last-order {
    page-break-after: auto;
  }

  @page {
    size: A4;
    margin: 8mm;
  }

  /* 强制所有子元素不分页 */
  .shipping-order-container,
  .content-section,
  .header-section,
  .info-card,
  .product-table,
  .reminder-section,
  .qr-codes-section {
    page-break-inside: avoid !important;
  }

  table {
    page-break-inside: avoid !important;
  }

  .batch-shipping-order-page {
    background-color: white;
    padding: 0;
  }

  /* 压缩打印尺寸以适应一页 */
  .shipping-order-container {
    padding: 8px;
    font-size: 13px;
  }

  .header-section {
    margin-bottom: 8px;
    padding-bottom: 8px;
  }

  .header-content h2 {
    font-size: 22px;
  }

  .logo {
    width: 50px;
    height: 50px;
  }

  .info-card {
    padding: 10px;
    margin-bottom: 8px;
  }

  .info-label {
    font-size: 12px;
  }

  .info-value {
    font-size: 12px;
  }

  .product-table th,
  .product-table td {
    padding: 6px;
    font-size: 12px;
  }

  .reminder-section {
    padding: 10px;
    margin-bottom: 8px;
  }

  .reminder-text {
    font-size: 13px;
  }

  .contact-text {
    font-size: 12px;
  }

  .qr-codes-section {
    padding: 8px 0;
  }

  .qr-code {
    width: 90px;
    height: 90px;
  }

  .qr-code-label {
    font-size: 11px;
    margin-top: 4px;
  }

  .info-row {
    margin-bottom: 4px;
  }

  h6 {
    font-size: 14px;
    margin-bottom: 6px;
  }
}
</style>

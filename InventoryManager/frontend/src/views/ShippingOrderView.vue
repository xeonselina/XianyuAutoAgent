<template>
  <div class="shipping-order-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <el-button @click="goBack" type="primary" size="large">
        <el-icon><ArrowLeft /></el-icon>
        返回甘特图
      </el-button>
      <h1>发货单</h1>
      <el-button @click="printOrder" type="success" size="large">
        <el-icon><Printer /></el-icon>
        打印发货单
      </el-button>
    </div>

    <!-- 发货单内容 -->
    <div class="shipping-order-container" v-if="rental">
      <div class="content-section">
        <!-- 页眉 -->
        <div class="header-section">
          <div class="header-content">
            <img src="/src/assets/logo.jpg" alt="光影租界" class="logo" />
            <h2><el-icon><Document /></el-icon> 出货单</h2>
          </div>
        </div>

        <!-- 合并的客户信息卡片 -->
        <div class="info-card customer-info">
          <div class="info-grid">
            <div class="info-item">
              <span class="info-label"><el-icon><User /></el-icon> 买家ID：</span>
              <span class="info-value">{{ rental?.customer_name }}</span>
            </div>
            <div class="info-item">
              <span class="info-label"><el-icon><Phone /></el-icon> 电话：</span>
              <span class="info-value">{{ rental?.customer_phone }}</span>
            </div>
            <div class="info-item full-width">
              <span class="info-label"><el-icon><Location /></el-icon> 收货地址：</span>
              <span class="info-value">{{ rental?.destination }}</span>
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
              <th style="width: 20%;">资产编号</th>
              <th style="width: 24%;">序列号/附件说明</th>
            </tr>
          </thead>
          <tbody>
            <!-- 主设备 -->
            <tr class="main-product">
              <td>1</td>
              <td class="device-name">{{ rental?.device?.device_model?.display_name || rental?.device_name }}</td>
              <td>1台</td>
              <td>{{ rental?.device_name }}</td>
              <td class="serial-number">{{ deviceInfo?.serial_number || rental?.device?.serial_number || '-' }}/{{ getDefaultAccessories() }}</td>
            </tr>
            <!-- 个性化附件 -->
            <tr v-for="(accessory, index) in getPersonalizedAccessories()" :key="`personal-${accessory.id}`">
              <td>{{ index + 2 }}</td>
              <td>{{ accessory.model }}</td>
              <td>1个</td>
              <td>{{ accessory.name || '-' }}</td>
              <td>个性化附件</td>
            </tr>
          </tbody>
        </table>

        <!-- 合并的时间和寄回信息 -->
        <div class="info-card combined-info">
          <div class="info-grid">
            <!-- 时间信息 -->
            <div class="time-section">
              <h6><el-icon><Calendar /></el-icon> 租赁时间信息</h6>
              <div class="info-row compact">
                <span class="info-label">寄出时间：</span>
                <span class="info-value">{{ formatDate(rental?.ship_out_time) }}</span>
              </div>
              <div class="info-row compact">
                <span class="info-label">租赁时间：</span>
                <span class="info-value">{{ rental?.start_date }} 至 {{ rental?.end_date }}</span>
              </div>
              <div class="info-row compact">
                <span class="info-label">归还时间：</span>
                <span class="info-value return-date">{{ getReturnDate() }} 中午 12:00 前</span>  
              </div>
              <div class="info-row compact">
                <span class="info-label">租赁天数：</span>
                <span class="info-value">{{ rentalDays }} 天</span>
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
            为避免器材损坏并尽快返还您押金，请在归还日中午12:00将此发货单随货发<span class="sf-express">顺丰</span>（寄付）寄回
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
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { 
  ArrowLeft, 
  Printer, 
  Document, 
  User, 
  Phone, 
  Location, 
  Calendar, 
  ChatLineRound, 
  Box, 
  Warning, 
  Money
} from '@element-plus/icons-vue'
import { useGanttStore, type Rental } from '../stores/gantt'
import dayjs from 'dayjs'

const router = useRouter()
const route = useRoute()
const ganttStore = useGanttStore()

// 响应式状态
const rental = ref<Rental | null>(null)
const deviceInfo = ref<any>(null)

// 计算属性
const rentalDays = computed(() => {
  if (!rental.value?.start_date || !rental.value?.end_date) return 0
  const start = dayjs(rental.value.start_date)
  const end = dayjs(rental.value.end_date)
  return end.diff(start, 'day') + 1
})

const customerMessage = computed(() => {
  // 这里可以从rental数据中获取买家留言，如果没有对应字段，可以扩展数据结构
  return ''
})

const deposit = computed(() => {
  if (!rental.value?.device_name) return 5000
  const deviceName = rental.value.device_name.toLowerCase()
  if (deviceName.includes('iphone') || deviceName.includes('华为') || deviceName.includes('huawei')) {
    return 8000
  }
  return 5000
})

const rentalFee = computed(() => {
  return 100
})

const totalFee = computed(() => {
  return rentalFee.value * rentalDays.value
})

// 方法
const goBack = () => {
  router.push('/gantt')
}

const formatDate = (dateString?: string) => {
  if (!dateString) return '-'
  return dayjs(dateString).format('YYYY-MM-DD')
}

const getReturnDate = () => {
  if (!rental.value?.end_date) return '-'
  return dayjs(rental.value.end_date).add(1, 'day').format('YYYY-MM-DD')
}

const printOrder = () => {
  handlePrint()
}

const handlePrint = () => {
  console.log('开始打印流程...')
  const printStyle = document.createElement('style')
  printStyle.textContent = `
    @media print {
      @page { size: A4; margin: 1.5cm; }
      body { margin: 0 !important; padding: 0 !important; }
      .shipping-order-page { display: block !important; position: static !important; max-height: none !important; height: auto !important; overflow: visible !important; transform: none !important; }
      .shipping-order-container { display: block !important; position: static !important; max-height: none !important; height: auto !important; overflow: visible !important; transform: none !important; }
      .page-header { display: none !important; }
    }
  `
  document.head.appendChild(printStyle)
  document.body.offsetHeight // Force reflow
  console.log('打印样式已应用，准备打印...')
  setTimeout(() => {
    try { window.print(); console.log('打印命令已执行') }
    catch (error) { console.error('打印失败:', error) }
    finally { document.head.removeChild(printStyle) }
  }, 200)
}

// 获取默认附件列表
const getDefaultAccessories = () => {
  if (!rental.value?.device?.device_model?.default_accessories) {
    return ""
  }

  const accessories = rental.value.device.device_model.default_accessories

  // 如果是数组，转换为字符串
  if (Array.isArray(accessories)) {
    return accessories.join('、')
  }

  // 如果是字符串，直接返回
  return accessories
}

// 获取个性化附件列表（从租赁记录的子租赁中获取）
const getPersonalizedAccessories = () => {
  if (!rental.value?.accessories) {
    return []
  }
  return rental.value.accessories.filter(acc => acc.is_accessory)
}

// 生命周期
onMounted(async () => {
  const rentalId = route.params.id
  if (rentalId) {
    const rentalData = await ganttStore.getRentalById(Number(rentalId))
    if (rentalData) {
      rental.value = rentalData
    }
  }
})
</script>

<style scoped>
.shipping-order-page {
  padding: 15px;
  background: #f5f5f5;
  min-height: 100vh;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  background: white;
  padding: 15px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.page-header h1 {
  margin: 0;
  color: #333;
}

.shipping-order-container {
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  overflow: hidden;
  font-family: "Microsoft YaHei", "微软雅黑", "SimHei", "黑体", Arial, sans-serif;
}

.content-section {
  padding: 20px;
}

.header-section {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  padding: 15px;
  text-align: center;
  margin: -20px -20px 20px -20px;
  position: relative;
}

.header-content {
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}

.logo {
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  height: 50px;
  width: auto;
  filter: brightness(1.2) contrast(1.1);
}

.header-section h1 {
  font-size: 2rem;
  font-weight: bold;
  margin-bottom: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
}

.platform-info {
  font-size: 1rem;
  opacity: 0.9;
  margin-top: 5px;
}

.info-card {
  background: #f8f9fa;
  border-radius: 8px;
  padding: 15px;
  margin-bottom: 15px;
  border-left: 4px solid #1890ff;
}

.info-card h6 {
  font-size: 16px;
  font-weight: bold;
  margin: 0 0 10px 0;
  color: #333;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 新增的网格布局样式 */
.info-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.info-item {
  display: flex;
  align-items: center;
}

.info-item.full-width {
  grid-column: 1 / -1;
}

.info-row {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
}

.info-row.compact {
  margin-bottom: 4px; /* Reduced margin for compact rows */
}

.info-label {
  min-width: 100px;
  font-weight: bold;
  color: #333;
  display: flex;
  align-items: center;
  gap: 8px;
}

.info-value {
  color: #666;
  flex: 1;
}

.product-table {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  background: white;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.product-table th,
.product-table td {
  border: 1px solid #ddd;
  padding: 6px;
  text-align: center;
  color: #333;
}

.product-table th {
  background-color: #f8f9fa;
  font-weight: bold;
  color: #333;
  padding: 8px 6px;
}

.main-product {
  background-color: #f0f8ff;
}

.main-product td {
  color: #333;
}

.device-name {
  font-weight: bold;
  color: #1890ff;
}

.serial-number {
  font-family: monospace;
  color: #666;
}

.product-table td:not(.device-name) {
  color: #333;
}

/* 合并信息卡片的特殊样式 */
.combined-info .info-grid {
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.time-section,
.return-section {
  background: transparent;
  padding: 0;
  border: none;
  margin: 0;
}

.return-section h6 {
  color: #4caf50;
}

.return-section .info-row {
  margin-bottom: 4px;
}

.message-box {
  background: white;
  border: 1px solid #ddd;
  border-radius: 4px;
  padding: 15px;
  min-height: 60px;
  color: #666;
}

.reminder-section {
  background: #fff3cd;
  padding: 12px;
  border-radius: 8px;
  border-left: 4px solid #ffc107;
  margin: 12px 0;
  text-align: center;
}

.reminder-text {
  font-weight: bold;
  color: #856404;
  font-size: 16px;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.contact-text {
  color: #6c757d;
  font-size: 14px;
}

.sf-express {
  font-size: 28px;
  font-weight: bold;
  color: #000000;
}

.return-date {
  font-size: 18px;
  font-weight: bold;
  color: #000000;
  background: #ffffff;
  border: 2px solid #1890ff;
  border-radius: 50px;
  padding: 6px 4px;
  display: inline-block;
  text-align: center;
  min-width: 45px;
}

.qr-codes-section {
  display: flex;
  justify-content: space-around;
  align-items: center;
  margin-top: 20px;
  padding: 15px;
  background: #f8f9fa;
  border-radius: 8px;
  border: 1px solid #e9ecef;
}

.qr-code-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.qr-code {
  width: 100px;
  height: 100px;
  object-fit: contain;
  border: 1px solid #ddd;
  border-radius: 4px;
  background: white;
  padding: 5px;
}

.qr-code-label {
  margin-top: 8px;
  font-size: 12px;
  font-weight: bold;
  color: #333;
  line-height: 1.2;
}

/* 打印样式优化 */
@media print {
  .page-header {
    display: none !important;
  }
  
  .shipping-order-page {
    box-shadow: none;
    margin: 0;
    padding: 0;
    max-height: none;
    overflow: visible;
  }
  
  body {
    background: white;
    font-size: 12px;
    line-height: 1.1;
  }
  
  .header-section h1 {
    font-size: 1.8rem;
  }
  
  .content-section {
    padding: 15px;
  }
  
  .product-table th,
  .product-table td {
    font-size: 11px;
    padding: 4px;
  }
  
  .info-card {
    margin-bottom: 10px;
    padding: 10px;
  }
  
  .info-grid {
    gap: 15px;
  }
  
  .reminder-text {
    font-size: 13px;
  }
  
  .return-date {
    font-size: 16px;
    padding: 6px 4px;
  }
  
  .sf-express {
    font-size: 24px;
  }

  .logo {
    height: 40px;
    filter: brightness(1) contrast(1);
  }

  .qr-codes-section {
    margin-top: 15px;
    padding: 10px;
  }

  .qr-code {
    width: 80px;
    height: 80px;
    padding: 3px;
  }

  .qr-code-label {
    font-size: 10px;
    margin-top: 5px;
  }
}
</style>

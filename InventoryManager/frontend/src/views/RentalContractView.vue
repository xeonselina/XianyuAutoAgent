<template>
  <div class="rental-contract-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <el-button @click="goBack" type="primary" size="large">
        <el-icon><ArrowLeft /></el-icon>
        返回甘特图
      </el-button>
      <h1>租赁合同</h1>
      <el-button @click="printContract" type="success" size="large">
        <el-icon><Printer /></el-icon>
        打印合同
      </el-button>
    </div>

    <!-- 身份证上传区域 -->
    <div class="upload-section">
      <el-card>
        <template #header>
          <div class="card-header">
            <el-icon><Camera /></el-icon>
            <span>上传身份证照片</span>
          </div>
        </template>
        <el-upload
          v-if="!ocrResult"
          class="upload-demo"
          drag
          action="#"
          :auto-upload="false"
          :on-change="handleFileChange"
          :limit="1"
          :show-file-list="false"
          accept="image/*"
          :disabled="!!uploadedFile"
        >
          <el-icon class="el-icon--upload"><upload-filled /></el-icon>
          <div class="el-upload__text">
            将文件拖到此处，或<em>点击上传</em>
          </div>
          <template #tip>
            <div class="el-upload__tip">
              只能上传jpg/png文件，且不超过2MB
            </div>
          </template>
        </el-upload>
        
        <!-- 图片预览和操作 -->
        <div class="image-preview" v-if="uploadedFile">
          <div class="preview-header">
            <span>已选择的身份证照片：</span>
            <el-button @click="clearUploadedFile" size="small" type="primary">重新上传</el-button>
          </div>
          <div class="preview-image">
            <img 
              :src="getImagePreviewUrl()" 
              alt="身份证预览" 
              @click="openImagePreview"
              class="clickable-image"
            />
          </div>
          <div class="preview-status" v-if="ocrLoading">
            <el-icon class="is-loading"><Loading /></el-icon>
            <span>正在识别中...</span>
          </div>
        </div>
      </el-card>
    </div>

    <!-- OCR结果展示 -->
    <div class="ocr-result" v-if="ocrResult">
      <el-card>
        <template #header>
          <div class="card-header">
            <el-icon><Document /></el-icon>
            <span>身份证识别结果</span>
            <el-button @click="clearUploadedFile" size="small" type="info">重新上传</el-button>
          </div>
        </template>
        <div class="ocr-content">
          <div class="ocr-item">
            <span class="label">姓名：</span>
            <el-input v-model="ocrResult.name" placeholder="识别出的姓名" />
          </div>
          <div class="ocr-item">
            <span class="label">身份证号：</span>
            <el-input v-model="ocrResult.idNumber" placeholder="识别出的身份证号" />
          </div>
          <div class="ocr-actions">
            <el-button type="success" @click="fillContract">
              <el-icon><Check /></el-icon>
              填入合同
            </el-button>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 合同内容 -->
    <div class="contract-container" v-if="rental">
      <div class="contract-content">
        <!-- 合同标题 -->
        <div class="contract-header">
          <div class="contract-title">设备租赁合同（{{ rental.device_name }}）</div>
        </div>
        
        <!-- 合同前言 -->
        <div class="contract-section">
          <p style="text-indent: 2em; line-height: 1.8;">根据《中华人民共和国民法典》及相关法律规定，经过双方友好协商，甲乙双方本着诚实守信、平等自愿、公平合理的原则，就乙方租赁甲方电子设备事宜达成如下合同，以资双方共同遵照执行。</p>
        </div>
        
        <!-- 甲乙双方信息表格 -->
        <div class="contract-section">
          <table class="table-contract party-table">
            <tr>
              <th style="width: 50%;">出租方（甲方）：</th>
              <th style="width: 50%;">承租方（乙方）：</th>
            </tr>
            <tr>
              <td style="vertical-align: top; padding: 15px;">
                <div>店铺名：光影租界</div>
                <div>公司名：深圳市光影租赁有限公司</div>
                <div>法人：张孝姝</div>
                <div>组织机构代码：91440300MAEWWJ2G1A</div>
                <div>联系方式：13510224947</div>
              </td>
              <td style="vertical-align: top; padding: 15px;">
                <div>闲鱼ID：{{ rental.customer_name }}</div>
                <div>真实姓名：<el-input v-model="contractForm.customerName" class="contract-input" placeholder="请输入真实姓名" style="width: 150px; display: inline-block; margin-left: 5px;" /></div>
                <div>身份证号：<el-input v-model="contractForm.customerIdNumber" class="contract-input" placeholder="请输入身份证号码" style="width: 200px; display: inline-block; margin-left: 5px;" /></div>
                <div>联系方式：{{ rental.customer_phone }}</div>
              </td>
            </tr>
          </table>
        </div>
        
        <!-- 租赁设备清单 -->
        <div class="contract-section">
          <h6><strong>租赁设备清单</strong></h6>
          <table class="table-contract">
            <tr>
              <th style="width: 40%;">设备名称</th>
              <th style="width: 25%;">序列号</th>
              <th style="width: 10%;">数量</th>
              <th style="width: 25%;">附件说明</th>
            </tr>
            <!-- 主设备 -->
            <tr>
              <td>{{ rental.device?.device_model?.name}}</td>
              <td>{{ rental.device_name }}/{{ deviceSerialNumber }}</td>
              <td>1台</td>
              <td>{{ getDefaultAccessories() }}</td>
            </tr>
            <!-- 个性化附件 -->
            <tr v-for="accessory in getPersonalizedAccessories()" :key="`personal-${accessory.id}`">
              <td>{{ accessory.model }}</td>
              <td>{{ accessory.name || '无' }}</td>
              <td>1个</td>
              <td>个性化附件</td>
            </tr>
          </table>
          <p style="margin-top: 10px;"><strong>注明：</strong>设备总价值约为¥{{ getTotalValue().toFixed(0) }}元。</p>
        </div>
        
        <!-- 租赁期限 -->
        <div class="contract-section">
          <h6><strong>租赁期限</strong></h6>
          <table class="table-contract">
            <tr>
              <th style="width: 50%;">收货日：{{ getReceiptDate(rental.start_date) }}</th>
              <th style="width: 50%;">租赁起止日期：{{ rental.start_date }}至{{ rental.end_date }}</th>
            </tr>
            <tr>
              <th>归还日：{{ getReturnDate(rental.end_date) }}</th>
              <th>总计：{{ rentalDays }}天</th>
            </tr>
          </table>
        </div>
        
        <!-- 押金 -->
        <div class="contract-section">
          <h6><strong>押金</strong></h6>
          <table class="table-contract">
            <tr>
              <th style="width: 25%;">项目</th>
              <th style="width: 25%;">金额</th>
              <th style="width: 25%;">支付方式</th>
              <th style="width: 25%;">退还条件</th>
            </tr>
            <tr>
              <td>押金</td>
              <td>
                <el-input 
                  v-model="contractForm.deposit" 
                  class="contract-input" 
                  placeholder="请输入押金金额" 
                  style="width: 100px; display: inline-block;"
                />
                <span style="margin-left: 5px;">元</span>
              </td>
              <td>闲鱼担保交易</td>
              <td>验收设备无损归还后，24小时内退还</td>
            </tr>
          </table>
        </div>
        
        <!-- 双方权利义务 -->
        <div class="contract-section">
          <h6><strong>双方权利义务</strong></h6>
          <div style="margin-left: 0;">
            <p><strong>甲方责任：</strong></p>
            <p>1. 确保设备功能正常、配件齐全；</p>
            <p>2. 提供基础操作指导（如需）；</p>
            <p>3. 确认收到租金及押金后，确保乙方在起租日前一天收到设备，并及时发货（更新物流信息）。</p>
            
            <p><strong>乙方责任：</strong></p>
            <p>1. 按操作规范使用设备，禁止私自改装/拆卸；</p>
            <p>2. 承担租赁期间设备保管责任；</p>
            <p>3. 归还前清理设备（镜头无指纹、机身无污渍）；</p>
            <p>4. 使用原装充电器，避免电池损坏。</p>
          </div>
        </div>
        
        <!-- 设备损坏赔偿 -->
        <div class="contract-section">
          <h6><strong>设备损坏赔偿</strong></h6>
          <table class="table-contract">
            <tr>
              <th style="width: 50%;">情形</th>
              <th style="width: 50%;">赔偿责任</th>
            </tr>
            <tr>
              <td>自然使用磨损</td>
              <td>甲方承担</td>
            </tr>
            <tr>
              <td>激光损坏</td>
              <td>甲方承担</td>
            </tr>
            <tr>
              <td>人为损坏/进水/摔碰导致显示或拍摄异常</td>
              <td>乙方按维修发票金额全额赔偿，及误工费400元</td>
            </tr>
            <tr>
              <td>设备丢失</td>
              <td>乙方按设备设备总价值赔偿</td>
            </tr>
          </table>
        </div>
        
        <!-- 归还验收 -->
        <div class="contract-section">
          <h6><strong>归还验收</strong></h6>
          <p>1. 乙方需在归还日12:00前寄出设备（保留快递凭证）；</p>
          <p>2. 甲方收到后24小时内完成检测，并视频记录开箱过程；</p>
          <p>3. 如有争议，双方可共同指定第三方检测机构鉴定（费用由责任方承担）。</p>
        </div>
        
        <!-- 违约条款 -->
        <div class="contract-section">
          <h6><strong>违约条款</strong></h6>
          <p>1. 乙方逾期归还：每超1天支付<el-input v-model="contractForm.overdueRate" class="contract-input" style="width: 60px; display: inline-block; margin: 0 3px;" />元/天的租金，必须提前24小时与甲方确认是否有档期，否则需按<el-input v-model="contractForm.compensationRate" class="contract-input" style="width: 60px; display: inline-block; margin: 0 3px;" />元/天补齐租金。</p>
          <p>2. 甲方未按约定退还押金：每逾期1天按押金10%支付违约金。</p>
        </div>
        
        <!-- 争议解决 -->
        <div class="contract-section">
          <h6><strong>争议解决</strong></h6>
          <p>因本合同产生的纠纷，双方应协商解决；协商不成时，可向甲方所在地人民法院提起诉讼。</p>
        </div>
        
            <!-- 其他约定 -->
    <div class="contract-section">
      <h6><strong>其他约定</strong></h6>
      <p>1. 本合同与闲鱼平台订单互为补充，冲突时以本合同为准；</p>
      <p>2. 设备检测标准参考《摄影器材通用验机规范》；</p>
      <p>3. 本合同自双方签字盖章之日起生效。</p>
    </div>
  </div>
</div>

<!-- 图片预览对话框 -->
<ImagePreviewDialog
  v-model="imagePreviewVisible"
  :image-url="previewImageUrl"
  image-alt="身份证预览"
/>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft,
  Printer,
  Camera,
  UploadFilled,
  Document,
  Check,
  Loading
} from '@element-plus/icons-vue'
import ImagePreviewDialog from '../components/ImagePreviewDialog.vue'
import { useGanttStore, type Rental } from '../stores/gantt'
import axios from 'axios'
import dayjs from 'dayjs'

const router = useRouter()
const route = useRoute()
const ganttStore = useGanttStore()

// 响应式状态
const rental = ref<Rental | null>(null)
const ocrResult = ref<{ name: string; idNumber: string } | null>(null)
const ocrLoading = ref(false)
const deviceSerialNumber = ref<string>('加载中...')
const uploadedFile = ref<File | null>(null)
const imagePreviewVisible = ref(false)
const previewImageUrl = ref('')

// 合同表单数据
const contractForm = ref({
  customerName: '',
  customerIdNumber: '',
  totalDeviceValue: '7500',
  deposit: '1',
  overdueRate: '30',
  compensationRate: '60'
})


// 计算收货日期（start_date - 1天）
const getReceiptDate = (dateString?: string) => {
  if (!dateString) return '-'
  console.log('原始日期字符串:', dateString)
  
  // 使用更简单可靠的方法
  const date = new Date(dateString + 'T12:00:00') // 使用中午时间避免时区问题
  date.setDate(date.getDate() - 1)
  
  console.log('目标Date对象:', date)
  console.log('年:', date.getFullYear())
  console.log('月:', date.getMonth() + 1)
  console.log('日:', date.getDate())
  
  // 使用toLocaleDateString确保本地时区
  const result = date.toLocaleDateString('sv-SE') // 'sv-SE' 格式为 YYYY-MM-DD
  
  console.log('最终结果:', result)
  return result
}

// 计算归还日期（end_date + 1天）
const getReturnDate = (dateString?: string) => {
  if (!dateString) return '-'
  console.log('原始日期字符串:', dateString)
  
  // 使用更简单可靠的方法
  const date = new Date(dateString + 'T12:00:00') // 使用中午时间避免时区问题
  date.setDate(date.getDate() + 1)
  
  console.log('目标Date对象:', date)
  console.log('年:', date.getFullYear())
  console.log('月:', date.getMonth() + 1)
  console.log('日:', date.getDate())
  
  // 使用toLocaleDateString确保本地时区
  const result = date.toLocaleDateString('sv-SE') // 'sv-SE' 格式为 YYYY-MM-DD
  
  console.log('最终结果:', result)
  return result
}

// 获取设备序列号
const getDeviceSerialNumber = async (deviceId: number) => {
  try {
    const response = await axios.get(`/api/devices/${deviceId}`)
    if (response.data.success) {
      deviceSerialNumber.value = response.data.data.serial_number || '未知'
    }
  } catch (error) {
    console.error('获取设备信息失败:', error)
    deviceSerialNumber.value = '未知'
  }
}

// 计算属性
const rentalDays = computed(() => {
  if (!rental.value?.start_date || !rental.value?.end_date) return 0
  const start = dayjs(rental.value.start_date)
  const end = dayjs(rental.value.end_date)
  return end.diff(start, 'day') + 1
})

// 方法
const goBack = () => {
  router.push('/gantt')
}

const handleFileChange = async (file: any) => {
  console.log('选择的文件:', file)
  // 只保存第一个文件
  if (file && (file.raw || file)) {
    uploadedFile.value = file.raw || file
    // 自动触发OCR识别
    await handleOCR()
  }
}

const handleOCR = async () => {
  if (!uploadedFile.value) {
    ElMessage.warning('请先选择身份证照片')
    return
  }

  ocrLoading.value = true
  try {
    // 创建 FormData 对象
    const formData = new FormData()
    formData.append('image', uploadedFile.value)
    
    // 调用后端 OCR 接口
    const response = await axios.post('/api/ocr/id-card', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })
    
    if (response.data.success) {
      ocrResult.value = {
        name: response.data.data.name || '',
        idNumber: response.data.data.id_number || ''
      }
      console.log(ocrResult.value)
      ElMessage.success('身份证识别成功')
    } else {
      throw new Error(response.data.error || '识别失败')
    }
  } catch (error: any) {
    console.error('OCR识别失败:', error)
    ElMessage.error(error.response?.data?.error || error.message || '身份证识别失败，请重试')
  } finally {
    ocrLoading.value = false
  }
}

// 获取图片预览URL
const getImagePreviewUrl = (): string => {
  if (uploadedFile.value) {
    return URL.createObjectURL(uploadedFile.value)
  }
  return ''
}

// 清除已上传的文件
const clearUploadedFile = () => {
  uploadedFile.value = null
  ocrResult.value = null
  // 重置上传组件
  const uploadRef = document.querySelector('.el-upload') as any
  if (uploadRef && uploadRef.clearFiles) {
    uploadRef.clearFiles()
  }
}

const openImagePreview = () => {
  if (uploadedFile.value) {
    previewImageUrl.value = getImagePreviewUrl()
    imagePreviewVisible.value = true
  }
}

const fillContract = () => {
  if (ocrResult.value) {
    contractForm.value.customerName = ocrResult.value.name
    contractForm.value.customerIdNumber = ocrResult.value.idNumber
    ElMessage.success('合同信息已填入')
  }
}

const printContract = () => {
  if (!contractForm.value.customerName.trim()) {
    if (confirm('承租方信息尚未填入，是否继续打印？')) {
      handlePrint()
    } else {
      ElMessage.info('请先上传身份证并填入合同信息。')
    }
  } else {
    handlePrint()
  }
}

const handlePrint = () => {
  console.log('开始打印流程...')
  const printStyle = document.createElement('style')
  printStyle.textContent = `
    @media print {
      @page { size: A4; margin: 1.5cm; }
      body { margin: 0 !important; padding: 0 !important; }
      .rental-contract-page { display: block !important; position: static !important; max-height: none !important; height: auto !important; overflow: visible !important; transform: none !important; }
      .contract-container { display: block !important; position: static !important; max-height: none !important; height: auto !important; overflow: visible !important; transform: none !important; }
      .page-header, .upload-section, .ocr-result { display: none !important; }
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

// 获取个性化附件列表（从租赁记录的附件中获取）
const getPersonalizedAccessories = () => {
  if (!rental.value?.accessories) {
    return []
  }
  return rental.value.accessories.filter((acc: any) => acc.is_accessory)
}

// 计算总价值
const getTotalValue = () => {
  let total = 0

  // 主设备价值
  if (rental.value?.device?.device_model?.device_value) {
    total += parseFloat(String(rental.value.device.device_model.device_value))
  }

  // 个性化附件价值（从实际租赁的附件中获取）
  const personalizedAccessories = getPersonalizedAccessories()
  personalizedAccessories.forEach((acc: any) => {
    // 暂时使用默认值，如果附件有价值信息的话
    if (acc.value) {
      total += parseFloat(String(acc.value))
    }
  })

  return total
}

// 生命周期
onMounted(async () => {
  const rentalId = route.params.id
  if (rentalId) {
    const rentalData = await ganttStore.getRentalById(Number(rentalId))
    if (rentalData) {
      rental.value = rentalData
      // 获取设备序列号
      if (rentalData.device_id) {
        await getDeviceSerialNumber(rentalData.device_id)
      }
    }
  }
})
</script>

<style scoped>
.rental-contract-page {
  padding: 20px;
  background: #f5f5f5;
  min-height: 100vh;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 30px;
  background: white;
  padding: 20px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.page-header h1 {
  margin: 0;
  color: #333;
}

.upload-section, .ocr-result {
  margin-bottom: 30px;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: bold;
}

.upload-actions {
  margin-top: 20px;
  text-align: center;
}

.ocr-content {
  display: flex;
  flex-direction: column;
  gap: 15px;
}

.ocr-item {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ocr-item .label {
  min-width: 80px;
  font-weight: bold;
}

.ocr-item .el-input {
  width: 300px;
}

.ocr-actions {
  text-align: center;
  margin-top: 20px;
}

.image-preview {
  margin-top: 20px;
  padding: 15px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  background-color: #fafafa;
}

.preview-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 15px;
  font-weight: bold;
  color: #606266;
}

.preview-image {
  text-align: center;
}

.preview-image img {
  max-width: 100%;
  max-height: 300px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.clickable-image {
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.clickable-image:hover {
  transform: scale(1.05);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.preview-status {
  margin-top: 15px;
  text-align: center;
  color: #409eff;
  font-size: 14px;
}

.preview-status .el-icon {
  margin-right: 8px;
  font-size: 16px;
}

.contract-container {
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  overflow: hidden;
}

.contract-content {
  padding: 40px;
  max-width: 800px;
  margin: 0 auto;
  font-family: 'Microsoft YaHei', Arial, sans-serif;
  line-height: 1.3;
  font-size: 12px;
  color: #333;
}

.contract-header {
  text-align: center;
  margin-bottom: 15px;
  padding-bottom: 10px;
  border-bottom: 2px solid #007bff;
}

.contract-title {
  font-size: 20px;
  font-weight: bold;
  color: #333;
  margin-bottom: 5px;
}

.contract-section {
  margin-bottom: 12px;
}

.contract-section p {
  margin-bottom: 4px;
  color: #333;
}

.contract-section h6 {
  margin-bottom: 6px;
  margin-top: 8px;
  font-size: 13px;
  font-weight: bold;
}

.table-contract {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
  font-size: 12px;
}

.table-contract th,
.table-contract td {
  border: 1px solid #333;
  padding: 4px 6px;
  text-align: left;
  vertical-align: top;
  color: #333;
}

.table-contract th {
  background-color: #f8f9fa;
  font-weight: bold;
  text-align: center;
}

.party-table th {
  background-color: #e9ecef;
  text-align: left;
  padding: 6px 8px;
  font-size: 12px;
}

.party-table td {
  padding: 8px;
  line-height: 1.3;
  font-size: 12px;
}

.party-table td div {
  margin-bottom: 4px;
}

.contract-input :deep(.el-input__wrapper) {
  border: 1px solid #ddd;
  border-radius: 3px;
  padding: 3px 6px;
  font-size: 12px;
  background-color: #fff;
  transition: border-color 0.2s;
  box-shadow: none;
}

.contract-input :deep(.el-input__wrapper):focus-within {
  border-color: #007bff;
  box-shadow: 0 0 0 2px rgba(0, 123, 255, 0.25);
}

.contract-input :deep(.el-input__inner) {
  font-weight: normal;
  color: black;
  font-size: 12px;
  background: transparent;
  border: none;
  padding: 0;
  margin: 0;
}

/* 打印样式 */
@media print {
  * { 
    -webkit-print-color-adjust: exact !important; 
    color-adjust: exact !important; 
    box-sizing: border-box !important; 
  }
  
  @page { 
    size: A4 !important; 
    margin: 1.5cm !important; 
  }
  
  html, body { 
    margin: 0 !important; 
    padding: 0 !important; 
    height: auto !important; 
    width: 100% !important; 
    overflow: visible !important; 
    background: white !important; 
    font-size: 12px !important; 
    line-height: 1.2 !important; 
    color: black !important; 
  }
  
  .page-header, .upload-section, .ocr-result { 
    display: none !important; 
  }
  
  .rental-contract-page { 
    display: block !important; 
    position: static !important; 
    box-shadow: none !important; 
    margin: 0 !important; 
    padding: 0 !important; 
    max-height: none !important; 
    min-height: auto !important; 
    height: auto !important; 
    overflow: visible !important; 
    max-width: none !important; 
    width: 100% !important; 
    border-radius: 0 !important; 
    background: white !important; 
    page-break-inside: auto !important; 
    transform: none !important; 
  }
  
  .contract-container { 
    display: block !important; 
    position: static !important; 
    background: white !important; 
    padding: 0 !important; 
    margin: 0 !important; 
    border-radius: 0 !important; 
    box-shadow: none !important; 
    max-height: none !important; 
    min-height: auto !important; 
    height: auto !important; 
    overflow: visible !important; 
    page-break-inside: auto !important; 
    transform: none !important; 
  }
  
  .contract-content { 
    display: block !important; 
    position: static !important; 
    background: white !important; 
    padding: 8px !important; 
    margin: 0 !important; 
    border-radius: 0 !important; 
    box-shadow: none !important; 
    max-height: none !important; 
    min-height: auto !important; 
    height: auto !important; 
    overflow: visible !important; 
    page-break-inside: auto !important; 
    transform: none !important; 
  }
  
  .contract-header { 
    display: block !important; 
    position: static !important; 
    margin-bottom: 15px !important; 
    page-break-after: avoid !important; 
    page-break-inside: avoid !important; 
  }
  
  .contract-title { 
    font-size: 16px !important; 
    font-weight: bold !important; 
    text-align: center !important; 
    margin-bottom: 5px !important; 
    page-break-after: avoid !important; 
  }
  
  .contract-section { 
    display: block !important; 
    position: static !important; 
    margin-bottom: 4px !important; 
    page-break-inside: auto !important; 
    page-break-before: auto !important; 
    page-break-after: auto !important; 
  }
  
  .table-contract { 
    display: table !important; 
    width: 100% !important; 
    margin: 8px 0 !important; 
    border-collapse: collapse !important; 
    page-break-inside: auto !important; 
    page-break-before: auto !important; 
    font-size: 12px !important; 
  }
  
  .table-contract th { 
    font-size: 12px !important; 
    font-weight: bold !important; 
    padding: 4px 6px !important; 
    border: 1px solid #333 !important; 
    background-color: #f8f9fa !important; 
    text-align: center !important; 
  }
  
  .table-contract td { 
    font-size: 12px !important; 
    padding: 4px 6px !important; 
    border: 1px solid #333 !important; 
    text-align: left !important; 
    vertical-align: top !important; 
  }
  
  .party-table th { 
    background-color: #e9ecef !important; 
    text-align: left !important; 
    padding: 6px 8px !important; 
    font-size: 12px !important; 
  }
  
  .party-table td { 
    font-size: 12px !important; 
    line-height: 1.1 !important; 
    padding: 3px !important; 
  }
  
  .contract-input :deep(.el-input__wrapper) { 
    border: none !important; 
    background: transparent !important; 
    box-shadow: none !important; 
    padding: 0 !important; 
    margin: 0 !important; 
  }
  
  .contract-input :deep(.el-input__inner) { 
    font-weight: normal !important; 
    color: black !important; 
    font-size: 12px !important; 
    background: transparent !important; 
    border: none !important; 
    padding: 0 !important; 
    margin: 0 !important; 
  }
  
  h6 { 
    font-size: 13px !important; 
    font-weight: bold !important; 
    margin: 8px 0 6px 0 !important; 
    page-break-after: avoid !important; 
    color: black !important; 
  }
  
  p { 
    margin-bottom: 4px !important; 
    line-height: 1.8 !important; 
    font-size: 12px !important; 
    color: black !important; 
  }
}
</style>

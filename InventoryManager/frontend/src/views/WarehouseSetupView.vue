<template>
  <main class="setup-page">
    <el-card class="setup-card" shadow="never" v-loading="loading">
      <template #header>
        <div>
          <h1>完成默认仓库设置</h1>
          <p>确认仓库与寄回资料后，才能进入库存、租赁、发货、打印和验货页面。</p>
        </div>
      </template>
      <el-alert
        type="info"
        :closable="false"
        title="注册手机号只是预填值，请确认联系人、电话和完整地址。"
      />
      <el-form label-width="100px" class="setup-form">
        <el-form-item label="仓库名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="联系人"><el-input v-model="form.contact_name" /></el-form-item>
        <el-form-item label="联系电话"><el-input v-model="form.contact_phone" /></el-form-item>
        <el-form-item label="省"><el-input v-model="form.province" /></el-form-item>
        <el-form-item label="市"><el-input v-model="form.city" /></el-form-item>
        <el-form-item label="区/县"><el-input v-model="form.district" /></el-form-item>
        <el-form-item label="详细地址">
          <el-input v-model="form.address_detail" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            :loading="submitting"
            :disabled="!canSubmit"
            @click="submit"
          >
            确认并进入系统
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import {
  getDefaultWarehouseSetup,
  setupDefaultWarehouse,
} from '@/api/warehouse'

const router = useRouter()
const loading = ref(false)
const submitting = ref(false)
const form = reactive({
  name: '默认仓库',
  contact_name: '',
  contact_phone: '',
  province: '',
  city: '',
  district: '',
  address_detail: '',
})

const canSubmit = computed(() =>
  Object.values(form).every(value => value.trim().length > 0)
)

const loadSetup = async () => {
  loading.value = true
  try {
    const warehouse = await getDefaultWarehouseSetup()
    if (warehouse.setup_state === 'ready') {
      await router.replace('/')
      return
    }
    form.name = warehouse.name || '默认仓库'
    form.contact_name = warehouse.contact_name || ''
    form.contact_phone = warehouse.contact_phone || ''
    form.province = warehouse.province || ''
    form.city = warehouse.city || ''
    form.district = warehouse.district || ''
    form.address_detail = warehouse.address_detail || ''
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

const submit = async () => {
  if (!canSubmit.value) return
  submitting.value = true
  try {
    await setupDefaultWarehouse({ ...form })
    ElMessage.success('默认仓库设置完成')
    await router.replace('/')
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    submitting.value = false
  }
}

onMounted(loadSetup)
</script>

<style scoped>
.setup-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 32px;
  background: #f5f7fa;
}
.setup-card { width: min(680px, 100%); }
.setup-card h1 { margin: 0 0 8px; }
.setup-card p { margin: 0; color: #606266; }
.setup-form { margin-top: 24px; }
</style>

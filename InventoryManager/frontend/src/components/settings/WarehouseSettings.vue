<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  createWarehouse,
  listWarehouseSettings,
  saveKuaimaiConfiguration,
  saveSfConfiguration,
  updateWarehouse,
  type WarehouseSettings,
} from '@/api/settings'
import { useTenantStore } from '@/stores/tenant'


const tenant = useTenantStore()
const warehouses = ref<WarehouseSettings[]>([])
const loading = ref(false)
const drawerOpen = ref(false)
const editingId = ref<number | null>(null)
const base = reactive({ province: '', city: '', name: '' })
const sf = reactive({
  partner_id: '', checkword: '', monthly_card: '', test_mode: false,
  sender_name: '', sender_phone: '', sender_address: '',
})
const kuaimai = reactive({ app_id: '', app_secret: '', printer_sn: '' })
const configured = reactive({ checkword: false, monthly_card: false, app_secret: false })

const load = async () => {
  loading.value = true
  try {
    warehouses.value = await listWarehouseSettings()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '仓库加载失败')
  } finally {
    loading.value = false
  }
}

const openWarehouse = (warehouse?: WarehouseSettings) => {
  editingId.value = warehouse?.id ?? null
  Object.assign(base, {
    province: warehouse?.province ?? '',
    city: warehouse?.city ?? '',
    name: warehouse?.name ?? '',
  })
  Object.assign(sf, {
    partner_id: warehouse?.sf_config?.partner_id ?? '',
    checkword: '',
    monthly_card: '',
    test_mode: warehouse?.sf_config?.test_mode ?? false,
    sender_name: warehouse?.sf_config?.sender_name ?? '',
    sender_phone: warehouse?.sf_config?.sender_phone ?? '',
    sender_address: warehouse?.sf_config?.sender_address ?? '',
  })
  Object.assign(kuaimai, {
    app_id: warehouse?.kuaimai_config?.app_id ?? '',
    app_secret: '',
    printer_sn: warehouse?.kuaimai_config?.printer_sn ?? '',
  })
  Object.assign(configured, {
    checkword: warehouse?.sf_config?.checkword_configured ?? false,
    monthly_card: warehouse?.sf_config?.monthly_card_configured ?? false,
    app_secret: warehouse?.kuaimai_config?.app_secret_configured ?? false,
  })
  drawerOpen.value = true
}

const saveBase = async () => {
  loading.value = true
  try {
    const payload = {
      province: base.province,
      city: base.city,
      name: base.name,
    }
    const saved = editingId.value === null
      ? await createWarehouse(payload)
      : await updateWarehouse(editingId.value, payload)
    editingId.value = saved.id
    await Promise.all([load(), tenant.loadWarehouses(true)])
    ElMessage.success('仓库基本信息已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '仓库保存失败')
  } finally {
    loading.value = false
  }
}

const requireSavedWarehouse = () => {
  if (editingId.value === null) {
    ElMessage.warning('请先保存仓库基本信息')
    return null
  }
  return editingId.value
}

const saveSf = async () => {
  const warehouseId = requireSavedWarehouse()
  if (warehouseId === null) return
  loading.value = true
  try {
    const saved = await saveSfConfiguration(warehouseId, { ...sf })
    configured.checkword = saved.checkword_configured
    configured.monthly_card = saved.monthly_card_configured
    sf.checkword = ''
    sf.monthly_card = ''
    await Promise.all([load(), tenant.loadWarehouses(true)])
    ElMessage.success('顺丰配置已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '顺丰配置保存失败')
  } finally {
    loading.value = false
  }
}

const saveKuaimai = async () => {
  const warehouseId = requireSavedWarehouse()
  if (warehouseId === null) return
  loading.value = true
  try {
    const saved = await saveKuaimaiConfiguration(warehouseId, { ...kuaimai })
    configured.app_secret = saved.app_secret_configured
    kuaimai.app_secret = ''
    await Promise.all([load(), tenant.loadWarehouses(true)])
    ElMessage.success('快麦与打印机配置已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '快麦配置保存失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section>
    <div class="section-actions">
      <p>顺丰、快麦和打印机均按仓库配置。</p>
      <el-button type="primary" @click="openWarehouse()">新增仓库</el-button>
    </div>
    <el-table :data="warehouses" v-loading="loading">
      <el-table-column prop="name" label="仓库" />
      <el-table-column label="省市">
        <template #default="{ row }">{{ row.province }} {{ row.city }}</template>
      </el-table-column>
      <el-table-column label="顺丰" width="100">
        <template #default="{ row }">{{ row.sf_configured ? '已配置' : '未配置' }}</template>
      </el-table-column>
      <el-table-column label="打印" width="100">
        <template #default="{ row }">{{ row.kuaimai_configured ? '已配置' : '未配置' }}</template>
      </el-table-column>
      <el-table-column width="100">
        <template #default="{ row }">
          <el-button link type="primary" @click="openWarehouse(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="drawerOpen" :title="editingId ? '编辑仓库' : '新增仓库'" size="560px">
      <h3>基本信息</h3>
      <el-form label-width="100px">
        <el-form-item label="省"><el-input v-model="base.province" /></el-form-item>
        <el-form-item label="市"><el-input v-model="base.city" /></el-form-item>
        <el-form-item label="仓库名称">
          <el-input v-model="base.name" placeholder="留空自动生成省市仓库" />
        </el-form-item>
        <el-form-item><el-button type="primary" @click="saveBase">保存基本信息</el-button></el-form-item>
      </el-form>

      <el-divider />
      <h3>顺丰配置</h3>
      <el-form label-width="100px">
        <el-form-item label="Partner ID"><el-input v-model="sf.partner_id" /></el-form-item>
        <el-form-item :label="configured.checkword ? 'Checkword（已配置）' : 'Checkword'">
          <el-input v-model="sf.checkword" type="password" show-password placeholder="留空保持原值" />
        </el-form-item>
        <el-form-item :label="configured.monthly_card ? '月结卡（已配置）' : '月结卡'">
          <el-input v-model="sf.monthly_card" type="password" show-password placeholder="留空保持原值" />
        </el-form-item>
        <el-form-item label="寄件人"><el-input v-model="sf.sender_name" /></el-form-item>
        <el-form-item label="寄件电话"><el-input v-model="sf.sender_phone" /></el-form-item>
        <el-form-item label="详细地址"><el-input v-model="sf.sender_address" type="textarea" /></el-form-item>
        <el-form-item label="测试模式"><el-switch v-model="sf.test_mode" /></el-form-item>
        <el-form-item><el-button type="primary" @click="saveSf">保存顺丰配置</el-button></el-form-item>
      </el-form>

      <el-divider />
      <h3>快麦与打印机</h3>
      <el-form label-width="100px">
        <el-form-item label="App ID"><el-input v-model="kuaimai.app_id" /></el-form-item>
        <el-form-item :label="configured.app_secret ? 'App Secret（已配置）' : 'App Secret'">
          <el-input v-model="kuaimai.app_secret" type="password" show-password placeholder="留空保持原值" />
        </el-form-item>
        <el-form-item label="打印机 SN"><el-input v-model="kuaimai.printer_sn" /></el-form-item>
        <el-form-item><el-button type="primary" @click="saveKuaimai">保存快麦配置</el-button></el-form-item>
      </el-form>
    </el-drawer>
  </section>
</template>

<style scoped>
.section-actions { display: flex; align-items: center; justify-content: space-between; }
.section-actions p { color: #667085; }
h3 { margin: 8px 0 18px; }
</style>

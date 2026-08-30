<script setup lang="ts">
import axios from 'axios'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Delete, Edit, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import type { Device, DeviceModel } from '@/stores/gantt'
import { useTenantStore } from '@/stores/tenant'
import WarehouseMovementDialog from '@/components/WarehouseMovementDialog.vue'


type DeviceListResponse = {
  devices: Device[]
  total: number
  pages: number
  current_page: number
  per_page: number
}

type EditorForm = {
  id?: number
  name: string
  serial_number: string
  model: string
  model_id?: number
  is_accessory: boolean
  lifecycle_status: Device['lifecycle_status']
  lifecycle_reason: string
}

const lifecycleOptions: Array<{
  value: Device['lifecycle_status']
  label: string
  type: 'success' | 'warning' | 'danger' | 'info'
}> = [
  { value: 'active', label: '使用中', type: 'success' },
  { value: 'sold', label: '已售出', type: 'warning' },
  { value: 'damaged', label: '已损坏', type: 'danger' },
  { value: 'decommissioned', label: '已停用', type: 'info' },
  { value: 'retired', label: '已退役', type: 'info' },
]

const tenant = useTenantStore()
const devices = ref<Device[]>([])
const deviceModels = ref<DeviceModel[]>([])
const loading = ref(false)
const saving = ref(false)
const editorVisible = ref(false)
const movementVisible = ref(false)
const movementDevice = ref<Device | null>(null)
const editorMode = ref<'create' | 'edit'>('create')
const originalLifecycle = ref<Device['lifecycle_status']>('active')
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const keyword = ref('')
const lifecycleFilter = ref<'all' | Device['lifecycle_status']>('all')
const typeFilter = ref<'all' | 'device' | 'accessory'>('all')

const blankForm = (): EditorForm => ({
  name: '',
  serial_number: '',
  model: '',
  model_id: undefined,
  is_accessory: false,
  lifecycle_status: 'active',
  lifecycle_reason: '',
})
const form = reactive<EditorForm>(blankForm())

const canWrite = computed(() => tenant.currentWarehouseId !== 'all')
const currentWarehouseLabel = computed(() => (
  tenant.currentWarehouse?.name || '全部仓库'
))

const apiError = (error: any, fallback: string) => (
  error?.response?.data?.message
  || error?.response?.data?.error
  || error?.message
  || fallback
)

const lifecycleMeta = (status: Device['lifecycle_status']) => (
  lifecycleOptions.find((item) => item.value === status) || lifecycleOptions[0]
)

const warehouseName = (warehouseId?: number) => (
  tenant.warehouses.find((item) => item.id === warehouseId)?.name || '—'
)

const loadModels = async () => {
  const response = await axios.get('/api/device-models')
  deviceModels.value = response.data?.data || []
}

const loadDevices = async () => {
  loading.value = true
  try {
    await tenant.initialize()
    const params: Record<string, string | number | boolean> = {
      page: page.value,
      per_page: pageSize.value,
      warehouse_id: tenant.currentWarehouseId,
    }
    if (keyword.value.trim()) params.q = keyword.value.trim()
    if (lifecycleFilter.value !== 'all') {
      params.lifecycle_status = lifecycleFilter.value
    }
    if (typeFilter.value !== 'all') {
      params.is_accessory = typeFilter.value === 'accessory'
    }
    const response = await axios.get('/api/devices', { params })
    const payload: DeviceListResponse = response.data?.data || response.data
    devices.value = payload.devices || []
    total.value = payload.total || 0
  } catch (error) {
    ElMessage.error(apiError(error, '设备列表加载失败'))
  } finally {
    loading.value = false
  }
}

const searchDevices = () => {
  page.value = 1
  void loadDevices()
}

const resetEditor = () => {
  Object.assign(form, blankForm())
  originalLifecycle.value = 'active'
}

const openCreate = () => {
  if (!canWrite.value) {
    ElMessage.warning('请先在顶部选择具体仓库')
    return
  }
  editorMode.value = 'create'
  resetEditor()
  editorVisible.value = true
}

const openEdit = (device: Device) => {
  if (!canWrite.value || device.warehouse_id !== tenant.currentWarehouseId) {
    ElMessage.warning('请切换到设备所在的具体仓库后再编辑')
    return
  }
  editorMode.value = 'edit'
  Object.assign(form, {
    id: device.id,
    name: device.name,
    serial_number: device.serial_number,
    model: device.model,
    model_id: device.model_id,
    is_accessory: device.is_accessory,
    lifecycle_status: device.lifecycle_status || 'active',
    lifecycle_reason: '',
  })
  originalLifecycle.value = device.lifecycle_status || 'active'
  editorVisible.value = true
}

const syncModelId = (modelName: string) => {
  form.model_id = deviceModels.value.find((item) => item.name === modelName)?.id
}

const submitEditor = async () => {
  const name = form.name.trim()
  const serialNumber = form.serial_number.trim()
  const model = form.model.trim()
  if (!name || !serialNumber || !model) {
    ElMessage.warning('请完整填写设备名称、序列号和型号')
    return
  }
  if (!canWrite.value) {
    ElMessage.warning('请先选择具体仓库')
    return
  }

  saving.value = true
  try {
    const payload = {
      name,
      serial_number: serialNumber,
      model,
      model_id: form.model_id,
      is_accessory: form.is_accessory,
    }
    if (editorMode.value === 'create') {
      await axios.post('/api/devices', {
        ...payload,
        warehouse_id: tenant.currentWarehouseId,
      })
      ElMessage.success('设备添加成功')
    } else if (form.id) {
      await axios.put(`/api/devices/${form.id}`, payload)
      if (form.lifecycle_status !== originalLifecycle.value) {
        await axios.put(`/api/devices/${form.id}/lifecycle`, {
          lifecycle_status: form.lifecycle_status,
          lifecycle_reason: form.lifecycle_reason.trim() || undefined,
        })
      }
      ElMessage.success('设备信息已更新')
    }
    editorVisible.value = false
    await loadDevices()
  } catch (error) {
    ElMessage.error(apiError(error, '保存设备失败'))
  } finally {
    saving.value = false
  }
}

const deleteDevice = async (device: Device) => {
  if (!canWrite.value || device.warehouse_id !== tenant.currentWarehouseId) {
    ElMessage.warning('请切换到设备所在的具体仓库后再删除')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认删除设备“${device.name}”（${device.serial_number}）？有租赁记录的设备不会被删除。`,
      '删除设备',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
    await axios.delete(`/api/devices/${device.id}`)
    ElMessage.success('设备已删除')
    if (devices.value.length === 1 && page.value > 1) page.value -= 1
    await loadDevices()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiError(error, '删除设备失败'))
  }
}

const openMovement = (device: Device) => {
  if (!canWrite.value || device.warehouse_id !== tenant.currentWarehouseId) {
    ElMessage.warning('请切换到设备所在的具体仓库后再移仓')
    return
  }
  movementDevice.value = device
  movementVisible.value = true
}

const finishMovement = async () => {
  movementVisible.value = false
  movementDevice.value = null
  await loadDevices()
}

watch(() => tenant.currentWarehouseId, () => {
  page.value = 1
  void loadDevices()
})

onMounted(async () => {
  try {
    await Promise.all([tenant.initialize(), loadModels()])
  } catch (error) {
    ElMessage.error(apiError(error, '设备管理初始化失败'))
  }
  await loadDevices()
})
</script>

<template>
  <div class="device-page">
    <header class="device-page__heading">
      <div>
        <span class="page-kicker">INVENTORY</span>
        <h1>设备管理</h1>
        <p>{{ currentWarehouseLabel }} · 共 {{ total }} 台设备与附件</p>
      </div>
      <div class="heading-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadDevices">刷新</el-button>
        <el-button
          data-testid="add-device"
          type="primary"
          :icon="Plus"
          :disabled="!canWrite"
          @click="openCreate"
        >
          添加设备
        </el-button>
      </div>
    </header>

    <section class="device-panel">
      <div class="filters">
        <el-input
          v-model="keyword"
          class="keyword-input"
          clearable
          placeholder="搜索设备名称、序列号或型号"
          :prefix-icon="Search"
          @keyup.enter="searchDevices"
          @clear="searchDevices"
        />
        <el-select v-model="lifecycleFilter" class="filter-select" @change="searchDevices">
          <el-option label="全部状态" value="all" />
          <el-option
            v-for="item in lifecycleOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <el-select v-model="typeFilter" class="filter-select" @change="searchDevices">
          <el-option label="全部类型" value="all" />
          <el-option label="主设备" value="device" />
          <el-option label="附件" value="accessory" />
        </el-select>
        <el-button type="primary" :icon="Search" @click="searchDevices">查询</el-button>
      </div>

      <el-alert
        v-if="!canWrite"
        class="warehouse-hint"
        title="当前正在查看全部仓库；如需新增、编辑或删除，请先在顶部选择具体仓库。"
        type="info"
        :closable="false"
        show-icon
      />

      <el-table v-loading="loading" :data="devices" stripe class="device-table">
        <el-table-column prop="name" label="设备名称" min-width="180">
          <template #default="{ row }">
            <div class="device-name-cell">
              <strong>{{ row.name }}</strong>
              <small>{{ row.is_accessory ? '附件' : '主设备' }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="serial_number" label="序列号" min-width="150" />
        <el-table-column label="型号" min-width="150">
          <template #default="{ row }">
            {{ row.device_model?.display_name || row.model || '—' }}
          </template>
        </el-table-column>
        <el-table-column label="所在仓库" min-width="130">
          <template #default="{ row }">{{ warehouseName(row.warehouse_id) }}</template>
        </el-table-column>
        <el-table-column label="设备状态" width="110">
          <template #default="{ row }">
            <el-tag :type="lifecycleMeta(row.lifecycle_status).type" effect="light">
              {{ lifecycleMeta(row.lifecycle_status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="205" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="tenant.warehouses.length > 1"
              link
              :disabled="!canWrite || row.warehouse_id !== tenant.currentWarehouseId"
              @click="openMovement(row)"
            >移仓</el-button>
            <el-button
              link
              type="primary"
              :icon="Edit"
              :disabled="!canWrite || row.warehouse_id !== tenant.currentWarehouseId"
              @click="openEdit(row)"
            >编辑</el-button>
            <el-button
              link
              type="danger"
              :icon="Delete"
              :disabled="!canWrite || row.warehouse_id !== tenant.currentWarehouseId"
              @click="deleteDevice(row)"
            >删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="没有符合条件的设备" />
        </template>
      </el-table>

      <el-pagination
        v-if="total > 0"
        v-model:current-page="page"
        v-model:page-size="pageSize"
        class="pagination"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        @current-change="loadDevices"
        @size-change="searchDevices"
      />
    </section>

    <el-dialog
      v-model="editorVisible"
      :title="editorMode === 'create' ? '添加设备' : '编辑设备'"
      width="520px"
      destroy-on-close
    >
      <el-form label-position="top" @submit.prevent="submitEditor">
        <div class="form-grid">
          <el-form-item label="设备名称" required>
            <el-input v-model="form.name" maxlength="100" placeholder="例如：X200U 01" />
          </el-form-item>
          <el-form-item label="序列号" required>
            <el-input v-model="form.serial_number" maxlength="100" placeholder="请输入唯一序列号" />
          </el-form-item>
        </div>
        <el-form-item label="型号" required>
          <el-select
            v-model="form.model"
            filterable
            allow-create
            default-first-option
            placeholder="选择或输入设备型号"
            style="width: 100%"
            @change="syncModelId"
          >
            <el-option
              v-for="model in deviceModels"
              :key="model.id"
              :label="model.display_name"
              :value="model.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="设备类型">
          <el-radio-group v-model="form.is_accessory">
            <el-radio-button :value="false">主设备</el-radio-button>
            <el-radio-button :value="true">附件</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <template v-if="editorMode === 'edit'">
          <el-form-item label="设备状态">
            <el-select v-model="form.lifecycle_status" style="width: 100%">
              <el-option
                v-for="item in lifecycleOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item v-if="form.lifecycle_status !== originalLifecycle" label="状态变更原因">
            <el-input
              v-model="form.lifecycle_reason"
              type="textarea"
              :rows="2"
              maxlength="255"
              placeholder="选填，用于记录设备状态变更原因"
            />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitEditor">
          {{ editorMode === 'create' ? '添加设备' : '保存修改' }}
        </el-button>
      </template>
    </el-dialog>

    <WarehouseMovementDialog
      v-if="movementDevice?.warehouse_id"
      v-model="movementVisible"
      :device-id="movementDevice.id"
      :current-warehouse-id="movementDevice.warehouse_id"
      @moved="finishMovement"
    />
  </div>
</template>

<style scoped>
.device-page { min-height: 100%; padding: 26px clamp(18px, 3vw, 42px) 44px; color: #101828; background: #f7f9fc; }
.device-page__heading { display: flex; max-width: 1360px; align-items: flex-end; justify-content: space-between; gap: 20px; margin: 0 auto 18px; }
.page-kicker { color: #2e90fa; font-size: 11px; font-weight: 800; letter-spacing: .14em; }
.device-page__heading h1 { margin: 5px 0 4px; font-size: 28px; letter-spacing: -.03em; }
.device-page__heading p { margin: 0; color: #667085; font-size: 13px; }
.heading-actions { display: flex; gap: 8px; }
.device-panel { max-width: 1360px; margin: 0 auto; padding: 16px; border: 1px solid #e4e7ec; border-radius: 12px; background: #fff; box-shadow: 0 1px 3px rgb(16 24 40 / 5%); }
.filters { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.keyword-input { max-width: 360px; }
.filter-select { width: 150px; }
.warehouse-hint { margin-bottom: 14px; }
.device-table { width: 100%; }
.device-name-cell { display: grid; gap: 2px; }
.device-name-cell strong { color: #101828; font-size: 13px; }
.device-name-cell small { color: #98a2b3; font-size: 11px; }
.pagination { justify-content: flex-end; margin-top: 16px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }

@media (max-width: 720px) {
  .device-page { padding: 18px 12px 32px; }
  .device-page__heading { align-items: flex-start; flex-direction: column; }
  .filters { align-items: stretch; flex-direction: column; }
  .keyword-input, .filter-select { width: 100%; max-width: none; }
  .form-grid { grid-template-columns: 1fr; gap: 0; }
}
</style>

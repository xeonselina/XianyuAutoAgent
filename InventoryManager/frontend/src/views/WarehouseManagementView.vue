<template>
  <main class="warehouse-page">
    <header class="page-header">
      <div>
        <el-button text @click="router.push('/')">← 返回甘特图</el-button>
        <h1>仓库与设备调仓</h1>
        <p>设备位置以实际仓库为准；调仓不会自动改写订单物流天数或计划日期。</p>
      </div>
      <div class="header-actions">
        <el-button @click="deviceDialogVisible = true">新增主设备</el-button>
        <el-button type="primary" @click="openCreate">新增仓库</el-button>
      </div>
    </header>

    <el-card v-loading="loading" shadow="never">
      <template #header>当前仓库</template>
      <el-table :data="warehouses" empty-text="暂无可用仓库">
        <el-table-column prop="name" label="仓库" min-width="140">
          <template #default="scope">
            {{ scope.row.name }}
            <el-tag v-if="scope.row.is_default" size="small">默认</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="联系人" min-width="160">
          <template #default="scope">
            {{ scope.row.contact_name }} · {{ scope.row.contact_phone }}
          </template>
        </el-table-column>
        <el-table-column label="地址" min-width="280">
          <template #default="scope">
            {{ warehouseAddress(scope.row) }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="scope">
            <el-tag :type="scope.row.status === 'active' ? 'success' : 'info'">
              {{ scope.row.status === 'active' ? '启用' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="250" fixed="right">
          <template #default="scope">
            <el-button
              v-if="scope.row.status === 'active'"
              link
              type="primary"
              @click="openEdit(scope.row)"
            >
              编辑
            </el-button>
            <el-button
              v-if="scope.row.status === 'active' && !scope.row.is_default"
              link
              @click="makeDefault(scope.row)"
            >
              设为默认
            </el-button>
            <el-button
              v-if="scope.row.status === 'active' && !scope.row.is_default"
              link
              type="danger"
              @click="deactivate(scope.row)"
            >
              停用
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="preference-card" shadow="never">
      <template #header>我的最近工作仓</template>
      <p class="card-tip">各业务页面会优先使用这里记住的仓库；不可用时回退到默认仓。</p>
      <div class="preference-grid">
        <label v-for="scene in preferenceScenes" :key="scene.value">
          <span>{{ scene.label }}</span>
          <el-select
            v-model="preferenceForm[scene.value]"
            placeholder="选择仓库"
            @change="savePreference(scene.value)"
          >
            <el-option
              v-for="warehouse in readyWarehouses"
              :key="warehouse.id"
              :label="warehouse.name || '未命名仓库'"
              :value="warehouse.id"
            />
          </el-select>
        </label>
      </div>
    </el-card>

    <el-card class="move-card" shadow="never">
      <template #header>更改主设备仓库</template>
      <el-form label-width="110px" class="move-form">
        <el-form-item label="主设备">
          <el-select
            v-model="moveForm.deviceId"
            filterable
            placeholder="选择主设备"
            @change="moveForm.targetWarehouseId = null"
          >
            <el-option
              v-for="device in devices"
              :key="device.id"
              :value="device.id"
              :label="`${device.name} · ${warehouseName(device.warehouse_id)}`"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="目标仓库">
          <el-select
            v-model="moveForm.targetWarehouseId"
            placeholder="选择目标仓库"
          >
            <el-option
              v-for="warehouse in targetWarehouses"
              :key="warehouse.id"
              :value="warehouse.id"
              :label="warehouse.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="调仓备注">
          <el-input
            v-model="moveForm.note"
            maxlength="500"
            show-word-limit
            placeholder="可选，记录调仓原因"
          />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            :loading="previewLoading"
            :disabled="!canPreview"
            @click="loadPreview"
          >
            预览影响并确认
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-dialog
      v-model="previewDialogVisible"
      title="确认设备调仓"
      width="820px"
    >
      <template v-if="preview">
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          title="调仓只更新真实设备位置并重新分配逻辑附件，不会修改下列订单的物流天数、计划寄出/回仓日期或估算快照。"
        />
        <el-descriptions :column="2" border class="move-summary">
          <el-descriptions-item label="设备">
            {{ preview.device.name }}
          </el-descriptions-item>
          <el-descriptions-item label="仓库变化">
            {{ preview.current_warehouse?.name || '未设置' }} →
            {{ preview.target_warehouse.name }}
          </el-descriptions-item>
        </el-descriptions>
        <el-table
          :data="preview.affected_rentals"
          max-height="360"
          empty-text="没有受影响的未来订单"
        >
          <el-table-column label="订单" min-width="130">
            <template #default="scope">
              {{ scope.row.order_number || `#${scope.row.rental_id}` }}
            </template>
          </el-table-column>
          <el-table-column label="客户使用期" min-width="190">
            <template #default="scope">
              {{ scope.row.customer_start_date }} ～ {{ scope.row.customer_end_date }}
            </template>
          </el-table-column>
          <el-table-column prop="logistics_days" label="物流天数" width="95" />
          <el-table-column label="计划寄出 / 回仓" min-width="210">
            <template #default="scope">
              {{ scope.row.planned_ship_out_date || '未设置' }} /
              {{ scope.row.planned_return_date || '未设置' }}
            </template>
          </el-table-column>
          <el-table-column label="附件" min-width="150">
            <template #default="scope">
              {{ scope.row.affected_accessory_types.map((item: any) => item.name).join('、') || '无' }}
            </template>
          </el-table-column>
        </el-table>
      </template>
      <template #footer>
        <el-button @click="previewDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="confirmLoading" @click="confirmMove">
          确认调仓
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="deviceDialogVisible" title="新增主设备" width="520px">
      <el-form label-width="90px">
        <el-form-item label="设备名称"><el-input v-model="deviceForm.name" /></el-form-item>
        <el-form-item label="序列号"><el-input v-model="deviceForm.serial_number" /></el-form-item>
        <el-form-item label="设备型号">
          <el-select v-model="deviceForm.model_id" placeholder="选择主设备型号">
            <el-option
              v-for="model in deviceModels"
              :key="model.id"
              :label="model.display_name"
              :value="model.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="所在仓库">
          <el-select v-model="deviceForm.warehouse_id" placeholder="不选则使用默认仓">
            <el-option
              v-for="warehouse in readyWarehouses"
              :key="warehouse.id"
              :label="warehouse.name || '未命名仓库'"
              :value="warehouse.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="deviceDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="deviceCreateLoading"
          :disabled="!canCreateDevice"
          @click="submitDevice"
        >
          创建设备
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="createDialogVisible"
      :title="editingWarehouseId === null ? '新增仓库' : '编辑仓库'"
      width="560px"
    >
      <el-form label-width="90px">
        <el-form-item label="仓库名称"><el-input v-model="createForm.name" /></el-form-item>
        <el-form-item label="联系人"><el-input v-model="createForm.contact_name" /></el-form-item>
        <el-form-item label="联系电话"><el-input v-model="createForm.contact_phone" /></el-form-item>
        <el-form-item label="省"><el-input v-model="createForm.province" /></el-form-item>
        <el-form-item label="市"><el-input v-model="createForm.city" /></el-form-item>
        <el-form-item label="区/县"><el-input v-model="createForm.district" /></el-form-item>
        <el-form-item label="详细地址"><el-input v-model="createForm.address_detail" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="createLoading"
          :disabled="!canCreate"
          @click="submitProfile"
        >
          {{ editingWarehouseId === null ? '创建仓库' : '保存修改' }}
        </el-button>
      </template>
    </el-dialog>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'

import {
  confirmDeviceMove,
  createWarehouseMainDevice,
  createWarehouse,
  deactivateWarehouse,
  getWarehousePreferences,
  listWarehouseDevices,
  listWarehouseDeviceModels,
  listWarehouses,
  previewDeviceMove,
  setDefaultWarehouse,
  setWarehousePreference,
  updateWarehouse,
  type DeviceMovePreview,
  type WarehouseDevice,
  type WarehouseSummary,
  type WarehousePreferenceScene,
  type WarehouseDeviceModel,
} from '@/api/warehouse'

const router = useRouter()
const loading = ref(false)
const previewLoading = ref(false)
const confirmLoading = ref(false)
const createLoading = ref(false)
const deviceCreateLoading = ref(false)
const previewDialogVisible = ref(false)
const createDialogVisible = ref(false)
const deviceDialogVisible = ref(false)
const editingWarehouseId = ref<number | null>(null)
const warehouses = ref<WarehouseSummary[]>([])
const devices = ref<WarehouseDevice[]>([])
const deviceModels = ref<WarehouseDeviceModel[]>([])
const preview = ref<DeviceMovePreview | null>(null)
const preferenceForm = reactive<Record<WarehousePreferenceScene, number | null>>({
  booking: null,
  shipping: null,
  inspection: null,
})
const preferenceScenes: Array<{
  value: WarehousePreferenceScene
  label: string
}> = [
  { value: 'booking', label: '预约' },
  { value: 'shipping', label: '发货与打印' },
  { value: 'inspection', label: '验货' },
]

const moveForm = reactive({
  deviceId: null as number | null,
  targetWarehouseId: null as number | null,
  note: '',
})

const createForm = reactive({
  name: '',
  contact_name: '',
  contact_phone: '',
  province: '',
  city: '',
  district: '',
  address_detail: '',
})
const deviceForm = reactive({
  name: '',
  serial_number: '',
  model_id: null as number | null,
  warehouse_id: null as number | null,
})

const selectedDevice = computed(() =>
  devices.value.find(device => device.id === moveForm.deviceId)
)
const targetWarehouses = computed(() =>
  warehouses.value.filter(
    warehouse => warehouse.id !== selectedDevice.value?.warehouse_id
      && warehouse.status === 'active'
      && warehouse.setup_state === 'ready'
  )
)
const readyWarehouses = computed(() =>
  warehouses.value.filter(
    warehouse => warehouse.status === 'active'
      && warehouse.setup_state === 'ready'
  )
)
const canPreview = computed(() =>
  moveForm.deviceId !== null && moveForm.targetWarehouseId !== null
)
const canCreate = computed(() =>
  Object.values(createForm).every(value => value.trim().length > 0)
)
const canCreateDevice = computed(() =>
  deviceForm.name.trim().length > 0
    && deviceForm.serial_number.trim().length > 0
    && deviceForm.model_id !== null
)

const warehouseName = (warehouseId: number | null) =>
  warehouses.value.find(item => item.id === warehouseId)?.name || '未设置仓库'
const warehouseAddress = (warehouse: WarehouseSummary) =>
  [
    warehouse.province,
    warehouse.city,
    warehouse.district,
    warehouse.address_detail,
  ].filter(Boolean).join('')

const resetProfileForm = () => {
  Object.keys(createForm).forEach((key) => {
    createForm[key as keyof typeof createForm] = ''
  })
}

const openCreate = () => {
  editingWarehouseId.value = null
  resetProfileForm()
  createDialogVisible.value = true
}

const openEdit = (warehouse: WarehouseSummary) => {
  editingWarehouseId.value = warehouse.id
  createForm.name = warehouse.name || ''
  createForm.contact_name = warehouse.contact_name || ''
  createForm.contact_phone = warehouse.contact_phone || ''
  createForm.province = warehouse.province || ''
  createForm.city = warehouse.city || ''
  createForm.district = warehouse.district || ''
  createForm.address_detail = warehouse.address_detail || ''
  createDialogVisible.value = true
}

const loadPage = async () => {
  loading.value = true
  try {
    const [warehouseRows, deviceRows, modelRows, preferences] = await Promise.all([
      listWarehouses(),
      listWarehouseDevices(),
      listWarehouseDeviceModels(),
      getWarehousePreferences(),
    ])
    warehouses.value = warehouseRows
    devices.value = deviceRows
    deviceModels.value = modelRows
    preferenceForm.booking = preferences.booking ?? null
    preferenceForm.shipping = preferences.shipping ?? null
    preferenceForm.inspection = preferences.inspection ?? null
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

const loadPreview = async () => {
  if (!canPreview.value) return
  previewLoading.value = true
  try {
    preview.value = await previewDeviceMove({
      device_id: moveForm.deviceId!,
      target_warehouse_id: moveForm.targetWarehouseId!,
    })
    previewDialogVisible.value = true
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    previewLoading.value = false
  }
}

const confirmMove = async () => {
  if (!preview.value) return
  confirmLoading.value = true
  try {
    const result = await confirmDeviceMove({
      device_id: preview.value.device.id,
      target_warehouse_id: preview.value.target_warehouse.id,
      expected_current_warehouse_id: preview.value.device.warehouse_id,
      expected_preview_revision: preview.value.revision,
      confirmed: true,
      ...(moveForm.note.trim() ? { note: moveForm.note.trim() } : {}),
    })
    const shortageIds = Array.from(new Set(
      result.accessory_fulfillment
        .filter(item => item.status === 'shortage')
        .map(item => item.rental_id)
    )).sort((left, right) => left - right)
    if (shortageIds.length > 0) {
      ElMessage.warning(
        `调仓已完成；订单 #${shortageIds.join('、#')} 的附件仍然不足`
      )
    } else {
      ElMessage.success('调仓完成，未来附件预留已重新核对')
    }
    previewDialogVisible.value = false
    preview.value = null
    moveForm.deviceId = null
    moveForm.targetWarehouseId = null
    moveForm.note = ''
    await loadPage()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    confirmLoading.value = false
  }
}

const submitProfile = async () => {
  if (!canCreate.value) return
  createLoading.value = true
  try {
    if (editingWarehouseId.value === null) {
      await createWarehouse({ ...createForm })
      ElMessage.success('仓库创建成功')
    } else {
      await updateWarehouse(editingWarehouseId.value, { ...createForm })
      ElMessage.success('仓库资料已更新')
    }
    createDialogVisible.value = false
    editingWarehouseId.value = null
    resetProfileForm()
    await loadPage()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    createLoading.value = false
  }
}

const makeDefault = async (warehouse: WarehouseSummary) => {
  try {
    await ElMessageBox.confirm(
      `确认将“${warehouse.name || '未命名仓库'}”设为默认仓库？`,
      '更改默认仓库',
      { type: 'warning' },
    )
    await setDefaultWarehouse(warehouse.id)
    ElMessage.success('默认仓库已更新')
    await loadPage()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error((error as Error).message)
    }
  }
}

const deactivate = async (warehouse: WarehouseSummary) => {
  try {
    await ElMessageBox.confirm(
      `停用“${warehouse.name || '未命名仓库'}”后将不再用于新业务，历史记录仍会保留。`,
      '确认停用仓库',
      { type: 'warning' },
    )
    await deactivateWarehouse(warehouse.id)
    ElMessage.success('仓库已停用，历史记录保持不变')
    await loadPage()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error((error as Error).message)
    }
  }
}

const savePreference = async (scene: WarehousePreferenceScene) => {
  const warehouseId = preferenceForm[scene]
  if (warehouseId === null) return
  try {
    await setWarehousePreference(scene, warehouseId)
    ElMessage.success('最近工作仓已保存')
  } catch (error) {
    ElMessage.error((error as Error).message)
    await loadPage()
  }
}

const submitDevice = async () => {
  if (!canCreateDevice.value || deviceForm.model_id === null) return
  deviceCreateLoading.value = true
  try {
    await createWarehouseMainDevice({
      name: deviceForm.name.trim(),
      serial_number: deviceForm.serial_number.trim(),
      model_id: deviceForm.model_id,
      ...(deviceForm.warehouse_id === null
        ? {}
        : { warehouse_id: deviceForm.warehouse_id }),
    })
    ElMessage.success('主设备已创建并分配仓库')
    deviceDialogVisible.value = false
    deviceForm.name = ''
    deviceForm.serial_number = ''
    deviceForm.model_id = null
    deviceForm.warehouse_id = null
    await loadPage()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    deviceCreateLoading.value = false
  }
}

onMounted(loadPage)
</script>

<style scoped>
.warehouse-page {
  min-height: 100vh;
  padding: 28px;
  background: #f5f7fa;
}
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 20px;
}
.page-header h1 { margin: 8px 0; }
.page-header p { margin: 0; color: #606266; }
.header-actions { display: flex; gap: 8px; }
.move-card { margin-top: 20px; }
.preference-card { margin-top: 20px; }
.card-tip { margin: 0 0 14px; color: #606266; }
.preference-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(180px, 1fr));
  gap: 16px;
}
.preference-grid label { display: grid; gap: 8px; color: #606266; }
.preference-grid :deep(.el-select) { width: 100%; }
.move-form { max-width: 640px; }
.move-form :deep(.el-select) { width: 100%; }
.setup-form :deep(.el-select),
.el-dialog :deep(.el-select) { width: 100%; }
.move-summary { margin: 16px 0; }
</style>

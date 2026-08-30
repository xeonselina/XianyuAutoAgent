<script setup lang="ts">
import axios from 'axios'
import { computed, onMounted, reactive, ref } from 'vue'
import { Delete, Edit, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import type { DeviceModel } from '@/stores/gantt'
import { useAuthStore } from '@/stores/auth'


type LibraryModel = DeviceModel & {
  device_count: number
  accessory_count: number
  is_accessory: boolean
  parent_model_id: number | null
}

type LegacyGroup = {
  normalized_model: string
  model: string
  device_count: number
}

type ModelForm = {
  id?: number
  name: string
  display_name: string
  description: string
  device_value?: number
  is_accessory: boolean
  parent_model_id?: number
  is_active: boolean
  default_accessories_text: string
}

const emit = defineEmits<{ changed: [] }>()
const auth = useAuthStore()
const models = ref<LibraryModel[]>([])
const legacyGroups = ref<LegacyGroup[]>([])
const loading = ref(false)
const saving = ref(false)
const editorVisible = ref(false)
const editorMode = ref<'create' | 'edit'>('create')
const keyword = ref('')
const typeFilter = ref<'all' | 'device' | 'accessory'>('all')
const statusFilter = ref<'all' | 'active' | 'inactive'>('all')
const legacyAssignments = reactive<Record<string, number | undefined>>({})

const canManage = computed(() => auth.member?.role === 'admin')
const blankForm = (): ModelForm => ({
  name: '',
  display_name: '',
  description: '',
  device_value: undefined,
  is_accessory: false,
  parent_model_id: undefined,
  is_active: true,
  default_accessories_text: '',
})
const form = reactive<ModelForm>(blankForm())

const mainModels = computed(() => models.value.filter((item) => !item.is_accessory))
const activeModels = computed(() => models.value.filter((item) => item.is_active))
const filteredModels = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  return models.value.filter((item) => {
    if (typeFilter.value === 'device' && item.is_accessory) return false
    if (typeFilter.value === 'accessory' && !item.is_accessory) return false
    if (statusFilter.value === 'active' && !item.is_active) return false
    if (statusFilter.value === 'inactive' && item.is_active) return false
    if (!query) return true
    return item.name.toLowerCase().includes(query)
      || item.display_name.toLowerCase().includes(query)
      || (item.description || '').toLowerCase().includes(query)
  })
})

const apiError = (error: any, fallback: string) => (
  error?.response?.data?.message
  || error?.response?.data?.error
  || error?.message
  || fallback
)

const loadLibrary = async () => {
  loading.value = true
  try {
    const response = await axios.get('/api/device-models/library')
    const payload = response.data?.data || {}
    models.value = payload.models || []
    legacyGroups.value = payload.legacy_groups || []
  } catch (error) {
    ElMessage.error(apiError(error, '型号库加载失败'))
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  editorMode.value = 'create'
  Object.assign(form, blankForm())
  editorVisible.value = true
}

const openEdit = (model: LibraryModel) => {
  editorMode.value = 'edit'
  Object.assign(form, {
    id: model.id,
    name: model.name,
    display_name: model.display_name,
    description: model.description || '',
    device_value: model.device_value ?? undefined,
    is_accessory: model.is_accessory,
    parent_model_id: model.parent_model_id ?? undefined,
    is_active: model.is_active,
    default_accessories_text: (model.default_accessories || []).join('\n'),
  })
  editorVisible.value = true
}

const saveModel = async () => {
  if (!form.name.trim() || !form.display_name.trim()) {
    ElMessage.warning('请填写型号编码和显示名称')
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      display_name: form.display_name.trim(),
      description: form.description.trim() || null,
      device_value: form.device_value ?? null,
      is_accessory: form.is_accessory,
      parent_model_id: form.is_accessory ? form.parent_model_id || null : null,
      is_active: form.is_active,
      default_accessories: form.default_accessories_text
        .split('\n')
        .map((item) => item.trim())
        .filter(Boolean),
    }
    if (editorMode.value === 'create') {
      await axios.post('/api/device-models', payload)
      ElMessage.success('型号创建成功')
    } else if (form.id) {
      await axios.put(`/api/device-models/${form.id}`, payload)
      ElMessage.success('型号更新成功')
    }
    editorVisible.value = false
    await loadLibrary()
    emit('changed')
  } catch (error) {
    ElMessage.error(apiError(error, '型号保存失败'))
  } finally {
    saving.value = false
  }
}

const toggleModel = async (model: LibraryModel) => {
  const nextActive = !model.is_active
  if (!nextActive) {
    try {
      await ElMessageBox.confirm(
        `停用“${model.display_name}”后，它不会再出现在新增设备的型号列表中，历史设备不受影响。`,
        '停用型号',
        { type: 'warning', confirmButtonText: '确认停用', cancelButtonText: '取消' },
      )
    } catch (error) {
      if (error === 'cancel' || error === 'close') return
      throw error
    }
  }
  try {
    await axios.put(`/api/device-models/${model.id}`, {
      name: model.name,
      is_active: nextActive,
    })
    ElMessage.success(nextActive ? '型号已启用' : '型号已停用')
    await loadLibrary()
    emit('changed')
  } catch (error) {
    ElMessage.error(apiError(error, '型号状态更新失败'))
  }
}

const deleteModel = async (model: LibraryModel) => {
  try {
    await ElMessageBox.confirm(
      `确认永久删除未使用的型号“${model.display_name}”？`,
      '删除型号',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
    await axios.delete(`/api/device-models/${model.id}`)
    ElMessage.success('型号已删除')
    await loadLibrary()
    emit('changed')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiError(error, '型号删除失败'))
  }
}

const assignLegacy = async (group: LegacyGroup) => {
  const modelId = legacyAssignments[group.normalized_model]
  if (!modelId) {
    ElMessage.warning('请选择要归入的正式型号')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将 ${group.device_count} 台“${group.model}”设备统一归入所选正式型号？`,
      '归类历史型号',
      { type: 'warning', confirmButtonText: '确认归类', cancelButtonText: '取消' },
    )
    await axios.post('/api/device-models/assign-legacy', {
      legacy_model: group.normalized_model,
      model_id: modelId,
    })
    ElMessage.success('历史型号归类成功')
    await loadLibrary()
    emit('changed')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiError(error, '历史型号归类失败'))
  }
}

onMounted(loadLibrary)
defineExpose({ loadLibrary, openCreate })
</script>

<template>
  <section class="model-panel" data-testid="model-library">
    <div class="model-toolbar">
      <el-input
        v-model="keyword"
        class="model-search"
        clearable
        placeholder="搜索型号编码、名称或说明"
        :prefix-icon="Search"
      />
      <el-select v-model="typeFilter" class="model-filter">
        <el-option label="全部类型" value="all" />
        <el-option label="主设备" value="device" />
        <el-option label="附件" value="accessory" />
      </el-select>
      <el-select v-model="statusFilter" class="model-filter">
        <el-option label="全部状态" value="all" />
        <el-option label="启用" value="active" />
        <el-option label="停用" value="inactive" />
      </el-select>
      <span class="toolbar-spacer" />
      <el-button :icon="Refresh" :loading="loading" @click="loadLibrary">刷新</el-button>
      <el-button
        data-testid="add-model"
        type="primary"
        :icon="Plus"
        :disabled="!canManage"
        @click="openCreate"
      >新增型号</el-button>
    </div>

    <el-alert
      v-if="!canManage"
      title="普通操作员可以查看型号库；新增、编辑、停用和删除仅限店铺管理员。"
      type="info"
      :closable="false"
      show-icon
    />

    <div v-if="legacyGroups.length" class="legacy-card">
      <div class="legacy-card__heading">
        <div>
          <strong>待归类历史型号</strong>
          <span>这些设备仍在使用旧的自由文本型号，归类后统计与筛选会更准确。</span>
        </div>
        <el-tag type="warning">{{ legacyGroups.length }} 组</el-tag>
      </div>
      <div
        v-for="group in legacyGroups"
        :key="group.normalized_model"
        class="legacy-row"
      >
        <div>
          <strong>{{ group.model }}</strong>
          <small>{{ group.device_count }} 台设备</small>
        </div>
        <el-select
          v-model="legacyAssignments[group.normalized_model]"
          filterable
          placeholder="选择正式型号"
        >
          <el-option
            v-for="model in activeModels"
            :key="model.id"
            :label="`${model.display_name} · ${model.name}`"
            :value="model.id"
          />
        </el-select>
        <el-button
          type="primary"
          plain
          :disabled="!canManage"
          @click="assignLegacy(group)"
        >归类</el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="filteredModels" stripe>
      <el-table-column label="型号" min-width="210">
        <template #default="{ row }">
          <div class="model-name">
            <strong>{{ row.display_name }}</strong>
            <code>{{ row.name }}</code>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="90">
        <template #default="{ row }">{{ row.is_accessory ? '附件' : '主设备' }}</template>
      </el-table-column>
      <el-table-column label="设备价值" width="130">
        <template #default="{ row }">
          {{ row.device_value == null ? '—' : `¥${Number(row.device_value).toLocaleString()}` }}
        </template>
      </el-table-column>
      <el-table-column prop="device_count" label="关联设备" width="100" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="说明" min-width="180" show-overflow-tooltip />
      <el-table-column label="操作" width="205" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" :icon="Edit" :disabled="!canManage" @click="openEdit(row)">编辑</el-button>
          <el-button link :disabled="!canManage" @click="toggleModel(row)">
            {{ row.is_active ? '停用' : '启用' }}
          </el-button>
          <el-button
            link
            type="danger"
            :icon="Delete"
            :disabled="!canManage || row.device_count > 0 || row.accessory_count > 0"
            @click="deleteModel(row)"
          >删除</el-button>
        </template>
      </el-table-column>
      <template #empty><el-empty description="没有符合条件的型号" /></template>
    </el-table>

    <el-dialog
      v-model="editorVisible"
      :title="editorMode === 'create' ? '新增设备型号' : '编辑设备型号'"
      width="560px"
      destroy-on-close
    >
      <el-form label-position="top" @submit.prevent="saveModel">
        <div class="form-grid">
          <el-form-item label="型号编码" required>
            <el-input
              v-model="form.name"
              :disabled="editorMode === 'edit'"
              maxlength="50"
              placeholder="例如 x200u"
            />
          </el-form-item>
          <el-form-item label="显示名称" required>
            <el-input v-model="form.display_name" maxlength="100" placeholder="例如 富士 X200U" />
          </el-form-item>
        </div>
        <div class="form-grid">
          <el-form-item label="型号类型">
            <el-radio-group v-model="form.is_accessory">
              <el-radio-button :value="false">主设备</el-radio-button>
              <el-radio-button :value="true">附件</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="设备价值">
            <el-input-number v-model="form.device_value" :min="0" :max="99999999.99" :precision="2" controls-position="right" />
          </el-form-item>
        </div>
        <el-form-item v-if="form.is_accessory" label="所属主设备型号">
          <el-select v-model="form.parent_model_id" clearable filterable style="width: 100%">
            <el-option
              v-for="model in mainModels"
              :key="model.id"
              :label="model.display_name"
              :value="model.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="默认附件清单">
          <el-input
            v-model="form.default_accessories_text"
            type="textarea"
            :rows="3"
            placeholder="每行一个，例如：电池&#10;充电器&#10;收纳包"
          />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" type="textarea" :rows="2" maxlength="500" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.is_active" active-text="启用" inactive-text="停用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveModel">保存型号</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.model-panel { display: grid; gap: 14px; }
.model-toolbar { display: flex; align-items: center; gap: 10px; }
.model-search { width: min(360px, 35vw); }
.model-filter { width: 130px; }
.toolbar-spacer { flex: 1; }
.legacy-card { display: grid; gap: 8px; padding: 14px; border: 1px solid #fedf89; border-radius: 10px; background: #fffaeb; }
.legacy-card__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.legacy-card__heading div { display: grid; gap: 3px; }
.legacy-card__heading span { color: #93370d; font-size: 12px; }
.legacy-row { display: grid; grid-template-columns: minmax(170px, 1fr) minmax(240px, 1.4fr) auto; align-items: center; gap: 10px; padding-top: 8px; border-top: 1px solid #fedf89; }
.legacy-row > div { display: grid; gap: 2px; }
.legacy-row small { color: #b54708; }
.model-name { display: grid; gap: 3px; }
.model-name code { width: fit-content; padding: 1px 5px; border-radius: 4px; color: #475467; background: #f2f4f7; font-size: 11px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }

@media (max-width: 760px) {
  .model-toolbar { align-items: stretch; flex-direction: column; }
  .model-search, .model-filter { width: 100%; }
  .toolbar-spacer { display: none; }
  .legacy-row { grid-template-columns: 1fr; }
  .form-grid { grid-template-columns: 1fr; gap: 0; }
}
</style>

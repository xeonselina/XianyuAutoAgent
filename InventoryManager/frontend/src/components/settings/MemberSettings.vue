<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  createMember,
  listMembers,
  updateMember,
  type TenantMember,
} from '@/api/settings'


const members = ref<TenantMember[]>([])
const loading = ref(false)
const adding = ref(false)
const form = reactive({ phone: '', role: 'operator' as TenantMember['role'] })

const load = async () => {
  loading.value = true
  try {
    members.value = await listMembers()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '成员加载失败')
  } finally {
    loading.value = false
  }
}

const add = async () => {
  if (!form.phone.trim()) return
  loading.value = true
  try {
    await createMember(form.phone, form.role)
    form.phone = ''
    adding.value = false
    await load()
    ElMessage.success('成员已添加')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '成员添加失败')
  } finally {
    loading.value = false
  }
}

const patchMember = async (
  member: TenantMember,
  patch: Partial<Pick<TenantMember, 'role' | 'status'>>,
) => {
  try {
    const updated = await updateMember(member.id, patch)
    Object.assign(member, updated)
    ElMessage.success('成员已更新')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '成员更新失败')
  }
}

onMounted(load)
</script>

<template>
  <section>
    <div class="section-actions">
      <p>成员用手机号登录，禁用后现有会话将失效。</p>
      <el-button type="primary" @click="adding = true">添加成员</el-button>
    </div>
    <el-table :data="members" v-loading="loading">
      <el-table-column prop="phone" label="手机号" />
      <el-table-column label="角色" width="160">
        <template #default="{ row }">
          <el-select
            :model-value="row.role"
            @update:model-value="patchMember(row, { role: $event })"
          >
            <el-option label="Admin" value="admin" />
            <el-option label="Operator" value="operator" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="150">
        <template #default="{ row }">
          <el-switch
            :model-value="row.status === 'active'"
            active-text="启用"
            inactive-text="禁用"
            @change="patchMember(row, { status: $event ? 'active' : 'disabled' })"
          />
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="adding" title="添加成员" width="420px">
      <el-form label-width="80px">
        <el-form-item label="手机号">
          <el-input v-model="form.phone" placeholder="13800138000" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role">
            <el-option label="Operator" value="operator" />
            <el-option label="Admin" value="admin" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="adding = false">取消</el-button>
        <el-button type="primary" :loading="loading" @click="add">添加</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.section-actions { display: flex; align-items: center; justify-content: space-between; }
.section-actions p { color: #667085; }
</style>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  createMember,
  listMembers,
  resetMemberPassword,
  updateMember,
  type TenantMember,
} from '@/api/settings'
import { useAuthStore } from '@/stores/auth'


const auth = useAuthStore()
const members = ref<TenantMember[]>([])
const loading = ref(false)
const adding = ref(false)
const resetting = ref(false)
const resetTarget = ref<TenantMember | null>(null)
const form = reactive({
  phone: '',
  role: 'operator' as TenantMember['role'],
  initialPassword: '',
  confirmPassword: '',
})
const resetForm = reactive({ newPassword: '', confirmPassword: '' })

const passwordIsValid = (password: string) => (
  password.length >= 8 && password.length <= 128
)

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
  if (!form.phone.trim()) {
    ElMessage.warning('请输入成员手机号')
    return
  }
  if (!passwordIsValid(form.initialPassword)) {
    ElMessage.warning('初始密码必须为 8 至 128 个字符')
    return
  }
  if (form.initialPassword !== form.confirmPassword) {
    ElMessage.warning('两次输入的初始密码不一致')
    return
  }
  loading.value = true
  try {
    await createMember(form.phone, form.role, form.initialPassword)
    form.phone = ''
    form.initialPassword = ''
    form.confirmPassword = ''
    adding.value = false
    await load()
    ElMessage.success('成员已添加')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '成员添加失败')
  } finally {
    loading.value = false
  }
}

const openPasswordReset = (member: TenantMember) => {
  resetTarget.value = member
  resetForm.newPassword = ''
  resetForm.confirmPassword = ''
}

const closePasswordReset = () => {
  resetTarget.value = null
  resetForm.newPassword = ''
  resetForm.confirmPassword = ''
}

const resetPassword = async () => {
  if (!resetTarget.value) return
  if (!passwordIsValid(resetForm.newPassword)) {
    ElMessage.warning('新密码必须为 8 至 128 个字符')
    return
  }
  if (resetForm.newPassword !== resetForm.confirmPassword) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  resetting.value = true
  try {
    await resetMemberPassword(
      resetTarget.value.id,
      resetForm.newPassword,
    )
    closePasswordReset()
    ElMessage.success('密码已重置，该成员需重新登录')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '密码重置失败')
  } finally {
    resetting.value = false
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
      <p>成员使用手机号和管理员设置的密码登录。</p>
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
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <el-button
            type="primary"
            link
            :disabled="auth.member?.id === row.id"
            :title="
              auth.member?.id === row.id
                ? '请从右上角进入修改密码'
                : '为该成员设置新密码'
            "
            @click="openPasswordReset(row)"
          >重置密码</el-button>
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
        <el-form-item label="初始密码">
          <el-input
            v-model="form.initialPassword"
            data-testid="member-initial-password"
            type="password"
            show-password
            autocomplete="new-password"
            minlength="8"
            maxlength="128"
            placeholder="8 至 128 个字符"
          />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input
            v-model="form.confirmPassword"
            data-testid="member-confirm-password"
            type="password"
            show-password
            autocomplete="new-password"
            minlength="8"
            maxlength="128"
            placeholder="再次输入初始密码"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="adding = false">取消</el-button>
        <el-button type="primary" :loading="loading" @click="add">添加</el-button>
      </template>
    </el-dialog>

    <el-dialog
      :model-value="resetTarget !== null"
      :title="`重置成员密码 · ${resetTarget?.phone || ''}`"
      width="420px"
      @close="closePasswordReset"
    >
      <el-alert
        title="保存后，该成员在其他设备上的登录会立即失效。"
        type="warning"
        :closable="false"
        show-icon
      />
      <el-form label-width="88px" class="password-form">
        <el-form-item label="新密码">
          <el-input
            v-model="resetForm.newPassword"
            data-testid="member-reset-password"
            type="password"
            show-password
            autocomplete="new-password"
            minlength="8"
            maxlength="128"
            placeholder="8 至 128 个字符"
          />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input
            v-model="resetForm.confirmPassword"
            data-testid="member-reset-confirm-password"
            type="password"
            show-password
            autocomplete="new-password"
            minlength="8"
            maxlength="128"
            placeholder="再次输入新密码"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closePasswordReset">取消</el-button>
        <el-button type="primary" :loading="resetting" @click="resetPassword">确认重置</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.section-actions { display: flex; align-items: center; justify-content: space-between; }
.section-actions p { color: #667085; }
.password-form { margin-top: 20px; }
</style>

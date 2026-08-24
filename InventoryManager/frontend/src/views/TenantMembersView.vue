<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  confirmTenantMemberMutation,
  createTenantInvitation,
  getTenantMemberDirectory,
  mutateTenantMember,
  requestAdminInvitationChallenge,
  requestTenantMemberMutationChallenge,
  revokeTenantInvitation,
  type TenantInvitationSummary,
  type TenantMemberDirectory,
  type TenantMemberSummary,
  type TenantMemberMutationAction,
} from '@/api/tenantIdentity'

const directory = ref<TenantMemberDirectory | null>(null)
const loading = ref(false)
const submitting = ref(false)
const phone = ref('')
const role = ref<'admin' | 'operator'>('operator')
const adminActionId = ref('')
const adminChallengeId = ref('')
const adminCode = ref('')
const oneTimeLink = ref('')
const mutatingMemberId = ref('')

const pendingInvitations = computed(() =>
  directory.value?.invitations.filter(item => item.status === 'pending') ?? [],
)

async function refresh() {
  loading.value = true
  try {
    directory.value = await getTenantMemberDirectory()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '成员列表加载失败')
  } finally {
    loading.value = false
  }
}

async function submitInvitation() {
  if (!phone.value.trim()) return ElMessage.warning('请输入中国大陆手机号')
  submitting.value = true
  try {
    if (role.value === 'admin' && !adminChallengeId.value) {
      if (!adminActionId.value) adminActionId.value = crypto.randomUUID()
      const challenge = await requestAdminInvitationChallenge(
        phone.value,
        adminActionId.value,
      )
      adminChallengeId.value = challenge.challenge_id
      ElMessage.success('验证码已发送到你当前登录的手机号')
      return
    }
    const result = await createTenantInvitation({
      phone: phone.value,
      role: role.value,
      action_id: adminActionId.value || undefined,
      challenge_id: adminChallengeId.value || undefined,
      code: adminCode.value || undefined,
    })
    oneTimeLink.value = new URL(result.invitation_path, window.location.origin).href
    phone.value = ''
    adminChallengeId.value = ''
    adminCode.value = ''
    await refresh()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '邀请创建失败')
  } finally {
    submitting.value = false
  }
}

async function rotateLink(item: TenantInvitationSummary) {
  submitting.value = true
  try {
    const result = await createTenantInvitation({
      phone: item.phone,
      role: item.role,
      expected_row_version: item.row_version,
    })
    oneTimeLink.value = new URL(result.invitation_path, window.location.origin).href
    await refresh()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '链接重新生成失败')
  } finally {
    submitting.value = false
  }
}

async function revoke(item: TenantInvitationSummary) {
  try {
    await ElMessageBox.confirm('撤销后该链接将立即失效并释放席位。', '撤销邀请')
    await revokeTenantInvitation(item.invitation_id, item.row_version)
    await refresh()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error instanceof Error ? error.message : '邀请撤销失败')
  }
}

async function copyOneTimeLink() {
  await navigator.clipboard.writeText(oneTimeLink.value)
  ElMessage.success('邀请链接已复制，请通过微信等现有渠道发送')
}

async function mutateMember(
  member: TenantMemberSummary,
  action: TenantMemberMutationAction,
  targetRole?: 'admin' | 'operator',
) {
  const labels = {
    enable: '启用',
    disable: '停用',
    release: '移除',
    change_role: targetRole === 'admin' ? '设为 Admin' : '设为 Operator',
  }
  try {
    await ElMessageBox.confirm(
      `${labels[action]}该 ${member.role}？${action === 'release' ? '移除后不会自动恢复历史邀请。' : ''}`,
      `${labels[action]}成员`,
    )
    mutatingMemberId.value = member.membership_id
    if (member.role === 'admin' || action === 'change_role') {
      const actionId = crypto.randomUUID()
      const challenge = await requestTenantMemberMutationChallenge(
        member,
        action,
        actionId,
        targetRole,
      )
      const { value: code } = await ElMessageBox.prompt(
        '验证码已发送到你当前登录的手机号，5 分钟内有效。',
        '验证本人',
        {
          inputPattern: /^\d{6}$/,
          inputErrorMessage: '请输入 6 位验证码',
          confirmButtonText: '确认变更',
        },
      )
      await confirmTenantMemberMutation(
        member,
        action,
        actionId,
        challenge.challenge_id,
        code,
        targetRole,
      )
    } else {
      await mutateTenantMember(member, action)
    }
    await refresh()
    ElMessage.success(`成员已${labels[action]}`)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error instanceof Error ? error.message : '成员变更失败')
  } finally {
    mutatingMemberId.value = ''
  }
}

function resetAdminProof() {
  adminActionId.value = ''
  adminChallengeId.value = ''
  adminCode.value = ''
}

onMounted(refresh)
</script>

<template>
  <main class="members-page" v-loading="loading">
    <header>
      <div>
        <h1>成员与邀请</h1>
        <p>唯一席位规则：有效成员与未过期邀请合计最多 10 个。</p>
      </div>
      <el-tag v-if="directory" size="large">
        {{ directory.seat_usage.used }} / {{ directory.seat_usage.limit }} 席
      </el-tag>
    </header>

    <el-card class="invite-card">
      <template #header>创建邀请</template>
      <el-form inline @submit.prevent="submitInvitation">
        <el-form-item label="手机号">
          <el-input v-model="phone" placeholder="13800138000" @input="resetAdminProof" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="role" style="width: 130px" @change="resetAdminProof">
            <el-option label="Operator" value="operator" />
            <el-option label="Admin" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="adminChallengeId" label="本人验证码">
          <el-input v-model="adminCode" maxlength="6" inputmode="numeric" />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="submitting">
          {{ role === 'admin' && !adminChallengeId ? '验证本人并邀请' : '生成邀请链接' }}
        </el-button>
      </el-form>
      <p class="hint">Admin 邀请需要验证当前操作者本人手机号；系统不会发送邀请通知短信。</p>
    </el-card>

    <el-alert
      v-if="oneTimeLink"
      title="邀请链接只在本次生成后显示"
      type="success"
      :closable="false"
      show-icon
    >
      <div class="link-row">
        <el-input :model-value="oneTimeLink" readonly />
        <el-button type="success" @click="copyOneTimeLink">复制链接</el-button>
      </div>
      <p>链接绑定指定手机号、7 天有效且只能使用一次。丢失后请重新生成。</p>
    </el-alert>

    <el-card>
      <template #header>成员</template>
      <el-table :data="directory?.members ?? []" empty-text="暂无成员">
        <el-table-column prop="masked_phone" label="手机号" />
        <el-table-column prop="role" label="角色" />
        <el-table-column prop="status" label="状态" />
        <el-table-column label="操作" width="300">
          <template #default="scope">
            <el-button
              v-if="scope.row.status === 'disabled'"
              link
              type="primary"
              :loading="mutatingMemberId === scope.row.membership_id"
              @click="mutateMember(scope.row, 'enable')"
            >启用</el-button>
            <el-button
              v-else
              link
              type="warning"
              :loading="mutatingMemberId === scope.row.membership_id"
              @click="mutateMember(scope.row, 'disable')"
            >停用</el-button>
            <el-button
              link
              type="danger"
              :loading="mutatingMemberId === scope.row.membership_id"
              @click="mutateMember(scope.row, 'release')"
            >移除</el-button>
            <el-button
              link
              type="primary"
              :loading="mutatingMemberId === scope.row.membership_id"
              @click="mutateMember(
                scope.row,
                'change_role',
                scope.row.role === 'admin' ? 'operator' : 'admin',
              )"
            >{{ scope.row.role === 'admin' ? '设为 Operator' : '设为 Admin' }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card>
      <template #header>待接受邀请（{{ pendingInvitations.length }}）</template>
      <el-table :data="pendingInvitations" empty-text="暂无待接受邀请">
        <el-table-column prop="masked_phone" label="手机号" />
        <el-table-column prop="role" label="角色" />
        <el-table-column prop="expires_at" label="到期时间" />
        <el-table-column label="操作" width="220">
          <template #default="scope">
            <el-button link type="primary" @click="rotateLink(scope.row)">重新生成链接</el-button>
            <el-button link type="danger" @click="revoke(scope.row)">撤销</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </main>
</template>

<style scoped>
.members-page { max-width: 1100px; margin: 0 auto; padding: 28px; display: grid; gap: 20px; }
header { display: flex; justify-content: space-between; align-items: center; }
h1 { margin: 0 0 8px; }
p { margin: 0; color: #667085; }
.hint { margin-top: 8px; font-size: 13px; }
.link-row { display: flex; gap: 12px; margin: 12px 0 8px; }
</style>

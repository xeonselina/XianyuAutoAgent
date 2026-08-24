<template>
  <section class="members-view">
    <van-nav-bar title="成员与邀请" left-arrow @click-left="router.back()" />
    <van-loading v-if="loading" class="loading" vertical>加载成员</van-loading>
    <template v-else-if="directory">
      <div class="seat-card">
        <strong>{{ directory.seat_usage.used }} / {{ directory.seat_usage.limit }} 席</strong>
        <span>有效成员 {{ directory.seat_usage.active_members }}，待接受 {{ directory.seat_usage.pending_invitations }}</span>
      </div>
      <van-form class="invite-form" @submit="submit">
        <van-field v-model="phone" label="手机号" placeholder="13800138000" @update:model-value="resetProof" />
        <van-field name="role" label="角色">
          <template #input>
            <van-radio-group v-model="role" direction="horizontal" @change="resetProof">
              <van-radio name="operator">Operator</van-radio>
              <van-radio name="admin">Admin</van-radio>
            </van-radio-group>
          </template>
        </van-field>
        <van-field v-if="adminChallengeId" v-model="adminCode" label="本人验证码" maxlength="6" type="digit" />
        <div class="submit"><van-button block type="primary" native-type="submit" :loading="submitting">
          {{ role === 'admin' && !adminChallengeId ? '验证本人并邀请' : '生成邀请链接' }}
        </van-button></div>
      </van-form>
      <div v-if="oneTimeLink" class="link-card">
        <strong>链接仅本次显示</strong>
        <p>{{ oneTimeLink }}</p>
        <van-button size="small" type="success" @click="copyLink">复制链接</van-button>
      </div>
      <van-cell-group inset title="成员">
        <van-swipe-cell v-for="member in directory.members" :key="member.membership_id">
          <van-cell :title="member.masked_phone" :label="member.role" :value="member.status" />
          <template #right>
            <van-button
              v-if="member.status === 'disabled'"
              square
              type="primary"
              text="启用"
              class="swipe-button"
              @click="mutateMember(member, 'enable')"
            />
            <van-button
              v-else
              square
              type="warning"
              text="停用"
              class="swipe-button"
              @click="mutateMember(member, 'disable')"
            />
            <van-button square type="danger" text="移除" class="swipe-button" @click="mutateMember(member, 'release')" />
            <van-button
              square
              type="primary"
              :text="member.role === 'admin' ? '降为 Operator' : '升为 Admin'"
              class="swipe-button role-button"
              @click="mutateMember(
                member,
                'change_role',
                member.role === 'admin' ? 'operator' : 'admin',
              )"
            />
          </template>
        </van-swipe-cell>
      </van-cell-group>
      <van-dialog
        v-model:show="adminMutationVisible"
        title="验证本人"
        show-cancel-button
        :before-close="finishAdminMutation"
      >
        <p class="dialog-hint">验证码已发送到你当前登录的手机号，5 分钟内有效。</p>
        <van-field v-model="memberCode" label="验证码" maxlength="6" type="digit" placeholder="请输入 6 位验证码" />
      </van-dialog>
      <van-cell-group inset title="待接受邀请">
        <van-swipe-cell v-for="item in pending" :key="item.invitation_id">
          <van-cell :title="item.masked_phone" :label="`${item.role} · ${formatTime(item.expires_at)}`" />
          <template #right>
            <van-button square type="primary" text="重发" class="swipe-button" @click="rotate(item)" />
            <van-button square type="danger" text="撤销" class="swipe-button" @click="revoke(item)" />
          </template>
        </van-swipe-cell>
        <van-empty v-if="pending.length === 0" description="暂无待接受邀请" />
      </van-cell-group>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { showConfirmDialog, showFailToast, showSuccessToast } from 'vant'
import { useRouter } from 'vue-router'

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

const router = useRouter()
const directory = ref<TenantMemberDirectory | null>(null)
const loading = ref(true)
const submitting = ref(false)
const phone = ref('')
const role = ref<'admin' | 'operator'>('operator')
const adminActionId = ref('')
const adminChallengeId = ref('')
const adminCode = ref('')
const oneTimeLink = ref('')
const pending = computed(() => directory.value?.invitations.filter(item => item.status === 'pending') ?? [])
const adminMutationVisible = ref(false)
const memberCode = ref('')
const pendingAdminMutation = ref<{
  member: TenantMemberSummary
  action: TenantMemberMutationAction
  actionId: string
  challengeId: string
  targetRole?: 'admin' | 'operator'
} | null>(null)
const formatTime = (value: string) => new Date(value).toLocaleString('zh-CN')

async function load() {
  loading.value = true
  try { directory.value = await getTenantMemberDirectory() }
  catch (error) { showFailToast((error as Error).message) }
  finally { loading.value = false }
}

function resetProof() {
  adminActionId.value = ''
  adminChallengeId.value = ''
  adminCode.value = ''
}

async function submit() {
  if (!phone.value.trim()) return showFailToast('请输入中国大陆手机号')
  submitting.value = true
  try {
    if (role.value === 'admin' && !adminChallengeId.value) {
      if (!adminActionId.value) adminActionId.value = crypto.randomUUID()
      adminChallengeId.value = (await requestAdminInvitationChallenge(
        phone.value,
        adminActionId.value,
      )).challenge_id
      showSuccessToast('验证码已发送到本人手机号')
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
    resetProof()
    await load()
  } catch (error) { showFailToast((error as Error).message) }
  finally { submitting.value = false }
}

async function rotate(item: TenantInvitationSummary) {
  try {
    const result = await createTenantInvitation({ phone: item.phone, role: item.role, expected_row_version: item.row_version })
    oneTimeLink.value = new URL(result.invitation_path, window.location.origin).href
    await load()
  } catch (error) { showFailToast((error as Error).message) }
}

async function revoke(item: TenantInvitationSummary) {
  try {
    await showConfirmDialog({ title: '撤销邀请', message: '撤销后链接立即失效并释放席位。' })
    await revokeTenantInvitation(item.invitation_id, item.row_version)
    await load()
  } catch (error) {
    if (error) showFailToast((error as Error).message)
  }
}

async function copyLink() {
  await navigator.clipboard.writeText(oneTimeLink.value)
  showSuccessToast('邀请链接已复制')
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
    await showConfirmDialog({
      title: `${labels[action]}成员`,
      message: `${labels[action]}该 ${member.role}？${action === 'release' ? '移除后不会自动恢复历史邀请。' : ''}`,
    })
    if (member.role === 'admin' || action === 'change_role') {
      const actionId = crypto.randomUUID()
      const challenge = await requestTenantMemberMutationChallenge(
        member,
        action,
        actionId,
        targetRole,
      )
      pendingAdminMutation.value = {
        member,
        action,
        actionId,
        challengeId: challenge.challenge_id,
        targetRole,
      }
      memberCode.value = ''
      adminMutationVisible.value = true
      return
    }
    await mutateTenantMember(member, action)
    await load()
    showSuccessToast(`成员已${labels[action]}`)
  } catch (error) {
    if (error) showFailToast((error as Error).message)
  }
}

async function finishAdminMutation(action: string): Promise<boolean> {
  if (action !== 'confirm') {
    pendingAdminMutation.value = null
    memberCode.value = ''
    return true
  }
  if (!/^\d{6}$/.test(memberCode.value)) {
    showFailToast('请输入 6 位验证码')
    return false
  }
  const pending = pendingAdminMutation.value
  if (!pending) return true
  try {
    await confirmTenantMemberMutation(
      pending.member,
      pending.action,
      pending.actionId,
      pending.challengeId,
      memberCode.value,
      pending.targetRole,
    )
    pendingAdminMutation.value = null
    memberCode.value = ''
    await load()
    showSuccessToast('成员已变更')
    return true
  } catch (error) {
    showFailToast((error as Error).message)
    return false
  }
}

onMounted(load)
</script>

<style scoped>
.members-view { min-height: 100%; padding-bottom: 32px; background: #f7f8fa; }
.loading { padding-top: 30vh; }
.seat-card, .link-card { margin: 16px; padding: 16px; border-radius: 8px; background: white; }
.seat-card { display: flex; justify-content: space-between; }
.seat-card span, .link-card p { color: #646566; font-size: 13px; word-break: break-all; }
.invite-form { margin: 16px; overflow: hidden; border-radius: 8px; background: white; }
.submit { padding: 16px; }
.swipe-button { height: 100%; }
.role-button { min-width: 92px; }
.dialog-hint { margin: 16px 16px 0; color: #646566; font-size: 13px; }
</style>

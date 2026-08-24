<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  acceptTenantInvitation,
  inspectTenantInvitation,
  requestTenantInvitationCode,
  type TenantInvitationCredential,
  type TenantInvitationPublicSummary,
} from '@/api/tenantIdentity'

const credential = ref<TenantInvitationCredential | null>(null)
const summary = ref<TenantInvitationPublicSummary | null>(null)
const challengeId = ref('')
const code = ref('')
const loading = ref(true)
const submitting = ref(false)
const accepted = ref(false)

function consumeFragment(): TenantInvitationCredential | null {
  const values = new URLSearchParams(window.location.hash.slice(1))
  const invitationId = values.get('invitation')
  const token = values.get('token')
  const generation = Number(values.get('generation'))
  window.history.replaceState(null, '', window.location.pathname)
  if (!invitationId || !token || !Number.isInteger(generation) || generation < 1) return null
  return { invitation_id: invitationId, token, generation }
}

onMounted(async () => {
  document.querySelector('meta[name="referrer"]')?.setAttribute('content', 'no-referrer')
  credential.value = consumeFragment()
  try {
    if (!credential.value) throw new Error('邀请链接格式无效')
    summary.value = await inspectTenantInvitation(credential.value)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '邀请已失效')
  } finally {
    loading.value = false
  }
})

async function requestCode() {
  if (!credential.value) return
  submitting.value = true
  try {
    const challenge = await requestTenantInvitationCode(credential.value)
    challengeId.value = challenge.challenge_id
    ElMessage.success(`验证码已发送至 ${summary.value?.masked_phone ?? '邀请绑定手机号'}`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '验证码发送失败')
  } finally {
    submitting.value = false
  }
}

async function accept() {
  if (!credential.value || !challengeId.value || code.value.length !== 6) return
  submitting.value = true
  try {
    await acceptTenantInvitation(credential.value, challengeId.value, code.value)
    credential.value = null
    code.value = ''
    accepted.value = true
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '邀请接受失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="invite-page" v-loading="loading">
    <el-result v-if="accepted" icon="success" title="已加入租户" sub-title="请使用邀请绑定手机号登录。">
      <template #extra><el-button type="primary" @click="$router.replace('/login')">去登录</el-button></template>
    </el-result>
    <el-card v-else-if="summary" class="invite-card">
      <h1>接受成员邀请</h1>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="租户">{{ summary.tenant_name }}</el-descriptions-item>
        <el-descriptions-item label="角色">{{ summary.role }}</el-descriptions-item>
        <el-descriptions-item label="绑定手机号">{{ summary.masked_phone }}</el-descriptions-item>
        <el-descriptions-item label="到期时间">{{ summary.expires_at }}</el-descriptions-item>
      </el-descriptions>
      <p>链接本身不能建立成员身份，必须验证邀请绑定的手机号。</p>
      <el-button v-if="!challengeId" type="primary" :loading="submitting" @click="requestCode">发送验证码</el-button>
      <div v-else class="verification">
        <el-input v-model="code" maxlength="6" inputmode="numeric" placeholder="6 位验证码" />
        <el-button type="primary" :loading="submitting" @click="accept">验证并加入</el-button>
      </div>
    </el-card>
    <el-result v-else icon="error" title="邀请不可用" sub-title="请联系邀请人重新生成链接。" />
  </main>
</template>

<style scoped>
.invite-page { min-height: 70vh; display: grid; place-items: center; padding: 24px; }
.invite-card { width: min(560px, 100%); }
h1 { margin-top: 0; }
p { color: #667085; margin: 18px 0; }
.verification { display: flex; gap: 12px; }
</style>

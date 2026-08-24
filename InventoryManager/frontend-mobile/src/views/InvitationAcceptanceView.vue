<template>
  <section class="invite-view">
    <van-nav-bar title="接受成员邀请" />
    <van-loading v-if="loading" class="loading" vertical>验证邀请</van-loading>
    <div v-else-if="accepted" class="success-card">
      <van-icon name="passed" size="64" color="#07c160" />
      <h1>已加入租户</h1>
      <p>请使用邀请绑定手机号登录。</p>
      <van-button type="primary" block @click="router.replace({ name: 'tenant-login' })">去登录</van-button>
    </div>
    <div v-else-if="summary" class="card">
      <h1>{{ summary.tenant_name }}</h1>
      <van-cell-group inset>
        <van-cell title="角色" :value="summary.role" />
        <van-cell title="绑定手机号" :value="summary.masked_phone" />
        <van-cell title="到期时间" :value="formatTime(summary.expires_at)" />
      </van-cell-group>
      <p>链接本身不能建立成员身份，必须验证邀请绑定的手机号。</p>
      <van-button v-if="!challengeId" block type="primary" :loading="submitting" @click="requestCode">发送验证码</van-button>
      <van-form v-else @submit="accept">
        <van-field v-model="code" label="验证码" type="digit" maxlength="6" placeholder="6 位验证码" />
        <van-button block type="primary" native-type="submit" :loading="submitting">验证并加入</van-button>
      </van-form>
    </div>
    <van-empty v-else image="error" description="邀请不可用，请联系邀请人重新生成链接" />
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { showFailToast, showSuccessToast } from 'vant'
import { useRouter } from 'vue-router'

import {
  acceptTenantInvitation,
  inspectTenantInvitation,
  requestTenantInvitationCode,
  type TenantInvitationCredential,
  type TenantInvitationPublicSummary,
} from '@/api/tenantIdentity'

const router = useRouter()
const credential = ref<TenantInvitationCredential | null>(null)
const summary = ref<TenantInvitationPublicSummary | null>(null)
const challengeId = ref('')
const code = ref('')
const loading = ref(true)
const submitting = ref(false)
const accepted = ref(false)
const formatTime = (value: string) => new Date(value).toLocaleString('zh-CN')

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
  } catch (error) { showFailToast((error as Error).message) }
  finally { loading.value = false }
})

async function requestCode() {
  if (!credential.value) return
  submitting.value = true
  try {
    challengeId.value = (await requestTenantInvitationCode(credential.value)).challenge_id
    showSuccessToast(`验证码已发送至 ${summary.value?.masked_phone ?? '绑定手机号'}`)
  } catch (error) { showFailToast((error as Error).message) }
  finally { submitting.value = false }
}

async function accept() {
  if (!credential.value || code.value.length !== 6) return
  submitting.value = true
  try {
    await acceptTenantInvitation(credential.value, challengeId.value, code.value)
    credential.value = null
    code.value = ''
    accepted.value = true
  } catch (error) { showFailToast((error as Error).message) }
  finally { submitting.value = false }
}
</script>

<style scoped>
.invite-view { min-height: 100%; background: #f7f8fa; }
.loading { padding-top: 30vh; }
.card { padding: 24px 16px; }
.success-card { padding: 64px 24px; text-align: center; }
h1 { text-align: center; }
p { margin: 20px 0; color: #646566; font-size: 14px; line-height: 1.6; }
</style>

<template>
  <section class="integrations-view">
    <van-nav-bar title="租户集成" left-arrow @click-left="router.back()" />
    <div class="notice">凭证仅用于本次提交，不会回显，也不会保存到浏览器。</div>

    <van-form class="panel" @submit="createIntegration">
      <van-cell-group inset title="创建连接">
        <van-field name="provider" label="服务">
          <template #input>
            <van-radio-group v-model="newProvider" direction="horizontal" @change="resetCreateReplay">
              <van-radio v-for="(item, provider) in PROVIDERS" :key="provider" :name="provider">
                {{ item.label }}
              </van-radio>
            </van-radio-group>
          </template>
        </van-field>
        <van-field
          v-model="newName"
          label="名称"
          maxlength="120"
          placeholder="例如：顺丰主账号"
          @update:model-value="resetCreateReplay"
        />
        <div class="actions">
          <van-button block type="primary" native-type="submit" :loading="submitting">创建</van-button>
        </div>
      </van-cell-group>
    </van-form>

    <van-loading v-if="loading" class="loading" vertical>加载连接</van-loading>
    <van-empty v-else-if="integrations.length === 0" description="暂无连接，请先创建" />
    <template v-else>
      <van-cell-group inset title="选择连接">
        <van-radio-group v-model="selectedId">
          <van-cell
            v-for="item in integrations"
            :key="item.integration_id"
            clickable
            :title="`${PROVIDERS[item.provider].label} · ${item.name}`"
            :label="`${item.status} · ${item.configured ? '已配置' : '未配置'}`"
            @click="selectedId = item.integration_id"
          >
            <template #right-icon><van-radio :name="item.integration_id" /></template>
          </van-cell>
        </van-radio-group>
      </van-cell-group>

      <van-form v-if="selected" class="panel" @submit="submitCredentials">
        <van-cell-group inset title="写入新凭证">
          <van-field
            v-for="field in credentialFields"
            :key="field.key"
            v-model="credentialValues[field.key]"
            :label="field.label"
            type="password"
            maxlength="4096"
            autocomplete="new-password"
            @update:model-value="invalidateCredentialChallenge"
          />
          <van-field
            v-if="challengeId"
            v-model="verificationCode"
            label="本人验证码"
            type="digit"
            maxlength="6"
            autocomplete="one-time-code"
          />
          <van-cell title="最近验证" :value="selected.last_verified_at || '尚未验证'" />
          <div class="actions">
            <van-button block type="primary" native-type="submit" :loading="submitting">
              {{ challengeId ? '确认并保存凭证' : '验证本人' }}
            </van-button>
          </div>
        </van-cell-group>
      </van-form>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { showFailToast, showSuccessToast } from 'vant'
import { useRouter } from 'vue-router'

import {
  confirmTenantIntegrationCredentials,
  createTenantIntegration,
  listTenantIntegrations,
  requestTenantIntegrationCredentialChallenge,
  type TenantIntegrationCredentials,
  type TenantIntegrationProvider,
  type TenantIntegrationSummary,
} from '@/api/tenantIntegrations'

const PROVIDERS: Record<TenantIntegrationProvider, {
  label: string
  fields: Array<{ key: string; label: string }>
}> = {
  sf: { label: '顺丰', fields: [
    { key: 'partner_id', label: '合作伙伴编码' },
    { key: 'checkword', label: '校验码' },
  ] },
  xianyu: { label: '闲鱼', fields: [
    { key: 'app_key', label: 'App Key' },
    { key: 'app_secret', label: 'App Secret' },
  ] },
  kuaimai: { label: '快麦', fields: [
    { key: 'app_id', label: 'App ID' },
    { key: 'app_secret', label: 'App Secret' },
  ] },
}

const router = useRouter()
const integrations = ref<TenantIntegrationSummary[]>([])
const loading = ref(true)
const submitting = ref(false)
const selectedId = ref('')
const newProvider = ref<TenantIntegrationProvider>('sf')
const newName = ref('')
const createId = ref('')
const credentialValues = ref<TenantIntegrationCredentials>({})
const actionId = ref('')
const challengeId = ref('')
const verificationCode = ref('')
const selected = computed(() => integrations.value.find(item => item.integration_id === selectedId.value) ?? null)
const credentialFields = computed(() => selected.value ? PROVIDERS[selected.value.provider].fields : [])

function clearCredentialFlow(clearCredentials = false) {
  actionId.value = ''
  challengeId.value = ''
  verificationCode.value = ''
  if (clearCredentials) credentialValues.value = {}
}

function invalidateCredentialChallenge() {
  actionId.value = ''
  challengeId.value = ''
  verificationCode.value = ''
}

function resetCreateReplay() {
  createId.value = ''
}

function exactCredentials(): TenantIntegrationCredentials | null {
  const result: TenantIntegrationCredentials = {}
  for (const field of credentialFields.value) {
    const value = credentialValues.value[field.key]
    if (typeof value !== 'string' || value.length === 0) return null
    result[field.key] = value
  }
  return result
}

async function load(preferredId?: string) {
  loading.value = true
  try {
    integrations.value = await listTenantIntegrations()
    const nextId = preferredId || selectedId.value
    selectedId.value = integrations.value.some(item => item.integration_id === nextId)
      ? nextId
      : (integrations.value[0]?.integration_id ?? '')
  } catch (error) {
    showFailToast((error as Error).message)
  } finally {
    loading.value = false
  }
}

async function createIntegration() {
  if (!newName.value.trim()) return showFailToast('请输入连接名称')
  if (!createId.value) createId.value = crypto.randomUUID()
  submitting.value = true
  try {
    const created = await createTenantIntegration({
      integration_id: createId.value,
      provider: newProvider.value,
      name: newName.value.trim(),
    })
    const createdId = created.integration_id
    newName.value = ''
    createId.value = ''
    await load(createdId)
    showSuccessToast('连接已创建')
  } catch (error) {
    showFailToast((error as Error).message)
  } finally {
    submitting.value = false
  }
}

async function submitCredentials() {
  const integration = selected.value
  const credentials = exactCredentials()
  if (!integration) return showFailToast('请先选择连接')
  if (!credentials) return showFailToast('请完整填写凭证字段')
  submitting.value = true
  try {
    if (!challengeId.value) {
      if (!actionId.value) actionId.value = crypto.randomUUID()
      challengeId.value = (await requestTenantIntegrationCredentialChallenge(
        integration,
        actionId.value,
        credentials,
      )).challenge_id
      showSuccessToast('验证码已发送到本人手机号')
      return
    }
    if (!/^\d{6}$/.test(verificationCode.value)) {
      return showFailToast('请输入 6 位验证码')
    }
    await confirmTenantIntegrationCredentials(integration, {
      action_id: actionId.value,
      challenge_id: challengeId.value,
      code: verificationCode.value,
      credentials,
    })
    clearCredentialFlow(true)
    await load(integration.integration_id)
    showSuccessToast('凭证已保存，正在后台验证')
  } catch (error) {
    showFailToast((error as Error).message)
  } finally {
    submitting.value = false
  }
}

watch(selectedId, () => clearCredentialFlow(true))
onMounted(() => load())
onBeforeUnmount(() => clearCredentialFlow(true))
</script>

<style scoped>
.integrations-view { min-height: 100%; padding-bottom: 32px; overflow-y: auto; background: #f7f8fa; }
.notice { margin: 16px; padding: 12px; border-radius: 8px; color: #646566; background: #fff; font-size: 13px; }
.panel { margin: 16px 0; }
.actions { padding: 16px; }
.loading { padding-top: 72px; }
</style>

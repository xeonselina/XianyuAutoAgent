<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

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
  sf: {
    label: '顺丰',
    fields: [
      { key: 'partner_id', label: '合作伙伴编码' },
      { key: 'checkword', label: '校验码' },
    ],
  },
  xianyu: {
    label: '闲鱼',
    fields: [
      { key: 'app_key', label: 'App Key' },
      { key: 'app_secret', label: 'App Secret' },
    ],
  },
  kuaimai: {
    label: '快麦',
    fields: [
      { key: 'app_id', label: 'App ID' },
      { key: 'app_secret', label: 'App Secret' },
    ],
  },
}

const integrations = ref<TenantIntegrationSummary[]>([])
const loading = ref(false)
const submitting = ref(false)
const selectedId = ref('')
const newProvider = ref<TenantIntegrationProvider>('sf')
const newName = ref('')
const createId = ref('')
const credentialValues = ref<TenantIntegrationCredentials>({})
const actionId = ref('')
const challengeId = ref('')
const verificationCode = ref('')

const selected = computed(() =>
  integrations.value.find(item => item.integration_id === selectedId.value) ?? null,
)
const credentialFields = computed(() =>
  selected.value ? PROVIDERS[selected.value.provider].fields : [],
)

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

async function refresh(preferredId?: string) {
  loading.value = true
  try {
    integrations.value = await listTenantIntegrations()
    const nextId = preferredId || selectedId.value
    selectedId.value = integrations.value.some(item => item.integration_id === nextId)
      ? nextId
      : (integrations.value[0]?.integration_id ?? '')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '集成列表加载失败')
  } finally {
    loading.value = false
  }
}

async function createIntegration() {
  if (!newName.value.trim()) return ElMessage.warning('请输入连接名称')
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
    await refresh(createdId)
    ElMessage.success('连接已创建，请继续填写凭证')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '连接创建失败')
  } finally {
    submitting.value = false
  }
}

async function submitCredentials() {
  const integration = selected.value
  const credentials = exactCredentials()
  if (!integration) return ElMessage.warning('请先选择连接')
  if (!credentials) return ElMessage.warning('请完整填写凭证字段')
  submitting.value = true
  try {
    if (!challengeId.value) {
      if (!actionId.value) actionId.value = crypto.randomUUID()
      const challenge = await requestTenantIntegrationCredentialChallenge(
        integration,
        actionId.value,
        credentials,
      )
      challengeId.value = challenge.challenge_id
      ElMessage.success('验证码已发送到你当前登录的手机号')
      return
    }
    if (!/^\d{6}$/.test(verificationCode.value)) {
      return ElMessage.warning('请输入 6 位验证码')
    }
    await confirmTenantIntegrationCredentials(integration, {
      action_id: actionId.value,
      challenge_id: challengeId.value,
      code: verificationCode.value,
      credentials,
    })
    clearCredentialFlow(true)
    await refresh(integration.integration_id)
    ElMessage.success('凭证已安全保存，正在后台验证')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '凭证保存失败')
  } finally {
    submitting.value = false
  }
}

watch(selectedId, () => clearCredentialFlow(true))
watch([newProvider, newName], resetCreateReplay)
onMounted(() => refresh())
onBeforeUnmount(() => clearCredentialFlow(true))
</script>

<template>
  <main class="integrations-page" v-loading="loading">
    <header>
      <div>
        <h1>租户集成</h1>
        <p>凭证仅用于本次提交，不会回显，也不会保存到浏览器。</p>
      </div>
      <el-button @click="refresh()">刷新</el-button>
    </header>

    <el-card>
      <template #header>创建连接</template>
      <el-form inline @submit.prevent="createIntegration">
        <el-form-item label="服务">
          <el-select v-model="newProvider" style="width: 140px">
            <el-option
              v-for="(definition, provider) in PROVIDERS"
              :key="provider"
              :label="definition.label"
              :value="provider"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="连接名称">
          <el-input v-model="newName" maxlength="120" placeholder="例如：顺丰主账号" />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="submitting">
          创建
        </el-button>
      </el-form>
    </el-card>

    <el-card>
      <template #header>连接与凭证</template>
      <el-empty v-if="integrations.length === 0" description="暂无连接，请先创建" />
      <template v-else>
        <el-form label-width="130px" @submit.prevent="submitCredentials">
          <el-form-item label="连接">
            <el-select v-model="selectedId" style="width: 100%">
              <el-option
                v-for="item in integrations"
                :key="item.integration_id"
                :label="`${PROVIDERS[item.provider].label} · ${item.name}`"
                :value="item.integration_id"
              />
            </el-select>
          </el-form-item>
          <template v-if="selected">
            <el-descriptions :column="3" border class="summary">
              <el-descriptions-item label="状态">{{ selected.status }}</el-descriptions-item>
              <el-descriptions-item label="已配置">
                {{ selected.configured ? '是' : '否' }}
              </el-descriptions-item>
              <el-descriptions-item label="最近验证">
                {{ selected.last_verified_at || '尚未验证' }}
              </el-descriptions-item>
            </el-descriptions>
            <el-form-item
              v-for="field in credentialFields"
              :key="field.key"
              :label="field.label"
            >
              <el-input
                v-model="credentialValues[field.key]"
                type="password"
                autocomplete="new-password"
                maxlength="4096"
                @input="invalidateCredentialChallenge"
              />
            </el-form-item>
            <el-form-item v-if="challengeId" label="本人验证码">
              <el-input
                v-model="verificationCode"
                maxlength="6"
                inputmode="numeric"
                autocomplete="one-time-code"
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" native-type="submit" :loading="submitting">
                {{ challengeId ? '确认并保存凭证' : '验证本人' }}
              </el-button>
            </el-form-item>
          </template>
        </el-form>
      </template>
    </el-card>
  </main>
</template>

<style scoped>
.integrations-page { max-width: 920px; margin: 0 auto; padding: 28px; display: grid; gap: 20px; }
header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
h1 { margin: 0 0 8px; }
p { margin: 0; color: #667085; }
.summary { margin-bottom: 20px; }
</style>

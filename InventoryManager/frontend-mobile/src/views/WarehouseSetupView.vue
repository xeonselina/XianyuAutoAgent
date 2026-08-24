<template>
  <section class="setup-view">
    <van-nav-bar title="完成默认仓库设置" />
    <van-loading v-if="loading" class="setup-loading" vertical>
      加载仓库资料
    </van-loading>
    <template v-else>
      <div class="setup-intro">
        <h1>确认寄回资料</h1>
        <p>注册手机号只是预填值。全部资料确认后，才能进入库存、租赁、发货、打印和验货页面。</p>
      </div>
      <van-form @submit="submit">
        <van-cell-group inset>
          <van-field v-model="form.name" name="name" label="仓库名称" :rules="requiredRule" />
          <van-field v-model="form.contact_name" name="contact_name" label="联系人" :rules="requiredRule" />
          <van-field v-model="form.contact_phone" name="contact_phone" label="联系电话" type="tel" :rules="requiredRule" />
          <van-field v-model="form.province" name="province" label="省" :rules="requiredRule" />
          <van-field v-model="form.city" name="city" label="市" :rules="requiredRule" />
          <van-field v-model="form.district" name="district" label="区/县" :rules="requiredRule" />
          <van-field
            v-model="form.address_detail"
            name="address_detail"
            label="详细地址"
            type="textarea"
            rows="3"
            autosize
            :rules="requiredRule"
          />
        </van-cell-group>
        <div class="setup-actions">
          <van-button block round type="primary" native-type="submit" :loading="submitting">
            确认并进入系统
          </van-button>
        </div>
      </van-form>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { showFailToast, showSuccessToast } from 'vant'
import { useRouter } from 'vue-router'

import {
  getDefaultWarehouseSetup,
  setupDefaultWarehouse,
} from '@/api/warehouseSetup'

const router = useRouter()
const loading = ref(true)
const submitting = ref(false)
const requiredRule = [{ required: true, message: '请填写此项' }]
const form = reactive({
  name: '默认仓库',
  contact_name: '',
  contact_phone: '',
  province: '',
  city: '',
  district: '',
  address_detail: '',
})

const loadSetup = async () => {
  loading.value = true
  try {
    const warehouse = await getDefaultWarehouseSetup()
    if (warehouse.setup_state === 'ready') {
      await router.replace({ name: 'gantt' })
      return
    }
    form.name = warehouse.name || '默认仓库'
    form.contact_name = warehouse.contact_name || ''
    form.contact_phone = warehouse.contact_phone || ''
    form.province = warehouse.province || ''
    form.city = warehouse.city || ''
    form.district = warehouse.district || ''
    form.address_detail = warehouse.address_detail || ''
  } catch (error) {
    showFailToast((error as Error).message)
  } finally {
    loading.value = false
  }
}

const submit = async () => {
  if (submitting.value) return
  submitting.value = true
  try {
    await setupDefaultWarehouse({ ...form })
    showSuccessToast('默认仓库设置完成')
    await router.replace({ name: 'gantt' })
  } catch (error) {
    showFailToast((error as Error).message)
  } finally {
    submitting.value = false
  }
}

onMounted(loadSetup)
</script>

<style scoped>
.setup-view {
  min-height: 100%;
  overflow-y: auto;
  background: #f7f8fa;
}

.setup-loading {
  padding-top: 30vh;
}

.setup-intro {
  padding: 24px 20px 16px;
}

.setup-intro h1 {
  margin: 0 0 8px;
  font-size: 22px;
}

.setup-intro p {
  margin: 0;
  color: #646566;
  font-size: 14px;
  line-height: 1.6;
}

.setup-actions {
  padding: 24px 16px calc(24px + env(safe-area-inset-bottom));
}
</style>


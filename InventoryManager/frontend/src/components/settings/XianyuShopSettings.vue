<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createXianyuShop, listXianyuShops, syncXianyuShop, updateXianyuShop,
  type XianyuShopSettings } from '@/api/settings'

const shops = ref<XianyuShopSettings[]>([])
const busy = ref(false)
const open = ref(false)
const editingId = ref<number>()
const form = reactive({ name: '', app_key: '', app_secret: '', is_active: false })
const load = async () => { shops.value = await listXianyuShops() }
const edit = (shop?: XianyuShopSettings) => {
  editingId.value = shop?.id
  Object.assign(form, { name: shop?.name || '', app_key: shop?.app_key || '',
    app_secret: '', is_active: shop?.is_active || false })
  open.value = true
}
const save = async () => {
  busy.value = true
  try {
    editingId.value
      ? await updateXianyuShop(editingId.value, { ...form })
      : await createXianyuShop({ ...form })
    open.value = false
    await load()
    ElMessage.success('闲鱼店铺已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally { busy.value = false }
}
const toggle = async (shop: XianyuShopSettings) => {
  await updateXianyuShop(shop.id, { is_active: !shop.is_active })
  await load()
}
const sync = async (shop: XianyuShopSettings) => {
  busy.value = true
  try { await syncXianyuShop(shop.id); await load(); ElMessage.success('同步完成') }
  catch (error) { ElMessage.error(error instanceof Error ? error.message : '同步失败') }
  finally { busy.value = false }
}
onMounted(() => load().catch(() => ElMessage.error('店铺加载失败')))
</script>

<template>
  <section>
    <div class="section-actions"><p>每个店铺独立同步订单。</p>
      <el-button type="primary" @click="edit()">新增店铺</el-button></div>
    <el-table :data="shops" v-loading="busy">
      <el-table-column prop="name" label="店铺" /><el-table-column prop="app_key" label="App Key" />
      <el-table-column label="配置"><template #default="{ row }">
        {{ row.app_secret_configured ? '已配置' : '未配置' }}</template></el-table-column>
      <el-table-column prop="last_success_at" label="最近成功" />
      <el-table-column prop="last_error" label="最近错误" />
      <el-table-column label="操作" width="240"><template #default="{ row }">
        <el-button link @click="edit(row)">编辑</el-button>
        <el-button link @click="toggle(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
        <el-button link :disabled="!row.is_active" @click="sync(row)">立即同步</el-button>
      </template></el-table-column>
    </el-table>
    <el-dialog v-model="open" :title="editingId ? '编辑店铺' : '新增店铺'" width="480px">
      <el-form label-width="100px">
        <el-form-item label="店铺名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="App Key"><el-input v-model="form.app_key" /></el-form-item>
        <el-form-item label="App Secret"><el-input v-model="form.app_secret" type="password"
          show-password placeholder="留空保持原值" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.is_active" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="open = false">取消</el-button>
        <el-button type="primary" :loading="busy" @click="save">保存</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>.section-actions{display:flex;align-items:center;justify-content:space-between}</style>

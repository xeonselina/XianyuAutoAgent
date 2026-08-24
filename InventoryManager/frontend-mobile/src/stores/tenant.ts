import axios from 'axios'
import { ref } from 'vue'
import { defineStore } from 'pinia'


export type MobileWarehouse = {
  id: number
  province: string
  city: string
  name: string
  sf_configured?: boolean
  kuaimai_configured?: boolean
}

export const useMobileTenantStore = defineStore('mobile-tenant', () => {
  const warehouses = ref<MobileWarehouse[]>([])
  const currentWarehouseId = ref<number | 'all'>('all')
  const loaded = ref(false)

  const setWarehousesForSession = (rows: MobileWarehouse[]) => {
    const previous = currentWarehouseId.value
    const wasLoaded = loaded.value
    warehouses.value = rows.slice()
    if (rows.length === 0) {
      currentWarehouseId.value = 'all'
    } else if (wasLoaded && previous === 'all' && rows.length > 1) {
      currentWarehouseId.value = 'all'
    } else if (
      typeof previous === 'number'
      && rows.some((warehouse) => warehouse.id === previous)
    ) {
      currentWarehouseId.value = previous
    } else {
      currentWarehouseId.value = rows[0].id
    }
    loaded.value = true
  }

  const loadWarehouses = async (force = false) => {
    if (loaded.value && !force) return warehouses.value
    const response = await axios.get('/api/warehouses')
    if (!response.data.success || !Array.isArray(response.data.data)) {
      throw new Error(response.data.message || '仓库加载失败')
    }
    setWarehousesForSession(response.data.data)
    return warehouses.value
  }

  const selectWarehouse = (warehouseId: number | 'all') => {
    if (warehouseId === 'all') {
      if (warehouses.value.length > 1) currentWarehouseId.value = 'all'
      return
    }
    if (!warehouses.value.some((warehouse) => warehouse.id === warehouseId)) {
      throw new Error('仓库不存在')
    }
    currentWarehouseId.value = warehouseId
  }

  const requireConcreteWarehouse = () => {
    if (currentWarehouseId.value === 'all') {
      throw new Error('请选择具体仓库')
    }
    return currentWarehouseId.value
  }

  return {
    currentWarehouseId,
    loadWarehouses,
    requireConcreteWarehouse,
    selectWarehouse,
    setWarehousesForSession,
    warehouses,
  }
})

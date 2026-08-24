import axios from 'axios'
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'


export type Warehouse = {
  id: number
  province: string
  city: string
  name: string
  sf_configured?: boolean
  kuaimai_configured?: boolean
  created_at?: string
  updated_at?: string
}

type WarehouseEnvelope = {
  success: boolean
  data?: Warehouse[]
  message?: string
}

export const useTenantStore = defineStore('tenant', () => {
  const warehouses = ref<Warehouse[]>([])
  const currentWarehouseId = ref<number | 'all'>('all')
  const loading = ref(false)
  const loaded = ref(false)
  const ready = ref(false)
  let sessionGeneration = 0
  let initializePromise: Promise<Warehouse[]> | null = null

  const currentWarehouse = computed(() => (
    typeof currentWarehouseId.value === 'number'
      ? warehouses.value.find((item) => item.id === currentWarehouseId.value) || null
      : null
  ))

  const setWarehousesForSession = (rows: Warehouse[]) => {
    const previous = currentWarehouseId.value
    const wasLoaded = loaded.value
    warehouses.value = rows.slice()
    if (rows.length === 0) {
      currentWarehouseId.value = 'all'
    } else if (wasLoaded && previous === 'all' && rows.length > 1) {
      currentWarehouseId.value = 'all'
    } else if (
      typeof previous === 'number'
      && rows.some((item) => item.id === previous)
    ) {
      currentWarehouseId.value = previous
    } else {
      currentWarehouseId.value = rows[0].id
    }
    loaded.value = true
    ready.value = true
  }

  const initialize = (force = false): Promise<Warehouse[]> => {
    if (ready.value && !force) return Promise.resolve(warehouses.value)
    if (initializePromise) return initializePromise
    const requestGeneration = sessionGeneration
    loading.value = true
    initializePromise = axios.get<WarehouseEnvelope>('/api/warehouses').then((response) => {
      if (!response.data.success || !Array.isArray(response.data.data)) {
        throw new Error(response.data.message || '仓库加载失败')
      }
      if (requestGeneration !== sessionGeneration) return warehouses.value
      setWarehousesForSession(response.data.data)
      return warehouses.value
    }).finally(() => {
      if (requestGeneration === sessionGeneration) {
        loading.value = false
        initializePromise = null
      }
    })
    return initializePromise
  }

  const loadWarehouses = (force = false) => initialize(force)

  const selectWarehouse = (warehouseId: number | 'all') => {
    if (warehouseId === 'all') {
      if (warehouses.value.length > 1) currentWarehouseId.value = 'all'
      return
    }
    if (!warehouses.value.some((item) => item.id === warehouseId)) {
      throw new Error('仓库不存在')
    }
    currentWarehouseId.value = warehouseId
  }

  const requireConcreteWarehouse = () => {
    if (currentWarehouseId.value === 'all') throw new Error('请选择具体仓库')
    return currentWarehouseId.value
  }

  const reset = () => {
    sessionGeneration += 1
    initializePromise = null
    warehouses.value = []
    currentWarehouseId.value = 'all'
    loaded.value = false
    ready.value = false
    loading.value = false
  }

  return {
    currentWarehouse,
    currentWarehouseId,
    initialize,
    loadWarehouses,
    loaded,
    loading,
    ready,
    reset,
    requireConcreteWarehouse,
    selectWarehouse,
    setWarehousesForSession,
    warehouses,
  }
})

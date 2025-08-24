// Pinia 状态管理 (Vue 3 推荐)
import { defineStore } from 'pinia'
import axios from 'axios'

export const useGanttStore = defineStore('gantt', {
  state: () => ({
    devices: [],
    rentals: [],
    currentDate: new Date(),
    loading: false,
    error: null
  }),

  getters: {
    // 自动计算的派生状态
    dateRange: (state) => {
      const start = new Date(state.currentDate)
      start.setDate(start.getDate() - 15)
      const end = new Date(state.currentDate)
      end.setDate(end.getDate() + 15)
      return { start, end }
    },

    currentPeriod: (state) => {
      const { start, end } = state.dateRange
      return `${formatDate(start)} - ${formatDate(end)}`
    },

    getRentalsForDevice: (state) => (deviceId) => {
      return state.rentals.filter(rental => rental.device_id === deviceId)
    },

    availableDevices: (state) => {
      return state.devices.filter(device => device.status === 'available')
    }
  },

  actions: {
    // 异步操作
    async loadData() {
      this.loading = true
      this.error = null
      
      try {
        const response = await axios.get('/api/gantt/data', {
          params: {
            start_date: formatDate(this.dateRange.start),
            end_date: formatDate(this.dateRange.end)
          }
        })
        
        if (response.data.success) {
          this.devices = response.data.data.devices
          this.rentals = response.data.data.rentals
        } else {
          throw new Error(response.data.error || '加载数据失败')
        }
      } catch (error) {
        this.error = error.message
        console.error('加载数据失败:', error)
      } finally {
        this.loading = false
      }
    },

    navigateWeek(weeks) {
      const newDate = new Date(this.currentDate)
      newDate.setDate(newDate.getDate() + (weeks * 7))
      this.currentDate = newDate
      this.loadData()
    },

    goToToday() {
      this.currentDate = new Date()
      this.loadData()
    },

    async createRental(rentalData) {
      try {
        const response = await axios.post('/api/rentals', rentalData)
        if (response.data.success) {
          // 重新加载数据以获取最新状态
          await this.loadData()
          return response.data
        } else {
          throw new Error(response.data.error || '创建租赁失败')
        }
      } catch (error) {
        console.error('创建租赁失败:', error)
        throw error
      }
    },

    async updateRental(rentalId, updateData) {
      try {
        const response = await axios.put(`/api/rentals/${rentalId}`, updateData)
        if (response.data.success) {
          await this.loadData()
          return response.data
        } else {
          throw new Error(response.data.error || '更新租赁失败')
        }
      } catch (error) {
        console.error('更新租赁失败:', error)
        throw error
      }
    },

    async deleteRental(rentalId) {
      try {
        const response = await axios.delete(`/api/rentals/${rentalId}`)
        if (response.data.success) {
          await this.loadData()
          return response.data
        } else {
          throw new Error(response.data.error || '删除租赁失败')
        }
      } catch (error) {
        console.error('删除租赁失败:', error)
        throw error
      }
    }
  }
})

// 工具函数
function formatDate(date) {
  return date.toISOString().split('T')[0]
}

// 使用示例：
// const ganttStore = useGanttStore()
// ganttStore.loadData() // 加载数据
// ganttStore.navigateWeek(1) // 导航到下周
// console.log(ganttStore.currentPeriod) // 获取当前周期文本

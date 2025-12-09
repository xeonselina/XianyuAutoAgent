<template>
  <div class="sf-tracking-container">
    <div class="header">
      <h2><i class="bi bi-truck"></i> 顺丰物流追踪</h2>
      <div class="date-filter">
        <button @click="setDateRange('recent4')" :class="{ active: dateRangeType === 'recent4' }">
          最近8天
        </button>
        <button @click="setDateRange('recent7')" :class="{ active: dateRangeType === 'recent7' }">
          最近7天
        </button>
        <button @click="setDateRange('recent30')" :class="{ active: dateRangeType === 'recent30' }">
          最近30天
        </button>
        <button @click="setDateRange('all')" :class="{ active: dateRangeType === 'all' }">
          全部
        </button>
        <button @click="batchRefresh" class="refresh-btn" :disabled="loading || rentals.length === 0">
          <i class="bi bi-arrow-repeat"></i> 批量刷新
        </button>
      </div>
    </div>

    <div v-if="loading" class="loading">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">加载中...</span>
      </div>
      <p>加载中...</p>
    </div>

    <div v-else-if="rentals.length === 0" class="empty-state">
      <i class="bi bi-inbox"></i>
      <p>暂无发货订单</p>
    </div>

    <div v-else class="table-container">
      <table class="table table-hover">
        <thead>
          <tr>
            <th>租赁ID</th>
            <th>客户姓名</th>
            <th>客户电话</th>
            <th>目的地</th>
            <th>设备</th>
            <th>运单号</th>
            <th>发货时间</th>
            <th>物流状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="rental in paginatedRentals" :key="rental.rental_id">
            <td>{{ rental.rental_id }}</td>
            <td>{{ rental.customer_name }}</td>
            <td>{{ rental.customer_phone }}</td>
            <td>{{ rental.destination }}</td>
            <td>{{ rental.device_name || '-' }}</td>
            <td>
              <code>{{ rental.ship_out_tracking_no }}</code>
            </td>
            <td>{{ formatDate(rental.ship_out_time) }}</td>
            <td>
              <span
                class="status-badge"
                :class="getStatusClass(trackingStatus[rental.ship_out_tracking_no])"
              >
                {{ getStatusText(trackingStatus[rental.ship_out_tracking_no]) }}
              </span>
            </td>
            <td>
              <button
                class="btn btn-sm btn-primary"
                @click="viewTracking(rental.ship_out_tracking_no)"
                :disabled="loadingTracking[rental.ship_out_tracking_no]"
              >
                <span v-if="loadingTracking[rental.ship_out_tracking_no]" class="spinner-border spinner-border-sm"></span>
                <span v-else>查看轨迹</span>
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <div class="pagination" v-if="totalPages > 1">
        <button @click="currentPage--" :disabled="currentPage === 1">上一页</button>
        <span>第 {{ currentPage }} / {{ totalPages }} 页</span>
        <button @click="currentPage++" :disabled="currentPage === totalPages">下一页</button>
      </div>
    </div>

    <!-- 物流轨迹模态框 -->
    <div v-if="showTrackingModal" class="modal-overlay" @click="closeModal">
      <div class="modal-content" @click.stop>
        <div class="modal-header">
          <h3>物流轨迹详情</h3>
          <button class="close-btn" @click="closeModal">&times;</button>
        </div>
        <div class="modal-body">
          <div v-if="currentTracking">
            <div class="tracking-info">
              <p><strong>运单号:</strong> <code>{{ currentTrackingNumber }}</code></p>
              <p><strong>当前状态:</strong>
                <span
                  class="status-badge"
                  :class="getStatusClass(currentTracking.status)"
                >
                  {{ getStatusText(currentTracking.status) }}
                </span>
              </p>
              <p v-if="currentTracking.last_update">
                <strong>最后更新:</strong> {{ currentTracking.last_update }}
              </p>
              <p v-if="currentTracking.delivered_time">
                <strong>签收时间:</strong> {{ currentTracking.delivered_time }}
              </p>
            </div>

            <div v-if="currentTracking.routes && currentTracking.routes.length > 0" class="timeline">
              <div
                v-for="(route, index) in currentTracking.routes"
                :key="index"
                class="timeline-item"
              >
                <div class="timeline-marker"></div>
                <div class="timeline-content">
                  <div class="timeline-time">{{ route.accept_time }}</div>
                  <div class="timeline-location">{{ route.accept_address }}</div>
                  <div class="timeline-remark">{{ route.remark }}</div>
                </div>
              </div>
            </div>

            <div v-else class="empty-routes">
              <p>暂无物流轨迹信息</p>
            </div>
          </div>
          <div v-else class="loading-modal">
            <div class="spinner-border text-primary"></div>
            <p>查询中...</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import axios from 'axios'

interface Rental {
  rental_id: number
  customer_name: string
  customer_phone: string
  destination: string
  device_name: string | null
  ship_out_tracking_no: string
  ship_out_time: string
  status: string
}

interface TrackingRoute {
  accept_time: string
  accept_address: string
  remark: string
  op_code?: string
}

interface TrackingInfo {
  tracking_number: string
  status: string
  routes: TrackingRoute[]
  last_update: string | null
  delivered_time: string | null
}

export default {
  name: 'SFTrackingView',
  data(): {
    rentals: Rental[]
    loading: boolean
    trackingStatus: Record<string, string>
    loadingTracking: Record<string, boolean>
    showTrackingModal: boolean
    currentTracking: TrackingInfo | null
    currentTrackingNumber: string
    dateRangeType: string
    currentPage: number
    pageSize: number
  } {
    return {
      rentals: [],
      loading: false,
      trackingStatus: {},
      loadingTracking: {},
      showTrackingModal: false,
      currentTracking: null,
      currentTrackingNumber: '',
      dateRangeType: 'recent4',
      currentPage: 1,
      pageSize: 20
    }
  },
  computed: {
    paginatedRentals() {
      const start = (this.currentPage - 1) * this.pageSize
      const end = start + this.pageSize
      return this.rentals.slice(start, end)
    },
    totalPages() {
      return Math.ceil(this.rentals.length / this.pageSize)
    }
  },
  mounted() {
    this.loadRentals()
  },
  methods: {
    async loadRentals() {
      this.loading = true
      try {
        const params: Record<string, string> = {}

        // 根据日期范围类型设置参数
        if (this.dateRangeType === 'recent4') {
          // 默认: 过去4天 + 未来4天 (API默认行为)
          // 不需要传参数
        } else if (this.dateRangeType === 'recent7') {
          const endDate = new Date()
          const startDate = new Date()
          startDate.setDate(startDate.getDate() - 7)
          params.start_date = startDate.toISOString()
          params.end_date = endDate.toISOString()
        } else if (this.dateRangeType === 'recent30') {
          const endDate = new Date()
          const startDate = new Date()
          startDate.setDate(startDate.getDate() - 30)
          params.start_date = startDate.toISOString()
          params.end_date = endDate.toISOString()
        } else if (this.dateRangeType === 'all') {
          // 全部: 使用很大的日期范围
          const endDate = new Date()
          endDate.setFullYear(endDate.getFullYear() + 1)
          const startDate = new Date()
          startDate.setFullYear(startDate.getFullYear() - 2)
          params.start_date = startDate.toISOString()
          params.end_date = endDate.toISOString()
        }

        const response = await axios.get('/api/sf-tracking/list', { params })
        this.rentals = response.data.data || []
        this.currentPage = 1
      } catch (error: any) {
        console.error('加载租赁列表失败:', error)
        alert('加载列表失败: ' + (error.response?.data?.message || error.message))
      } finally {
        this.loading = false
      }
    },
    async viewTracking(trackingNumber: string) {
      this.currentTrackingNumber = trackingNumber
      this.showTrackingModal = true
      this.currentTracking = null
      this.loadingTracking[trackingNumber] = true

      try {
        const response = await axios.post('/api/sf-tracking/query', {
          tracking_number: trackingNumber
        })

        if (response.data.success) {
          this.currentTracking = response.data.data
          // 更新状态缓存
          this.trackingStatus[trackingNumber] = response.data.data.status
        } else {
          alert('查询失败: ' + response.data.message)
          this.closeModal()
        }
      } catch (error: any) {
        console.error('查询物流失败:', error)
        alert('查询失败: ' + (error.response?.data?.message || error.message))
        this.closeModal()
      } finally {
        this.loadingTracking[trackingNumber] = false
      }
    },
    async batchRefresh() {
      if (this.rentals.length === 0) return

      const trackingNumbers = this.rentals.map(r => r.ship_out_tracking_no)
      this.loading = true

      try {
        const response = await axios.post('/api/sf-tracking/batch-query', {
          tracking_numbers: trackingNumbers
        })

        if (response.data.success) {
          // 更新所有运单的状态
          const data = response.data.data
          for (const trackingNumber in data) {
            this.trackingStatus[trackingNumber] = data[trackingNumber].status
          }

          // 显示统计信息
          const successCount = response.data.success_count
          const total = response.data.total
          alert(`批量刷新完成: 成功 ${successCount}/${total}`)
        } else {
          alert('批量刷新失败: ' + response.data.message)
        }
      } catch (error: any) {
        console.error('批量刷新失败:', error)
        alert('批量刷新失败: ' + (error.response?.data?.message || error.message))
      } finally {
        this.loading = false
      }
    },
    setDateRange(type: string) {
      this.dateRangeType = type
      this.loadRentals()
    },
    closeModal() {
      this.showTrackingModal = false
      this.currentTracking = null
      this.currentTrackingNumber = ''
    },
    formatDate(dateStr: string | null) {
      if (!dateStr) return '-'
      const date = new Date(dateStr)
      return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
      })
    },
    getStatusText(status: string | undefined) {
      const statusMap = {
        'picked_up': '已揽收',
        'in_transit': '运输中',
        'delivering': '派送中',
        'delivered': '已签收',
        'processing': '处理中',
        'not_found': '未找到',
        'unknown': '未知'
      }
      return statusMap[status as keyof typeof statusMap] || '未查询'
    },
    getStatusClass(status: string | undefined) {
      const classMap = {
        'picked_up': 'status-picked',
        'in_transit': 'status-transit',
        'delivering': 'status-delivering',
        'delivered': 'status-delivered',
        'processing': 'status-processing',
        'not_found': 'status-notfound',
        'unknown': 'status-unknown'
      }
      return classMap[status as keyof typeof classMap] || 'status-default'
    }
  }
}
</script>

<style scoped>
.sf-tracking-container {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.header h2 {
  margin: 0;
}

.date-filter {
  display: flex;
  gap: 10px;
}

.date-filter button {
  padding: 8px 16px;
  border: 1px solid #ddd;
  background: white;
  border-radius: 4px;
  cursor: pointer;
}

.date-filter button.active {
  background: #0d6efd;
  color: white;
  border-color: #0d6efd;
}

.date-filter button:hover:not(:disabled) {
  background: #f8f9fa;
}

.date-filter button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.refresh-btn {
  background: #28a745 !important;
  color: white !important;
  border-color: #28a745 !important;
}

.refresh-btn:hover:not(:disabled) {
  background: #218838 !important;
}

.loading {
  text-align: center;
  padding: 60px 20px;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #6c757d;
}

.empty-state i {
  font-size: 4rem;
  margin-bottom: 20px;
}

.table-container {
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
  overflow: hidden;
}

.table {
  margin: 0;
}

.table th {
  background: #f8f9fa;
  font-weight: 600;
}

code {
  background: #f8f9fa;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.9em;
}

.status-badge {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 0.85em;
  font-weight: 500;
}

.status-picked { background: #d1ecf1; color: #0c5460; }
.status-transit { background: #fff3cd; color: #856404; }
.status-delivering { background: #cfe2ff; color: #084298; }
.status-delivered { background: #d1e7dd; color: #0f5132; }
.status-processing { background: #e2e3e5; color: #383d41; }
.status-notfound { background: #f8d7da; color: #842029; }
.status-unknown { background: #e2e3e5; color: #383d41; }
.status-default { background: #e2e3e5; color: #383d41; }

.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 20px;
  padding: 20px;
  border-top: 1px solid #dee2e6;
}

.pagination button {
  padding: 6px 12px;
  border: 1px solid #dee2e6;
  background: white;
  border-radius: 4px;
  cursor: pointer;
}

.pagination button:hover:not(:disabled) {
  background: #f8f9fa;
}

.pagination button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Modal styles */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0,0,0,0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: white;
  border-radius: 8px;
  max-width: 800px;
  width: 90%;
  max-height: 80vh;
  overflow-y: auto;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px;
  border-bottom: 1px solid #dee2e6;
}

.modal-header h3 {
  margin: 0;
}

.close-btn {
  background: none;
  border: none;
  font-size: 2rem;
  cursor: pointer;
  color: #6c757d;
  line-height: 1;
}

.close-btn:hover {
  color: #000;
}

.modal-body {
  padding: 20px;
}

.tracking-info {
  margin-bottom: 30px;
  padding: 15px;
  background: #f8f9fa;
  border-radius: 6px;
}

.tracking-info p {
  margin: 8px 0;
}

.timeline {
  position: relative;
  padding-left: 30px;
}

.timeline::before {
  content: '';
  position: absolute;
  left: 8px;
  top: 0;
  bottom: 0;
  width: 2px;
  background: #dee2e6;
}

.timeline-item {
  position: relative;
  margin-bottom: 25px;
}

.timeline-marker {
  position: absolute;
  left: -26px;
  top: 5px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #0d6efd;
  border: 2px solid white;
  box-shadow: 0 0 0 2px #0d6efd;
}

.timeline-item:first-child .timeline-marker {
  background: #28a745;
  box-shadow: 0 0 0 2px #28a745;
}

.timeline-content {
  padding: 10px 15px;
  background: #f8f9fa;
  border-radius: 6px;
}

.timeline-time {
  font-weight: 600;
  color: #0d6efd;
  margin-bottom: 5px;
}

.timeline-location {
  font-size: 0.95em;
  margin-bottom: 5px;
}

.timeline-remark {
  font-size: 0.9em;
  color: #6c757d;
}

.empty-routes {
  text-align: center;
  padding: 40px;
  color: #6c757d;
}

.loading-modal {
  text-align: center;
  padding: 40px;
}
</style>

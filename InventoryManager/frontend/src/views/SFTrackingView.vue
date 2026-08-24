<template>
  <div class="sf-tracking-container">
    <div class="header">
      <h2><i class="bi bi-truck"></i> 顺丰物流追踪</h2>
      <div class="date-filter">
        <button @click="batchRefresh" class="refresh-btn" :disabled="loading || shipments.length === 0">
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

    <div v-else-if="shipments.length === 0" class="empty-state">
      <i class="bi bi-inbox"></i>
      <p>暂无发货订单</p>
    </div>

    <div v-else class="table-container">
      <table class="table table-hover">
        <thead>
          <tr>
            <th>租赁ID</th>
            <th>发货仓</th>
            <th>运单号</th>
            <th>发货时间</th>
            <th>运单状态</th>
            <th>物流状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="shipment in shipments" :key="shipment.shipment_id">
            <td>{{ shipment.rental_id }}</td>
            <td><code>{{ shipment.origin_warehouse_uuid }}</code></td>
            <td>
              <code>{{ shipment.waybill_no }}</code>
            </td>
            <td>{{ formatDate(shipment.submitted_at) }}</td>
            <td>{{ shipment.shipment_status }}</td>
            <td>
              <span
                class="status-badge"
                :class="getStatusClass(trackingStatus[shipment.shipment_id])"
              >
                {{ getStatusText(trackingStatus[shipment.shipment_id]) }}
              </span>
            </td>
            <td>
              <button
                class="btn btn-sm btn-primary"
                @click="viewTracking(shipment)"
                :disabled="loadingTracking[shipment.shipment_id]"
              >
                <span v-if="loadingTracking[shipment.shipment_id]" class="spinner-border spinner-border-sm"></span>
                <span v-else>查看轨迹</span>
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <div class="pagination" v-if="pageNumber > 1 || nextCursor">
        <button @click="previousPage" :disabled="pageNumber === 1 || loading">上一页</button>
        <span>第 {{ pageNumber }} 页</span>
        <button @click="nextPage" :disabled="!nextCursor || loading">下一页</button>
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
                  :class="getStatusClass(currentTracking.status_code)"
                >
                  {{ getStatusText(currentTracking) }}
                </span>
              </p>
              <p v-if="currentTracking.last_update">
                <strong>最后更新:</strong> {{ currentTracking.last_update }}
              </p>
            </div>

            <div v-if="currentTracking.events.length > 0" class="timeline">
              <div
                v-for="(event, index) in currentTracking.events"
                :key="index"
                class="timeline-item"
              >
                <div class="timeline-marker"></div>
                <div class="timeline-content">
                  <div class="timeline-time">{{ formatDate(event.occurred_at) }}</div>
                  <div class="timeline-location">{{ getStatusText(event.status_code) }}</div>
                  <div class="timeline-remark">{{ event.summary }}</div>
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

interface ShipmentSummary {
  shipment_id: string
  rental_id: number
  waybill_no: string
  shipment_status: string
  origin_warehouse_uuid: string
  submitted_at: string
}

interface TrackingEvent {
  occurred_at: string
  status_code: string
  summary: string
}

interface TrackingInfo {
  shipment_id: string
  waybill_no: string
  found: boolean
  status_code: string
  events: TrackingEvent[]
  last_update: string | null
}

export default {
  name: 'SFTrackingView',
  data(): {
    shipments: ShipmentSummary[]
    loading: boolean
    trackingStatus: Record<string, TrackingInfo>
    loadingTracking: Record<string, boolean>
    showTrackingModal: boolean
    currentTracking: TrackingInfo | null
    currentTrackingNumber: string
    pageSize: number
    nextCursor: string | null
    cursorHistory: Array<string | null>
  } {
    return {
      shipments: [],
      loading: false,
      trackingStatus: {},
      loadingTracking: {},
      showTrackingModal: false,
      currentTracking: null,
      currentTrackingNumber: '',
      pageSize: 20,
      nextCursor: null,
      cursorHistory: [null]
    }
  },
  computed: {
    pageNumber() {
      return this.cursorHistory.length
    }
  },
  mounted() {
    this.loadRentals()
  },
  methods: {
    async loadRentals(cursor: string | null = null) {
      this.loading = true
      try {
        const params: Record<string, string | number> = { page_size: this.pageSize }
        if (cursor) params.after_cursor = cursor
        const response = await axios.get('/api/sf-tracking/list', { params })
        this.shipments = response.data.data?.items || []
        this.nextCursor = response.data.data?.next_cursor || null
      } catch (error: any) {
        console.error('加载租赁列表失败:', error)
        alert('加载列表失败: ' + (error.response?.data?.message || error.message))
      } finally {
        this.loading = false
      }
    },
    async viewTracking(shipment: ShipmentSummary) {
      this.currentTrackingNumber = shipment.waybill_no
      this.showTrackingModal = true
      this.currentTracking = null
      this.loadingTracking[shipment.shipment_id] = true

      try {
        const response = await axios.post('/api/sf-tracking/query', {
          shipment_id: shipment.shipment_id
        })

        if (response.data.success) {
          this.currentTracking = response.data.data
          // 更新状态缓存 - 保存完整对象
          this.trackingStatus[shipment.shipment_id] = response.data.data
        } else {
          alert('查询失败: ' + response.data.message)
          this.closeModal()
        }
      } catch (error: any) {
        console.error('查询物流失败:', error)
        alert('查询失败: ' + (error.response?.data?.message || error.message))
        this.closeModal()
      } finally {
        this.loadingTracking[shipment.shipment_id] = false
      }
    },
    async batchRefresh() {
      if (this.shipments.length === 0) return

      const shipmentIds = this.shipments.map(item => item.shipment_id)
      this.loading = true

      try {
        const response = await axios.post('/api/sf-tracking/batch-query', {
          shipment_ids: shipmentIds
        })

        if (response.data.success) {
          const items: TrackingInfo[] = response.data.data?.items || []
          for (const item of items) {
            this.trackingStatus[item.shipment_id] = item
          }
          const foundCount = items.filter(item => item.found).length
          alert(`批量刷新完成: 找到 ${foundCount}/${items.length}`)
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
    async nextPage() {
      if (!this.nextCursor) return
      const cursor = this.nextCursor
      this.cursorHistory.push(cursor)
      await this.loadRentals(cursor)
    },
    async previousPage() {
      if (this.cursorHistory.length <= 1) return
      this.cursorHistory.pop()
      await this.loadRentals(
        this.cursorHistory[this.cursorHistory.length - 1] ?? null
      )
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
    getStatusText(status: string | TrackingInfo | undefined) {
      if (typeof status === 'object' && status !== null) {
        status = (status as TrackingInfo).status_code
      }

      const statusMap = {
        'picked_up': '已揽收',
        'in_transit': '运送中',
        'delivering': '派送中',
        'delivered': '已签收',
        'returned': '退回中',
        'exception': '物流异常',
        'processing': '处理中',
        'not_found': '未找到',
        'unknown': '未知'
      }
      return statusMap[status as keyof typeof statusMap] || '未查询'
    },
    getStatusClass(status: string | TrackingInfo | undefined) {
      let statusStr = status
      if (typeof status === 'object' && status !== null) {
        statusStr = (status as TrackingInfo).status_code
      }

      const classMap = {
        'picked_up': 'status-picked',
        'in_transit': 'status-transit',
        'delivering': 'status-delivering',
        'delivered': 'status-delivered',
        'returned': 'status-returned',
        'exception': 'status-exception',
        'processing': 'status-processing',
        'not_found': 'status-notfound',
        'unknown': 'status-unknown'
      }
      return classMap[statusStr as keyof typeof classMap] || 'status-default'
    }
  }
}
</script>

<style scoped>
.sf-tracking-container {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
  color: #000;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.header h2 {
  margin: 0;
  color: #000;
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
  color: #000;
}

.table td {
  color: #000;
}

code {
  background: #f8f9fa;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.9em;
  color: #000;
}

.status-badge {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 0.85em;
  font-weight: 500;
}

.status-picked { background: #d1ecf1; color: #000; }
.status-transit { background: #fff3cd; color: #000; }
.status-delivering { background: #cfe2ff; color: #000; }
.status-delivered { background: #d1e7dd; color: #000; font-weight: 600; }
.status-returned { background: #fff3cd; color: #664d03; }
.status-exception { background: #f8d7da; color: #842029; }
.status-processing { background: #e2e3e5; color: #000; }
.status-notfound { background: #f8d7da; color: #000; }
.status-unknown { background: #e2e3e5; color: #000; }
.status-default { background: #e2e3e5; color: #000; }

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
  color: #000;
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
  color: #000;
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
  color: #000;
  margin-bottom: 5px;
}

.timeline-location {
  font-size: 0.95em;
  margin-bottom: 5px;
  color: #000;
}

.timeline-remark {
  font-size: 0.9em;
  color: #000;
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

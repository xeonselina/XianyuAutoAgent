# 前端甘特图设备状态修改功能修复总结

## 问题描述
前端 Vue 甘特图页面中修改设备状态时没有请求后端接口，状态没有保存到数据库。

## 修复内容

### 1. 在 gantt store 中添加设备状态更新方法

**文件**: `frontend/src/stores/gantt.ts`

添加了 `updateDeviceStatus` 方法：
```typescript
// 更新设备状态
const updateDeviceStatus = async (deviceId: number, status: string) => {
  try {
    const response = await axios.put(`/api/devices/${deviceId}`, {
      status: status
    })
    
    if (response.data.success) {
      // 更新本地设备状态
      const device = devices.value.find(d => d.id === deviceId)
      if (device) {
        device.status = status as Device['status']
      }
      return response.data
    } else {
      throw new Error(response.data.error || '更新设备状态失败')
    }
  } catch (err: any) {
    throw new Error(err.response?.data?.error || err.message || '更新设备状态失败')
  }
}
```

### 2. 修复 GanttChart 组件的处理函数

**文件**: `frontend/src/components/GanttChart.vue`

修复了 `handleUpdateDeviceStatus` 函数：
```typescript
const handleUpdateDeviceStatus = async (device: Device, newStatus: string) => {
  try {
    await ganttStore.updateDeviceStatus(device.id, newStatus)
    ElMessage.success('设备状态更新成功！')
  } catch (error) {
    ElMessage.error('状态更新失败：' + (error as Error).message)
    // 如果更新失败，恢复原状态
    const originalDevice = ganttStore.devices.find(d => d.id === device.id)
    if (originalDevice) {
      // 重新加载数据以确保状态同步
      await ganttStore.loadData()
    }
  }
}
```

### 3. 修复 GanttRow 组件的状态选择器

**文件**: `frontend/src/components/GanttRow.vue`

修改了设备状态选择器的绑定方式：
```vue
<!-- 修改前 -->
<el-select 
  v-model="device.status" 
  size="small" 
  style="width: 80px;"
  @change="updateDeviceStatus"
>

<!-- 修改后 -->
<el-select 
  :model-value="device.status" 
  size="small" 
  style="width: 80px;"
  @change="updateDeviceStatus"
>
```

## 功能流程

1. 用户在甘特图中选择设备状态下拉框
2. 触发 `GanttRow` 组件的 `updateDeviceStatus` 方法
3. 通过 `emit` 事件传递给 `GanttChart` 组件的 `handleUpdateDeviceStatus` 方法
4. 调用 gantt store 的 `updateDeviceStatus` 方法
5. 发送 PUT 请求到 `/api/devices/{device_id}` 更新设备状态
6. 成功后更新本地状态并显示成功消息
7. 失败时显示错误消息并重新加载数据以保持状态同步

## 后端 API 接口

使用现有的设备更新接口：
```
PUT /api/devices/{device_id}
Content-Type: application/json

{
  "status": "新状态值"
}
```

支持的状态值：
- `idle`: 空闲
- `pending_ship`: 待寄出  
- `renting`: 租赁中
- `pending_return`: 待收回
- `returned`: 已归还
- `offline`: 离线

## 错误处理

1. **网络错误**: 显示具体错误消息，重新加载数据恢复界面状态
2. **后端验证错误**: 显示后端返回的错误消息
3. **状态不同步**: 失败时重新加载数据确保前后端状态一致

## 测试建议

1. 在甘特图页面尝试修改不同设备的状态
2. 检查浏览器网络面板确认API请求发送成功
3. 刷新页面确认状态已持久化到数据库
4. 测试网络错误情况下的错误处理
5. 测试并发修改情况下的状态同步

## 注意事项

1. 修改使用了单向数据绑定 (`:model-value`) 而不是双向绑定 (`v-model`)，避免直接修改 props
2. 包含了完整的错误处理和用户反馈
3. 保持了前端状态和后端数据的同步
4. 添加了失败时的数据重新加载机制
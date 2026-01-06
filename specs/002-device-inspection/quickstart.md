# Quick Start: 设备验货系统开发指南

**Feature**: 002-device-inspection  
**Date**: 2026-01-04  
**Target Audience**: 开发人员

## 概述

本指南帮助开发人员快速理解验货系统的架构和实现，并提供开发流程的最佳实践。

## 前置条件

- 已阅读 [spec.md](./spec.md)（功能规格说明）
- 已阅读 [data-model.md](./data-model.md)（数据模型设计）
- 已阅读 [research.md](./research.md)（技术调研）
- 熟悉 Flask、SQLAlchemy、Vue 3、TypeScript

## 开发环境设置

### 1. 后端环境

```bash
# 确保在项目根目录
cd /path/to/XianyuAutoAgent/InventoryManager

# 激活虚拟环境（如果有）
source venv/bin/activate

# 安装依赖（如果有新增）
pip install -r requirements.txt

# 数据库迁移
flask db upgrade
```

### 2. 前端环境

```bash
# 进入前端目录
cd frontend

# 安装依赖（如果有新增）
npm install

# 启动开发服务器
npm run dev
```

### 3. 数据库迁移

```bash
# 创建迁移脚本
flask db migrate -m "添加验货记录表和扩展租赁表"

# 检查迁移脚本
# 编辑 migrations/versions/xxxx_add_inspection_tables.py

# 执行迁移
flask db upgrade

# 如果需要回滚
flask db downgrade
```

---

## 开发流程（按优先级）

### Phase 1: 数据模型和数据库迁移（P1 - 核心基础）

**目标**: 创建验货记录和检查项的数据库表，扩展租赁表

#### 步骤 1.1: 创建数据库迁移脚本

```bash
flask db migrate -m "添加验货记录表和扩展租赁表"
```

#### 步骤 1.2: 编辑迁移脚本

编辑生成的迁移文件 `migrations/versions/xxxx_add_inspection_tables.py`：

```python
def upgrade():
    # 1. 为 rental 表添加 photo_transfer 字段
    op.add_column('rental', 
        sa.Column('photo_transfer', sa.Boolean(), nullable=False, server_default='0', 
                 comment='是否代传照片')
    )
    
    # 2. 创建 inspection_record 表
    op.create_table('inspection_record',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('rental_id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('inspector_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['device_id'], ['device.id'], ),
        sa.ForeignKeyConstraint(['rental_id'], ['rental.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_inspection_record_device_id'), 'inspection_record', ['device_id'], unique=False)
    op.create_index(op.f('ix_inspection_record_rental_id'), 'inspection_record', ['rental_id'], unique=False)
    op.create_index(op.f('ix_inspection_record_status'), 'inspection_record', ['status'], unique=False)
    
    # 3. 创建 inspection_check_item 表
    op.create_table('inspection_check_item',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('inspection_record_id', sa.Integer(), nullable=False),
        sa.Column('item_name', sa.String(length=100), nullable=False),
        sa.Column('is_checked', sa.Boolean(), nullable=False),
        sa.Column('item_order', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['inspection_record_id'], ['inspection_record.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_inspection_check_item_inspection_record_id'), 
                   'inspection_check_item', ['inspection_record_id'], unique=False)

def downgrade():
    op.drop_index(op.f('ix_inspection_check_item_inspection_record_id'), table_name='inspection_check_item')
    op.drop_table('inspection_check_item')
    op.drop_index(op.f('ix_inspection_record_status'), table_name='inspection_record')
    op.drop_index(op.f('ix_inspection_record_rental_id'), table_name='inspection_record')
    op.drop_index(op.f('ix_inspection_record_device_id'), table_name='inspection_record')
    op.drop_table('inspection_record')
    op.drop_column('rental', 'photo_transfer')
```

#### 步骤 1.3: 执行迁移

```bash
flask db upgrade
```

#### 步骤 1.4: 验证迁移

```bash
# 连接数据库
mysql -u your_user -p your_database

# 检查表结构
DESC inspection_record;
DESC inspection_check_item;
DESC rental;  # 验证 photo_transfer 字段
```

---

### Phase 2: 后端模型和服务层（P1 - 核心逻辑）

**目标**: 实现验货记录和检查项的 ORM 模型，以及业务逻辑服务

#### 步骤 2.1: 创建 InspectionRecord 模型

创建文件 `app/models/inspection_record.py`（参考 [data-model.md](./data-model.md) 的 SQLAlchemy 定义）

```python
# app/models/inspection_record.py

from app import db
from datetime import datetime

class InspectionRecord(db.Model):
    """验货记录模型"""
    
    __tablename__ = 'inspection_record'
    
    id = db.Column(db.Integer, primary_key=True)
    rental_id = db.Column(db.Integer, db.ForeignKey('rental.id'), nullable=False, index=True)
    device_id = db.Column(db.Integer, db.ForeignKey('device.id'), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='abnormal', index=True)
    inspector_user_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联关系
    rental = db.relationship('Rental', backref='inspection_records', lazy='joined')
    device = db.relationship('Device', backref='inspection_records', lazy='joined')
    check_items = db.relationship('InspectionCheckItem', backref='inspection_record', 
                                  lazy='select', cascade='all, delete-orphan', 
                                  order_by='InspectionCheckItem.item_order')
    
    def calculate_status(self):
        """根据检查项勾选情况计算验货状态"""
        if not self.check_items:
            return 'abnormal'
        all_checked = all(item.is_checked for item in self.check_items)
        return 'normal' if all_checked else 'abnormal'
    
    def to_dict(self):
        """转换为字典（API 响应）"""
        return {
            'id': self.id,
            'rental_id': self.rental_id,
            'device_id': self.device_id,
            'device_name': self.device.name if self.device else None,
            'customer_name': self.rental.customer_name if self.rental else None,
            'status': self.status,
            'inspector_user_id': self.inspector_user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'check_items': [item.to_dict() for item in self.check_items]
        }
```

#### 步骤 2.2: 创建 InspectionCheckItem 模型

创建文件 `app/models/inspection_check_item.py`

```python
# app/models/inspection_check_item.py

from app import db

class InspectionCheckItem(db.Model):
    """验货检查项模型"""
    
    __tablename__ = 'inspection_check_item'
    
    id = db.Column(db.Integer, primary_key=True)
    inspection_record_id = db.Column(db.Integer, db.ForeignKey('inspection_record.id'), 
                                    nullable=False, index=True)
    item_name = db.Column(db.String(100), nullable=False)
    is_checked = db.Column(db.Boolean, nullable=False, default=False)
    item_order = db.Column(db.Integer, nullable=False, default=0)
    
    def to_dict(self):
        """转换为字典（API 响应）"""
        return {
            'id': self.id,
            'inspection_record_id': self.inspection_record_id,
            'item_name': self.item_name,
            'is_checked': self.is_checked,
            'item_order': self.item_order
        }
```

#### 步骤 2.3: 更新 Rental 模型

编辑 `app/models/rental.py`，添加 `photo_transfer` 字段：

```python
# app/models/rental.py

class Rental(db.Model):
    # ... 现有字段 ...
    
    # 新增字段
    photo_transfer = db.Column(db.Boolean, default=False, nullable=False, comment='是否代传照片')
```

#### 步骤 2.4: 更新模型 __init__.py

编辑 `app/models/__init__.py`，导入新模型：

```python
# app/models/__init__.py

from .inspection_record import InspectionRecord
from .inspection_check_item import InspectionCheckItem
# ... 其他模型导入 ...
```

#### 步骤 2.5: 创建检查清单生成服务

创建文件 `app/services/checklist_generator.py`（参考 [research.md](./research.md) 的实现方案）

```python
# app/services/checklist_generator.py

class ChecklistGenerator:
    """动态检查清单生成器"""
    
    BASE_CHECK_ITEMS = [
        "手机,镜头无严重磕碰",
        "摄像头各焦段无白色十字",
        "镜头镜片清晰,无雾无破裂",
        "镜头拆装顺滑",
        "充电头和充电线"
    ]
    
    @staticmethod
    def generate_checklist(rental):
        """根据租赁记录生成检查清单"""
        checklist = ChecklistGenerator.BASE_CHECK_ITEMS.copy()
        order = len(checklist)
        
        if rental.includes_handle:
            checklist.append("手柄")
        
        if rental.includes_lens_mount:
            checklist.append("镜头支架")
        
        for accessory in rental.accessories:
            if not accessory.is_bundled:
                checklist.append(accessory.name)
        
        if rental.photo_transfer:
            checklist.append("代传照片")
        
        return checklist
```

#### 步骤 2.6: 创建验货业务服务

创建文件 `app/services/inspection_service.py`

```python
# app/services/inspection_service.py

from app import db
from app.models.inspection_record import InspectionRecord
from app.models.inspection_check_item import InspectionCheckItem
from app.models.rental import Rental
from app.services.checklist_generator import ChecklistGenerator

class InspectionService:
    """验货业务逻辑服务"""
    
    @staticmethod
    def create_inspection(rental_id, device_id, check_items_data, inspector_user_id=None):
        """创建验货记录"""
        # 1. 创建验货记录
        inspection = InspectionRecord(
            rental_id=rental_id,
            device_id=device_id,
            inspector_user_id=inspector_user_id
        )
        db.session.add(inspection)
        db.session.flush()  # 获取 inspection.id
        
        # 2. 创建检查项
        for item_data in check_items_data:
            check_item = InspectionCheckItem(
                inspection_record_id=inspection.id,
                item_name=item_data['item_name'],
                is_checked=item_data['is_checked'],
                item_order=item_data['item_order']
            )
            db.session.add(check_item)
        
        # 3. 计算验货状态
        inspection.status = inspection.calculate_status()
        
        db.session.commit()
        return inspection
    
    @staticmethod
    def update_inspection(inspection_id, check_items_updates):
        """更新验货记录"""
        inspection = InspectionRecord.query.get_or_404(inspection_id)
        
        # 更新检查项勾选状态
        for update in check_items_updates:
            item = InspectionCheckItem.query.get(update['id'])
            if item and item.inspection_record_id == inspection_id:
                item.is_checked = update['is_checked']
        
        # 重新计算验货状态
        inspection.status = inspection.calculate_status()
        
        db.session.commit()
        return inspection
```

---

### Phase 3: 后端 API 路由（P1 - 接口实现）

**目标**: 实现验货相关的 RESTful API 端点

#### 步骤 3.1: 创建验货 API 路由

创建文件 `app/routes/inspection_api.py`

```python
# app/routes/inspection_api.py

from flask import Blueprint, request, jsonify
from app.models.rental import Rental
from app.models.device import Device
from app.services.checklist_generator import ChecklistGenerator
from app.services.inspection_service import InspectionService
from app.models.inspection_record import InspectionRecord
from datetime import datetime

bp = Blueprint('inspection', __name__, url_prefix='/api')

@bp.route('/rentals/by-device/<device_id>/latest', methods=['GET'])
def get_latest_rental_by_device(device_id):
    """根据设备编号查询最近的租赁记录"""
    try:
        # 查询设备
        device = Device.query.filter_by(name=device_id).first()
        if not device:
            return jsonify({'success': False, 'error': '未找到该设备'}), 404
        
        # 查询今天之前的最近一条租赁记录
        today = datetime.now().date()
        rental = Rental.query.filter(
            Rental.device_id == device.id,
            Rental.end_date < today
        ).order_by(Rental.end_date.desc()).first()
        
        if not rental:
            return jsonify({'success': False, 'error': '未找到该设备的租赁记录'}), 404
        
        # 生成检查清单
        checklist = ChecklistGenerator.generate_checklist(rental)
        
        # 构建响应
        data = {
            'id': rental.id,
            'device_id': rental.device_id,
            'device_name': device.name,
            'device_model': rental.device.device_model.name if rental.device.device_model else None,
            'customer_name': rental.customer_name,
            'customer_phone': rental.customer_phone,
            'includes_handle': rental.includes_handle,
            'includes_lens_mount': rental.includes_lens_mount,
            'photo_transfer': rental.photo_transfer,
            'accessories': [
                {
                    'id': acc.id,
                    'name': acc.name,
                    'is_bundled': acc.is_bundled
                } for acc in rental.accessories
            ],
            'checklist': checklist
        }
        
        return jsonify({'success': True, 'data': data}), 200
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/inspections', methods=['POST'])
def create_inspection():
    """创建验货记录"""
    try:
        data = request.get_json()
        
        # 验证必填字段
        if not data.get('rental_id') or not data.get('device_id') or not data.get('check_items'):
            return jsonify({'success': False, 'error': '缺少必填字段'}), 400
        
        # 创建验货记录
        inspection = InspectionService.create_inspection(
            rental_id=data['rental_id'],
            device_id=data['device_id'],
            check_items_data=data['check_items'],
            inspector_user_id=data.get('inspector_user_id')
        )
        
        return jsonify({'success': True, 'data': inspection.to_dict()}), 201
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/inspections', methods=['GET'])
def get_inspections():
    """查询验货记录列表"""
    try:
        # 获取查询参数
        device_name = request.args.get('device_name', '')
        status = request.args.get('status', 'all')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        
        # 构建查询
        query = InspectionRecord.query
        
        # 设备名称筛选
        if device_name:
            query = query.join(Device).filter(Device.name.like(f'%{device_name}%'))
        
        # 状态筛选
        if status != 'all':
            query = query.filter(InspectionRecord.status == status)
        
        # 按时间倒序
        query = query.order_by(InspectionRecord.created_at.desc())
        
        # 分页
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        
        # 构建响应
        items = [
            {
                'id': record.id,
                'rental_id': record.rental_id,
                'device_id': record.device_id,
                'device_name': record.device.name if record.device else None,
                'device_model': record.device.device_model.name if record.device and record.device.device_model else None,
                'customer_name': record.rental.customer_name if record.rental else None,
                'status': record.status,
                'created_at': record.created_at.isoformat() if record.created_at else None,
                'updated_at': record.updated_at.isoformat() if record.updated_at else None
            }
            for record in pagination.items
        ]
        
        data = {
            'items': items,
            'total': pagination.total,
            'page': page,
            'per_page': per_page,
            'pages': pagination.pages
        }
        
        return jsonify({'success': True, 'data': data}), 200
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/inspections/<int:inspection_id>', methods=['GET'])
def get_inspection(inspection_id):
    """查询验货记录详情"""
    try:
        inspection = InspectionRecord.query.get_or_404(inspection_id)
        return jsonify({'success': True, 'data': inspection.to_dict()}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/inspections/<int:inspection_id>', methods=['PUT'])
def update_inspection(inspection_id):
    """更新验货记录"""
    try:
        data = request.get_json()
        
        if not data.get('check_items'):
            return jsonify({'success': False, 'error': '缺少 check_items 字段'}), 400
        
        inspection = InspectionService.update_inspection(
            inspection_id=inspection_id,
            check_items_updates=data['check_items']
        )
        
        return jsonify({'success': True, 'data': inspection.to_dict()}), 200
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
```

#### 步骤 3.2: 注册蓝图

编辑 `app/__init__.py`，注册验货 API 蓝图：

```python
# app/__init__.py

def create_app():
    # ... 现有代码 ...
    
    # 注册验货 API 蓝图
    from app.routes import inspection_api
    app.register_blueprint(inspection_api.bp)
    
    return app
```

#### 步骤 3.3: 更新租赁 API（添加 photo_transfer 字段）

编辑 `app/routes/rental_api.py`，确保创建和更新租赁记录时支持 `photo_transfer` 字段。

---

### Phase 4: 前端状态管理（P1 - 数据流）

**目标**: 使用 Pinia 管理验货相关的全局状态

#### 步骤 4.1: 创建验货状态 Store

创建文件 `frontend/src/stores/inspection.ts`

```typescript
// frontend/src/stores/inspection.ts

import { defineStore } from 'pinia'
import type { Rental, InspectionRecord, InspectionRecordSummary } from '../types/inspection'
import { inspectionApi } from '../services/inspectionApi'

export const useInspectionStore = defineStore('inspection', {
  state: () => ({
    // 当前验货会话
    currentRental: null as Rental | null,
    currentChecklist: [] as string[],
    
    // 验货记录列表
    inspectionRecords: [] as InspectionRecordSummary[],
    totalRecords: 0,
    currentPage: 1,
    perPage: 20,
    
    // 筛选条件
    filters: {
      deviceName: '',
      status: 'all' as 'all' | 'normal' | 'abnormal'
    },
    
    // 加载状态
    loading: false,
    error: null as string | null
  }),
  
  actions: {
    // 根据设备编号查询租赁信息
    async fetchRentalByDevice(deviceId: string) {
      this.loading = true
      this.error = null
      try {
        const response = await inspectionApi.getLatestRentalByDevice(deviceId)
        if (response.success) {
          this.currentRental = response.data
          this.currentChecklist = response.data.checklist
        } else {
          this.error = response.error
        }
      } catch (err: any) {
        this.error = err.message
      } finally {
        this.loading = false
      }
    },
    
    // 提交验货记录
    async submitInspection(inspectionData: any) {
      this.loading = true
      this.error = null
      try {
        const response = await inspectionApi.createInspection(inspectionData)
        if (response.success) {
          // 清空当前会话
          this.currentRental = null
          this.currentChecklist = []
          return response.data
        } else {
          this.error = response.error
          throw new Error(response.error)
        }
      } catch (err: any) {
        this.error = err.message
        throw err
      } finally {
        this.loading = false
      }
    },
    
    // 获取验货记录列表
    async fetchInspectionRecords(page: number = 1) {
      this.loading = true
      this.error = null
      try {
        const response = await inspectionApi.getInspectionRecords({
          deviceName: this.filters.deviceName,
          status: this.filters.status === 'all' ? undefined : this.filters.status,
          page,
          perPage: this.perPage
        })
        if (response.success) {
          this.inspectionRecords = response.data.items
          this.totalRecords = response.data.total
          this.currentPage = response.data.page
        } else {
          this.error = response.error
        }
      } catch (err: any) {
        this.error = err.message
      } finally {
        this.loading = false
      }
    },
    
    // 更新验货记录
    async updateInspectionRecord(id: number, updates: any) {
      this.loading = true
      this.error = null
      try {
        const response = await inspectionApi.updateInspection(id, updates)
        if (response.success) {
          // 刷新列表
          await this.fetchInspectionRecords(this.currentPage)
          return response.data
        } else {
          this.error = response.error
          throw new Error(response.error)
        }
      } catch (err: any) {
        this.error = err.message
        throw err
      } finally {
        this.loading = false
      }
    },
    
    // 更新筛选条件
    updateFilters(filters: Partial<typeof this.filters>) {
      this.filters = { ...this.filters, ...filters }
    },
    
    // 清空错误
    clearError() {
      this.error = null
    }
  }
})
```

#### 步骤 4.2: 创建 API 服务层

创建文件 `frontend/src/services/inspectionApi.ts`

```typescript
// frontend/src/services/inspectionApi.ts

import axios from 'axios'

const API_BASE = '/api'

export const inspectionApi = {
  // 根据设备编号查询最近的租赁记录
  async getLatestRentalByDevice(deviceId: string) {
    const response = await axios.get(`${API_BASE}/rentals/by-device/${deviceId}/latest`)
    return response.data
  },
  
  // 创建验货记录
  async createInspection(data: any) {
    const response = await axios.post(`${API_BASE}/inspections`, data)
    return response.data
  },
  
  // 获取验货记录列表
  async getInspectionRecords(params: {
    deviceName?: string
    status?: 'normal' | 'abnormal'
    page?: number
    perPage?: number
  }) {
    const response = await axios.get(`${API_BASE}/inspections`, { params })
    return response.data
  },
  
  // 获取验货记录详情
  async getInspectionDetail(id: number) {
    const response = await axios.get(`${API_BASE}/inspections/${id}`)
    return response.data
  },
  
  // 更新验货记录
  async updateInspection(id: number, data: any) {
    const response = await axios.put(`${API_BASE}/inspections/${id}`, data)
    return response.data
  }
}
```

---

### Phase 5: 前端验货页面（P1 - 核心交互）

**目标**: 实现验货表单页面，支持设备编号搜索、检查清单勾选和提交

#### 步骤 5.1: 创建验货视图页面

创建文件 `frontend/src/views/InspectionView.vue`

```vue
<template>
  <div class="inspection-view">
    <h1>设备验货</h1>
    
    <!-- 设备编号搜索 -->
    <el-card>
      <el-form @submit.prevent="searchDevice">
        <el-form-item label="设备编号">
          <el-input
            v-model="deviceId"
            type="text"
            inputmode="numeric"
            pattern="[0-9]*"
            placeholder="请输入设备编号（纯数字）"
            clearable
          />
        </el-form-item>
        <el-button type="primary" @click="searchDevice" :loading="loading">
          查询租赁信息
        </el-button>
      </el-form>
    </el-card>
    
    <!-- 租赁信息展示 -->
    <el-card v-if="currentRental" class="rental-info-card">
      <h3>租赁信息</h3>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="客户姓名">{{ currentRental.customer_name }}</el-descriptions-item>
        <el-descriptions-item label="客户电话">{{ currentRental.customer_phone }}</el-descriptions-item>
        <el-descriptions-item label="设备型号" :span="2">{{ currentRental.device_model }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
    
    <!-- 验货检查清单 -->
    <el-card v-if="currentChecklist.length > 0" class="checklist-card">
      <h3>验货检查清单</h3>
      <el-checkbox-group v-model="checkedItems">
        <el-checkbox v-for="(item, index) in currentChecklist" :key="index" :label="item">
          {{ item }}
        </el-checkbox>
      </el-checkbox-group>
      
      <div class="status-indicator">
        <el-tag :type="inspectionStatus === 'normal' ? 'success' : 'danger'" size="large">
          {{ inspectionStatus === 'normal' ? '验机正常' : '验机异常' }}
        </el-tag>
      </div>
      
      <el-button type="success" @click="submitInspection" :loading="loading" size="large">
        提交验货记录
      </el-button>
    </el-card>
    
    <!-- 错误提示 -->
    <el-alert v-if="error" :title="error" type="error" show-icon closable @close="clearError" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useInspectionStore } from '../stores/inspection'
import { ElMessage } from 'element-plus'

const inspectionStore = useInspectionStore()

const deviceId = ref('')
const checkedItems = ref<string[]>([])

const loading = computed(() => inspectionStore.loading)
const error = computed(() => inspectionStore.error)
const currentRental = computed(() => inspectionStore.currentRental)
const currentChecklist = computed(() => inspectionStore.currentChecklist)

const inspectionStatus = computed(() => {
  if (checkedItems.value.length === currentChecklist.value.length) {
    return 'normal'
  }
  return 'abnormal'
})

async function searchDevice() {
  if (!deviceId.value) {
    ElMessage.warning('请输入设备编号')
    return
  }
  
  await inspectionStore.fetchRentalByDevice(deviceId.value)
  
  if (inspectionStore.error) {
    ElMessage.error(inspectionStore.error)
  }
}

async function submitInspection() {
  if (!currentRental.value) return
  
  // 构建检查项数据
  const checkItems = currentChecklist.value.map((itemName, index) => ({
    item_name: itemName,
    is_checked: checkedItems.value.includes(itemName),
    item_order: index
  }))
  
  const inspectionData = {
    rental_id: currentRental.value.id,
    device_id: currentRental.value.device_id,
    check_items: checkItems
  }
  
  try {
    await inspectionStore.submitInspection(inspectionData)
    ElMessage.success('验货记录提交成功')
    
    // 清空表单
    deviceId.value = ''
    checkedItems.value = []
  } catch (err: any) {
    ElMessage.error(`提交失败: ${err.message}`)
  }
}

function clearError() {
  inspectionStore.clearError()
}
</script>

<style scoped>
.inspection-view {
  padding: 20px;
  max-width: 800px;
  margin: 0 auto;
}

.rental-info-card,
.checklist-card {
  margin-top: 20px;
}

.el-checkbox {
  display: block;
  margin: 15px 0;
  font-size: 16px;
}

.status-indicator {
  margin: 20px 0;
}

.el-button[size="large"] {
  width: 100%;
  margin-top: 20px;
}
</style>
```

#### 步骤 5.2: 添加路由

编辑 `frontend/src/router/index.ts`，添加验货相关路由：

```typescript
// frontend/src/router/index.ts

const routes = [
  // ... 现有路由 ...
  
  {
    path: '/inspection',
    name: 'Inspection',
    component: () => import('../views/InspectionView.vue')
  },
  {
    path: '/inspection-records',
    name: 'InspectionRecords',
    component: () => import('../views/InspectionRecordsView.vue')
  }
]
```

---

### Phase 6: 前端验货记录列表（P2 - 管理功能）

**目标**: 实现验货记录查询、筛选和编辑功能

#### 步骤 6.1: 创建验货记录列表视图

创建文件 `frontend/src/views/InspectionRecordsView.vue`（完整实现请参考源代码）

---

### Phase 7: 租赁记录表单扩展（P2 - 支持功能）

**目标**: 在租赁记录创建/编辑表单中添加"代传照片"复选框

#### 步骤 7.1: 更新 BookingDialog.vue

编辑 `frontend/src/components/BookingDialog.vue`，添加"代传照片"复选框：

```vue
<el-form-item label="代传照片">
  <el-checkbox v-model="form.photo_transfer">包含代传照片服务</el-checkbox>
</el-form-item>
```

#### 步骤 7.2: 更新 EditRentalDialogNew.vue

类似地更新编辑对话框，确保支持 `photo_transfer` 字段。

---

## 测试策略

### 1. 后端单元测试

创建 `tests/test_inspection.py`：

```python
import pytest
from app.models.inspection_record import InspectionRecord
from app.services.checklist_generator import ChecklistGenerator

def test_checklist_generator_basic():
    """测试基础检查项生成"""
    # ... 测试代码 ...

def test_create_inspection():
    """测试创建验货记录"""
    # ... 测试代码 ...

def test_update_inspection():
    """测试更新验货记录"""
    # ... 测试代码 ...
```

### 2. API 集成测试

使用 Postman 或 pytest 测试 API 端点。

### 3. 前端组件测试

使用 Vitest 测试 Vue 组件。

---

## 部署检查清单

- [ ] 数据库迁移已执行
- [ ] 后端模型和服务已测试
- [ ] API 端点已测试
- [ ] 前端页面在 iPad 上测试
- [ ] 数字键盘正确弹出
- [ ] 验货状态计算正确
- [ ] 筛选和分页功能正常
- [ ] 错误处理和提示完善

---

## 常见问题

### Q1: 数字键盘在 iPad 上不弹出？

确保 `<input>` 标签使用了 `inputmode="numeric"` 属性。

### Q2: 验货状态计算不正确？

检查 `InspectionRecord.calculate_status()` 方法是否正确遍历了所有检查项。

### Q3: 检查清单生成不完整？

确认 `ChecklistGenerator.generate_checklist()` 方法考虑了所有附件类型。

---

## 相关文档

- [spec.md](./spec.md) - 功能规格说明
- [data-model.md](./data-model.md) - 数据模型设计
- [research.md](./research.md) - 技术调研
- [contracts/inspection-api.yaml](./contracts/inspection-api.yaml) - API 接口规范
- [plan.md](./plan.md) - 实施计划

---

**下一步**: 进入 Phase 2 - 使用 `/speckit.tasks` 命令生成详细的任务分解

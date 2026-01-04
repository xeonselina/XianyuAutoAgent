# 快速开始: 简化租赁附件选择功能

**功能**: 001-simplify-rental-accessories  
**最后更新**: 2026-01-04  
**预计开发时间**: 3-5个工作日

---

## 目录

1. [功能概述](#功能概述)
2. [前置条件](#前置条件)
3. [开发环境设置](#开发环境设置)
4. [实施步骤](#实施步骤)
5. [测试指南](#测试指南)
6. [部署流程](#部署流程)
7. [常见问题](#常见问题)

---

## 功能概述

### 业务背景

租赁设备时原本需要为4种附件(手柄、镜头支架、手机支架、三脚架)分别选择具体的设备。现在手柄和镜头支架已与主设备1:1配齐,无需选择具体编号,只需勾选是否使用即可。

### 技术变更

- **数据库**: 在`rentals`表添加`includes_handle`和`includes_lens_mount`布尔字段
- **后端API**: 调整创建/更新订单接口,接受布尔值参数
- **前端UI**: 将手柄和镜头支架改为复选框,保留手机支架和三脚架的下拉选择
- **打印/甘特图**: 兼容性调整,确保附件信息正确显示

### 影响范围

| 模块 | 文件数量 | 影响程度 |
|------|---------|---------|
| 数据模型 | 1 | 中 (添加字段) |
| 后端API | 3-5 | 中 (逻辑调整) |
| 前端UI | 5-7 | 高 (界面改造) |
| 打印服务 | 2-3 | 低 (兼容性调整) |
| 甘特图 | 2-3 | 低 (数据格式调整) |

---

## 前置条件

### 必需工具

- **后端开发**:
  - Python 3.10+
  - MySQL 5.7+
  - Flask 2.3.3
  - Alembic (数据库迁移)

- **前端开发**:
  - Node.js 20.19.0+ 或 22.12.0+
  - npm/yarn
  - Vue 3.5+
  - TypeScript 5.8+

- **开发工具**:
  - IDE: VSCode, PyCharm, WebStorm 等
  - Git
  - Postman/curl (API测试)

### 必需权限

- [ ] 数据库写权限(创建表字段和迁移脚本)
- [ ] 代码仓库推送权限
- [ ] 测试环境部署权限

### 必需知识

- Flask ORM (SQLAlchemy)
- Vue 3 Composition API
- Element Plus组件库
- RESTful API设计

---

## 开发环境设置

### 1. 克隆代码仓库

```bash
git clone <repository-url>
cd InventoryManager
```

### 2. 切换到功能分支

```bash
git checkout 001-simplify-rental-accessories
```

### 3. 后端环境设置

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑.env文件,配置数据库连接等
```

### 4. 前端环境设置

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

### 5. 数据库设置

```bash
# 回到项目根目录
cd ..

# 创建数据库(如果未创建)
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS inventory_management CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 运行现有迁移
flask db upgrade

# 运行新迁移(本功能的迁移脚本)
flask db migrate -m "添加配套附件标记字段"
flask db upgrade
```

### 6. 验证环境

```bash
# 启动后端服务
flask run

# 另开终端,测试API
curl http://localhost:5000/api/rentals
```

---

## 实施步骤

### 阶段1: 数据库迁移 (预计1天)

#### 1.1 生成迁移脚本

```bash
flask db migrate -m "添加配套附件标记字段"
```

#### 1.2 审查迁移脚本

编辑生成的迁移文件 `migrations/versions/[timestamp]_add_bundled_accessory_flags.py`:

```python
def upgrade():
    # 添加新字段
    op.add_column('rentals', sa.Column('includes_handle', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('rentals', sa.Column('includes_lens_mount', sa.Boolean(), nullable=False, server_default='0'))
    
    # 数据迁移逻辑(参考 data-model.md 第6节)
    # ...

def downgrade():
    op.drop_column('rentals', 'includes_lens_mount')
    op.drop_column('rentals', 'includes_handle')
```

#### 1.3 在开发环境执行迁移

```bash
# 备份数据库(重要!)
mysqldump -u root -p inventory_management > backup_before_migration_$(date +%Y%m%d).sql

# 执行迁移
flask db upgrade

# 验证迁移结果
mysql -u root -p inventory_management -e "DESCRIBE rentals;"
mysql -u root -p inventory_management -e "SELECT id, includes_handle, includes_lens_mount FROM rentals LIMIT 10;"
```

#### 1.4 验证数据完整性

运行SQL验证查询(参考 `data-model.md` 第6.2节):

```sql
SELECT 
    r.id,
    r.includes_handle,
    r.includes_lens_mount,
    COUNT(CASE WHEN d.name LIKE '%手柄%' THEN 1 END) as handle_count,
    COUNT(CASE WHEN d.name LIKE '%镜头支架%' THEN 1 END) as lens_mount_count
FROM rentals r
LEFT JOIN rentals child ON child.parent_rental_id = r.id
LEFT JOIN devices d ON child.device_id = d.id
WHERE r.parent_rental_id IS NULL
GROUP BY r.id
LIMIT 20;
```

---

### 阶段2: 后端API开发 (预计1-1.5天)

#### 2.1 更新Rental模型

**文件**: `app/models/rental.py`

添加新字段和相关方法:

```python
class Rental(db.Model):
    # ...现有字段
    
    # 新增字段
    includes_handle = db.Column(db.Boolean, default=False, nullable=False)
    includes_lens_mount = db.Column(db.Boolean, default=False, nullable=False)
    
    def get_all_accessories_for_display(self) -> list:
        """获取所有附件信息(用于打印和甘特图显示)"""
        # 实现参考 data-model.md 第2.1节
        pass
```

#### 2.2 更新RentalService

**文件**: `app/services/rental/rental_service.py`

修改 `create_rental_with_accessories` 方法:

```python
def create_rental_with_accessories(data: Dict[str, Any]) -> Tuple[Rental, List[Rental]]:
    # 创建主租赁记录(含布尔字段)
    main_rental = Rental(
        device_id=data['device_id'],
        # ...其他字段
        includes_handle=data.get('includes_handle', False),
        includes_lens_mount=data.get('includes_lens_mount', False),
        status='not_shipped'
    )
    db.session.add(main_rental)
    db.session.flush()
    
    # 只为库存附件(手机支架、三脚架)创建子租赁记录
    accessory_rentals = []
    for accessory_id in data.get('accessory_ids', []):
        # 确认不是手柄或镜头支架
        accessory_device = Device.query.get(accessory_id)
        if accessory_device and accessory_device.is_accessory:
            if '手柄' not in accessory_device.name and '镜头支架' not in accessory_device.name:
                accessory_rental = Rental(
                    device_id=accessory_id,
                    customer_name=data['customer_name'],
                    # ...复制主订单信息
                    parent_rental_id=main_rental.id,
                    status='not_shipped'
                )
                db.session.add(accessory_rental)
                accessory_rentals.append(accessory_rental)
    
    db.session.commit()
    return main_rental, accessory_rentals
```

#### 2.3 更新API路由

**文件**: `app/routes/rental_api.py`

确保API接受新参数:

```python
@rental_bp.route('/rentals', methods=['POST'])
def create_rental():
    data = request.get_json()
    
    # 验证数据(包括新字段)
    is_valid, error_msg = RentalValidator.validate_create_data(data)
    if not is_valid:
        return jsonify({'error': error_msg}), 400
    
    # 调用服务层
    rental, accessory_rentals = create_rental_with_accessories(data)
    
    return jsonify(rental.to_dict()), 201
```

#### 2.4 测试后端API

使用Postman或curl测试:

```bash
# 测试创建订单(含配套附件)
curl -X POST http://localhost:5000/api/rentals \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": 123,
    "start_date": "2026-01-05",
    "end_date": "2026-01-10",
    "customer_name": "测试用户",
    "customer_phone": "13800138000",
    "includes_handle": true,
    "includes_lens_mount": false,
    "accessory_ids": [45]
  }'

# 验证响应
# 预期: HTTP 201, 返回订单详情(includes_handle: true)
```

---

### 阶段3: 前端UI开发 (预计1.5-2天)

#### 3.1 更新TypeScript类型定义

**文件**: `frontend/src/types/rental.ts` (新建)

```typescript
export interface RentalFormData {
  device_id: number
  start_date: string
  end_date: string
  customer_name: string
  customer_phone?: string
  
  // 新增附件字段
  bundled_accessories: string[]  // UI层: ['handle', 'lens_mount']
  phone_holder_id: number | null
  tripod_id: number | null
}

export interface RentalCreatePayload {
  device_id: number
  start_date: string
  end_date: string
  customer_name: string
  customer_phone?: string
  
  // API层
  includes_handle: boolean
  includes_lens_mount: boolean
  accessory_ids: number[]
}
```

#### 3.2 修改BookingDialog组件

**文件**: `frontend/src/components/BookingDialog.vue`

找到附件选择部分(约第175-250行),替换为:

```vue
<template>
  <!-- 配套附件:复选框 -->
  <el-form-item label="配套附件">
    <el-checkbox-group v-model="form.bundledAccessories">
      <el-checkbox label="handle">手柄</el-checkbox>
      <el-checkbox label="lens_mount">镜头支架</el-checkbox>
    </el-checkbox-group>
  </el-form-item>
  
  <!-- 手机支架:下拉选择 -->
  <el-form-item label="手机支架">
    <el-select 
      v-model="form.phoneHolderId" 
      clearable 
      placeholder="选择手机支架(可选)"
      @focus="checkPhoneHolderAvailability"
    >
      <el-option
        v-for="holder in phoneHolders"
        :key="holder.id"
        :label="`${holder.name} ${holder.is_available ? '(可用)' : '(冲突)'}`"
        :value="holder.id"
        :disabled="!holder.is_available"
      />
    </el-select>
  </el-form-item>
  
  <!-- 三脚架:同理 -->
  <!-- ... -->
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { RentalFormData, RentalCreatePayload } from '@/types/rental'

const form = ref<RentalFormData>({
  device_id: 0,
  start_date: '',
  end_date: '',
  customer_name: '',
  bundledAccessories: [],
  phone_holder_id: null,
  tripod_id: null
})

// 转换为API payload
const createPayload = computed((): RentalCreatePayload => ({
  device_id: form.value.device_id,
  start_date: form.value.start_date,
  end_date: form.value.end_date,
  customer_name: form.value.customer_name,
  customer_phone: form.value.customer_phone,
  includes_handle: form.value.bundledAccessories.includes('handle'),
  includes_lens_mount: form.value.bundledAccessories.includes('lens_mount'),
  accessory_ids: [
    form.value.phone_holder_id,
    form.value.tripod_id
  ].filter((id): id is number => id !== null)
}))

async function submitForm() {
  const response = await fetch('/api/rentals', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(createPayload.value)
  })
  
  if (response.ok) {
    ElMessage.success('订单创建成功')
    // ...
  }
}
</script>
```

#### 3.3 修改RentalAccessorySelector组件

**文件**: `frontend/src/components/rental/RentalAccessorySelector.vue`

应用类似的改动,将手柄和镜头支架改为复选框。

#### 3.4 修改EditRentalDialogNew组件

**文件**: `frontend/src/components/rental/EditRentalDialogNew.vue`

确保编辑订单时:
1. 加载历史数据时正确显示复选框状态
2. 提交时使用新的API格式

```typescript
// 加载历史订单数据
function loadRentalData(rental: Rental) {
  form.value.bundledAccessories = []
  
  if (rental.includes_handle) {
    form.value.bundledAccessories.push('handle')
  }
  if (rental.includes_lens_mount) {
    form.value.bundledAccessories.push('lens_mount')
  }
  
  // 库存附件
  const phoneHolder = rental.accessories.find(a => a.type === 'phone_holder')
  form.value.phone_holder_id = phoneHolder?.id || null
}
```

#### 3.5 前端测试

```bash
cd frontend
npm run dev

# 打开浏览器访问开发服务器
# 测试:
# 1. 创建新订单,勾选手柄复选框,选择手机支架
# 2. 保存后查看订单详情
# 3. 编辑订单,修改附件配置
# 4. 加载历史订单,验证数据显示正确
```

---

### 阶段4: 打印和甘特图调整 (预计0.5-1天)

#### 4.1 更新发货单生成服务

**文件**: `app/services/printing/shipping_slip_image_service.py`

修改 `_draw_accessories_section` 方法:

```python
def _draw_accessories_section(self, draw, rental):
    """绘制附件清单部分"""
    y = self.current_y
    
    draw.text((self.margin, y), "附件清单:", font=self.font_bold)
    y += self.line_height
    
    # 获取完整附件列表
    all_accessories = rental.get_all_accessories_for_display()
    
    for accessory in all_accessories:
        if accessory.get('is_bundled'):
            # 配套附件
            text = f"✓ {accessory['name']} (配套)"
        else:
            # 库存附件
            text = f"• {accessory['name']} (编号: {accessory.get('serial_number', 'N/A')})"
        
        draw.text((self.margin + 20, y), text, font=self.font)
        y += self.line_height
    
    self.current_y = y
```

#### 4.2 更新甘特图API

**文件**: `app/routes/gantt_api.py`

确保 `GET /api/gantt/data` 返回完整附件信息:

```python
def format_rental_for_gantt(rental: Rental) -> dict:
    return {
        'id': rental.id,
        'device_name': rental.device.name,
        'start_date': rental.start_date.isoformat(),
        'end_date': rental.end_date.isoformat(),
        'accessories': rental.get_all_accessories_for_display()  # 使用新方法
    }
```

#### 4.3 更新前端甘特图显示

**文件**: `frontend/src/components/GanttRow.vue`

更新工具提示内容:

```vue
<el-tooltip placement="top">
  <template #content>
    <div>
      <p><strong>订单 #{{ rental.id }}</strong></p>
      <p>客户: {{ rental.customer_name }}</p>
      <p>附件:</p>
      <ul>
        <li v-for="acc in rental.accessories" :key="acc.name || acc.id">
          {{ acc.name }}
          <el-tag v-if="acc.is_bundled" size="small" type="info">配套</el-tag>
          <span v-else-if="acc.serial_number">({{ acc.serial_number }})</span>
        </li>
      </ul>
    </div>
  </template>
  <div class="rental-bar">{{ rental.device_name }}</div>
</el-tooltip>
```

---

### 阶段5: 测试 (预计1天)

参考下方 [测试指南](#测试指南) 部分。

---

## 测试指南

### 单元测试

#### 后端单元测试

**文件**: `tests/unit/test_rental_service.py`

```bash
# 运行测试
pytest tests/unit/test_rental_service.py -v

# 测试用例:
# - test_create_rental_with_bundled_accessories
# - test_create_rental_with_mixed_accessories
# - test_update_rental_accessories
# - test_get_all_accessories_for_display
```

#### 前端组件测试

**文件**: `frontend/tests/unit/RentalAccessorySelector.spec.ts`

```bash
cd frontend
npm run test:unit

# 测试用例:
# - 显示手柄和镜头支架复选框
# - 手机支架显示为下拉选择
# - 正确加载历史订单数据
```

### 集成测试

#### API集成测试

```bash
pytest tests/integration/test_rental_api.py -v

# 测试场景:
# 1. 创建订单(仅配套附件)
# 2. 创建订单(配套附件 + 库存附件)
# 3. 更新订单附件配置
# 4. 获取订单详情(验证附件信息完整)
```

#### 端到端测试

**测试场景**:

1. **创建新订单流程**:
   - 登录系统
   - 打开预订对话框
   - 选择设备和日期
   - 勾选"手柄"复选框
   - 选择"手机支架-P01"
   - 保存订单
   - 验证订单详情页显示正确

2. **编辑订单流程**:
   - 打开已有订单
   - 修改附件配置(取消手柄,添加镜头支架)
   - 保存
   - 验证更新成功

3. **打印流程**:
   - 选择订单
   - 生成发货单
   - 验证发货单上附件清单完整且格式正确

4. **甘特图显示**:
   - 打开甘特图页面
   - 悬停在订单条上
   - 验证工具提示显示所有附件(含配套和库存)

### 性能测试

```bash
# 使用Apache Bench测试API性能
ab -n 100 -c 10 -T 'application/json' -p rental_payload.json http://localhost:5000/api/rentals

# 预期:
# - 响应时间 < 500ms (p95)
# - 无数据库连接泄漏
```

### 兼容性测试

- [ ] Chrome 最新版
- [ ] Firefox 最新版
- [ ] Safari 最新版
- [ ] Edge 最新版
- [ ] 移动端浏览器(如有)

---

## 部署流程

### 准备阶段

#### 1. 代码审查

```bash
# 创建Pull Request
git push origin 001-simplify-rental-accessories

# 在Git平台(GitHub/GitLab)创建PR
# 等待代码审查通过
```

#### 2. 准备部署清单

- [ ] 所有测试通过
- [ ] 代码审查通过
- [ ] 数据库迁移脚本已审查
- [ ] 回滚方案已准备
- [ ] 备份策略已确认

#### 3. 备份生产数据库

```bash
# 在生产服务器执行
mysqldump -u root -p inventory_management > backup_before_accessory_simplification_$(date +%Y%m%d_%H%M%S).sql

# 验证备份文件
ls -lh backup_before_accessory_simplification_*.sql
```

---

### Staging环境部署

#### 1. 部署到Staging

```bash
# SSH到staging服务器
ssh user@staging.example.com

cd /path/to/InventoryManager

# 拉取最新代码
git fetch origin
git checkout 001-simplify-rental-accessories
git pull origin 001-simplify-rental-accessories

# 后端部署
source venv/bin/activate
pip install -r requirements.txt
flask db upgrade

# 重启后端服务
systemctl restart inventory-backend

# 前端部署
cd frontend
npm install
npm run build
# 部署dist/到nginx/apache

# 重启前端服务(如需要)
systemctl restart nginx
```

#### 2. Staging环境冒烟测试

- [ ] 创建一个测试订单(含配套附件)
- [ ] 编辑订单,修改附件
- [ ] 生成发货单,检查附件显示
- [ ] 打开甘特图,验证附件信息
- [ ] 检查应用日志,确认无错误

#### 3. Staging环境性能测试

```bash
# 简单压测
ab -n 50 -c 5 https://staging.example.com/api/rentals
```

---

### 生产环境部署

#### 1. 部署时间窗口

建议选择低峰时段,例如:
- 工作日晚上22:00-23:00
- 周末下午

#### 2. 部署步骤(与Staging类似)

```bash
# 1. 备份数据库(再次确认)
mysqldump -u root -p inventory_management > backup_production_$(date +%Y%m%d_%H%M%S).sql

# 2. 进入维护模式(可选)
# 在nginx配置中返回503页面

# 3. 拉取代码
git fetch origin
git checkout 001-simplify-rental-accessories
git pull origin 001-simplify-rental-accessories

# 4. 部署后端
source venv/bin/activate
pip install -r requirements.txt
flask db upgrade
systemctl restart inventory-backend

# 5. 部署前端
cd frontend
npm install
npm run build
# 复制dist/到生产目录
systemctl restart nginx

# 6. 退出维护模式
```

#### 3. 生产环境验证

- [ ] 健康检查: `curl https://api.example.com/health`
- [ ] 创建一个真实订单测试
- [ ] 检查应用日志
- [ ] 监控数据库性能
- [ ] 确认打印功能正常

---

### 部署后监控(前24小时)

#### 监控指标

- **应用性能**:
  - API响应时间 (目标: p95 < 500ms)
  - 错误率 (目标: < 0.1%)
  - 请求量

- **数据库**:
  - 查询性能
  - 连接池使用率
  - 慢查询日志

- **业务指标**:
  - 订单创建成功率
  - 打印服务调用成功率
  - 用户反馈

#### 回滚决策条件

如果出现以下情况,考虑回滚:
- API错误率 > 5%
- 关键功能(创建订单/打印)不可用
- 数据库性能显著下降
- 收到多个用户投诉

---

### 回滚流程

```bash
# 1. 回滚代码
git checkout main  # 或上一个稳定版本
git pull origin main

# 2. 回滚前端
cd frontend
npm install
npm run build
# 重新部署

# 3. 回滚数据库(如需要)
flask db downgrade  # 回滚一个版本

# 或从备份恢复(极端情况)
mysql -u root -p inventory_management < backup_production_YYYYMMDD_HHMMSS.sql

# 4. 重启服务
systemctl restart inventory-backend
systemctl restart nginx

# 5. 验证回滚成功
curl https://api.example.com/health
```

---

## 常见问题

### 开发阶段

**Q1: 迁移脚本执行失败,提示 "Column 'includes_handle' cannot be null"**

A: 确保迁移脚本中添加了 `server_default='0'`:
```python
op.add_column('rentals', sa.Column('includes_handle', sa.Boolean(), nullable=False, server_default='0'))
```

**Q2: 前端复选框不显示,控制台报错 "Cannot read property 'includes' of undefined"**

A: 确保 `form.bundledAccessories` 初始化为数组:
```typescript
const form = ref({
  bundledAccessories: [] as string[],  // 不是null
  // ...
})
```

**Q3: API返回的附件列表为空**

A: 检查是否调用了新方法 `get_all_accessories_for_display()`,而非旧的 `child_rentals`。

---

### 测试阶段

**Q4: 历史订单加载后,复选框状态不正确**

A: 确认数据迁移脚本正确执行。运行验证SQL(见 `data-model.md` 第6.2节)。

**Q5: 打印的发货单上没有显示配套附件**

A: 检查 `ShippingSlipImageService` 是否使用了 `get_all_accessories_for_display()` 方法。

---

### 部署阶段

**Q6: 数据库迁移卡住**

A: 可能是表锁。检查是否有长时间运行的查询:
```sql
SHOW FULL PROCESSLIST;
```
考虑在维护窗口执行迁移。

**Q7: 部署后性能下降明显**

A: 检查是否添加了建议的索引:
```sql
CREATE INDEX idx_rentals_includes_handle ON rentals(includes_handle);
CREATE INDEX idx_rentals_includes_lens_mount ON rentals(includes_lens_mount);
```

---

### 运维阶段

**Q8: 用户报告编辑订单时附件选择不显示**

A: 清除浏览器缓存,或强制刷新前端资源(Ctrl+Shift+R)。

**Q9: 甘特图加载缓慢**

A: 检查 `/api/gantt/data` 的查询性能。可能需要添加索引或优化查询:
```python
rentals = Rental.query.options(
    db.joinedload(Rental.device),
    db.joinedload(Rental.child_rentals).joinedload(Rental.device)
).filter(...).all()
```

---

## 相关文档

- [功能规范 (spec.md)](./spec.md)
- [实施计划 (plan.md)](./plan.md)
- [技术调研 (research.md)](./research.md)
- [数据模型设计 (data-model.md)](./data-model.md)
- [API合约 (contracts/api-spec.yaml)](./contracts/api-spec.yaml)

---

## 联系方式

遇到问题或需要帮助?

- **技术问题**: 在项目仓库创建Issue
- **紧急问题**: 联系开发团队负责人
- **反馈建议**: 通过内部沟通渠道反馈

---

**文档版本**: 1.0  
**最后更新**: 2026-01-04  
**维护者**: 开发团队

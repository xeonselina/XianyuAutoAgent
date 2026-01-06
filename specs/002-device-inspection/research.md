# Research: 设备验货系统技术调研

**Feature**: 002-device-inspection  
**Date**: 2026-01-04  
**Status**: Complete

## 调研目标

1. 确定移动端（iPad）数字键盘触发方案
2. 研究动态检查清单生成的最佳实践
3. 确定验货记录和检查项的数据模型设计
4. 研究现有租赁系统的扩展方案
5. 确定前端状态管理和组件设计模式

## 1. iPad 数字键盘触发方案

### 调研内容

移动设备（特别是 iPad）需要在输入纯数字时自动弹出数字键盘，提升用户体验。

### 技术选项

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| `<input type="number">` | 标准 HTML5 属性，浏览器原生支持 | 允许输入 e、+、- 等非纯数字字符 | ★★★☆☆ |
| `<input type="tel">` | 弹出电话号码键盘，只有数字 | 语义不够准确（不是电话号码） | ★★★★☆ |
| `<input inputmode="numeric">` | HTML5 标准，语义准确，纯数字键盘 | 需要浏览器支持（iOS 12.2+） | ★★★★★ |
| 组合方案：`type="text" + inputmode="numeric" + pattern="[0-9]*"` | 最佳兼容性和用户体验 | 代码稍复杂 | ★★★★★ |

### 决策

**选择组合方案**：`type="text" + inputmode="numeric" + pattern="[0-9]*"`

### 理由

1. `type="text"` 避免了 `type="number"` 允许 e、+、- 的问题
2. `inputmode="numeric"` 确保弹出纯数字键盘（iOS 12.2+、Android、现代浏览器支持良好）
3. `pattern="[0-9]*"` 提供额外的语义提示和客户端验证
4. 兼容性最佳，覆盖 iPad Safari、Chrome、Firefox 等主流浏览器

### 实现示例

```html
<input 
  type="text" 
  inputmode="numeric" 
  pattern="[0-9]*"
  placeholder="请输入设备编号"
/>
```

### 参考资料

- [MDN: inputmode 属性](https://developer.mozilla.org/en-US/docs/Web/HTML/Global_attributes/inputmode)
- [HTML Living Standard: Input types](https://html.spec.whatwg.org/multipage/input.html)
- [Can I use: inputmode attribute](https://caniuse.com/input-inputmode)

---

## 2. 动态检查清单生成最佳实践

### 调研内容

需要根据租赁订单的内容（附件信息）动态生成验货检查清单，确保准确性和可维护性。

### 设计模式选项

| 模式 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **配置驱动** | 将基础检查项定义为配置常量 | 易于维护，集中管理 | 静态配置 |
| **策略模式** | 不同类型租赁使用不同的检查清单生成策略 | 灵活，可扩展 | 过度设计（当前需求简单） |
| **组合模式** | 基础检查项 + 动态附件检查项组合 | 简单清晰，符合需求 | N/A |
| **模板方法** | 定义检查清单生成模板，子类实现细节 | 标准化流程 | 过度设计 |

### 决策

**选择组合模式**：基础检查项（常量） + 动态附件检查项（从租赁记录提取）

### 理由

1. **需求匹配**: 规格明确要求所有订单包含 5 个基础检查项 + 根据附件动态添加检查项
2. **简单有效**: 组合模式直观，代码易于理解和维护
3. **避免过度设计**: 策略模式和模板方法适合复杂场景，当前需求不需要
4. **易于扩展**: 未来如果需要更复杂的检查项生成逻辑，可以在组合模式基础上重构

### 实现方案

**后端服务层（Python）**：

```python
# app/services/checklist_generator.py

class ChecklistGenerator:
    """动态检查清单生成器"""
    
    # 基础检查项（常量）
    BASE_CHECK_ITEMS = [
        "手机,镜头无严重磕碰",
        "摄像头各焦段无白色十字",
        "镜头镜片清晰,无雾无破裂",
        "镜头拆装顺滑",
        "充电头和充电线"
    ]
    
    @staticmethod
    def generate_checklist(rental):
        """
        根据租赁记录生成检查清单
        
        Args:
            rental: Rental 对象
            
        Returns:
            list: 检查项名称列表
        """
        checklist = ChecklistGenerator.BASE_CHECK_ITEMS.copy()
        
        # 添加手柄检查项
        if rental.includes_handle:
            checklist.append("手柄")
        
        # 添加镜头支架检查项
        if rental.includes_lens_mount:
            checklist.append("镜头支架")
        
        # 添加个性化附件检查项
        for accessory in rental.accessories:
            if not accessory.is_bundled:  # 只添加非配套附件
                checklist.append(accessory.name)
        
        # 添加代传照片检查项
        if rental.photo_transfer:
            checklist.append("代传照片")
        
        return checklist
```

**前端（TypeScript/Vue）**：

前端接收后端生成的检查清单数组，直接渲染为复选框，无需前端逻辑。

### 替代方案及拒绝原因

- **策略模式**: 当前只有一种检查清单生成逻辑，引入策略模式会增加不必要的复杂度
- **前端生成检查清单**: 将检查清单生成逻辑放在前端会导致逻辑分散，且难以保证与后端一致性

---

## 3. 验货记录数据模型设计

### 调研内容

设计验货记录（InspectionRecord）和验货检查项（InspectionCheckItem）的数据库模型。

### 设计选项

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **单表模式** | 验货记录包含 JSON 字段存储所有检查项 | 查询简单，一次查询获取所有数据 | JSON 字段不利于查询和索引 |
| **主从表模式** | InspectionRecord (主表) + InspectionCheckItem (从表) | 结构清晰，便于查询单个检查项 | 关联查询稍复杂 |
| **EAV 模式** | 实体-属性-值模式，动态存储检查项 | 极度灵活 | 查询复杂，性能较差 |

### 决策

**选择主从表模式**：InspectionRecord (1) → InspectionCheckItem (N)

### 理由

1. **关系型数据库最佳实践**: 符合数据库设计第三范式
2. **查询灵活**: 可以按检查项名称、勾选状态等维度查询
3. **数据完整性**: 外键约束确保数据一致性
4. **便于审计**: 清晰记录每个检查项的勾选状态和变更历史
5. **性能可接受**: 每条验货记录包含 5-15 个检查项，关联查询性能充足

### 数据模型设计

**InspectionRecord（验货记录）**

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | Integer | PK, Auto Increment | 验货记录ID |
| rental_id | Integer | FK(Rental.id), NOT NULL, INDEX | 关联的租赁记录ID |
| device_id | Integer | FK(Device.id), NOT NULL, INDEX | 关联的设备ID |
| status | String(20) | NOT NULL, INDEX | 验货状态：'normal' (验机正常) / 'abnormal' (验机异常) |
| inspector_user_id | Integer | FK(User.id), NULLABLE | 验货人员ID（如果系统有用户模块） |
| created_at | DateTime | NOT NULL | 创建时间 |
| updated_at | DateTime | NOT NULL | 最后修改时间 |

**InspectionCheckItem（验货检查项）**

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | Integer | PK, Auto Increment | 检查项ID |
| inspection_record_id | Integer | FK(InspectionRecord.id), NOT NULL, INDEX | 所属验货记录ID |
| item_name | String(100) | NOT NULL | 检查项名称 |
| is_checked | Boolean | NOT NULL, DEFAULT=False | 是否已勾选 |
| item_order | Integer | NOT NULL | 显示顺序 |

**关系**

- InspectionRecord 1 → N InspectionCheckItem（一对多）
- InspectionRecord N → 1 Rental（多对一，一个租赁可以有多次验货）
- InspectionRecord N → 1 Device（多对一，一个设备可以有多次验货）

### 索引设计

- InspectionRecord.rental_id（查询某个租赁的验货记录）
- InspectionRecord.device_id（查询某个设备的验货历史）
- InspectionRecord.status（按验货状态筛选）
- InspectionRecord.created_at（按时间排序）
- InspectionCheckItem.inspection_record_id（关联查询）

### 替代方案及拒绝原因

- **单表 JSON 模式**: JSON 字段难以建立索引，不利于按检查项查询或统计
- **EAV 模式**: 过度复杂，查询性能差，不适合当前需求

---

## 4. 租赁记录扩展方案

### 调研内容

需要在现有 Rental 模型中添加"代传照片"（photo_transfer）字段。

### 扩展方案

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **直接添加字段** | 在 Rental 表中添加 photo_transfer 布尔字段 | 简单直接，查询快速 | 修改核心表结构 |
| **扩展表** | 创建 RentalExtension 表存储扩展属性 | 不修改核心表，解耦 | 增加关联查询复杂度 |
| **JSON 字段** | 在 Rental 表中添加 extra_fields JSON 字段 | 灵活，可扩展 | JSON 字段不利于查询和索引 |

### 决策

**选择直接添加字段**：在 Rental 表中添加 `photo_transfer` 布尔字段

### 理由

1. **需求明确**: "代传照片"是明确的业务字段，不是临时或实验性功能
2. **查询性能**: 直接字段查询速度最快，可以建立索引
3. **简单维护**: 避免引入额外的关联表或 JSON 解析逻辑
4. **符合现有模式**: Rental 表已有 `includes_handle`、`includes_lens_mount` 等布尔字段，保持一致性

### 实现方案

**数据库迁移（Flask-Migrate）**

```python
# migrations/versions/xxxx_add_photo_transfer_to_rental.py

def upgrade():
    op.add_column('rental', 
        sa.Column('photo_transfer', sa.Boolean(), nullable=False, server_default='0')
    )

def downgrade():
    op.drop_column('rental', 'photo_transfer')
```

**模型更新**

```python
# app/models/rental.py

class Rental(db.Model):
    # ... 现有字段 ...
    
    photo_transfer = db.Column(db.Boolean, default=False, nullable=False, comment='是否代传照片')
```

### 替代方案及拒绝原因

- **扩展表**: 仅为一个字段创建扩展表，过度设计，增加查询复杂度
- **JSON 字段**: 不利于查询和筛选，且当前只有一个扩展字段，使用 JSON 过于复杂

---

## 5. 前端状态管理和组件设计

### 调研内容

确定前端验货功能的状态管理方案和组件划分。

### 状态管理方案

| 方案 | 描述 | 适用场景 | 推荐度 |
|------|------|----------|--------|
| **Pinia Store** | 全局状态管理 | 跨页面/组件共享状态 | ★★★★★ |
| **组件本地状态** | Vue 3 Composition API (ref/reactive) | 单页面内部状态 | ★★★★☆ |
| **Props/Emits** | 父子组件通信 | 组件间数据传递 | ★★★★★ |

### 决策

**混合方案**：
- **Pinia Store** 管理验货记录列表、当前验货会话、筛选条件等全局状态
- **组件本地状态** 管理表单输入、临时 UI 状态等局部状态
- **Props/Emits** 实现组件间通信

### 理由

1. **职责分离**: 全局状态（如验货记录列表）使用 Pinia 统一管理，局部状态（如输入框内容）使用本地状态
2. **符合 Vue 3 最佳实践**: Pinia 是 Vue 3 官方推荐的状态管理库
3. **可维护性**: 状态清晰，便于调试和测试
4. **性能优化**: 避免不必要的全局状态，减少响应式开销

### 组件设计

#### 页面级组件

1. **InspectionView.vue**（验货表单页面）
   - 设备编号搜索
   - 租赁信息展示
   - 验货检查清单
   - 提交验货记录

2. **InspectionRecordsView.vue**（验货记录列表页面）
   - 验货记录列表
   - 筛选器（设备名称、验货状态）
   - 编辑验货记录

#### 功能组件

1. **DeviceSearch.vue**（设备编号搜索组件）
   - 数字输入框（触发数字键盘）
   - 搜索按钮
   - 加载状态

2. **RentalInfo.vue**（租赁信息展示组件）
   - 客户名称、电话
   - 设备型号
   - 租赁状态

3. **ChecklistForm.vue**（验货检查清单组件）
   - 动态渲染检查项复选框
   - 全选/取消全选
   - 验货状态自动计算

4. **InspectionRecordCard.vue**（验货记录卡片组件）
   - 验货记录摘要信息
   - 验货状态标签
   - 点击展开详情

### Pinia Store 设计

```typescript
// src/stores/inspection.ts

export const useInspectionStore = defineStore('inspection', {
  state: () => ({
    // 当前验货会话
    currentInspection: null as CurrentInspection | null,
    
    // 验货记录列表
    inspectionRecords: [] as InspectionRecord[],
    
    // 筛选条件
    filters: {
      deviceName: '',
      status: 'all' // 'all' | 'normal' | 'abnormal'
    },
    
    // 加载状态
    loading: false,
    error: null as string | null
  }),
  
  actions: {
    // 根据设备编号查询租赁信息
    async fetchRentalByDevice(deviceId: string) { /* ... */ },
    
    // 提交验货记录
    async submitInspection(inspectionData: InspectionData) { /* ... */ },
    
    // 获取验货记录列表
    async fetchInspectionRecords(filters?: Filters) { /* ... */ },
    
    // 更新验货记录
    async updateInspectionRecord(id: number, updates: Partial<InspectionRecord>) { /* ... */ }
  }
})
```

### 替代方案及拒绝原因

- **全局状态管理所有状态**: 过度使用全局状态会导致状态管理复杂，难以维护
- **完全本地状态**: 不使用 Pinia 会导致跨页面数据共享困难，需要频繁的 API 请求

---

## 6. 移动端响应式设计

### 调研内容

确保验货页面在 iPad 上的最佳用户体验。

### 响应式设计策略

| 策略 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **移动优先** | 从移动端设计开始，逐步增强到桌面端 | 确保移动端体验优先 | 可能在桌面端过于简化 |
| **桌面优先** | 从桌面端设计开始，适配到移动端 | 桌面端功能完整 | 移动端适配困难 |
| **自适应布局** | 使用 CSS Grid/Flexbox 实现流式布局 | 适配多种屏幕尺寸 | 需要仔细调整断点 |

### 决策

**移动优先 + 自适应布局**

### 理由

1. **需求明确**: 规格要求"在 iPad 上使用"，移动端是主要使用场景
2. **渐进增强**: 从简单的移动端设计开始，逐步增强到桌面端
3. **Element Plus 支持**: Element Plus 组件库原生支持响应式设计

### 实现要点

1. **触摸友好的控件大小**: 按钮和复选框最小点击区域 44x44px（遵循 Apple HIG）
2. **viewport 设置**:
   ```html
   <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
   ```
3. **断点设计**:
   - 移动端（< 768px）: 单列布局
   - iPad（768px - 1024px）: 双列布局，侧边栏折叠
   - 桌面端（> 1024px）: 多列布局，侧边栏展开
4. **字体大小**:
   - 移动端: 16px 基础字号（避免 iOS 自动缩放）
   - iPad: 18px 基础字号
5. **表单优化**:
   - 使用 `inputmode="numeric"` 触发数字键盘
   - 表单项之间留有足够间距，避免误触

---

## 7. 网络错误处理

### 调研内容

确定网络中断时的错误处理策略（根据规格，不支持离线缓存）。

### 错误处理方案

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **简单提示** | 显示错误消息，要求用户重试 | 实现简单 | 用户体验一般 |
| **自动重试** | 网络错误时自动重试 2-3 次 | 提升成功率 | 可能延长响应时间 |
| **离线缓存** | 暂存数据到本地，网络恢复后提交 | 最佳用户体验 | 规格明确不支持 |

### 决策

**简单提示 + 表单数据保留**

### 理由

1. **符合规格**: 规格明确要求"网络中断时提示保存失败，用户需要重新提交"
2. **用户友好**: 虽然不缓存到服务器，但保留表单数据，避免用户重新填写
3. **实现简单**: 使用 Element Plus 的 Message 组件显示错误消息

### 实现方案

```typescript
// 提交验货记录
async function submitInspection() {
  try {
    await inspectionStore.submitInspection(formData)
    ElMessage.success('验货记录提交成功')
    // 清空表单
    resetForm()
  } catch (error) {
    if (error.message.includes('Network Error')) {
      ElMessage.error('网络连接失败，请检查网络后重试')
    } else {
      ElMessage.error(`提交失败: ${error.message}`)
    }
    // 保留表单数据，用户可以重新提交
  }
}
```

---

## 8. API 设计原则

### 调研内容

确定验货功能的 RESTful API 设计规范。

### API 设计原则

1. **RESTful 风格**: 使用标准 HTTP 方法（GET, POST, PUT, DELETE）
2. **资源命名**: 使用复数名词，如 `/api/inspections`
3. **状态码**: 正确使用 HTTP 状态码（200, 201, 400, 404, 500）
4. **响应格式**: 统一的 JSON 格式
5. **分页**: 列表接口支持分页（`page`, `per_page`）
6. **筛选**: 使用查询参数（`?device_name=2001&status=normal`）

### API 端点设计

详见 `contracts/inspection-api.yaml`（Phase 1 生成）

---

## 总结

### 关键技术决策

1. ✅ **数字键盘**: `type="text" + inputmode="numeric" + pattern="[0-9]*"`
2. ✅ **检查清单生成**: 组合模式（基础检查项 + 动态附件检查项）
3. ✅ **数据模型**: 主从表模式（InspectionRecord + InspectionCheckItem）
4. ✅ **租赁记录扩展**: 直接添加 `photo_transfer` 字段
5. ✅ **前端状态管理**: Pinia Store（全局状态） + 组件本地状态（局部状态）
6. ✅ **响应式设计**: 移动优先 + 自适应布局
7. ✅ **网络错误处理**: 简单提示 + 表单数据保留

### 未决问题

无 - 所有技术问题已调研完成。

### 下一步

进入 **Phase 1: Design & Contracts**，生成：
- `data-model.md`：数据模型详细设计
- `contracts/`：API 接口规范（OpenAPI）
- `quickstart.md`：开发快速入门指南

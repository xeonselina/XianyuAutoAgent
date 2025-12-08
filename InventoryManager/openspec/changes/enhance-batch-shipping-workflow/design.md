# Design Document: Enhanced Batch Shipping Workflow

## Context

当前系统已实现批量打印发货单功能,但后续的运单录入、API调用、发货通知仍需手动完成。本设计文档描述如何将批量打印升级为端到端的批量发货自动化工作流。

### Stakeholders
- **操作人员**: 使用扫码枪录入运单,减少手动输入
- **客户**: 通过闲鱼平台及时收到发货通知
- **系统维护者**: 需要配置外部API凭证和定时任务

### Constraints
- 必须兼容现有的批量打印功能
- 依赖顺丰和闲鱼外部API的可用性
- 扫码枪硬件必须支持USB HID模式(模拟键盘输入)
- 定时任务框架需要持久化,避免服务器重启丢失

## Goals / Non-Goals

### Goals
- 实现扫码录入运单号,替代手动输入
- 自动调用顺丰API下单和闲鱼API发货通知
- 提供预约发货功能,在指定时间批量执行API调用
- 清晰的发货进度追踪(未打印/已打印/已录入/已发货)

### Non-Goals
- 不实现多人协作扫码(单人操作场景)
- 不实现复杂的批次管理(Phase 1使用rental字段)
- 不实现运单撤销/修改(Phase 2功能)
- 不实现实时WebSocket推送(轮询或页面刷新即可)

## Decisions

### Decision 1: 扫码枪输入处理方式

**选择**: 监听键盘事件,使用防抖识别扫码结束

**理由**:
- 扫码枪USB HID模式模拟键盘输入,无需特殊驱动
- 使用防抖(200ms)检测扫码结束(扫码枪输入速度快)
- 通过正则区分租赁ID(纯数字)和顺丰面单(字母+数字)

**替代方案**:
- 使用串口读取: 复杂,需要特定扫码枪配置
- 使用USB库直接读取: 浏览器不支持

**实现细节**:
```javascript
let scanBuffer = ''
let scanTimeout = null

document.addEventListener('keydown', (e) => {
  clearTimeout(scanTimeout)

  if (e.key === 'Enter') {
    processScan(scanBuffer)
    scanBuffer = ''
  } else if (e.key.length === 1) {
    scanBuffer += e.key
    scanTimeout = setTimeout(() => {
      scanBuffer = ''
    }, 200)
  }
})

function processScan(value) {
  if (/^\d+$/.test(value)) {
    // Rental ID
    handleRentalScan(value)
  } else if (/^[A-Z0-9]{10,}$/i.test(value)) {
    // SF Waybill
    handleWaybillScan(value)
  }
}
```

### Decision 2: 发货单二维码生成方式

**选择**: 服务端生成QR码图片,嵌入HTML模板

**理由**:
- Python `qrcode` 库简单可靠
- 打印时无需依赖JavaScript执行
- 二维码内容为纯数字rental ID,易于解析

**替代方案**:
- 前端JS生成: 打印预览可能不稳定
- 使用条形码: QR码兼容性更好,可用手机扫描调试

**实现细节**:
```python
import qrcode
from io import BytesIO
import base64

def generate_qr_code_base64(rental_id: int) -> str:
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(str(rental_id))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format='PNG')
    img_str = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{img_str}"
```

### Decision 3: 定时发货任务实现

**选择**: APScheduler + 数据库字段 `scheduled_ship_time`

**理由**:
- APScheduler已在项目中使用(`scheduler_tasks.py`)
- 每5分钟轮询检查 `scheduled_ship_time <= now` 的记录
- 简单可靠,无需额外消息队列

**替代方案**:
- Celery Beat: 更强大但增加Redis/RabbitMQ依赖
- Cron + Flask CLI: 需要单独进程管理

**实现细节**:
```python
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime

def process_scheduled_shipments():
    """处理预约发货任务"""
    now = datetime.utcnow()
    rentals = Rental.query.filter(
        Rental.scheduled_ship_time <= now,
        Rental.status != 'shipped',
        Rental.sf_waybill_no.isnot(None)
    ).all()

    for rental in rentals:
        try:
            # 调用顺丰API
            sf_service.place_shipping_order(rental)

            # 调用闲鱼API
            if rental.xianyu_order_no:
                xianyu_service.ship_order(rental)

            # 更新状态
            rental.status = 'shipped'
            rental.ship_out_time = now
            db.session.commit()

            logger.info(f"成功发货 rental {rental.id}")
        except Exception as e:
            logger.error(f"发货失败 rental {rental.id}: {e}")
            db.session.rollback()

scheduler = BackgroundScheduler()
scheduler.add_job(process_scheduled_shipments, 'interval', minutes=5)
scheduler.start()
```

### Decision 4: 顺丰API鉴权方式

**选择**: OAuth2客户端凭证流 + MD5签名

**理由**:
- 按照 `docs/顺丰oauth2鉴权.docx` 规范实现
- 先获取access_token,再调用业务API
- 每个请求使用MD5签名验证

**实现细节**:
```python
class SFExpressOAuth2:
    def get_access_token(self) -> str:
        """获取访问令牌"""
        timestamp = int(time.time() * 1000)
        sign_str = f"{self.app_key}{timestamp}{self.app_secret}"
        sign = hashlib.md5(sign_str.encode()).hexdigest()

        response = requests.post(
            "https://sfapi.sf-express.com/oauth2/accessToken",
            json={
                "appKey": self.app_key,
                "timestamp": timestamp,
                "sign": sign
            }
        )
        return response.json()['data']['accessToken']
```

### Decision 5: 闲鱼API签名方式

**选择**: MD5签名(参数排序 + secret)

**理由**:
- 按照 `docs/闲鱼管家 api 文档.md` 规范
- 参数按key排序,拼接后加secret,MD5哈希

**实现细节**:
```python
def generate_sign(params: dict, secret: str) -> str:
    """生成闲鱼API签名"""
    sorted_params = sorted(params.items(), key=lambda x: x[0])
    sign_str = ''.join([f'{k}{v}' for k, v in sorted_params])
    sign_str += secret
    return hashlib.md5(sign_str.encode()).hexdigest()
```

### Decision 6: 语音提示实现

**选择**: Web Speech API (`window.speechSynthesis`)

**理由**:
- 浏览器原生支持,无需外部库
- 简单的中文语音提示足够
- 可配置开关(用户偏好)

**替代方案**:
- 音频文件播放: 需要录制音频,不灵活
- 第三方TTS API: 增加延迟和依赖

**实现细节**:
```javascript
function speak(text) {
  if (!window.speechSynthesis) return

  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'zh-CN'
  utterance.rate = 1.0
  window.speechSynthesis.speak(utterance)
}

// 使用
speak('请扫描顺丰面单')
```

## Data Model Changes

### Rental表新增字段

```python
class Rental(db.Model):
    # 现有字段...

    # 新增字段
    scheduled_ship_time = db.Column(
        db.DateTime,
        nullable=True,
        comment='预约发货时间'
    )
    sf_waybill_no = db.Column(
        db.String(50),
        nullable=True,
        comment='顺丰运单号(速运API返回)'
    )
```

**说明**:
- `scheduled_ship_time`: 用户设置的预约发货时间,定时任务检查此字段
- `sf_waybill_no`: 顺丰速运API返回的运单号,区别于 `ship_out_tracking_no`(手动录入的快递单号)

### 数据库迁移脚本

```python
# migrations/versions/xxxx_add_scheduled_shipping_fields.py

def upgrade():
    op.add_column('rentals', sa.Column('scheduled_ship_time', sa.DateTime(), nullable=True))
    op.add_column('rentals', sa.Column('sf_waybill_no', sa.String(50), nullable=True))

def downgrade():
    op.drop_column('rentals', 'sf_waybill_no')
    op.drop_column('rentals', 'scheduled_ship_time')
```

## API Design

### POST /api/shipping-batch/scan-rental

**Request**:
```json
{
  "rental_id": 123
}
```

**Response**:
```json
{
  "success": true,
  "data": {
    "rental_id": 123,
    "customer_name": "张三",
    "customer_phone": "13800138000",
    "destination": "广东省深圳市...",
    "device_name": "Insta360 X4",
    "accessories": ["云台手柄", "自拍杆"],
    "start_date": "2024-01-15",
    "end_date": "2024-01-20",
    "ship_out_time": null,
    "sf_waybill_no": null
  }
}
```

### POST /api/shipping-batch/record-waybill

**Request**:
```json
{
  "rental_id": 123,
  "waybill_no": "SF1234567890"
}
```

**Response**:
```json
{
  "success": true,
  "message": "运单号已录入"
}
```

### POST /api/shipping-batch/schedule

**Request**:
```json
{
  "rental_ids": [123, 124, 125],
  "scheduled_time": "2024-01-15T14:00:00Z"
}
```

**Response**:
```json
{
  "success": true,
  "data": {
    "scheduled_count": 3,
    "failed_rentals": []
  }
}
```

## Risks / Trade-offs

### Risk 1: 外部API失败率高

**风险**: 顺丰或闲鱼API不稳定,导致批量发货失败

**缓解措施**:
- 实现重试机制(最多3次,指数退避)
- 记录失败日志,提供手动重试界面
- 发送邮件/钉钉通知管理员

**Trade-off**: 增加复杂度,但提高可靠性

### Risk 2: 定时任务丢失

**风险**: 服务器重启导致scheduled任务未执行

**缓解措施**:
- APScheduler配置 `misfire_grace_time=300`(5分钟宽限)
- 轮询检查而非精确定时,容忍5分钟延迟
- 考虑Phase 2使用数据库持久化任务队列

**Trade-off**: 5分钟轮询频率,资源消耗可接受

### Risk 3: 扫码错误或重复扫码

**风险**: 误扫、重复扫码导致数据错误

**缓解措施**:
- 检查 `sf_waybill_no` 是否已存在,防止重复录入
- UI提示当前已录入状态
- Phase 2实现撤销/修改功能

**Trade-off**: Phase 1无撤销,依赖数据库手动修正

### Risk 4: 语音提示不工作

**风险**: 浏览器不支持或用户禁用语音

**缓解措施**:
- 提供视觉提示(弹框、toast)作为备选
- 检测 `window.speechSynthesis` 可用性
- 提供开关让用户禁用语音

**Trade-off**: 语音为辅助功能,非核心依赖

## Migration Plan

### Phase 1: 核心功能部署

1. **数据库迁移**: 在低峰期执行 `flask db upgrade`
2. **环境变量配置**: 添加顺丰和闲鱼API凭证到 `.env`
3. **前端部署**: 发布包含 `BatchShippingView` 的新版本
4. **后端部署**: 重启Flask应用,启动APScheduler
5. **验证**: 测试扫码、API调用、定时任务

### Phase 2: 监控和优化

1. **添加日志监控**: 集成日志聚合工具(如ELK)
2. **添加API失败告警**: 钉钉/邮件通知
3. **优化API性能**: 批量调用、异步处理

### Rollback Plan

1. **数据库回滚**: `flask db downgrade` 删除新增字段
2. **代码回滚**: 恢复到 `batch-print-shipping-orders` 版本
3. **数据完整性**: 新增字段为nullable,回滚不影响现有数据

## Open Questions

1. **顺丰API寄件方信息**: 使用固定配置还是支持多仓库?
   - **建议**: Phase 1使用环境变量配置单一寄件地址

2. **闲鱼订单号缺失**: 如果 `xianyu_order_no` 为空,是否跳过闲鱼API?
   - **建议**: 跳过闲鱼API,仅调用顺丰API,记录警告日志

3. **定时任务并发**: 多个rental同时到达scheduled_time,是否并发调用API?
   - **建议**: Phase 1串行处理,避免API速率限制;Phase 2考虑线程池

4. **扫码权限**: 是否需要限制只有特定角色才能扫码?
   - **建议**: Phase 1无权限控制,Phase 2添加操作员角色

5. **发货单打印状态**: 如何追踪发货单是否已打印?
   - **建议**: Phase 2添加 `print_time` 字段,访问 `BatchShippingOrderView` 时记录

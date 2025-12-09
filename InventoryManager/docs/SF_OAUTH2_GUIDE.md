# 顺丰 OAuth2.0 鉴权配置指南

## 概述

顺丰 SDK 现在支持两种鉴权方式：
1. **OAuth2.0** - 新版 API（推荐，默认启用）
2. **msgDigest** - 旧版 API（兼容性保留）

## 环境变量配置

在 `.env` 文件中配置以下参数：

```bash
# 顺丰 API 基础配置
SF_API_MODE=test              # API 模式: test(沙箱) 或 prod(生产)
SF_PARTNER_ID=your_dev_id     # OAuth2.0: 开发者 ID; msgDigest: 合作伙伴 ID
SF_CHECKWORD=your_dev_key     # OAuth2.0: 开发者密钥; msgDigest: 校验码

# 寄件人信息（可选，有默认值）
SF_SENDER_NAME=张女士
SF_SENDER_PHONE=13510224947
SF_SENDER_ADDRESS=广东省深圳市南山区西丽街道松坪村竹苑9栋4单元415
```

## OAuth2.0 vs msgDigest

### OAuth2.0 鉴权方式（默认）

**特点：**
- 新版 API，推荐使用
- 使用 Access Token 机制
- Token 有效期 2 小时，自动刷新
- API 地址：
  - 测试环境：`https://sfapi-sbox.sf-express.com/open/api`
  - 生产环境：`https://sfapi.sf-express.com/open/api`

**鉴权流程：**
1. 使用 `partnerID` 和 `secretKey` 获取 Access Token
2. 使用 Access Token 调用业务 API
3. Token 过期前自动刷新

**配置示例：**
```python
# 默认使用 OAuth2.0
sdk = SFExpressSDK(
    partner_id='your_dev_id',
    checkword='your_dev_key',
    test_mode=True,
    use_oauth=True  # 默认为 True
)
```

### msgDigest 鉴权方式（旧版）

**特点：**
- 旧版 API，兼容性保留
- 使用 MD5 + Base64 签名
- 每次请求都需要计算签名
- API 地址：
  - 测试环境：`https://sfapi-sbox.sf-express.com/std/service`
  - 生产环境：`https://sfapi.sf-express.com/std/service`

**配置示例：**
```python
# 使用旧版 msgDigest
sdk = SFExpressSDK(
    partner_id='your_partner_id',
    checkword='your_checkword',
    test_mode=True,
    use_oauth=False
)
```

## 测试 API 端点

### 1. 查看配置状态

```bash
GET /api/sf-test/status
```

**响应示例：**
```json
{
  "success": true,
  "data": {
    "test_mode": true,
    "use_oauth": true,
    "auth_method": "OAuth2.0",
    "api_url": "https://sfapi-sbox.sf-express.com/open/api",
    "partner_id_configured": true,
    "checkword_configured": true,
    "sender_info": {
      "name": "张女士",
      "phone": "13510224947",
      "address": "广东省深圳市南山区西丽街道松坪村竹苑9栋4单元415"
    }
  }
}
```

### 2. 使用租赁记录测试下单

```bash
POST /api/sf-test/order/<rental_id>
```

**响应示例：**
```json
{
  "success": true,
  "message": "下单成功",
  "data": {...},
  "test_mode": true,
  "auth_method": "OAuth2.0",
  "rental_info": {
    "id": 123,
    "customer_name": "测试客户",
    "customer_phone": "13800138000",
    "destination": "广东省深圳市福田区测试地址",
    "tracking_no": "SF1234567890"
  }
}
```

### 3. 使用模拟数据测试下单

```bash
POST /api/sf-test/mock-order
Content-Type: application/json

{
  "order_id": "TEST_ORDER_001",
  "waybill_no": "SF1234567890",
  "consignee_info": {
    "name": "测试收件人",
    "mobile": "13800138000",
    "address": "广东省深圳市福田区测试地址"
  },
  "cargo_details": [
    {
      "name": "测试商品",
      "count": 1
    }
  ]
}
```

## 常见问题

### Q1: 如何切换鉴权方式？

修改 `sf_sdk_wrapper.py` 中的 `use_oauth` 参数，或在创建 SDK 实例时指定：

```python
# 使用 OAuth2.0
sdk = SFExpressSDK(partner_id, checkword, test_mode=True, use_oauth=True)

# 使用 msgDigest
sdk = SFExpressSDK(partner_id, checkword, test_mode=True, use_oauth=False)
```

### Q2: Access Token 如何管理？

SDK 自动管理 Access Token：
- 首次调用时自动获取
- Token 缓存在内存中
- 过期前 5 分钟自动刷新
- 无需手动处理

### Q3: 如何在沙箱环境测试？

在 `.env` 中设置：
```bash
SF_API_MODE=test
```

或在代码中指定：
```python
sdk = SFExpressSDK(partner_id, checkword, test_mode=True)
```

### Q4: OAuth2.0 和 msgDigest 的 Partner ID 不同吗？

是的：
- **OAuth2.0**: 使用开发者 ID (`dev_id`) 和开发者密钥 (`dev_key`)
- **msgDigest**: 使用合作伙伴 ID (`partner_id`) 和校验码 (`checkword`)

需要在顺丰开放平台分别申请。

## 日志说明

SDK 会输出详细日志：

```
INFO - 获取顺丰 OAuth2.0 Access Token
INFO - OAuth2.0 Token 响应状态: 200
INFO - Access Token 获取成功，有效期: 7200s
INFO - 调用顺丰API (OAuth2.0): EXP_RECE_CREATE_ORDER
DEBUG - 请求数据: {...}
INFO - HTTP状态码: 200
DEBUG - 响应内容: {...}
```

## 代码示例

### 完整下单流程

```python
from app.services.shipping.sf_express_service import get_sf_express_service

# 获取服务实例（自动使用 OAuth2.0）
sf_service = get_sf_express_service()

# 下单
result = sf_service.place_shipping_order(rental)

if result.get('success'):
    print(f"下单成功: {result.get('data')}")
else:
    print(f"下单失败: {result.get('message')}")
```

### 直接使用 SDK

```python
from app.utils.sf.sf_sdk_wrapper import SFExpressSDK

# 创建 SDK 实例
sdk = SFExpressSDK(
    partner_id='your_dev_id',
    checkword='your_dev_key',
    test_mode=True,
    use_oauth=True
)

# 下单
order_data = {
    'orderId': 'ORDER_001',
    'waybillNo': 'SF1234567890',
    'consigneeInfo': {
        'name': '张三',
        'mobile': '13800138000',
        'address': '广东省深圳市福田区测试地址'
    },
    # ... 其他订单信息
}

result = sdk.create_order(order_data)
```

## 参考文档

- [顺丰开放平台](https://open.sf-express.com/)
- [顺丰 OAuth2.0 文档](https://open.sf-express.com/developSupport/734349?activeIndex=0)
- [速运下单接口文档](https://open.sf-express.com/developSupport/734351?activeIndex=0)

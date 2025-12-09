# 顺丰 OAuth2.0 配置教程

## 1. 获取顺丰开发者凭证

### 1.1 注册顺丰开放平台账号

1. 访问 [顺丰开放平台](https://open.sf-express.com/)
2. 注册/登录账号
3. 完成企业认证

### 1.2 创建应用

1. 进入"应用管理"页面
2. 点击"创建应用"
3. 填写应用信息：
   - 应用名称：自定义（如：库存管理系统）
   - 应用类型：服务端应用
   - 接入方式：OAuth2.0
4. 提交审核

### 1.3 获取凭证

应用审核通过后，你会获得：
- **开发者ID (dev_id)**: 用于 `SF_PARTNER_ID`
- **开发者密钥 (dev_key)**: 用于 `SF_CHECKWORD`

## 2. 配置环境变量

在 `.env` 文件中添加以下配置：

```bash
# 顺丰 OAuth2.0 配置
SF_API_MODE=test                    # test=沙箱环境, prod=生产环境
SF_PARTNER_ID=your_dev_id_here      # 替换为你的开发者ID
SF_CHECKWORD=your_dev_key_here      # 替换为你的开发者密钥

# 寄件人信息（必填）
SF_SENDER_NAME=张女士
SF_SENDER_PHONE=13510224947
SF_SENDER_ADDRESS=广东省深圳市南山区西丽街道松坪村竹苑9栋4单元415
```

## 3. 测试配置

### 3.1 查看配置状态

```bash
curl http://localhost:5000/api/sf-test/status | jq
```

**预期响应：**
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

### 3.2 测试模拟下单

```bash
curl -X POST http://localhost:5000/api/sf-test/mock-order \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "TEST_ORDER_001",
    "waybill_no": "SF1234567890",
    "consignee_info": {
      "name": "测试收件人",
      "mobile": "13800138000",
      "address": "广东省深圳市福田区测试地址123号"
    },
    "cargo_details": [
      {
        "name": "测试商品",
        "count": 1
      }
    ]
  }' | jq
```

## 4. 常见错误及解决方案

### 4.1 `auth_error:partner_info_is_invalid`

**原因：** 开发者ID或密钥错误

**解决：**
1. 检查 `.env` 中的 `SF_PARTNER_ID` 和 `SF_CHECKWORD` 是否正确
2. 确认应用已通过审核
3. 确认使用的是 OAuth2.0 凭证（不是旧版的 partner_id）

### 4.2 `网络请求异常`

**原因：** 无法连接到顺丰服务器

**解决：**
1. 检查网络连接
2. 确认防火墙没有阻止访问
3. 检查 API 地址是否正确

### 4.3 `JSON解析异常`

**原因：** 顺丰服务器返回的不是有效的 JSON

**解决：**
1. 检查 API 地址是否正确
2. 查看日志中的响应状态码
3. 联系顺丰技术支持

## 5. 沙箱环境 vs 生产环境

### 5.1 沙箱环境（测试）

- 配置：`SF_API_MODE=test`
- API 地址：`https://sfapi-sbox.sf-express.com`
- 特点：
  - 不会真实下单
  - 不会产生费用
  - 用于开发和测试
  - 需要使用测试凭证

### 5.2 生产环境

- 配置：`SF_API_MODE=prod`
- API 地址：`https://sfapi.sf-express.com`
- 特点：
  - 真实下单
  - 会产生实际费用
  - 需要正式的企业认证
  - 需要与顺丰签订合作协议

## 6. 切换到生产环境

当测试完成后，切换到生产环境：

1. 在顺丰开放平台申请生产环境权限
2. 获取生产环境凭证
3. 修改 `.env`：
   ```bash
   SF_API_MODE=prod
   SF_PARTNER_ID=your_prod_dev_id
   SF_CHECKWORD=your_prod_dev_key
   ```
4. 重启应用
5. 测试一笔真实订单

## 7. 参考文档

- [顺丰开放平台](https://open.sf-express.com/)
- [OAuth2.0 接入文档](https://open.sf-express.com/developSupport/734349)
- [速运下单接口](https://open.sf-express.com/developSupport/734351)
- [API 错误码](https://open.sf-express.com/developSupport/734354)

## 8. 技术支持

如遇到问题，可通过以下方式获取帮助：
- 顺丰开放平台工单系统
- 技术支持邮箱
- 开发者社区

---

**重要提示：**
- 请妥善保管开发者密钥，不要泄露给他人
- 不要将凭证提交到代码仓库
- 定期检查 API 调用情况，避免异常消费

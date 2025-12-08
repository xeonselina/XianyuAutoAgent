# 查询订单详情

## OpenAPI Specification

```yaml
openapi: 3.0.1
info:
  title: ''
  description: ''
  version: 1.0.0
paths:
  /api/open/order/detail:
    post:
      summary: 查询订单详情
      deprecated: false
      description: ''
      operationId: GetOpenOrderDetail
      tags:
        - 订单
        - order
      parameters:
        - name: appid
          in: query
          description: 开放平台的AppKey
          required: true
          example: '{{appid}}'
          schema:
            type: integer
            default: '{{appid}}'
        - name: timestamp
          in: query
          description: 当前时间戳（单位秒，5分钟内有效）
          required: false
          example: '{{timestamp}}'
          schema:
            type: integer
        - name: seller_id
          in: query
          description: 商家ID（仅商务对接传入，自研/第三方ERP对接忽略即可）
          example: '{{seller_id}}'
          schema:
            type: integer
        - name: sign
          in: query
          description: 签名MD5值（参考签名说明）
          required: true
          example: '{{sign}}'
          schema:
            type: string
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/GetOpenOrderDetailReq'
      responses:
        '200':
          description: A successful response.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/GetOpenOrderDetailResp'
          headers: {}
          x-apifox-name: 成功
        x-200:失败:
          description: ''
          content:
            application/json:
              schema:
                type: object
                properties:
                  code:
                    type: integer
                    format: int32
                    examples:
                      - 500
                    additionalProperties: false
                  msg:
                    type: string
                    examples:
                      - Internal Server Error
                    additionalProperties: false
                required:
                  - code
                  - msg
                x-apifox-orders:
                  - code
                  - msg
                x-apifox-ignore-properties: []
          headers: {}
          x-apifox-name: 失败
      security: []
      x-apifox-folder: 订单
      x-apifox-status: released
      x-run-in-apifox: https://app.apifox.com/web/project/2973339/apis/api-93586385-run
components:
  schemas:
    GetOpenOrderDetailReq:
      type: object
      properties:
        order_no:
          type: string
          description: ' 闲鱼订单号，示例：2226688164543566229'
      title: GetOpenOrderDetailReq
      required:
        - order_no
      x-apifox-orders:
        - order_no
      x-apifox-ignore-properties: []
      x-apifox-folder: ''
    GetOpenOrderDetailResp:
      type: object
      properties:
        order_no:
          type: string
          description: ' 闲鱼订单号'
        order_status:
          type: integer
          format: int32
          description: ' 订单状态'
        order_type:
          type: integer
          format: int32
          description: ' 订单类型'
        order_time:
          type: integer
          format: int64
          description: ' 买家下单时间'
        total_amount:
          type: integer
          format: int64
          description: ' 订单下单金额（分）'
        pay_amount:
          type: integer
          format: int64
          description: ' 订单实付金额（分）'
        pay_no:
          type: string
          description: ' 支付宝交易号'
        pay_time:
          type: integer
          format: int64
          description: ' 订单支付时间'
        refund_status:
          type: integer
          format: int32
          description: ' 订单退款状态'
        refund_amount:
          type: integer
          format: int64
          examples:
            - '1'
          description: 订单退款金额（分）
        refund_time:
          type: integer
          format: int64
          description: ' 订单退款时间，仅退款成功有值'
        receiver_mobile:
          type: string
          description: ' 收货人号码，仅待发货状态返回'
        receiver_name:
          type: string
          description: ' 收货人姓名，仅待发货状态返回'
        prov_name:
          type: string
          description: ' 收货省份，仅待发货状态返回'
        city_name:
          type: string
          description: ' 收货城市，仅待发货状态返回'
        area_name:
          type: string
          description: ' 收货地区，仅待发货状态返回'
        town_name:
          type: string
          description: ' 收货街道，仅待发货状态返回'
        address:
          type: string
          description: ' 收货详情地址，仅待发货状态返回'
        waybill_no:
          type: string
          description: ' 快递单号'
        express_code:
          type: string
          description: ' 快递公司代码'
        express_name:
          type: string
          description: ' 快递公司名称'
        express_fee:
          type: integer
          format: int32
          description: ' 运费（分）'
        consign_type:
          type: integer
          format: int32
          description: ' 订单发货类型，枚举值：; 1 : 物流发货; 2 : 虚拟发货'
        consign_time:
          type: integer
          format: int64
          description: ' 订单发货时间'
        confirm_time:
          type: integer
          format: int64
          description: ' 订单成交时间'
        cancel_reason:
          type: string
          description: ' 订单取消原因'
        cancel_time:
          type: integer
          format: int64
          description: ' 订单取消时间'
        create_time:
          type: integer
          format: int64
          description: ' 订单创建时间'
        update_time:
          type: integer
          format: int64
          description: ' 订单更新时间'
        buyer_eid:
          type: string
          description: ' 买家标识，闲鱼体系内唯一的用户标识'
        buyer_nick:
          type: string
          description: ' 买家昵称'
        seller_eid:
          type: string
          description: ' 卖家标识，闲鱼体系内唯一的用户标识'
        seller_name:
          type: string
          description: ' 卖家会员名'
        seller_remark:
          type: string
          description: ' 卖家备注'
        idle_biz_type:
          type: integer
          format: int32
          description: ' 子业务类型'
        pin_group_status:
          type: integer
          format: int32
          description: ' 拼团状态'
        goods:
          $ref: '#/components/schemas/Goods'
        xyb_seller_amount:
          type: integer
          format: int64
          description: ' 卖家应收闲鱼币'
      title: GetOpenOrderDetailResp
      required:
        - order_no
        - order_status
        - order_type
        - order_time
        - total_amount
        - pay_amount
        - pay_no
        - pay_time
        - refund_status
        - refund_amount
        - refund_time
        - receiver_mobile
        - receiver_name
        - prov_name
        - city_name
        - area_name
        - town_name
        - address
        - waybill_no
        - express_code
        - express_name
        - express_fee
        - consign_type
        - consign_time
        - confirm_time
        - cancel_reason
        - cancel_time
        - create_time
        - update_time
        - buyer_eid
        - buyer_nick
        - seller_eid
        - seller_name
        - seller_remark
        - idle_biz_type
        - pin_group_status
        - goods
        - xyb_seller_amount
      x-apifox-orders:
        - order_no
        - order_status
        - order_type
        - order_time
        - total_amount
        - pay_amount
        - pay_no
        - pay_time
        - refund_status
        - refund_amount
        - refund_time
        - receiver_mobile
        - receiver_name
        - prov_name
        - city_name
        - area_name
        - town_name
        - address
        - waybill_no
        - express_code
        - express_name
        - express_fee
        - consign_type
        - consign_time
        - confirm_time
        - cancel_reason
        - cancel_time
        - create_time
        - update_time
        - buyer_eid
        - buyer_nick
        - seller_eid
        - seller_name
        - seller_remark
        - idle_biz_type
        - pin_group_status
        - goods
        - xyb_seller_amount
      x-apifox-ignore-properties: []
      x-apifox-folder: ''
    Goods:
      type: object
      properties:
        quantity:
          type: integer
          format: int32
          description: ' 购买数量'
        price:
          type: integer
          format: int64
          description: ' 商品单价（分）'
        product_id:
          type: integer
          format: int64
          description: ' 管家商品ID'
        item_id:
          type: integer
          format: int64
          description: ' 闲鱼商品ID'
        outer_id:
          type: string
          description: ' 商家编码'
        sku_id:
          type: integer
          format: int64
          description: ' 管家SKUID'
        sku_outer_id:
          type: string
          description: ' 商家SKU编码'
        sku_text:
          type: string
          description: ' SKU规格'
        title:
          type: string
          description: ' 商品标题'
        images:
          type: array
          items:
            type: string
          description: ' 商品主图'
        service_support:
          type: string
          description: ' 商品服务项'
      title: Goods
      required:
        - quantity
        - price
        - product_id
        - item_id
        - outer_id
        - sku_id
        - sku_outer_id
        - sku_text
        - title
        - images
        - service_support
      x-apifox-orders:
        - quantity
        - price
        - product_id
        - item_id
        - outer_id
        - sku_id
        - sku_outer_id
        - sku_text
        - title
        - images
        - service_support
      x-apifox-ignore-properties: []
      x-apifox-folder: ''
  securitySchemes:
    apiKey:
      type: apikey
      description: Enter JWT Bearer token **_only_**
      name: Authorization
      in: header
servers:
  - url: https://open.goofish.pro
    description: 新版正式环境
security: []

```

# 订单物流发货

## OpenAPI Specification

```yaml
openapi: 3.0.1
info:
  title: ''
  description: ''
  version: 1.0.0
paths:
  /api/open/order/ship:
    post:
      summary: 订单物流发货
      deprecated: false
      description: >-
        ### 新版接口变更说明


        新增字段：

        express_name


        注意事项：

        1：该接口中的信息需要按实填入，否则将可能导致发货失败或无法在闲鱼中查看物流信息；

        2：寄件方信息可通过以下三种方式传入；


        * 组合1：`ship_name` `ship_mobile` `ship_district_id` `ship_address`；

        * 组合2：`ship_name` `ship_mobile` `ship_prov_name` `ship_city_name`
        `ship_area_name` `ship_address`；

        * 组合3：如以上参数均不传入，则需要用户在闲管家后台填写默认发货地址；


        以上条件均不满足则发货信息为空，将可能存在发货失败等情况；
      tags:
        - 订单
      parameters:
        - name: appid
          in: query
          description: 开放平台的AppKey
          required: true
          example: '{{appid}}'
          schema:
            type: integer
            default: '{{appid}}'
        - name: timestamp
          in: query
          description: 当前时间戳（单位秒，5分钟内有效）
          required: false
          example: '{{timestamp}}'
          schema:
            type: integer
        - name: seller_id
          in: query
          description: 商家ID（仅商务对接传入，自研/第三方ERP对接忽略即可）
          example: '{{seller_id}}'
          schema:
            type: integer
        - name: sign
          in: query
          description: 签名MD5值（参考签名说明）
          required: true
          example: '{{sign}}'
          schema:
            type: string
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                order_no:
                  type: string
                  title: 闲鱼订单号
                  pattern: /^\d{19,}$/
                  examples:
                    - '2226688164543566229'
                ship_name:
                  type: string
                  title: 寄件方姓名
                  examples:
                    - 张三
                ship_mobile:
                  type: string
                  title: 寄件方号码
                  pattern: /^1([3456789]\d{9})$/
                  examples:
                    - '13800138000'
                ship_district_id:
                  type: integer
                  title: 寄件方所在地区ID
                  description: 如果没有传入该参数，则必传省市区
                  format: int32
                  examples:
                    - 440305
                ship_prov_name:
                  type: string
                  title: 寄件方所在省份
                  description: 如果没有传入ship_district_id，则必传该参数
                  examples:
                    - 广东省
                ship_city_name:
                  type: string
                  title: 寄件方所在城市
                  description: 如果没有传入ship_district_id，则必传该参数
                  examples:
                    - 深圳市
                ship_area_name:
                  type: string
                  title: 寄件方所在地区
                  description: 如果没有传入ship_district_id，则必传该参数
                  examples:
                    - 南山区
                ship_address:
                  type: string
                  title: 寄件方详细地址
                  examples:
                    - 侨香路某某大厦A栋301室
                waybill_no:
                  type: string
                  title: 快递单号
                  pattern: /^\w{10,}$/
                  examples:
                    - SF428948923411
                express_code:
                  type: string
                  title: 快递公司代码
                  examples:
                    - shunfeng
                  description: 可通过快递公司列表接口查询
                express_name:
                  type: string
                  title: 快递公司名称
                  examples:
                    - 顺丰速运
                  description: 注意：当 express_code 传入 other 时，请传入实际快递公司名称
              required:
                - order_no
                - waybill_no
                - express_code
                - express_name
              x-apifox-orders:
                - order_no
                - ship_name
                - ship_mobile
                - ship_district_id
                - ship_prov_name
                - ship_city_name
                - ship_area_name
                - ship_address
                - waybill_no
                - express_code
                - express_name
            example:
              order_no: '1339920336328048683'
              ship_name: 张三
              ship_mobile: '13800138000'
              ship_district_id: 440305
              ship_prov_name: 广东省
              ship_city_name: 深圳市
              ship_area_name: 南山区
              ship_address: 侨香路西丽街道丰泽园仓储中心
              waybill_no: '25051016899982'
              express_name: 其他
              express_code: qita
      responses:
        '200':
          description: ''
          content:
            application/json:
              schema:
                type: object
                properties:
                  code:
                    type: integer
                    format: int32
                    const: '0'
                  msg:
                    type: string
                    const: ok
                  data:
                    type: object
                    properties: {}
                    x-apifox-orders: []
                required:
                  - code
                  - msg
                x-apifox-orders:
                  - code
                  - msg
                  - data
              examples:
                '1':
                  summary: 成功示例
                  value:
                    code: 0
                    msg: ok
                    data: {}
                '2':
                  summary: 异常示例
                  value:
                    code: 100004
                    msg: 请求参数错误, field "express_name" is not set
          headers: {}
          x-apifox-name: 成功
        x-200:失败:
          description: ''
          content:
            application/json:
              schema:
                type: object
                properties:
                  msg:
                    type: string
                    examples:
                      - Internal Server Error
                    additionalProperties: false
                  code:
                    type: integer
                    format: int32
                    examples:
                      - 500
                    additionalProperties: false
                required:
                  - code
                  - msg
                x-apifox-orders:
                  - code
                  - msg
          headers: {}
          x-apifox-name: 失败
      security: []
      x-apifox-folder: 订单
      x-apifox-status: released
      x-run-in-apifox: https://app.apifox.com/web/project/2973339/apis/api-93586386-run
components:
  schemas: {}
  securitySchemes:
    apiKey:
      type: apikey
      description: Enter JWT Bearer token **_only_**
      name: Authorization
      in: header
servers:
  - url: https://open.goofish.pro
    description: 新版正式环境
security: []

```
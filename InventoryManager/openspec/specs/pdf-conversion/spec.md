# 顺丰 PDF 面单转热敏图像

## Purpose

描述当前 `PDFConversionService` 的纯转换管线，供顺丰面单打印使用。它处理内存中的 PDF 字节与 PIL 图像；转换失败作为逐单打印失败上报。

## Requirements

### Requirement: PDF 按页转为 PIL 图像

`convert_pdf_to_images(pdf_data,dpi)` MUST 用 `pdf2image.convert_from_bytes(pdf_data,dpi=target_dpi,fmt='PNG')` 返回按原页顺序排列的 PIL 图像列表。构造实例默认 DPI 为 203，显式参数可覆盖；代码未限制为 203／300 两个枚举值。转换异常统一抛 `PDFConversionError('PDF转换失败')`，不暴露底层异常信息。

#### Scenario: 两页面单
- **WHEN** 输入有效两页 PDF 且未传 DPI
- **THEN** 以 203 DPI 转换并得到两张图，页序保持不变

### Requirement: 图像优化采用固定灰度曲线与抖动

每页图像 MUST 先转灰度 `L`；灰度像素小于 128 时乘 0.7，大于等于 128 时按 `min(255,128+(x-128)×1.3)` 增强对比度，然后以 Floyd–Steinberg 抖动转 1-bit 模式。若增强过程抛异常，服务尝试直接 `image.convert('1')`。复刻需保持最终黑白热敏图像顺序及尺寸。

#### Scenario: 中间灰度输入
- **WHEN** PDF 某像素灰度为 100、另一像素为 200
- **THEN** 抖动前分别先经上述曲线向更暗／更亮方向变换

### Requirement: 每页编码成无前缀的 PNG base64

`image_to_base64` MUST 把 PIL 图像写入内存 `BytesIO` 的 PNG 格式，再返回 UTF-8 base64 文本，不加 `data:image/png;base64,` 前缀。编码异常抛 `PDFConversionError('图像base64编码失败')`。`convert_pdf_to_base64_images` 串联 PDF 转页、逐页优化和编码，返回同页数的字符串列表；非自定义异常转成 `PDFConversionError('PDF转base64流程失败')`。

#### Scenario: 一页转换后打印
- **WHEN** 输入一页顺丰 PDF
- **THEN** 打印管线拿到一个可还原为 PNG 的 base64 字符串并发送一次快麦打印请求

### Requirement: 空页与失败由上层打印服务解释

本服务不创建持久化临时文件，也不提供 PDF 下载重试；顺丰 PDF 下载在另一服务中执行。若转换结果为空列表，上层 `WaybillPrintService` MUST 返回“PDF转换结果为空”；若抛 `PDFConversionError`，上层 MUST 返回“面单处理失败”、`EXTERNAL_SERVICE_ERROR`。

#### Scenario: 无可打印页
- **WHEN** 转换调用得到空图像列表
- **THEN** 该租赁面单打印失败，不向快麦发送空任务

## 代码依据

`app/services/shipping/pdf_conversion_service.py`、`app/services/shipping/waybill_print_service.py`。旧归档规格中的“临时文件清理”和“只支持两种 DPI”不是当前代码约束。

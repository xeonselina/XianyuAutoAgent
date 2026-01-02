# 路由合约规范: User-Agent 设备检测

**功能**: 001-useragent-detection
**版本**: 1.0.0
**日期**: 2026-01-01

---

## 概述

本文档定义了基于 user-agent 检测的路由行为合约。所有路由端点必须遵循此规范以确保一致的用户体验。

---

## 1. 统一入口路由

### 端点: `/` 和 `/app/`

**用途**: 主入口路由,根据设备类型自动提供相应的前端

#### 请求

```http
GET / HTTP/1.1
Host: example.com
User-Agent: <浏览器user-agent字符串>
```

**支持的方法**: `GET`

**必需头部**:
- `User-Agent` (可选,但强烈推荐)

**可选头部**:
- `Sec-CH-UA-Mobile`: 新标准的客户端提示 (`?0` 桌面, `?1` 移动)
- `Accept-Language`: 语言偏好
- `Cookie`: Session 和偏好设置

#### 响应

**成功响应** (200 OK):

```http
HTTP/1.1 200 OK
Content-Type: text/html; charset=utf-8
Cache-Control: no-cache
Vary: User-Agent
Content-Length: <length>

<!DOCTYPE html>
<html>
...
</html>
```

**响应头部**:
- `Content-Type`: `text/html; charset=utf-8`
- `Cache-Control`: `no-cache` (避免缓存导致错误版本)
- `Vary`: `User-Agent` (告知缓存服务器 UA 影响响应)
- `X-Device-Type` (可选): `mobile` 或 `desktop` (调试用)

**错误响应** (500 Internal Server Error):

```http
HTTP/1.1 500 Internal Server Error
Content-Type: application/json

{
  "error": "Internal server error",
  "message": "Failed to detect device type"
}
```

#### 设备检测逻辑

```
IF User-Agent 头存在:
    解析 User-Agent
    IF 识别为移动设备 OR 平板设备:
        返回: mobile-dist/index.html
    ELSE IF 识别为桌面设备:
        返回: vue-dist/index.html
    ELSE (无法识别):
        返回: vue-dist/index.html (默认桌面版)
ELSE (User-Agent 头缺失):
    返回: vue-dist/index.html (默认桌面版)
```

#### 示例

**请求 (移动设备)**:
```http
GET / HTTP/1.1
Host: example.com
User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1
```

**响应**:
- Status: 200 OK
- Content: `mobile-dist/index.html`
- Header: `X-Device-Type: mobile`

**请求 (桌面设备)**:
```http
GET / HTTP/1.1
Host: example.com
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36
```

**响应**:
- Status: 200 OK
- Content: `vue-dist/index.html`
- Header: `X-Device-Type: desktop`

---

## 2. 静态资源路由

### 端点: `/assets/*`

**用途**: 提供前端静态资源 (JS, CSS, 图片等)

#### 请求

```http
GET /assets/<filename> HTTP/1.1
Host: example.com
User-Agent: <浏览器user-agent字符串>
```

**支持的方法**: `GET`

**路径参数**:
- `<filename>`: 资源文件名 (包含子路径)

#### 响应

**成功响应** (200 OK):

```http
HTTP/1.1 200 OK
Content-Type: <根据文件类型>
Cache-Control: public, max-age=31536000, immutable
ETag: "<hash>"
Content-Length: <length>

<文件内容>
```

**响应头部**:
- `Content-Type`: 根据文件扩展名自动设置
  - `.js`: `application/javascript`
  - `.css`: `text/css`
  - `.png`: `image/png`
  - `.jpg`: `image/jpeg`
  - `.svg`: `image/svg+xml`
  - `.woff2`: `font/woff2`
- `Cache-Control`: `public, max-age=31536000, immutable` (长期缓存)
- `ETag`: 文件内容哈希 (用于验证)

**错误响应** (404 Not Found):

```http
HTTP/1.1 404 Not Found
Content-Type: application/json

{
  "error": "File not found",
  "path": "/assets/<filename>"
}
```

#### 设备检测逻辑

```
IF User-Agent 指示移动设备:
    尝试从 mobile-dist/assets/ 提供文件
    IF 文件不存在:
        返回 404
ELSE (桌面设备 OR 无法识别):
    尝试从 vue-dist/assets/ 提供文件
    IF 文件不存在:
        返回 404
```

**注意**: 由于使用哈希文件名,移动和桌面版本的资源文件名不会冲突。

---

## 3. 兼容路由 (可选)

### 端点: `/vue/` 和 `/vue/*`

**用途**: 向后兼容,保留旧桌面版 URL

#### 请求

```http
GET /vue/ HTTP/1.1
Host: example.com
```

**支持的方法**: `GET`

#### 响应

**选项 A: 重定向到新 URL** (推荐):

```http
HTTP/1.1 302 Found
Location: /
Cache-Control: no-cache
```

**选项 B: 继续提供桌面版** (简单):

```http
HTTP/1.1 200 OK
Content-Type: text/html; charset=utf-8
X-Legacy-URL: true
Content-Length: <length>

<!DOCTYPE html>
...桌面版...
</html>
```

**选项 C: 显示废弃警告**:

```http
HTTP/1.1 200 OK
Content-Type: text/html; charset=utf-8
X-Deprecated: true
Content-Length: <length>

<!DOCTYPE html>
<html>
<head>
    <title>URL 已废弃</title>
</head>
<body>
    <h1>此 URL 已废弃</h1>
    <p>请使用新的统一 URL: <a href="/">example.com/</a></p>
    <p>自动跳转中...</p>
    <script>
        setTimeout(() => window.location.href = '/', 3000);
    </script>
</body>
</html>
```

### 端点: `/mobile/` 和 `/mobile/*`

**用途**: 向后兼容,保留旧移动版 URL

行为与 `/vue/` 类似,但目标是移动版前端。

---

## 4. API 端点

### 端点: `/api/device-info`

**用途**: 返回当前请求的设备检测信息 (调试和前端验证用)

#### 请求

```http
GET /api/device-info HTTP/1.1
Host: example.com
User-Agent: <浏览器user-agent字符串>
```

**支持的方法**: `GET`

#### 响应

**成功响应** (200 OK):

```http
HTTP/1.1 200 OK
Content-Type: application/json
Cache-Control: no-cache

{
  "type": "mobile",
  "device": "iPhone",
  "os": "iOS",
  "os_version": "16.6",
  "browser": "Mobile Safari",
  "browser_version": "16.6",
  "is_mobile": true,
  "is_tablet": false,
  "is_pc": false,
  "is_webview": false,
  "webview_app": null,
  "user_agent": "Mozilla/5.0 (iPhone; ..."
}
```

**响应字段说明**:

| 字段 | 类型 | 描述 | 可能值 |
|------|------|------|--------|
| `type` | string | 设备类型 | `"mobile"`, `"desktop"` |
| `device` | string | 设备系列 | `"iPhone"`, `"iPad"`, `"Generic"`, `"Other"` |
| `os` | string | 操作系统 | `"iOS"`, `"Android"`, `"Windows"`, `"macOS"`, `"Linux"` |
| `os_version` | string | OS 版本 | `"16.6"`, `"Unknown"` |
| `browser` | string | 浏览器名称 | `"Mobile Safari"`, `"Chrome"`, `"Firefox"` |
| `browser_version` | string | 浏览器版本 | `"119.0"`, `"Unknown"` |
| `is_mobile` | boolean | 是否为移动设备 | `true`, `false` |
| `is_tablet` | boolean | 是否为平板 | `true`, `false` |
| `is_pc` | boolean | 是否为桌面 | `true`, `false` |
| `is_webview` | boolean | 是否为 WebView | `true`, `false` |
| `webview_app` | string\|null | WebView 应用名 | `"wechat"`, `"facebook"`, `null` |
| `user_agent` | string | 原始 UA 字符串 | 完整 user-agent |

---

## 5. 错误处理

### 5.1 设备检测失败

**场景**: user-agent 解析库抛出异常

**行为**:
- 日志记录错误
- 默认返回桌面版
- 返回 200 OK (不中断用户体验)

### 5.2 静态文件缺失

**场景**: 请求的静态资源不存在

**行为**:
- 返回 404 Not Found
- 响应体包含错误信息 (JSON 或 HTML)

### 5.3 内部服务器错误

**场景**: 后端代码崩溃或无法恢复的错误

**行为**:
- 返回 500 Internal Server Error
- 响应体包含通用错误信息 (不暴露内部细节)
- 日志记录完整错误堆栈

---

## 6. 缓存策略

### 6.1 HTML 文件

**策略**: 不缓存

```http
Cache-Control: no-cache
Vary: User-Agent
```

**原因**:
- 确保设备切换时获取正确版本
- User-Agent 影响响应内容

### 6.2 静态资源 (JS/CSS/图片)

**策略**: 长期缓存

```http
Cache-Control: public, max-age=31536000, immutable
ETag: "<hash>"
```

**原因**:
- 文件名包含内容哈希,更新时自动失效
- 减少带宽和加载时间

### 6.3 API 响应

**策略**: 不缓存

```http
Cache-Control: no-cache
```

**原因**:
- 设备信息可能动态变化
- 用于调试和验证,不应缓存

---

## 7. 安全考虑

### 7.1 User-Agent 伪造

**风险**: 用户或工具可能伪造 user-agent

**缓解**:
- 不依赖 UA 进行安全决策
- 仅用于 UI 版本选择
- 允许用户手动切换 (如实施)

### 7.2 路径遍历攻击

**风险**: 恶意请求如 `/assets/../../../etc/passwd`

**缓解**:
- 使用 Flask `send_from_directory()` (内置保护)
- 验证文件路径在允许目录内
- 拒绝包含 `..` 的路径

### 7.3 XSS 攻击

**风险**: 用户提供的数据注入到响应中

**缓解**:
- 所有 API 响应使用 JSON (自动转义)
- HTML 响应使用静态文件 (无动态内容)
- 设置 `Content-Type` 头防止 MIME 嗅探

---

## 8. 性能要求

### 8.1 响应时间

| 端点 | 要求 | 测量方式 |
|------|------|---------|
| `/` (HTML) | < 100ms (p95) | 服务器处理时间 |
| `/assets/*` | < 50ms (p95) | 服务器处理时间 |
| `/api/device-info` | < 50ms (p95) | API 响应时间 |

### 8.2 吞吐量

| 指标 | 要求 |
|------|------|
| 并发请求 | > 100 req/s |
| 设备检测 | > 1000 detections/s |

### 8.3 资源使用

| 资源 | 限制 |
|------|------|
| CPU | < 50% (峰值) |
| 内存 | < 512MB (稳定运行) |
| 磁盘 I/O | < 10MB/s |

---

## 9. 测试用例

### 9.1 功能测试

```gherkin
Feature: User-Agent 设备检测

  Scenario: iPhone 用户访问
    Given 用户使用 iPhone Safari
    When 访问 "/"
    Then 响应状态码为 200
    And 响应头包含 "X-Device-Type: mobile"
    And 响应体包含移动版 HTML

  Scenario: 桌面用户访问
    Given 用户使用 Chrome Windows
    When 访问 "/"
    Then 响应状态码为 200
    And 响应头包含 "X-Device-Type: desktop"
    And 响应体包含桌面版 HTML

  Scenario: 无 User-Agent 访问
    Given 请求没有 User-Agent 头
    When 访问 "/"
    Then 响应状态码为 200
    And 默认返回桌面版 HTML
```

### 9.2 边界测试

```python
# tests/integration/test_routing.py

def test_empty_user_agent(client):
    """测试空 user-agent"""
    response = client.get('/', headers={'User-Agent': ''})
    assert response.status_code == 200
    # 应该返回桌面版

def test_malformed_user_agent(client):
    """测试畸形 user-agent"""
    response = client.get('/', headers={'User-Agent': 'x' * 10000})
    assert response.status_code == 200
    # 不应崩溃

def test_webview_detection(client):
    """测试 WebView 检测"""
    wechat_ua = "...MicroMessenger..."
    response = client.get('/', headers={'User-Agent': wechat_ua})
    assert response.status_code == 200
    # 基于 OS 返回对应版本
```

---

## 10. 版本控制

### 语义化版本

**格式**: `MAJOR.MINOR.PATCH`

- **MAJOR**: 不兼容的 API 更改
- **MINOR**: 向后兼容的功能添加
- **PATCH**: 向后兼容的错误修复

### 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-01-01 | 初始版本 |

---

## 11. 合约变更流程

1. **提出变更**: 创建 RFC 文档描述变更
2. **评审**: 团队评审影响和兼容性
3. **更新文档**: 更新此合约规范
4. **实施**: 按新合约实现
5. **测试**: 验证所有测试用例通过
6. **部署**: 滚动发布,监控错误

---

**文档版本**: 1.0.0
**最后更新**: 2026-01-01
**维护者**: 开发团队
**状态**: 已批准

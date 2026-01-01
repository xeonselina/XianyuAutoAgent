# 移动端前端部署指南

## 概述

本文档介绍如何部署库存管理系统的移动端前端应用。

## 架构说明

```
┌─────────────────┐
│   Mobile User   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Nginx (Port 80)│
│  /mobile/*      │
└────────┬────────┘
         │
         ├─────────────► Static Files (dist/)
         │
         └─────────────► API Proxy (/api → :5000)
```

## 部署步骤

### 1. 构建应用

```bash
cd frontend-mobile
npm install
npm run build
```

构建产物位于 `frontend-mobile/dist/` 目录。

### 2. 配置 Nginx

#### 方案 A: 独立域名部署

```nginx
# /etc/nginx/sites-available/inventory-mobile
server {
    listen 80;
    server_name mobile.inventory.com;
    
    root /path/to/InventoryManager/frontend-mobile/dist;
    index index.html;
    
    # 前端路由
    location / {
        try_files $uri $uri/ /index.html;
    }
    
    # API 代理
    location /api {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # 缓存静态资源
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

#### 方案 B: 子路径部署 (与PC端共存)

```nginx
# /etc/nginx/sites-available/inventory
server {
    listen 80;
    server_name inventory.com;
    
    # PC端前端
    location / {
        root /path/to/InventoryManager/frontend/dist;
        try_files $uri $uri/ /index.html;
    }
    
    # 移动端前端
    location /mobile {
        alias /path/to/InventoryManager/frontend-mobile/dist;
        try_files $uri $uri/ /mobile/index.html;
    }
    
    # API 代理
    location /api {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**注意**: 使用子路径部署时,需要修改 `vite.config.ts`:

```typescript
export default defineConfig({
  base: '/mobile/',  // 添加 base 路径
  // ...其他配置
})
```

然后重新构建:

```bash
npm run build
```

### 3. 启用配置

```bash
# 创建软链接
sudo ln -s /etc/nginx/sites-available/inventory-mobile /etc/nginx/sites-enabled/

# 测试配置
sudo nginx -t

# 重新加载 Nginx
sudo nginx -s reload
```

### 4. HTTPS 配置 (可选但推荐)

使用 Let's Encrypt 获取免费 SSL 证书:

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d mobile.inventory.com
```

Certbot 会自动修改 Nginx 配置并启用 HTTPS。

## Docker 部署

### 1. 创建 Dockerfile

```dockerfile
# frontend-mobile/Dockerfile
FROM node:18-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### 2. 创建 nginx.conf

```nginx
# frontend-mobile/nginx.conf
server {
    listen 80;
    server_name localhost;
    
    root /usr/share/nginx/html;
    index index.html;
    
    location / {
        try_files $uri $uri/ /index.html;
    }
    
    location /api {
        proxy_pass http://backend:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 3. 构建镜像

```bash
cd frontend-mobile
docker build -t inventory-mobile:latest .
```

### 4. 运行容器

```bash
docker run -d \
  --name inventory-mobile \
  -p 8080:80 \
  --network inventory-network \
  inventory-mobile:latest
```

### 5. Docker Compose (推荐)

```yaml
# docker-compose.yml (添加到项目根目录)
services:
  backend:
    build: .
    ports:
      - "5000:5000"
    networks:
      - inventory-network
  
  frontend-pc:
    build: ./frontend
    ports:
      - "8080:80"
    networks:
      - inventory-network
  
  frontend-mobile:
    build: ./frontend-mobile
    ports:
      - "8081:80"
    networks:
      - inventory-network

networks:
  inventory-network:
    driver: bridge
```

启动所有服务:

```bash
docker-compose up -d
```

## 环境变量配置

### 开发环境 (`.env.development`)

```bash
VITE_API_BASE_URL=/api
```

### 生产环境 (`.env.production`)

```bash
# 如果使用相同域名
VITE_API_BASE_URL=/api

# 如果API在不同域名
VITE_API_BASE_URL=https://api.inventory.com
```

## 性能优化

### 1. 启用 Gzip 压缩

```nginx
# nginx.conf
gzip on;
gzip_vary on;
gzip_proxied any;
gzip_comp_level 6;
gzip_types text/plain text/css text/xml text/javascript application/json application/javascript application/xml+rss;
```

### 2. 启用 HTTP/2

```nginx
listen 443 ssl http2;
```

### 3. CDN 加速 (可选)

将静态资源上传至 CDN,修改 `vite.config.ts`:

```typescript
export default defineConfig({
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vant': ['vant'],
          'vue': ['vue', 'vue-router', 'pinia']
        }
      }
    }
  }
})
```

## 监控与日志

### 1. Nginx 访问日志

```bash
tail -f /var/log/nginx/access.log
```

### 2. Nginx 错误日志

```bash
tail -f /var/log/nginx/error.log
```

### 3. 应用错误监控

集成 Sentry 进行错误追踪:

```typescript
// main.ts
import * as Sentry from "@sentry/vue"

Sentry.init({
  app,
  dsn: "YOUR_SENTRY_DSN",
  environment: import.meta.env.MODE
})
```

## 回滚策略

### 1. 保留构建历史

```bash
# 备份当前版本
cp -r dist dist.backup.$(date +%Y%m%d_%H%M%S)

# 部署新版本
npm run build
```

### 2. 快速回滚

```bash
# 恢复上一个版本
rm -rf dist
cp -r dist.backup.20250101_120000 dist

# 重启 Nginx
sudo nginx -s reload
```

## 测试清单

部署后需要验证的功能:

- [ ] 设备档期页面加载正常
- [ ] 时间轴显示正确
- [ ] 搜索功能正常
- [ ] 日期导航功能正常
- [ ] 点击租赁块显示详情
- [ ] 预约页面功能正常
- [ ] 设备选择器工作正常
- [ ] 日期选择器工作正常
- [ ] 表单提交成功
- [ ] 冲突检测正常
- [ ] API 请求成功
- [ ] 下拉刷新功能正常
- [ ] 底部导航栏切换正常

## 故障排查

### 问题1: 页面空白

**原因**: 路由配置或 base 路径错误

**解决**:
```bash
# 检查浏览器控制台错误
# 确认 base 路径配置正确
# 检查 Nginx location 配置
```

### 问题2: API 请求 404

**原因**: Nginx 代理配置错误

**解决**:
```nginx
# 确认 location /api 配置正确
location /api {
    proxy_pass http://localhost:5000;
    # 不要写成 http://localhost:5000/api
}
```

### 问题3: 跨域错误

**原因**: CORS 配置问题

**解决**:
```python
# 后端 Flask 配置
from flask_cors import CORS
CORS(app, resources={r"/api/*": {"origins": "*"}})
```

## 安全建议

1. **启用 HTTPS**: 使用 SSL/TLS 加密传输
2. **设置 CSP**: Content Security Policy
3. **限制访问**: 配置 IP 白名单(如果需要)
4. **定期更新**: 及时更新依赖包
5. **监控异常**: 配置错误监控和告警

## 维护周期

- **每周**: 检查日志和监控指标
- **每月**: 更新依赖包
- **每季度**: 性能测试和优化
- **每年**: 安全审计

## 联系支持

遇到问题时:
1. 检查日志文件
2. 查看浏览器控制台
3. 验证后端服务状态
4. 联系开发团队

---

**最后更新**: 2025-12-31

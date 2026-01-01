# 集成部署指南

## 概述

本文档说明如何通过统一的构建和部署流程启动 **PC端** 和 **移动端** 前端。两个前端应用都由同一个 Flask 后端服务器提供,使用相同的端口。

## 架构说明

```
┌──────────────────────────────────────────────────────┐
│           Docker Container (Port 5002)                │
├──────────────────────────────────────────────────────┤
│                                                        │
│  Flask Backend (Gunicorn)                             │
│  ├── /api/*          → API 端点                       │
│  ├── /vue/*          → PC端前端 (static/vue-dist/)    │
│  └── /mobile/*       → 移动端前端 (static/mobile-dist/)│
│                                                        │
└──────────────────────────────────────────────────────┘
```

## 访问地址

- **PC端前端**: http://localhost:5002/vue
- **移动端前端**: http://localhost:5002/mobile
- **API**: http://localhost:5002/api

## 快速开始

### 方法1: 使用 Make 命令 (推荐)

```bash
# 构建 x86 镜像并运行 (包含 PC端 + 移动端)
make build-and-run-x86
```

这个命令会:
1. 构建 PC端前端 → `static/vue-dist/`
2. 构建移动端前端 → `static/mobile-dist/`
3. 构建 x86 Docker 镜像
4. 启动容器

**访问应用**:
- PC端: http://localhost:5002/vue
- 移动端: http://localhost:5002/mobile

### 方法2: 手动构建和部署

```bash
# 1. 构建所有前端应用
make frontend-build-all

# 2. 构建 Docker 镜像
make build-x86

# 3. 启动容器
docker run -d -p 5002:5002 \
  --add-host=host.docker.internal:host-gateway \
  --env-file .env \
  inventory-manager:x86-local
```

## 开发模式

### PC端前端开发

```bash
cd frontend
npm run dev
```

访问: http://localhost:5173 (Vite 开发服务器)

### 移动端前端开发

```bash
cd frontend-mobile
npm run dev
```

访问: http://localhost:5174 (Vite 开发服务器)

开发模式下,API 请求会通过 Vite 代理转发到 `http://localhost:5000`。

### 后端开发

```bash
make run
```

后端运行在: http://localhost:5000

## 生产部署

### 完整构建流程

```bash
# 1. 构建所有前端 (PC + 移动)
make frontend-build-all

# 2. 构建多平台镜像
make docker-build-multiplatform

# 3. 查看构建的镜像
docker images | grep inventory-manager
```

输出:
```
inventory-manager  arm64-local  ...
inventory-manager  x86-local    ...
```

### 部署到服务器

```bash
# 方式1: 直接运行容器
docker run -d \
  --name inventory-manager \
  -p 5002:5002 \
  --add-host=host.docker.internal:host-gateway \
  --env-file .env \
  inventory-manager:x86-local

# 方式2: 使用 Docker Compose
docker-compose up -d
```

## 构建命令详解

| 命令 | 说明 |
|------|------|
| `make frontend-build` | 仅构建 PC端前端 |
| `make frontend-mobile-build` | 仅构建移动端前端 |
| `make frontend-build-all` | 构建所有前端 (PC + 移动) |
| `make build-x86` | 完整构建 x86 镜像 (包含所有前端) |
| `make build-arm` | 完整构建 ARM 镜像 (包含所有前端) |
| `make build-and-run-x86` | 构建并运行 x86 容器 |
| `make build-and-run-arm` | 构建并运行 ARM 容器 |

## 目录结构

```
InventoryManager/
├── frontend/              # PC端前端源码
│   ├── src/
│   ├── package.json
│   └── vite.config.ts
├── frontend-mobile/       # 移动端前端源码
│   ├── src/
│   ├── package.json
│   └── vite.config.ts
├── static/                # 构建产物
│   ├── vue-dist/         # PC端构建输出
│   └── mobile-dist/      # 移动端构建输出
├── app/                   # Flask 后端
│   └── routes/
│       └── vue_app.py    # 前端路由配置
├── Dockerfile
├── Makefile
└── .env
```

## Flask 路由配置

后端通过 `app/routes/vue_app.py` 提供前端服务:

```python
# PC端
@bp.route('/vue')
@bp.route('/vue/<path:filename>')
def vue_index():
    # 返回 static/vue-dist/index.html
    pass

# 移动端
@bp.route('/mobile')
@bp.route('/mobile/<path:filename>')
def mobile_index():
    # 返回 static/mobile-dist/index.html
    pass
```

## 前端路由配置

### PC端 (vite.config.ts)

```typescript
export default defineConfig({
  base: '/vue/',
  build: {
    outDir: '../static/vue-dist'
  }
})
```

### 移动端 (vite.config.ts)

```typescript
export default defineConfig({
  base: '/mobile/',
  build: {
    outDir: '../static/mobile-dist'
  }
})
```

## 环境变量配置

确保 `.env` 文件包含以下配置:

```bash
# 应用配置
APP_PORT=5002
APP_HOST=0.0.0.0

# 数据库配置
DATABASE_URL=mysql+pymysql://user:password@host:3306/dbname

# 其他配置...
```

## Nginx 反向代理 (可选)

如果需要通过 Nginx 提供服务:

```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    # PC端
    location /vue {
        proxy_pass http://localhost:5002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    # 移动端
    location /mobile {
        proxy_pass http://localhost:5002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    # API
    location /api {
        proxy_pass http://localhost:5002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 容器管理

### 查看运行中的容器

```bash
docker ps
```

### 查看容器日志

```bash
docker logs -f <container_id>
```

### 停止容器

```bash
docker stop <container_id>
```

### 重启容器

```bash
docker restart <container_id>
```

### 删除容器

```bash
docker rm <container_id>
```

## 故障排查

### 问题1: 前端页面404

**原因**: 前端未构建或构建路径错误

**解决**:
```bash
# 重新构建前端
make frontend-build-all

# 验证构建产物
ls -la static/vue-dist
ls -la static/mobile-dist
```

### 问题2: API 请求失败

**原因**: 后端服务未启动或环境变量配置错误

**解决**:
```bash
# 检查容器日志
docker logs <container_id>

# 验证环境变量
docker exec <container_id> env | grep DATABASE_URL
```

### 问题3: 静态资源404

**原因**: 资源路径配置错误

**解决**:
- 确认 `vite.config.ts` 中的 `base` 路径正确
- 确认 Flask 路由配置正确
- 重新构建前端

### 问题4: 端口冲突

**原因**: 5002 端口已被占用

**解决**:
```bash
# 查看占用端口的进程
lsof -i :5002

# 停止占用端口的容器
docker stop $(docker ps -q --filter "publish=5002")
```

## 更新部署

### 更新前端代码

```bash
# 1. 更新代码
git pull

# 2. 重新构建前端
make frontend-build-all

# 3. 重新构建镜像
make build-x86

# 4. 停止旧容器
docker stop <old_container_id>

# 5. 启动新容器
make build-and-run-x86
```

### 快速更新

```bash
# 一键重新构建和部署
make build-and-run-x86
```

## 性能优化

### 前端优化

- ✅ 代码分割和懒加载
- ✅ Gzip 压缩
- ✅ 静态资源缓存
- ✅ Tree Shaking

### 后端优化

- ✅ Gunicorn 多进程
- ✅ 连接池
- ✅ 静态文件直接服务

## 监控和日志

### 应用日志

```bash
# 实时查看日志
docker logs -f <container_id>

# 查看最近100行
docker logs --tail 100 <container_id>
```

### 访问日志

后端访问日志位于容器内 `/app/logs/` 目录。

## 备份和恢复

### 备份镜像

```bash
docker save inventory-manager:x86-local | gzip > inventory-manager.tar.gz
```

### 恢复镜像

```bash
gunzip -c inventory-manager.tar.gz | docker load
```

## 安全建议

1. **使用 HTTPS**: 在生产环境启用 SSL/TLS
2. **限制端口暴露**: 只暴露必要的端口
3. **定期更新**: 及时更新依赖包
4. **环境变量**: 不要在代码中硬编码敏感信息
5. **访问控制**: 配置防火墙和访问规则

## 总结

通过统一的构建流程:
- ✅ **一键部署**: `make build-and-run-x86`
- ✅ **统一端口**: PC端和移动端使用同一端口
- ✅ **容器化**: 便于部署和迁移
- ✅ **易于维护**: 清晰的目录结构和构建流程

---

**最后更新**: 2025-12-31

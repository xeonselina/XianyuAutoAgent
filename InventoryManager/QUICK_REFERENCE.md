# 快速参考卡片

## 🚀 一键部署

```bash
make build-and-run-x86
```

**访问地址**:
- PC端: http://localhost:5002/vue
- 移动端: http://localhost:5002/mobile
- API: http://localhost:5002/api

---

## 📦 常用命令

### 前端构建
```bash
# 构建所有前端 (PC + 移动)
make frontend-build-all

# 仅构建 PC端
make frontend-build

# 仅构建移动端
make frontend-mobile-build
```

### Docker 操作
```bash
# 构建 x86 镜像
make build-x86

# 构建 ARM 镜像
make build-arm

# 构建并运行 x86
make build-and-run-x86

# 查看运行中的容器
docker ps

# 查看日志
docker logs -f <container_id>

# 停止容器
docker stop <container_id>
```

### 开发模式
```bash
# PC端开发 (端口 5173)
cd frontend && npm run dev

# 移动端开发 (端口 5174)
cd frontend-mobile && npm run dev

# 后端开发 (端口 5000)
make run
```

---

## 📁 目录结构

```
InventoryManager/
├── frontend/           # PC端前端
├── frontend-mobile/    # 移动端前端
├── static/            
│   ├── vue-dist/      # PC端构建产物
│   └── mobile-dist/   # 移动端构建产物
├── app/               # Flask 后端
├── Makefile           # 构建脚本
└── Dockerfile         # Docker 配置
```

---

## 🌐 访问地址

| 环境 | PC端 | 移动端 | API |
|------|------|--------|-----|
| 生产 | http://localhost:5002/vue | http://localhost:5002/mobile | http://localhost:5002/api |
| PC开发 | http://localhost:5173 | - | http://localhost:5000/api |
| 移动开发 | - | http://localhost:5174 | http://localhost:5000/api |

---

## 🔧 故障排查

### 问题: 容器启动失败
```bash
# 检查日志
docker logs <container_id>

# 验证环境变量
docker exec <container_id> env | grep DATABASE_URL
```

### 问题: 前端页面404
```bash
# 重新构建前端
make frontend-build-all

# 验证产物
ls -la static/vue-dist
ls -la static/mobile-dist
```

### 问题: API 请求失败
```bash
# 检查后端服务
curl http://localhost:5002/api/devices

# 查看容器日志
docker logs <container_id>
```

### 问题: 端口冲突
```bash
# 停止占用端口的容器
docker stop $(docker ps -q --filter "publish=5002")
```

---

## 📚 文档索引

### 快速开始
- [快速开始 (移动端)](MOBILE_QUICKSTART.md)
- [集成部署指南](docs/integrated-deployment-guide.md)

### 详细文档
- [移动端 README](frontend-mobile/README.md)
- [移动端技术选型](docs/mobile-frontend-research.md)
- [移动端部署](docs/mobile-frontend-deployment.md)
- [移动端实现总结](docs/mobile-frontend-implementation-summary.md)
- [移动端集成总结](docs/mobile-integration-summary.md)

### 主项目文档
- [主 README](README.md)
- [Makefile 使用说明](docs/Makefile使用说明.md)
- [环境变量配置](docs/环境变量配置说明.md)

---

## 💡 提示

- 🖥️ PC端适合桌面浏览器 (完整功能)
- 📱 移动端适合手机浏览器 (简化版)
- 🔄 开发时前端和后端可独立运行
- 📦 生产时所有服务打包在一个容器
- 🚀 使用 `make build-and-run-x86` 一键部署

---

**最后更新**: 2025-12-31

# 库存管理系统多架构Docker镜像构建指南

本指南介绍如何在ARM芯片的Mac上使用colima为库存管理系统构建支持ARM64和AMD64架构的Docker镜像。

## 系统要求

- ARM芯片的Mac (Apple Silicon)
- colima 容器引擎
- Docker CLI
- Docker Buildx (用于多架构构建)

## 快速开始

### 1. 检查当前环境

```bash
# 检查colima状态
colima status

# 检查Docker版本
docker version

# 检查系统架构
uname -m
```

### 2. 安装Docker Buildx

如果你的Docker CLI没有buildx支持，需要先安装：

#### 方法1: 重启colima启用buildx (推荐)
```bash
colima stop
colima start --docker-experimental
```

#### 方法2: 手动安装buildx插件
```bash
mkdir -p ~/.docker/cli-plugins/
curl -L https://github.com/docker/buildx/releases/latest/download/buildx-v0.12.0.darwin-arm64 -o ~/.docker/cli-plugins/docker-buildx
chmod +x ~/.docker/cli-plugins/docker-buildx
```

#### 方法3: 升级Docker Desktop (如果使用)
下载最新的Docker Desktop，它包含了buildx支持。

### 3. 设置多架构构建器

```bash
# 使用Makefile命令
make setup-buildx

# 或手动设置
docker buildx create --name multiarch-builder --use --bootstrap
docker buildx inspect
```

## 构建方式

### 使用脚本构建 (推荐)

```bash
# 直接运行脚本
./build-multiarch.sh
```

### 使用Makefile构建

```bash
# 构建多架构镜像
make docker-build-multiarch

# 仅构建ARM64镜像
make docker-build-arm64-local

# 仅构建AMD64镜像
make docker-build-amd64

# 查看所有Docker相关命令
make help | grep docker
```

### 手动构建命令

```bash
# 创建构建器
docker buildx create --name multiarch-builder --use

# 构建多架构镜像（验证构建但不推送）
docker buildx build --platform linux/amd64,linux/arm64 --tag inventory-manager:latest .

# 构建并推送到镜像仓库
docker buildx build --platform linux/amd64,linux/arm64 --tag your-registry/inventory-manager:latest --push .

# 构建单一架构并加载到本地
docker buildx build --platform linux/arm64 --tag inventory-manager:arm64 --load .
```

## 验证构建结果

```bash
# 查看本地镜像
docker images | grep inventory-manager

# 检查镜像架构信息
docker inspect inventory-manager:arm64 | grep Architecture
docker inspect inventory-manager:amd64 | grep Architecture

# 运行测试
docker run --rm -p 5001:5001 inventory-manager:arm64
```

## 构建选项说明

### Dockerfile修改
- 移除了硬编码的`--platform=linux/amd64`
- 添加了`ARG TARGETPLATFORM`和`ARG BUILDPLATFORM`支持
- 增加了构建时的架构信息显示

### 支持的架构
- `linux/arm64` - ARM64架构（Apple Silicon Mac原生）
- `linux/amd64` - x86_64架构（传统服务器）

## 常见问题与解决方案

### 1. 构建器创建失败
```bash
# 清理现有构建器
docker buildx rm multiarch-builder

# 重新创建
docker buildx create --name multiarch-builder --use --bootstrap
```

### 2. buildx命令不存在
```bash
# 检查Docker版本
docker version

# 重启colima
colima stop && colima start --docker-experimental
```

### 3. 跨架构构建缓慢
这是正常现象，因为需要模拟不同架构的环境。ARM Mac构建x86镜像时会使用模拟器。

### 4. 内存不足
```bash
# 为colima分配更多资源
colima stop
colima start --memory 8 --cpu 4
```

## 生产环境部署

### 推送到镜像仓库
```bash
# 设置镜像仓库地址
REGISTRY="your-registry.com"

# 构建并推送
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --tag $REGISTRY/inventory-manager:latest \
  --push .
```

### 部署时指定架构
```bash
# 在ARM服务器上
docker run --platform linux/arm64 your-registry/inventory-manager:latest

# 在x86服务器上  
docker run --platform linux/amd64 your-registry/inventory-manager:latest
```

## 性能优化建议

1. **使用多阶段构建**: 当前Dockerfile已经优化，但可以考虑分离构建和运行时环境
2. **缓存优化**: 构建时利用Docker层缓存
3. **依赖优化**: 只安装必要的系统包
4. **并行构建**: 使用buildx的并行构建能力

## 监控和维护

```bash
# 查看构建历史
docker buildx imagetools inspect inventory-manager:latest

# 清理构建缓存
docker buildx prune

# 查看磁盘使用
docker system df
```

## 相关文件

- `Dockerfile` - 多架构Docker镜像定义
- `build-multiarch.sh` - 多架构构建脚本
- `Makefile` - 包含多架构构建命令
- `docker-compose.yml` - Docker Compose配置

## 更多信息

- [Docker Buildx官方文档](https://docs.docker.com/buildx/)
- [colima多架构支持](https://github.com/abiosoft/colima)
- [ARM64容器最佳实践](https://docs.docker.com/desktop/multi-arch/)
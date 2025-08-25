#!/bin/bash

# 多架构Docker镜像构建脚本
# 支持ARM64和AMD64架构

set -e  # 遇到错误立即退出

# 配置变量
IMAGE_NAME="inventory-manager"
IMAGE_TAG="latest"
REGISTRY=""  # 可以设置为你的镜像仓库地址，如 "your-registry.com"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== 库存管理系统多架构镜像构建脚本 ===${NC}"

# 检查Docker是否运行
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}错误: Docker未运行，请启动colima${NC}"
    echo "运行: colima start"
    exit 1
fi

# 检查并安装Docker Buildx
echo -e "${YELLOW}检查Docker Buildx支持...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker未安装${NC}"
    exit 1
fi

# 尝试使用buildx，如果不可用则提供安装说明
if ! docker buildx version > /dev/null 2>&1; then
    echo -e "${RED}Docker Buildx未安装${NC}"
    echo -e "${YELLOW}请安装Docker Buildx:${NC}"
    echo "方法1: 下载最新Docker Desktop (推荐)"
    echo "方法2: 手动安装buildx插件:"
    echo "  mkdir -p ~/.docker/cli-plugins/"
    echo "  curl -L https://github.com/docker/buildx/releases/latest/download/buildx-v0.12.0.darwin-arm64 -o ~/.docker/cli-plugins/docker-buildx"
    echo "  chmod +x ~/.docker/cli-plugins/docker-buildx"
    echo ""
    echo -e "${YELLOW}或者，你可以尝试重新启动colima以启用buildx:${NC}"
    echo "  colima stop && colima start --docker-experimental"
    exit 1
fi

# 检查当前构建器
echo -e "${YELLOW}当前构建器:${NC}"
docker buildx ls

# 创建并切换到多架构构建器
BUILDER_NAME="multiarch-builder"
echo -e "${YELLOW}创建多架构构建器: $BUILDER_NAME${NC}"

# 如果构建器已存在，则删除重建
if docker buildx ls | grep -q "$BUILDER_NAME"; then
    echo "删除现有构建器..."
    docker buildx rm "$BUILDER_NAME" || true
fi

# 创建新的构建器
docker buildx create --name "$BUILDER_NAME" --use --bootstrap

# 验证构建器支持的平台
echo -e "${YELLOW}验证支持的架构:${NC}"
docker buildx inspect

# 构建镜像名称
if [ -n "$REGISTRY" ]; then
    FULL_IMAGE_NAME="$REGISTRY/$IMAGE_NAME:$IMAGE_TAG"
else
    FULL_IMAGE_NAME="$IMAGE_NAME:$IMAGE_TAG"
fi

echo -e "${YELLOW}开始构建多架构镜像...${NC}"
echo "镜像名称: $FULL_IMAGE_NAME"
echo "目标架构: linux/amd64, linux/arm64"

# 构建多架构镜像
# --load 只能用于单架构，多架构需要使用 --push 或者 --output
echo -e "${GREEN}构建并导出到本地...${NC}"

# 选项1: 构建但不推送，只验证构建过程
docker buildx build \
    --platform linux/amd64,linux/arm64 \
    --tag "$FULL_IMAGE_NAME" \
    --progress plain \
    .

echo -e "${GREEN}构建完成！${NC}"

# 提供推送选项
echo ""
echo -e "${YELLOW}构建完成后的选项:${NC}"
echo "1. 推送到镜像仓库 (需要先设置REGISTRY变量):"
echo "   docker buildx build --platform linux/amd64,linux/arm64 --tag $FULL_IMAGE_NAME --push ."
echo ""
echo "2. 构建并加载单一架构到本地 (用于测试):"
echo "   # ARM64 (当前平台):"
echo "   docker buildx build --platform linux/arm64 --tag $IMAGE_NAME:arm64 --load ."
echo "   # AMD64:"
echo "   docker buildx build --platform linux/amd64 --tag $IMAGE_NAME:amd64 --load ."
echo ""
echo "3. 保存为tar文件:"
echo "   docker buildx build --platform linux/amd64,linux/arm64 --tag $FULL_IMAGE_NAME --output type=oci,dest=./inventory-manager-multiarch.tar ."

# 清理构建器（可选）
read -p "是否删除临时构建器? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    docker buildx rm "$BUILDER_NAME"
    echo "构建器已删除"
fi

echo -e "${GREEN}脚本执行完成！${NC}"
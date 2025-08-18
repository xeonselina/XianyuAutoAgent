# Makefile 使用说明

## 概述

本项目提供了完整的 Makefile 构建脚本，特别针对 ARM Mac 开发和 x86 Docker 部署场景进行了优化。

## 快速开始

### 1. 查看所有可用命令
```bash
make help
```

### 2. 快速启动开发环境
```bash
make dev
```

### 3. 快速启动Docker环境
```bash
make docker-dev
```

## 常用命令分类

### 🚀 开发环境命令

| 命令 | 说明 | 用途 |
|------|------|------|
| `make install-dev` | 安装开发依赖 | 安装开发所需的Python包 |
| `make install` | 安装生产依赖 | 安装生产环境的Python包 |
| `make clean` | 清理缓存文件 | 清理Python缓存和临时文件 |
| `make clean-all` | 完全清理 | 清理所有生成的文件和目录 |

### ⚙️ 环境配置命令

| 命令 | 说明 | 用途 |
|------|------|------|
| `make env-dev` | 配置开发环境 | 复制开发环境配置文件 |
| `make env-prod` | 配置生产环境 | 复制生产环境配置文件 |
| `make env-docker` | 配置Docker环境 | 复制Docker环境配置文件 |

### 🗄️ 数据库命令

| 命令 | 说明 | 用途 |
|------|------|------|
| `make db-init` | 初始化数据库 | 创建数据库表结构 |
| `make db-seed` | 填充示例数据 | 添加测试数据 |

### 🏃 应用运行命令

| 命令 | 说明 | 用途 |
|------|------|------|
| `make run` | 运行开发服务器 | 启动Flask开发服务器 |
| `make run-gunicorn` | 运行生产服务器 | 使用Gunicorn启动 |

### 🐳 Docker 命令

| 命令 | 说明 | 用途 |
|------|------|------|
| `make docker-build` | 构建Docker镜像 | 构建x86兼容的镜像 |
| `make docker-build-arm` | 构建ARM镜像 | 构建ARM64本地测试镜像 |
| `make docker-compose-up` | 启动Docker服务 | 启动所有Docker服务 |
| `make docker-compose-down` | 停止Docker服务 | 停止所有Docker服务 |
| `make docker-logs` | 查看Docker日志 | 实时查看服务日志 |

### 🧪 测试命令

| 命令 | 说明 | 用途 |
|------|------|------|
| `make test` | 运行测试 | 执行所有测试用例 |
| `make test-cov` | 测试覆盖率 | 生成测试覆盖率报告 |

### ✨ 代码质量命令

| 命令 | 说明 | 用途 |
|------|------|------|
| `make lint` | 代码检查 | 使用flake8检查代码质量 |
| `make format` | 代码格式化 | 使用black和isort格式化代码 |

### 🚀 部署命令

| 命令 | 说明 | 用途 |
|------|------|------|
| `make deploy-dev` | 部署开发环境 | 完整部署开发环境 |
| `make deploy-docker` | 部署Docker环境 | 部署到Docker环境 |

### 📊 监控命令

| 命令 | 说明 | 用途 |
|------|------|------|
| `make status` | 检查服务状态 | 查看Docker服务状态 |
| `make health` | 健康检查 | 检查应用健康状态 |

### 🔧 快速启动命令

| 命令 | 说明 | 用途 |
|------|------|------|
| `make dev` | 快速开发环境 | 一键启动开发环境 |
| `make docker-dev` | 快速Docker环境 | 一键启动Docker环境 |
| `make reset` | 重置环境 | 完全重置开发环境 |

### 🍎 ARM Mac 特殊命令

| 命令 | 说明 | 用途 |
|------|------|------|
| `make setup-arm` | ARM环境设置 | 专门为ARM Mac设置环境 |
| `make docker-x86-deploy` | x86部署 | 构建x86镜像并部署 |

## 使用场景

### 场景1：本地开发（ARM Mac）

```bash
# 1. 设置开发环境
make setup-arm

# 2. 配置环境变量
make env-dev

# 3. 启动开发服务器
make run
```

### 场景2：Docker开发环境

```bash
# 1. 配置Docker环境
make env-docker

# 2. 启动Docker服务
make docker-dev

# 3. 查看日志
make docker-logs
```

### 场景3：生产环境部署

```bash
# 1. 配置生产环境
make env-prod

# 2. 构建x86镜像
make docker-build

# 3. 部署服务
make docker-compose-up

# 4. 检查状态
make status
```

### 场景4：代码质量检查

```bash
# 1. 格式化代码
make format

# 2. 运行测试
make test

# 3. 代码检查
make lint
```

## ARM Mac 兼容性说明

### 为什么需要特殊处理？

1. **架构差异**：ARM Mac 使用 ARM64 架构，而生产环境通常是 x86_64
2. **Docker 平台**：需要指定正确的目标平台构建镜像
3. **依赖兼容性**：某些包在 ARM 上可能有兼容性问题

### 解决方案

1. **开发环境**：使用 `requirements-dev.txt`，避免有问题的包
2. **Docker 构建**：使用 `--platform linux/amd64` 指定目标平台
3. **本地测试**：可以构建 ARM64 镜像进行本地测试

### 最佳实践

```bash
# 开发时使用ARM兼容的依赖
make install-dev

# 构建生产镜像时指定x86平台
make docker-build

# 本地测试可以构建ARM镜像
make docker-build-arm
```

## 环境变量配置

### 重要变量

- `DOCKER_PLATFORM`：Docker 构建目标平台
- `FLASK_APP`：Flask 应用入口文件
- `FLASK_ENV`：Flask 运行环境

### 自定义配置

可以在 Makefile 中修改这些变量：

```makefile
# 修改Docker镜像名称
DOCKER_IMAGE = my-inventory-manager

# 修改目标平台
DOCKER_PLATFORM = linux/arm64

# 修改Flask环境
FLASK_ENV = production
```

## 故障排除

### 常见问题

1. **权限问题**
   ```bash
   # 使用sudo或检查文件权限
   sudo make install-dev
   ```

2. **Docker 构建失败**
   ```bash
   # 清理Docker缓存
   docker system prune -f
   make docker-build
   ```

3. **依赖安装失败**
   ```bash
   # 使用开发依赖
   make install-dev
   ```

4. **环境配置问题**
   ```bash
   # 重新配置环境
   make reset
   make env-dev
   ```

### 调试命令

```bash
# 查看系统信息
make info

# 检查服务状态
make status

# 查看Docker日志
make docker-logs

# 健康检查
make health
```

## 扩展和自定义

### 添加新命令

在 Makefile 中添加新的 `.PHONY` 目标：

```makefile
.PHONY: my-command
my-command: ## 我的自定义命令
	@echo "执行自定义命令..."
	# 在这里添加你的命令
```

### 修改现有命令

可以修改现有命令的行为：

```makefile
.PHONY: run
run: ## 运行开发服务器
	@echo "启动开发服务器..."
	export FLASK_APP=$(FLASK_APP) && export FLASK_ENV=$(FLASK_ENV) && python app.py --debug
```

## 总结

这个 Makefile 提供了完整的开发、测试、部署工作流，特别针对 ARM Mac 和 x86 Docker 的兼容性问题进行了优化。使用它可以：

1. **简化开发流程**：一键启动开发环境
2. **确保兼容性**：正确处理架构差异
3. **标准化操作**：统一的命令接口
4. **提高效率**：减少重复的手动操作

建议从 `make help` 开始，熟悉所有可用命令，然后根据实际需求选择合适的命令组合。

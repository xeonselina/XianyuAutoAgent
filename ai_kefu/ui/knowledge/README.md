# 知识库管理 UI

基于 Vue 3 + Vite 的知识库管理单页应用。

## 功能特性

- 知识条目列表（分页、搜索、过滤）
- 新建/编辑知识条目
- 批量导入 JSON 数据
- 导出知识库为 JSON
- 初始化默认知识条目
- 删除知识条目

## 开发环境

### 前置要求

- Node.js 18+
- npm 或 yarn

### 安装依赖

```bash
npm install
```

### 启动开发服务器

```bash
npm run dev
```

开发服务器会在 http://localhost:5173 启动，并自动代理 API 请求到 http://localhost:8000

### 构建生产版本

```bash
npm run build
```

构建产物会输出到 `dist/` 目录。

## 项目结构

```
src/
├── api.js                    # API 接口封装
├── router.js                 # Vue Router 配置
├── main.js                   # 应用入口
├── App.vue                   # 根组件
└── components/
    ├── KnowledgeList.vue     # 知识列表组件
    ├── KnowledgeForm.vue     # 新建/编辑表单组件
    └── BulkImport.vue        # 批量导入组件
```

## API 集成

UI 通过 `/knowledge` API 前缀与后端通信。开发环境下，Vite 会自动代理请求到 FastAPI 后端。

生产环境下，FastAPI 会将静态文件挂载到 `/ui/knowledge` 路径。

## 使用 Makefile 命令

从项目根目录运行：

```bash
# 安装依赖
make ui-install

# 启动开发服务器
make ui-dev

# 构建生产版本
make ui-build
```

## 访问生产环境 UI

启动 FastAPI 后访问：http://localhost:8000/ui/knowledge

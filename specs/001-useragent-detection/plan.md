# 实施计划: 基于 User-Agent 的设备检测

**分支**: `001-useragent-detection` | **日期**: 2026-01-01 | **规格说明**: [spec.md](./spec.md)
**输入**: 功能规格说明来自 `/specs/001-useragent-detection/spec.md`

**注意**: 此模板由 `/speckit.plan` 命令填写。执行工作流请参见 `.specify/templates/commands/plan.md`。

## 摘要

实现基于 user-agent 的自动设备检测,替代当前基于 URL 的路由系统 (`/vue/` 用于桌面端,`/mobile/` 用于移动端)。用户访问统一 URL 时,系统将根据其设备的 user-agent 字符串自动提供相应的界面版本 (桌面版或移动版),无需使用不同的 URL 路径。

## 技术上下文

**后端技术栈**:
- **语言/版本**: Python 3.x
- **Web 框架**: Flask 3.x
- **主要依赖**: werkzeug (user-agent 解析), user-agents 库 (可选,待研究)
- **测试**: pytest
- **目标平台**: Linux/Unix 服务器

**前端技术栈**:
- **桌面端**:
  - **框架**: Vue 3 (Composition API)
  - **语言**: TypeScript 5.8.0
  - **构建工具**: Vite 7.0.6
  - **UI 框架**: Element Plus 2.11.1
  - **状态管理**: Pinia 3.0.3
  - **路由**: Vue Router 4.5.1
  - **Node 版本**: 20.19.0 或 22.12.0+

- **移动端**:
  - **框架**: Vue 3 (Composition API)
  - **语言**: TypeScript 5.9.3
  - **构建工具**: Vite 7.2.4
  - **UI 框架**: Vant 4.9.22 (移动优化)
  - **状态管理**: Pinia 3.0.4
  - **路由**: Vue Router 4.6.4

**当前架构**:
- **项目类型**: Web 应用 (Flask 后端 + 双前端)
- **前端结构**: 两个独立的 Vue 3 项目
  - `frontend/` - 桌面版 (构建到 `static/vue-dist/`)
  - `frontend-mobile/` - 移动版 (构建到 `static/mobile-dist/`)
- **当前路由方式**: URL 路径区分
  - `/vue/` → 桌面版
  - `/mobile/` → 移动版
  - 静态资源分别从 `/assets/` 和 `/mobile/assets/` 提供

**存储**: N/A (此功能不涉及数据存储)

**性能目标**:
- User-agent 检测延迟 < 10ms
- 初始页面加载时间不受影响
- 99% 的标准浏览器正确识别

**约束**:
- 必须保持现有功能 100% 可用
- 不能影响现有 API 调用
- 必须支持现有的前端开发工作流 (dev server proxy)
- 向后兼容现有的 `/vue/` 和 `/mobile/` URL (至少在过渡期内)

**规模/范围**:
- 影响范围: 1 个后端路由文件 (`app/routes/vue_app.py`)
- 需要配置变更: 2 个 Vite 配置文件 (调整 base path)
- 部署环境: 单一 Flask 应用实例

**需要研究的技术问题**:
1. Python Flask 中 user-agent 检测的最佳实践库选择
2. 如何处理前端构建配置以支持统一 URL
3. 是否需要在前端也进行 user-agent 检测作为备用
4. Session 管理在设备切换场景下的处理
5. 如何处理开发环境的代理配置

## 宪法检查

*关卡: 必须在 Phase 0 研究之前通过。Phase 1 设计后重新检查。*

根据宪法文件,主要原则是:

### I. 中文文档规范 ✅ 通过
- 所有项目文档使用中文书写 ✅
- 代码使用英文,技术术语保留英文原文 ✅
- 本计划完全符合此原则

### 其他原则
宪法文件中的其他原则部分仍为模板占位符,无具体约束。

**初步评估**: ✅ 通过 - 无宪法冲突

## 项目结构

### 文档 (本功能)

```text
specs/001-useragent-detection/
├── spec.md              # 功能规格说明
├── plan.md              # 本文件 (/speckit.plan 命令输出)
├── research.md          # Phase 0 输出 (待生成)
├── data-model.md        # Phase 1 输出 (如适用)
├── quickstart.md        # Phase 1 输出 (待生成)
├── contracts/           # Phase 1 输出 (如适用)
├── checklists/          # 质量检查清单
│   └── requirements.md  # 规格说明质量检查 (已完成)
└── tasks.md             # Phase 2 输出 (/speckit.tasks 命令 - 尚未创建)
```

### 源代码 (仓库根目录)

```text
# Web 应用结构 (Flask 后端 + 双 Vue 前端)

# 后端
app/
├── routes/
│   ├── vue_app.py           # [修改] 添加 user-agent 检测逻辑
│   └── ...
├── utils/                   # [新增] 工具函数
│   └── device_detector.py   # [新增] 设备检测模块
└── __init__.py

tests/
├── unit/
│   └── test_device_detector.py  # [新增] 设备检测单元测试
└── integration/
    └── test_vue_routing.py      # [新增] 路由集成测试

# 桌面前端
frontend/
├── src/
│   ├── router/
│   │   └── index.ts         # [可能修改] 路由配置
│   └── main.ts
├── vite.config.ts           # [修改] 调整 base path
└── package.json

# 移动前端
frontend-mobile/
├── src/
│   ├── router/
│   │   └── index.ts         # [可能修改] 路由配置
│   └── main.ts
├── vite.config.ts           # [修改] 调整 base path
└── package.json

# 静态文件输出 (构建产物)
static/
├── vue-dist/                # 桌面版构建输出
└── mobile-dist/             # 移动版构建输出
```

**结构决策**:
保持现有的 Web 应用结构,主要修改集中在后端路由层 (`app/routes/vue_app.py`) 和前端构建配置。新增设备检测工具模块 (`app/utils/device_detector.py`) 以实现 user-agent 解析逻辑。前端项目保持独立,仅调整构建路径配置以支持统一 URL。

## 复杂度跟踪

> **仅在宪法检查有必须证明合理的违规时填写**

| 违规项 | 需要原因 | 拒绝更简单替代方案的原因 |
|--------|----------|-------------------------|
| N/A    | N/A      | N/A                     |

**说明**: 此功能不引入新的复杂度或违反现有宪法原则。

## Phase 0: 大纲与研究

### 待研究问题

基于技术上下文中的未知项,需要研究以下问题:

1. **User-Agent 检测库选择** (优先级: 高)
   - 问题: Python Flask 中最佳的 user-agent 解析库是什么?
   - 候选: `user-agents`, `ua-parser`, `werkzeug.user_agent`
   - 评估标准: 准确性、维护状态、性能、依赖大小

2. **前端构建配置策略** (优先级: 高)
   - 问题: 如何调整 Vite 配置以支持统一 URL (从 `/vue/` 和 `/mobile/` 改为 `/`)
   - 考虑: base path 配置、静态资源路径、路由 history 模式

3. **前端 User-Agent 检测备用方案** (优先级: 中)
   - 问题: 是否需要在前端也进行 user-agent 检测?
   - 场景: 静态部署、CDN 缓存、客户端路由
   - 方案: 纯后端检测 vs 前后端混合检测

4. **Session 管理跨设备场景** (优先级: 中)
   - 问题: 用户从移动设备切换到桌面设备时如何维护 session?
   - 当前机制: Flask session 实现
   - 需确认: Session cookie 作用域、跨设备同步需求

5. **开发环境代理配置** (优先级: 低)
   - 问题: 开发时前端 dev server 如何与新路由配合?
   - 当前: 桌面 dev server (5002) 和移动 dev server (5174) 代理到不同端口
   - 需确认: 是否需要调整 proxy 配置

6. **向后兼容性策略** (优先级: 中)
   - 问题: 旧 URL (`/vue/`, `/mobile/`) 应该如何处理?
   - 选项: 永久重定向、临时重定向、保持支持、废弃警告

7. **边界情况处理** (优先级: 高)
   - WebView (微信、Facebook 内置浏览器)
   - 隐私工具修改 user-agent
   - 移动浏览器"请求桌面站点"模式
   - 开发工具设备模拟

### 研究任务分配

将在 Phase 0 执行期间通过专门的研究代理处理上述问题,输出整合到 `research.md`。

## Phase 1: 设计与合约

**前置条件**: `research.md` 完成

### 数据模型

此功能不引入新的数据实体,主要是路由和配置逻辑的修改。不需要 `data-model.md`。

### API 合约

此功能不引入新的 API 端点,主要修改现有路由的行为:

**修改的路由端点**:

1. **统一入口路由** (新增)
   - **路径**: `/` 或 `/app/`
   - **方法**: GET
   - **功能**: 根据 user-agent 检测提供相应的前端
   - **响应**: HTML (index.html from vue-dist/ or mobile-dist/)
   - **头部**: 根据检测结果设置适当的 Content-Type 和缓存策略

2. **静态资源路由** (修改)
   - **路径**: `/assets/*`
   - **方法**: GET
   - **功能**: 根据请求来源提供相应的静态资源
   - **响应**: JS/CSS/图片等静态文件

3. **兼容路由** (保留,可选)
   - **路径**: `/vue/*` 和 `/mobile/*`
   - **方法**: GET
   - **功能**: 向后兼容,重定向到统一入口或继续服务
   - **响应**: 重定向或 HTML

**合约文档位置**: `contracts/routing-spec.md` (将在 Phase 1 生成)

### 快速入门

将生成 `quickstart.md` 文档,包含:
- 如何在本地测试 user-agent 检测
- 如何使用浏览器开发工具模拟不同设备
- 如何构建和部署新的路由系统
- 故障排查指南

## Phase 2: 任务生成

Phase 2 由单独的 `/speckit.tasks` 命令处理,将基于 Phase 0 研究结果和 Phase 1 设计生成具体的实施任务。

---

**下一步**: 执行 Phase 0 研究,生成 `research.md` 文档。

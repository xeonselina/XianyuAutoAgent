# Tasks: 基于 User-Agent 的设备检测

**功能**: 001-useragent-detection
**输入**: 设计文档来自 `/specs/001-useragent-detection/`
**前置条件**: plan.md, spec.md, research.md, contracts/routing-spec.md

**测试**: 此功能不要求 TDD 方法,测试任务为可选

**组织方式**: 任务按用户故事分组,以支持独立实施和测试每个故事

## 格式: `[ID] [P?] [Story] Description`

- **[P]**: 可并行运行 (不同文件,无依赖)
- **[Story]**: 此任务属于哪个用户故事 (如 US1, US2, US3)
- 包含描述中的确切文件路径

## 路径约定

本项目使用 Web 应用结构 (Flask 后端 + 双 Vue 前端):
- 后端: `app/`, `tests/` 在仓库根目录
- 前端桌面: `frontend/`
- 前端移动: `frontend-mobile/`

---

## Phase 1: 设置 (共享基础设施)

**目的**: 项目初始化和依赖安装

- [X] T001 安装 Python 依赖 user-agents 库到 requirements.txt
- [X] T002 [P] 创建 app/utils/ 目录用于工具模块
- [X] T003 [P] 确认现有路由文件位置 app/routes/vue_app.py

---

## Phase 2: 基础设施 (阻塞前置条件)

**目的**: 必须在任何用户故事实施之前完成的核心基础设施

**⚠️ 关键**: 在此阶段完成之前,不能开始任何用户故事工作

- [X] T004 创建设备检测模块 app/utils/device_detector.py,实现 detect_device_type() 函数
- [X] T005 在 app/utils/device_detector.py 中实现 is_webview() 辅助函数用于 WebView 检测
- [X] T006 在 app/utils/device_detector.py 中添加 LRU 缓存优化 (functools.lru_cache)

**检查点**: 基础设施就绪 - 现在可以并行开始用户故事实施

---

## Phase 3: 用户故事 1 - 自动设备检测 (优先级: P1) 🎯 MVP

**目标**: 实现基于 user-agent 的自动设备检测,用户访问统一 URL 时系统自动提供相应界面

**独立测试**: 从移动设备和桌面浏览器使用相同 URL 访问应用,验证各自收到适合其设备类型的界面版本

**验收标准**:
- 桌面浏览器 (Chrome, Firefox, Safari, Edge) 访问显示桌面版
- 移动设备 (iOS Safari, Android Chrome) 访问显示移动版
- 平板设备访问显示移动版

### 后端实施 (用户故事 1)

- [X] T007 [P] [US1] 修改 app/routes/vue_app.py 导入 device_detector 模块
- [X] T008 [US1] 在 app/routes/vue_app.py 中创建新路由 @bp.route('/') 和 @bp.route('/app/')
- [X] T009 [US1] 实现路由处理函数,调用 detect_device_type() 检测设备
- [X] T010 [US1] 根据检测结果返回相应前端 (mobile-dist 或 vue-dist)
- [X] T011 [US1] 添加响应头 X-Device-Type 用于调试
- [X] T012 [US1] 处理无 User-Agent 头的情况 (默认桌面版)
- [X] T013 [US1] 添加日志记录设备检测结果

### 前端配置调整 (用户故事 1)

- [X] T014 [P] [US1] 修改 frontend-mobile/vite.config.ts,将 base 从 '/mobile/' 改为 '/'
- [X] T015 [P] [US1] 验证 frontend/vite.config.ts 的 base 保持为 '/' (无需修改)
- [X] T016 [P] [US1] 更新 frontend-mobile/src/router/index.ts,将 history base 改为 '/'
- [ ] T017 [P] [US1] 重新构建前端 - 运行 make frontend-build-all
- [ ] T018 [P] [US1] 验证构建输出 static/vue-dist/ 和 static/mobile-dist/ 正确

### 静态资源路由 (用户故事 1)

- [X] T019 [US1] 修改 app/routes/vue_app.py 中的 /assets/* 路由以支持设备检测
- [X] T020 [US1] 实现静态资源路由逻辑,根据 User-Agent 从正确的 dist 目录提供文件
- [X] T021 [US1] 设置适当的缓存头 (Cache-Control, ETag) 用于静态资源

**检查点**: 此时用户故事 1 应完全功能正常且可独立测试

---

## Phase 4: 用户故事 2 - 无缝 URL 分享 (优先级: P2)

**目标**: 用户可以分享单一 URL,不同设备类型的接收者各自看到适合其设备的界面

**独立测试**: 通过电子邮件或消息分享单一 URL,让接收者在不同设备类型上打开,验证每个人都看到适合其设备的界面

**验收标准**:
- 桌面用户分享的 URL,移动用户点击后看到移动界面
- 移动用户分享的 URL,桌面用户点击后看到桌面界面
- 书签在不同设备上正确工作

### 向后兼容实施 (用户故事 2)

- [X] T022 [P] [US2] 保留 app/routes/vue_app.py 中的 /vue/ 和 /vue/* 路由
- [X] T023 [P] [US2] 保留 app/routes/vue_app.py 中的 /mobile/ 和 /mobile/* 路由
- [X] T024 [US2] 为旧 URL 添加日志警告,通知使用已废弃路径
- [X] T025 [US2] (可选) 实现重定向策略或废弃警告页面

### Session 管理验证 (用户故事 2)

- [X] T026 [US2] 验证 Flask session 配置无需修改
- [ ] T027 [US2] 测试用户登录状态在设备切换时保持
- [ ] T028 [US2] 确认 session cookie 在统一 URL 下正常工作

**检查点**: 此时用户故事 1 和 2 应都独立工作

---

## Phase 5: 用户故事 3 - 动态设备切换 (优先级: P3)

**目标**: 处理设备方向变化和视口调整时的界面适配

**独立测试**: 加载应用后调整浏览器窗口大小或旋转设备,验证界面适应

**验收标准**:
- 桌面浏览器调整窗口大小时,初始检测保持不变
- 移动设备旋转时界面适应新方向

### 前端响应式增强 (用户故事 3)

- [X] T029 [P] [US3] 确认 frontend/src/ 和 frontend-mobile/src/ 的 CSS 响应式设计
- [X] T030 [P] [US3] 验证移动端组件支持横屏/竖屏切换
- [X] T031 [US3] 添加 viewport meta 标签确保正确缩放
- [X] T032 [US3] 测试设备方向变化时的布局适应

**检查点**: 所有用户故事现在应该都独立功能正常

---

## Phase 6: 测试与质量保证

**目的**: 确保功能完整性和边界情况处理

### 单元测试

- [X] T033 [P] 创建 tests/unit/test_device_detector.py
- [X] T034 [P] 测试 iPhone User-Agent 识别为 mobile
- [X] T035 [P] 测试 iPad User-Agent 识别为 mobile
- [X] T036 [P] 测试 Android 手机 User-Agent 识别为 mobile
- [X] T037 [P] 测试 Chrome Windows User-Agent 识别为 desktop
- [X] T038 [P] 测试 Safari macOS User-Agent 识别为 desktop
- [X] T039 [P] 测试空 User-Agent 默认为 desktop
- [X] T040 [P] 测试无法识别的 User-Agent 默认为 desktop
- [X] T041 [P] 测试 WebView 检测 (微信, Facebook)

### 集成测试

- [ ] T042 [P] 创建 tests/integration/test_vue_routing.py
- [ ] T043 [P] 测试 GET / 使用移动 UA 返回 mobile-dist/index.html
- [ ] T044 [P] 测试 GET / 使用桌面 UA 返回 vue-dist/index.html
- [ ] T045 [P] 测试 /assets/* 路由根据 UA 提供正确的静态资源
- [ ] T046 [P] 测试旧 URL /vue/ 和 /mobile/ 仍可访问
- [ ] T047 [P] 测试响应头包含 X-Device-Type
- [ ] T048 [P] 测试 session 在设备切换后保持

### 边界情况测试

- [ ] T049 [P] 测试 WebView User-Agent (微信内置浏览器)
- [ ] T050 [P] 测试畸形或超长 User-Agent 字符串
- [ ] T051 [P] 测试移动浏览器"请求桌面站点"模式
- [ ] T052 [P] 测试浏览器开发工具设备模拟

---

## Phase 7: 优化与完善

**目的**: 性能优化、文档和监控

### 性能优化

- [ ] T053 [P] 验证 LRU 缓存配置 (maxsize=1024) 适当
- [ ] T054 [P] 测试检测延迟 < 10ms
- [ ] T055 [P] 基准测试 100 并发请求

### 文档

- [ ] T056 [P] 更新 README 或项目文档说明新的统一 URL
- [ ] T057 [P] 添加代码注释到 device_detector.py
- [ ] T058 [P] 更新 API 文档 (如有)

### 监控与日志

- [ ] T059 [P] 添加指标收集 (移动 vs 桌面访问统计)
- [ ] T060 [P] 配置告警 (检测失败率过高)
- [ ] T061 [P] 确保日志级别适当 (info 用于检测,debug 用于详情)

---

## Phase 8: 部署准备

**目的**: 生产环境部署准备

### 部署配置

- [ ] T062 检查 requirements.txt 包含 user-agents==2.2.0
- [ ] T063 更新部署脚本或 Docker 配置
- [ ] T064 准备回滚计划 (如何恢复旧 URL 路由)
- [ ] T065 创建部署检查清单

### 生产验证

- [ ] T066 在预生产环境测试所有设备类型
- [ ] T067 验证现有功能无损坏 (回归测试)
- [ ] T068 测试静态资源加载性能
- [ ] T069 验证缓存策略正确

---

## 依赖关系图

### 用户故事完成顺序

```
Phase 1 (Setup)
    ↓
Phase 2 (Foundation)
    ↓
┌───────────────────┬────────────────────┬──────────────────┐
│ Phase 3 (US1) 🎯  │  Phase 4 (US2)     │ Phase 5 (US3)    │
│ 自动设备检测       │  无缝 URL 分享     │  动态设备切换     │
│ (MVP - 必需)      │  (独立功能)        │  (增强功能)       │
└───────────────────┴────────────────────┴──────────────────┘
    ↓                     ↓                      ↓
    └─────────────────────┴──────────────────────┘
                          ↓
                  Phase 6 (测试与质量保证)
                          ↓
                  Phase 7 (优化与完善)
                          ↓
                  Phase 8 (部署准备)
```

### 故事依赖关系

- **US1 (自动设备检测)**: 无依赖 - 可立即开始
- **US2 (无缝 URL 分享)**: 轻微依赖 US1 (需要统一 URL 路由存在)
- **US3 (动态设备切换)**: 依赖 US1 (需要设备检测机制)

### 并行机会

**阶段内并行**:
- Phase 2: T004, T005, T006 可并行
- Phase 3: T014-T018 (前端配置) 可与 T007-T013 (后端) 并行
- Phase 6: 所有测试任务 T033-T052 可并行
- Phase 7: 所有优化任务 T053-T061 可并行

**阶段间并行**:
- Phase 3 完成后, Phase 4 和 Phase 5 可并行开始 (US2 和 US3 独立)
- Phase 6, 7, 8 必须顺序执行

---

## 实施策略

### MVP (最小可行产品) 范围

**仅 Phase 1-3** (用户故事 1):
- 基础设备检测
- 统一 URL 路由
- 移动/桌面自动识别

**交付物**:
- 用户可通过单一 URL 访问应用
- 系统自动提供适合其设备的界面
- 基本的边界情况处理

### 增量交付计划

**Sprint 1** (Week 1-2):
- Phase 1: Setup
- Phase 2: Foundation
- Phase 3: US1 (MVP)

**Sprint 2** (Week 3):
- Phase 4: US2 (向后兼容)
- Phase 6: 核心测试 (T033-T048)

**Sprint 3** (Week 4):
- Phase 5: US3 (响应式增强)
- Phase 6: 边界测试 (T049-T052)
- Phase 7: 优化

**Sprint 4** (Week 5):
- Phase 8: 部署准备
- 生产发布

### 独立测试标准

每个用户故事完成后应能通过以下独立测试:

**US1 测试**:
```bash
# 移动设备测试
curl -H "User-Agent: Mozilla/5.0 (iPhone; ...)" http://localhost:5001/
# 预期: 返回 mobile-dist/index.html

# 桌面设备测试
curl -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; ...)" http://localhost:5001/
# 预期: 返回 vue-dist/index.html
```

**US2 测试**:
```bash
# 旧 URL 测试
curl http://localhost:5001/vue/
# 预期: 仍可访问,返回桌面版

curl http://localhost:5001/mobile/
# 预期: 仍可访问,返回移动版
```

**US3 测试**:
```
1. 在移动设备上打开应用
2. 旋转设备到横屏
3. 验证: 界面适应横屏布局,保持移动版特性
```

---

## 任务统计

### 总计

- **总任务数**: 69
- **可并行任务**: 44 (标记 [P])
- **用户故事任务**:
  - US1: 22 任务 (T007-T021, T033-T039)
  - US2: 7 任务 (T022-T028)
  - US3: 4 任务 (T029-T032)
- **Setup/Foundation**: 6 任务 (T001-T006)
- **测试任务**: 20 任务 (T033-T052)
- **优化/部署**: 16 任务 (T053-T069)

### 按阶段分布

| 阶段 | 任务数 | 预估工作量 |
|------|--------|-----------|
| Phase 1: Setup | 3 | 1小时 |
| Phase 2: Foundation | 3 | 2-3小时 |
| Phase 3: US1 (MVP) | 22 | 8-12小时 |
| Phase 4: US2 | 7 | 3-4小时 |
| Phase 5: US3 | 4 | 2-3小时 |
| Phase 6: 测试 | 20 | 6-8小时 |
| Phase 7: 优化 | 9 | 3-4小时 |
| Phase 8: 部署 | 8 | 2-3小时 |
| **总计** | **69** | **27-40小时** |

### 关键路径

最长路径 (顺序依赖):
```
T001-T003 → T004-T006 → T007-T021 → T042-T048 → T062-T069
Setup (3)  Foundation(3)  US1(15)     Integration(7)  Deploy(8)
```

预估关键路径时间: **16-24小时**

---

## 验证检查清单

在标记任务完成之前,验证:

### 格式验证
- [x] 所有任务遵循 `- [ ] [ID] [P?] [Story?] Description` 格式
- [x] 任务 ID 顺序正确 (T001, T002, ...)
- [x] 用户故事标签正确 ([US1], [US2], [US3])
- [x] 可并行任务标记 [P]
- [x] 所有任务包含具体文件路径

### 内容验证
- [x] 每个用户故事都有对应任务
- [x] 每个功能需求都有对应实施任务
- [x] 包含边界情况处理
- [x] 包含测试任务 (可选但包含)
- [x] 包含部署准备任务

### 组织验证
- [x] 按用户故事组织
- [x] 每个故事可独立测试
- [x] 依赖关系明确
- [x] MVP 范围清晰定义
- [x] 并行机会已识别

---

## 下一步

1. **开始实施**: 运行 `/speckit.implement` 执行所有任务
2. **手动实施**: 按顺序完成每个 Phase 的任务
3. **迭代开发**: 先完成 MVP (Phase 1-3),验证后继续增强功能

**建议**: 从 MVP 开始 (Phase 1-3),尽早获得可工作的版本,然后增量添加 US2 和 US3。

---

**文档版本**: 1.0
**生成日期**: 2026-01-01
**状态**: 已生成,准备执行

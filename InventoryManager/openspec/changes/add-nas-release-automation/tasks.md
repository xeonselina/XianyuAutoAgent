## 1. 发布接口与测试

- [x] 1.1 为 Make 目标、版本生成和敏感值保护编写失败测试
- [x] 1.2 扩展 `InventoryManager/Makefile`，增加 build-push、check-nas、deploy-nas、release-nas、nas-status 和 nas-logs

## 2. NAS Compose

- [x] 2.1 为同镜像 app/worker、迁移服务、环境隔离和 FRP external network 编写 Compose 断言
- [x] 2.2 增加 NAS Compose 与非敏感配置示例
- [x] 2.3 验证 app 健康检查及 worker app-only 权限清空

## 3. 部署编排

- [x] 3.1 为远程预检、旧服务保护、迁移失败和 FRP 网络探针编写脚本测试
- [x] 3.2 实现安全的 SSH/Synology sudo、文件同步、镜像拉取和 release 元数据切换
- [x] 3.3 实现 frpc/network 检查、迁移顺序、Compose 更新和健康等待
- [x] 3.4 实现状态、有限日志和失败恢复提示

## 4. 文档与验证

- [x] 4.1 更新 SaaS Lite 部署手册，记录首次准备、日常发布和指定 tag 流程
- [x] 4.2 运行 shell、Compose、相关 Python 测试和敏感信息扫描
- [x] 4.3 在 NAS 执行只读预检并确认 frpc 的实际容器名、配置挂载和网络
- [x] 4.4 经用户确认备份和维护窗口后执行首次真实发布与 FRP 端到端验收

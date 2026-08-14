# Camera Quality

用于 vivo X200 Ultra、X300 Pro、X300 Ultra 搭配 2.35x 长焦增距镜的摄像头清晰度检测项目。

换机继续开发请先阅读 [项目交接文档](docs/PROJECT_HANDOFF.md)。该文档包含完整需求、技术决策、当前进展、构建方式、真机验证流程和后续任务。

当前阶段聚焦于真机能力验证：

- 枚举逻辑摄像头与物理摄像头；
- 自动选择最接近 85mm 等效焦距的后置物理摄像头；
- 对增距镜导致的画面倒置进行 180° 预览校正；
- 保存未经二次压缩的 JPEG 和对应 Camera2 元数据；
- 验证拍摄时实际使用的物理摄像头 ID。

目录：

- `android-app/`：Android 能力检测 APK；
- `server/`：远程基准与测试服务（后续阶段）；
- `algorithm/`：MTF50 算法与测试样本（后续阶段）；
- `docs/`：测试流程和真机验证记录。

详见 [android-app/README.md](android-app/README.md)。

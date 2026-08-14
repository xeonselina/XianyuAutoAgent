# 长焦摄像头清晰度检测项目交接文档

更新时间：2026-08-14

代码位置：`camera-quality/`

当前阶段：Camera2 真机能力检测 APK 已完成，等待目标手机验证

## 1. 项目目标

开发一个只部署在少量固定 Android 手机型号上的摄像头清晰度检测工具，用摄影测试图量化长焦摄像头的解析力，并与同型号正常手机建立的基准比较。

目标机型：

- vivo X200 Ultra；
- vivo X300 Pro；
- vivo X300 Ultra。

每款型号寻找至少 3 台确认正常的手机建立独立基准。测试结果低于该型号基准阈值时，用红色文字提示：

```text
比基准差 xx%
```

测试可以重复进行，并保留测试记录、原始证据图和拍摄参数。

## 2. 已确认的测试条件

| 项目 | 当前决定 |
|---|---|
| 手机型号 | X200 Ultra、X300 Pro、X300 Ultra |
| 基准设备 | 每个型号至少 3 台正常手机 |
| 手机原生长焦 | 约 85mm 等效焦距 |
| 外接镜头 | vivo 官方 2.35x 长焦增距镜 |
| 最终等效焦距 | 约 200mm |
| 测试距离 | 约 3 米 |
| 当前测试纸设想 | 约 30cm × 30cm，具体型号未定 |
| 支架 | 当前没有，正式测试强烈建议增加 |
| 固定光源 | 当前没有，正式测试强烈建议增加 |
| 摄像头调用 | App 使用 Camera2 直接调用 85mm 物理摄像头 |
| 增距镜画面 | App 自行处理 180° 倒置 |
| 基准存储 | 远程服务统一管理、版本化 |

### 测试图建议

200mm 等效焦距在 3 米处的画面范围约为 54cm × 36cm。30cm × 30cm 测试图适合测中心清晰度，但不适合完整检测四角和镜头偏心。

正式版本建议使用：

- A3 横向、约 42cm × 30cm；
- 哑光、平整硬板安装；
- 包含多个 ISO 12233/eSFR 斜边区域，覆盖中心、四边和四角；
- 测试图版本必须写入每次基准和测试记录。

## 3. 关键技术决策

### 3.1 每个型号建立独立基准

不同型号的传感器、镜头、光圈和图像处理不同，不能把不同型号的 MTF50 原始成绩放在一起取中位数。

基准键至少包含：

```text
手机型号
+ 系统构建版本
+ 增距镜型号
+ 测试图版本
+ 拍摄配置版本
+ MTF 算法版本
```

系统 OTA、拍摄算法或测试图变化后，应创建新基准版本，不能覆盖旧基准。

### 3.2 先验证 Camera2，再开发 MTF50

vivo 自带相机的“长焦增距”是厂商专用模式，第三方 App 不应依赖其私有接口。当前方案通过 Camera2：

1. 枚举逻辑摄像头及公开的物理摄像头；
2. 根据物理焦距和传感器尺寸估算 35mm 等效焦距；
3. 选择最接近 85mm 的后置物理摄像头；
4. 使用 `OutputConfiguration.setPhysicalCameraId` 指定预览和 JPEG 输出；
5. 在 CaptureResult 中再次核对实际活动的物理摄像头 ID。

物理摄像头 ID 不能写死。它可能因机型或系统升级变化，后续应把经过真机验证的设备配置放到远程服务中。

### 3.3 原始图片不进行二次 JPEG 旋转

增距镜采用开普勒光学结构，普通 Camera2 输出可能上下、左右倒置。当前实现：

- 屏幕预览旋转 180°，方便操作；
- HAL 输出的 JPEG 字节原样保存；
- JSON 写入 `analysisRotationDegrees = 180`；
- 后续本地和服务端算法通过坐标变换分析，不重新压缩 JPEG。

### 3.4 基准由远程服务统一管理

推荐混合计算模式：

- Android 本地做拍摄质量检查和 MTF50 初算，立即反馈；
- 上传原始照片、分区成绩和 CaptureResult 元数据；
- 服务端重新计算或校验 MTF50，作为正式结果；
- 服务端保存基准版本、阈值、测试记录和证据图。

保留原图后，算法升级时可以重新计算历史样本，不必重新召回全部基准手机。

### 3.5 增距镜是受控测试部件

如果目标是检测手机摄像头本体，同型号设备测试时应尽量使用同一枚确认正常、保持清洁的增距镜和转接装置。

如果每台手机使用自己的增距镜，最终判定对象实际上是：

```text
手机长焦模组 + 增距镜 + 转接环 + 安装状态
```

此时异常不能直接归因于手机摄像头。

## 4. 完整用户流程

### 4.1 登记基准

1. 管理员选择“登记基准”。
2. App 识别手机型号、系统版本和已下发的设备配置。
3. 打开经过验证的 85mm 物理长焦，配合 2.35x 增距镜达到约 200mm。
4. 引导用户在约 3 米处对准测试图。
5. 自动检查测试图完整性、透视、曝光、反光和手机晃动。
6. 自动对焦稳定后锁定焦点、曝光和白平衡。
7. 每台手机至少采集 5 张有效照片。
8. 上传照片、拍摄参数和本地分析结果。
9. 服务端先计算每台手机的分区中位数，再对同型号至少 3 台手机取中位数。
10. 管理员确认后发布新的基准版本。

### 4.2 执行测试

1. 用户选择“开始测试”。
2. App 获取当前型号适用的远程基准与拍摄配置。
3. 按与基准登记相同的镜头、距离、测试图和参数采集照片。
4. 连续采集多张，剔除不合格照片，取有效结果中位数。
5. 对中心、四边、四角分别计算 MTF50。
6. 本地立即显示临时结果，服务端返回正式判定。
7. 正常显示绿色提示；异常显示红色“比基准差 xx%”。
8. 保存测试记录，允许立即重新测试。

## 5. MTF50 与判定建议

使用 ISO 12233/eSFR 斜边法计算 MTF50，不使用简单的拉普拉斯方差作为最终清晰度标准。

不要只保存一个总分。每次至少保存：

- 中心区域；
- 上、下、左、右边缘；
- 四个角；
- 加权总分；
- 最差区域分；
- 区域清晰度热力信息。

每台基准手机先对自己的有效照片取中位数，再在 3 台设备间取中位数，避免把同一台手机的多张照片当成多台独立设备。

下降比例：

```text
下降比例 = (基准分 - 测试分) / 基准分 × 100%
```

初始阈值不要凭经验写死。采集正常机和已知异常机后，可从下式开始评估：

```text
不合格线 = 基准中位数 - max(基准中位数 × 10%, 3 × MAD)
```

最终还需要区域规则。例如总体成绩正常但单侧两个角明显下降时，仍应提示疑似镜头偏心。

## 6. 远程服务草案

建议在 `camera-quality/server/` 建立独立 FastAPI 服务，不与当前仓库中的闲鱼业务模块耦合。

第一版接口建议：

```text
POST /api/v1/calibrations
POST /api/v1/calibrations/{id}/shots
POST /api/v1/calibrations/{id}/publish
GET  /api/v1/baselines/current
POST /api/v1/tests
GET  /api/v1/tests/{id}
```

基准状态建议：

```text
DRAFT → COLLECTING → READY_TO_REVIEW → ACTIVE → SUPERSEDED
```

核心数据实体：

- device_profile：型号、系统范围、摄像头路由和允许参数；
- chart_profile：测试图版本、尺寸和 ROI 定义；
- calibration_session：基准采集批次；
- calibration_device：参与基准的独立手机；
- capture：图片、CaptureResult、质量检查和算法版本；
- baseline_version：各 ROI 中位数、MAD 和阈值；
- test_session：待测手机的一次完整测试；
- test_result：正式判定、下降比例和证据引用。

## 7. 当前已经完成

Android 工程位于 `camera-quality/android-app/`，当前版本号为 `0.1.0-probe`。

已完成：

- 独立 Gradle Android 工程，不影响仓库现有 Python 项目；
- Kotlin + 原生 Android View 界面；
- CAMERA 权限申请；
- 后置逻辑/物理摄像头能力扫描；
- 物理焦距、传感器尺寸和等效焦距估算；
- 自动选择最接近 85mm 的物理长焦路由；
- Camera2 物理输出会话；
- 增距镜预览旋转 180°；
- 最大公开 JPEG 分辨率拍摄；
- 未二次编码的 JPEG 保存；
- CaptureResult JSON 保存；
- 请求物理 ID 与实际活动物理 ID 核对；
- ISO、曝光、焦距、光圈、对焦距离和 AF/AE/AWB 状态记录；
- 焦距换算单元测试；
- 真机验证记录模板；
- Gradle Wrapper 及分发包 SHA-256 校验。

本机已执行：

```bash
./gradlew clean test lintDebug assembleDebug
```

结果：构建成功、单元测试通过、Lint 无错误。Debug APK 可正常生成。

## 8. 尚未完成

- 尚未在三款目标 vivo 手机上运行 APK；
- 尚未确认 vivo HAL 实际公开的 85mm 物理摄像头 ID；
- 尚未确认第三方 App 可获得的最大长焦 JPEG 分辨率；
- 尚未验证增距镜安装后 Camera2 图像是否统一倒置；
- 尚未实现最大 JPEG 会话失败后的分辨率降级重试；
- 尚未实现对焦完成等待和 AF 锁定；
- 尚未实现固定 ISO、快门和白平衡；
- 尚未实现陀螺仪防抖门槛、透视/曝光/反光检查；
- 尚未实现 MTF50 算法；
- 尚未实现远程服务和图片上传；
- 尚未实现基准登记、测试和历史记录正式界面。

## 9. 新电脑构建方法

推荐直接安装 Android Studio，并在其中配置 JDK 17 和 Android SDK 36。也可以只使用命令行工具。

克隆后进入：

```bash
cd XianyuAutoAgent/camera-quality/android-app
```

确认 `local.properties` 指向新电脑的 Android SDK。该文件包含本机路径，不提交到 Git：

```properties
sdk.dir=/新电脑上的/Android/sdk
```

构建：

```bash
./gradlew clean test lintDebug assembleDebug
```

APK 输出：

```text
app/build/outputs/apk/debug/app-debug.apk
```

安装到已开启 USB 调试的手机：

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

注意：`app/build/` 被 Git 忽略，因此换电脑后需要重新构建 APK。

## 10. 真机验证步骤

每个型号先验证 1 台，能力确认后再进入 3 台基准采集。

1. 升级到计划用于正式测试的系统版本。
2. 安装对应的 vivo 官方增距镜、手机壳和转接环。
3. 横屏打开 App 并允许摄像头权限。
4. 点击“重新扫描”。
5. 记录推荐路由、等效焦距、JPEG 最大分辨率、RAW 和手动曝光能力。
6. 点击“启动 85mm 长焦”。
7. 确认预览方向正确、没有主摄遮挡画面、没有异常暗角。
8. 分别在安装和拆除增距镜时各拍摄至少一张样张。
9. 连续拍摄 10 张，观察是否切换摄像头或出现会话失败。
10. 导出 JPEG 和 JSON。

文件位于：

```text
/sdcard/Android/data/com.xianyu.cameraquality/files/Pictures/camera-probe/
```

可以使用：

```bash
adb pull /sdcard/Android/data/com.xianyu.cameraquality/files/Pictures/camera-probe/
```

JSON 重点检查：

- `requestedPhysicalCameraId`；
- `activePhysicalCameraId`；
- `physicalCameraVerified`；
- `jpegWidth` / `jpegHeight`；
- `focalLengthMm`；
- `iso`；
- `exposureTimeNs`；
- `focusDistanceDiopters`；
- `analysisRotationDegrees`。

把结果填入 `docs/phase-1-device-validation.md`。

## 11. 已知风险

1. vivo 可能只向自带相机开放完整的长焦或 2 亿像素能力。
2. 最大 JPEG 与预览组合可能被 HAL 拒绝，需要按分辨率逐级降级。
3. Camera2 物理 ID 可能随系统升级变化，不能作为永久常量。
4. 不使用固定支架时，200mm 的手抖会显著影响 MTF50。
5. 没有固定光源时，ISO、快门和降噪会变化，可能被误判为镜头清晰度变化。
6. 增距镜的灰尘、安装偏心和转接环松动会成为额外变量。
7. 只有 3 台基准机时样本量仍较小，后续应逐步积累更多正常设备数据。
8. 系统 OTA 可能改变 Camera HAL 或图像处理，需要重新验证并视情况创建新基准。

## 12. 建议的下一步顺序

1. 把现有 APK 安装到 X200 Ultra，完成一次有/无增距镜能力验证。
2. 根据 X200 Ultra 的 JSON 和错误日志修正摄像头路由或分辨率策略。
3. 对 X300 Pro、X300 Ultra 重复验证。
4. 固化三个 device profile，并增加远程配置下发。
5. 增加对焦等待、参数锁定、连拍和拍摄质量门槛。
6. 确定并制作 A3 哑光 eSFR 测试图。
7. 在 `algorithm/` 实现可离线验证的 MTF50 算法。
8. 在 `server/` 实现基准登记与测试 API。
9. 将本地算法接入 Android，完成“登记基准”和“开始测试”业务界面。
10. 使用正常机和已知异常机共同确定正式阈值。

## 13. 代码入口

- `android-app/app/src/main/java/com/xianyu/cameraquality/MainActivity.kt`：界面、权限和操作流程；
- `android-app/app/src/main/java/com/xianyu/cameraquality/camera/CameraInventory.kt`：摄像头扫描与 85mm 路由选择；
- `android-app/app/src/main/java/com/xianyu/cameraquality/camera/Camera2ProbeController.kt`：Camera2 会话、物理输出和拍照；
- `android-app/app/src/main/java/com/xianyu/cameraquality/capture/CaptureArtifactWriter.kt`：JPEG 和 JSON 保存；
- `android-app/app/src/main/java/com/xianyu/cameraquality/model/FocalLengthMath.kt`：等效焦距换算；
- `docs/phase-1-device-validation.md`：三款机型的真机结果表。

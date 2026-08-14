# Camera Quality Probe Android App

第一阶段真机能力检测 APK。目标机型：

- vivo X200 Ultra；
- vivo X300 Pro；
- vivo X300 Ultra。

三款手机均按“85mm 物理长焦 + 2.35x 官方增距镜 ≈ 200mm”工作。

## 已实现

- 扫描后置逻辑摄像头和公开的物理摄像头；
- 根据传感器尺寸与物理焦距估算 35mm 等效焦距；
- 优先选择最接近 85mm 的物理摄像头；
- 使用 `OutputConfiguration.setPhysicalCameraId` 同时指定预览和 JPEG 输出；
- 将增距镜预览旋转 180°；
- 保存 HAL 原始 JPEG 字节，不进行二次旋转和压缩；
- 保存 ISO、曝光时间、焦距、对焦距离、AF/AE/AWB 状态等 JSON 元数据；
- 对比请求物理摄像头 ID 与 HAL 上报的活动物理摄像头 ID。

## 构建

需要 JDK 17、Android SDK 36、Build Tools 36.0.0：

```bash
cd camera-quality/android-app
./gradlew test assembleDebug
```

首次在新电脑克隆后，需要创建不提交到 Git 的 `local.properties`：

```properties
sdk.dir=/新电脑上的/Android/sdk
```

APK 输出位置：

```text
app/build/outputs/apk/debug/app-debug.apk
```

安装：

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## 真机验证

1. 手机升级到当前计划使用的系统版本。
2. 安装匹配机型的官方增距镜、手机壳和转接环，确认完全锁紧。
3. 横屏启动 App，允许摄像头权限。
4. 点击“重新扫描”，保存屏幕显示的能力清单。
5. 点击“启动 85mm 长焦”，确认画面方向正确且没有被主摄遮挡画面替代。
6. 点击“拍摄样张”，每台手机至少拍摄一张有增距镜、一张无增距镜照片。
7. 使用 `adb pull` 导出应用目录下的 `Pictures/camera-probe/`。

样张位于：

```text
/sdcard/Android/data/com.xianyu.cameraquality/files/Pictures/camera-probe/
```

每次拍摄会产生同名 `.jpg` 和 `.json`。重点检查 JSON 中：

- `requestedPhysicalCameraId`；
- `activePhysicalCameraId`；
- `physicalCameraVerified`；
- `jpegWidth` / `jpegHeight`；
- `focalLengthMm`；
- `iso` / `exposureTimeNs`。

## 当前边界

- 当前版本用于验证 HAL 能力，不计算 MTF50；
- 当前使用自动曝光、自动白平衡和连续自动对焦；
- 如果设备拒绝“物理镜头预览 + 最大 JPEG”组合，App 会明确报错，后续根据真机日志增加分辨率降级列表；
- 原图保持光学倒置状态，JSON 中写入 `analysisRotationDegrees = 180`，后续分析按坐标变换处理。

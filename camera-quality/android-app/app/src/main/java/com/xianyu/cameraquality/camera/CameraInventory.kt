package com.xianyu.cameraquality.camera

import android.content.Context
import android.graphics.ImageFormat
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.os.Build
import android.util.Size
import com.xianyu.cameraquality.model.CameraRoute
import com.xianyu.cameraquality.model.FocalLengthMath
import java.util.Locale

class CameraInventory(context: Context) {
    private val cameraManager = context.getSystemService(CameraManager::class.java)

    data class ScanResult(
        val routes: List<CameraRoute>,
        val selectedRoute: CameraRoute?,
        val report: String,
    )

    fun scan(): ScanResult {
        val routes = buildList {
            cameraManager.cameraIdList.forEach { logicalId ->
                val logicalCharacteristics = runCatching {
                    cameraManager.getCameraCharacteristics(logicalId)
                }.getOrNull() ?: return@forEach

                if (logicalCharacteristics.get(CameraCharacteristics.LENS_FACING) !=
                    CameraCharacteristics.LENS_FACING_BACK
                ) {
                    return@forEach
                }

                add(routeFrom(logicalId, null, logicalCharacteristics))

                logicalCharacteristics.physicalCameraIds.sorted().forEach physicalLoop@ { physicalId ->
                    val physicalCharacteristics = runCatching {
                        cameraManager.getCameraCharacteristics(physicalId)
                    }.getOrNull() ?: return@physicalLoop

                    add(routeFrom(logicalId, physicalId, physicalCharacteristics))
                }
            }
        }.distinctBy { it.routeId }

        val selected = selectClosest85mmPhysicalRoute(routes)
        return ScanResult(routes, selected, formatReport(routes, selected))
    }

    private fun routeFrom(
        logicalCameraId: String,
        physicalCameraId: String?,
        characteristics: CameraCharacteristics,
    ): CameraRoute {
        val capabilities = characteristics.get(
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES,
        ) ?: intArrayOf()
        val capabilitySet = capabilities.toSet()
        val focalLengths = characteristics.get(
            CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS,
        ) ?: floatArrayOf()
        val focalLengthList = focalLengths.toList()
        val sensorSize = characteristics.get(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE)
        val equivalentFocalLengths = focalLengthList.mapNotNull { focalLength: Float ->
            val size = sensorSize ?: return@mapNotNull null
            FocalLengthMath.equivalent35mm(
                focalLength.toDouble(),
                size.width.toDouble(),
                size.height.toDouble(),
            )
        }

        val streamMap = characteristics.get(
            CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP,
        )
        val jpegSizes = streamMap?.getOutputSizes(ImageFormat.JPEG).orEmpty().toList()
        val previewSizes = streamMap?.getOutputSizes(android.graphics.SurfaceTexture::class.java)
            .orEmpty()
            .toList()

        return CameraRoute(
            logicalCameraId = logicalCameraId,
            physicalCameraId = physicalCameraId,
            focalLengthsMm = focalLengthList,
            equivalentFocalLengthsMm = equivalentFocalLengths,
            sensorWidthMm = sensorSize?.width,
            sensorHeightMm = sensorSize?.height,
            jpegSizes = jpegSizes,
            previewSizes = previewSizes,
            supportsManualSensor = capabilitySet.contains(
                CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR,
            ),
            supportsRaw = capabilitySet.contains(
                CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_RAW,
            ),
            supportsUltraHighResolution = Build.VERSION.SDK_INT >= 31 && capabilitySet.contains(
                CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_ULTRA_HIGH_RESOLUTION_SENSOR,
            ),
            isLogicalMultiCamera = capabilitySet.contains(
                CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_LOGICAL_MULTI_CAMERA,
            ),
            sensorOrientationDegrees = characteristics.get(
                CameraCharacteristics.SENSOR_ORIENTATION,
            ) ?: 0,
            hardwareLevel = characteristics.get(
                CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL,
            ),
            minimumFocusDistanceDiopters = characteristics.get(
                CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE,
            ),
        )
    }

    private fun selectClosest85mmPhysicalRoute(routes: List<CameraRoute>): CameraRoute? {
        val usable = routes.filter { it.jpegSizes.isNotEmpty() && it.previewSizes.isNotEmpty() }
        if (usable.isEmpty()) return null

        return usable.minByOrNull { route ->
            val focalDistance = FocalLengthMath.distanceFromTarget(
                route.equivalentFocalLengthsMm,
                TARGET_EQUIVALENT_FOCAL_LENGTH_MM,
            )
            val physicalPenalty = if (route.physicalCameraId == null) 40.0 else 0.0
            focalDistance + physicalPenalty
        }
    }

    private fun formatReport(routes: List<CameraRoute>, selected: CameraRoute?): String = buildString {
        appendLine("设备: ${Build.MANUFACTURER} ${Build.MODEL}")
        appendLine("系统: Android ${Build.VERSION.RELEASE} / ${Build.DISPLAY}")
        appendLine("目标: 85mm 物理镜头 + 2.35x 增距镜 ≈ 200mm")
        appendLine("JPEG 保持原始字节；分析旋转: 180°")
        appendLine()

        if (selected == null) {
            appendLine("未找到同时支持预览和 JPEG 的后置摄像头。")
        } else {
            appendLine("推荐路由: ${selected.routeId}")
            appendLine(
                "估算等效焦距: ${selected.nearest85mmEquivalent?.format(1) ?: "未知"} mm",
            )
            appendLine("物理镜头锁定: ${if (selected.physicalCameraId != null) "是" else "否（仅逻辑镜头）"}")
        }

        appendLine()
        appendLine("发现 ${routes.size} 条后置摄像头路由")
        appendLine("────────────────────────")

        routes.forEach { route ->
            appendLine("路由 ${route.routeId}${if (route == selected) "  ← 推荐" else ""}")
            appendLine("  类型: ${if (route.physicalCameraId == null) "逻辑/独立" else "物理"}")
            appendLine("  物理焦距: ${route.focalLengthsMm.joinToString { it.toDouble().format(2) }} mm")
            appendLine(
                "  估算等效: ${route.equivalentFocalLengthsMm.joinToString { it.format(1) }} mm",
            )
            appendLine(
                "  传感器: ${route.sensorWidthMm?.toDouble()?.format(2) ?: "?"} × " +
                    "${route.sensorHeightMm?.toDouble()?.format(2) ?: "?"} mm",
            )
            appendLine("  JPEG 最大: ${route.largestJpeg?.asText() ?: "不支持"}")
            appendLine("  手动曝光: ${yesNo(route.supportsManualSensor)}")
            appendLine("  RAW: ${yesNo(route.supportsRaw)}")
            appendLine("  超高分辨率: ${yesNo(route.supportsUltraHighResolution)}")
            appendLine("  传感器方向: ${route.sensorOrientationDegrees}°")
            appendLine()
        }
    }

    private fun Double.format(digits: Int): String =
        String.format(Locale.US, "%.${digits}f", this)

    private fun Size.asText(): String = "$width × $height (${megapixels().format(1)} MP)"

    private fun Size.megapixels(): Double = width.toDouble() * height.toDouble() / 1_000_000.0

    private fun yesNo(value: Boolean): String = if (value) "支持" else "不支持/未公开"

    companion object {
        private const val TARGET_EQUIVALENT_FOCAL_LENGTH_MM = 85.0
    }
}

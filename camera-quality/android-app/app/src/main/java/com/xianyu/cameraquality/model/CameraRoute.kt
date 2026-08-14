package com.xianyu.cameraquality.model

import android.util.Size

data class CameraRoute(
    val logicalCameraId: String,
    val physicalCameraId: String?,
    val focalLengthsMm: List<Float>,
    val equivalentFocalLengthsMm: List<Double>,
    val sensorWidthMm: Float?,
    val sensorHeightMm: Float?,
    val jpegSizes: List<Size>,
    val previewSizes: List<Size>,
    val supportsManualSensor: Boolean,
    val supportsRaw: Boolean,
    val supportsUltraHighResolution: Boolean,
    val isLogicalMultiCamera: Boolean,
    val sensorOrientationDegrees: Int,
    val hardwareLevel: Int?,
    val minimumFocusDistanceDiopters: Float?,
) {
    val routeId: String
        get() = physicalCameraId?.let { "$logicalCameraId/$it" } ?: logicalCameraId

    val largestJpeg: Size?
        get() = jpegSizes.maxByOrNull { it.width.toLong() * it.height.toLong() }

    val nearest85mmEquivalent: Double?
        get() = equivalentFocalLengthsMm.minByOrNull { kotlin.math.abs(it - 85.0) }
}

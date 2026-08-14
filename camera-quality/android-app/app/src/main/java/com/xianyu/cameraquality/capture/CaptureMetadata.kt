package com.xianyu.cameraquality.capture

import com.xianyu.cameraquality.model.CameraRoute

data class CaptureMetadata(
    val captureId: String,
    val capturedAtUtc: String,
    val route: CameraRoute,
    val activePhysicalCameraId: String?,
    val sensorTimestampNs: Long?,
    val iso: Int?,
    val exposureTimeNs: Long?,
    val frameDurationNs: Long?,
    val focalLengthMm: Float?,
    val aperture: Float?,
    val focusDistanceDiopters: Float?,
    val afState: Int?,
    val aeState: Int?,
    val awbState: Int?,
    val lensState: Int?,
    val jpegWidth: Int,
    val jpegHeight: Int,
    val imageTimestampNs: Long?,
    val teleconverterMagnification: Double = 2.35,
    val analysisRotationDegrees: Int = 180,
)

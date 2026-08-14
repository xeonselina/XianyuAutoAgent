package com.xianyu.cameraquality.capture

import android.content.Context
import android.os.Build
import android.os.Environment
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.time.Instant
import java.util.Date
import java.util.Locale
import java.util.UUID

class CaptureArtifactWriter(context: Context) {
    private val captureDirectory = File(
        context.getExternalFilesDir(Environment.DIRECTORY_PICTURES) ?: context.filesDir,
        "camera-probe",
    ).apply { mkdirs() }

    data class CaptureFiles(
        val captureId: String,
        val jpegFile: File,
        val metadataFile: File,
    )

    fun newCaptureId(): String {
        val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.US).format(Date())
        return "${timestamp}_${UUID.randomUUID().toString().take(8)}"
    }

    fun jpegFile(captureId: String): File = File(captureDirectory, "$captureId.jpg")

    fun metadataFile(captureId: String): File = File(captureDirectory, "$captureId.json")

    fun writeJpeg(captureId: String, bytes: ByteArray): File =
        jpegFile(captureId).also { it.writeBytes(bytes) }

    fun writeMetadata(metadata: CaptureMetadata): File {
        val route = metadata.route
        val json = JSONObject().apply {
            put("schemaVersion", 1)
            put("captureId", metadata.captureId)
            put("capturedAtUtc", metadata.capturedAtUtc)
            put("manufacturer", Build.MANUFACTURER)
            put("model", Build.MODEL)
            put("device", Build.DEVICE)
            put("androidRelease", Build.VERSION.RELEASE)
            put("sdkInt", Build.VERSION.SDK_INT)
            put("buildDisplay", Build.DISPLAY)
            put("logicalCameraId", route.logicalCameraId)
            putNullable("requestedPhysicalCameraId", route.physicalCameraId)
            putNullable("activePhysicalCameraId", metadata.activePhysicalCameraId)
            put("physicalCameraVerified", metadata.activePhysicalCameraId != null &&
                metadata.activePhysicalCameraId == route.physicalCameraId)
            put("reportedFocalLengthsMm", JSONArray(route.focalLengthsMm))
            put("estimatedEquivalentFocalLengthsMm", JSONArray(route.equivalentFocalLengthsMm))
            put("teleconverterMagnification", metadata.teleconverterMagnification)
            put("nominalEquivalentFocalLengthMm", 200)
            put("analysisRotationDegrees", metadata.analysisRotationDegrees)
            put("jpegWidth", metadata.jpegWidth)
            put("jpegHeight", metadata.jpegHeight)
            putNullable("imageTimestampNs", metadata.imageTimestampNs)
            putNullable("sensorTimestampNs", metadata.sensorTimestampNs)
            putNullable("iso", metadata.iso)
            putNullable("exposureTimeNs", metadata.exposureTimeNs)
            putNullable("frameDurationNs", metadata.frameDurationNs)
            putNullable("focalLengthMm", metadata.focalLengthMm)
            putNullable("aperture", metadata.aperture)
            putNullable("focusDistanceDiopters", metadata.focusDistanceDiopters)
            putNullable("afState", metadata.afState)
            putNullable("aeState", metadata.aeState)
            putNullable("awbState", metadata.awbState)
            putNullable("lensState", metadata.lensState)
            put("jpegPreservedWithoutReencoding", true)
        }

        return metadataFile(metadata.captureId).also { file ->
            file.writeText(json.toString(2), Charsets.UTF_8)
        }
    }

    fun filesFor(captureId: String): CaptureFiles = CaptureFiles(
        captureId = captureId,
        jpegFile = jpegFile(captureId),
        metadataFile = metadataFile(captureId),
    )

    fun currentUtcTimestamp(): String = Instant.now().toString()

    private fun JSONObject.putNullable(key: String, value: Any?) {
        put(key, value ?: JSONObject.NULL)
    }
}

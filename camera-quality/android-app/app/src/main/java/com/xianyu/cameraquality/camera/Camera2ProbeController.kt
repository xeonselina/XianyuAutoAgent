package com.xianyu.cameraquality.camera

import android.content.Context
import android.graphics.ImageFormat
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CaptureResult
import android.hardware.camera2.TotalCaptureResult
import android.hardware.camera2.params.OutputConfiguration
import android.hardware.camera2.params.SessionConfiguration
import android.media.ImageReader
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.util.Size
import android.view.Surface
import com.xianyu.cameraquality.capture.CaptureArtifactWriter
import com.xianyu.cameraquality.capture.CaptureMetadata
import com.xianyu.cameraquality.model.CameraRoute
import com.xianyu.cameraquality.ui.AutoFitTextureView
import java.io.File
import java.util.concurrent.Executor

class Camera2ProbeController(
    context: Context,
    private val artifactWriter: CaptureArtifactWriter,
    private val listener: Listener,
) {
    interface Listener {
        fun onCameraOpening(route: CameraRoute)
        fun onCameraReady(route: CameraRoute, previewSize: Size, jpegSize: Size)
        fun onActivePhysicalCameraObserved(cameraId: String?)
        fun onCaptureStarted(captureId: String)
        fun onCaptureSaved(captureId: String, jpegFile: File, metadataFile: File)
        fun onCameraClosed()
        fun onError(message: String, throwable: Throwable? = null)
    }

    private data class CaptureWork(
        val id: String,
        var jpegWritten: Boolean = false,
        var metadataWritten: Boolean = false,
        var imageTimestampNs: Long? = null,
        var captureResult: TotalCaptureResult? = null,
    )

    private val cameraManager = context.getSystemService(CameraManager::class.java)
    private val cameraThread = HandlerThread("camera2-probe").apply { start() }
    private val cameraHandler = Handler(cameraThread.looper)
    private val mainHandler = Handler(Looper.getMainLooper())
    private val cameraExecutor = Executor { command -> cameraHandler.post(command) }

    private var cameraDevice: CameraDevice? = null
    private var captureSession: CameraCaptureSession? = null
    private var imageReader: ImageReader? = null
    private var previewSurface: Surface? = null
    private var previewRequestBuilder: CaptureRequest.Builder? = null
    private var currentRoute: CameraRoute? = null
    private var currentJpegSize: Size? = null
    private var captureWork: CaptureWork? = null
    private var lastObservedPhysicalId: String? = null
    private var released = false

    fun open(route: CameraRoute, textureView: AutoFitTextureView) {
        postCamera {
            closeInternal(notify = false)
            currentRoute = route
            dispatch { listener.onCameraOpening(route) }

            val previewSize = choosePreviewSize(route.previewSizes)
            val jpegSize = route.largestJpeg
                ?: throw IllegalStateException("摄像头 ${route.routeId} 不支持 JPEG 输出")

            textureView.post {
                textureView.setAspectRatio(previewSize.width, previewSize.height)
                // 开普勒增距镜在普通 Camera2 输出中上下、左右均倒置。
                textureView.rotation = TELECONVERTER_ROTATION_DEGREES.toFloat()
            }

            val surfaceTexture = textureView.surfaceTexture
                ?: throw IllegalStateException("预览 SurfaceTexture 尚未就绪")
            surfaceTexture.setDefaultBufferSize(previewSize.width, previewSize.height)
            previewSurface = Surface(surfaceTexture)
            currentJpegSize = jpegSize

            imageReader = ImageReader.newInstance(
                jpegSize.width,
                jpegSize.height,
                ImageFormat.JPEG,
                1,
            ).also { reader ->
                reader.setOnImageAvailableListener(::onImageAvailable, cameraHandler)
            }

            @Suppress("MissingPermission")
            cameraManager.openCamera(route.logicalCameraId, cameraStateCallback, cameraHandler)
        }
    }

    fun capture() {
        postCamera {
            val route = currentRoute ?: throw IllegalStateException("摄像头尚未启动")
            val device = cameraDevice ?: throw IllegalStateException("摄像头尚未打开")
            val session = captureSession ?: throw IllegalStateException("拍摄会话尚未就绪")
            val jpegSurface = imageReader?.surface
                ?: throw IllegalStateException("JPEG 输出尚未就绪")

            if (captureWork != null) {
                throw IllegalStateException("上一张照片仍在保存")
            }

            val captureId = artifactWriter.newCaptureId()
            captureWork = CaptureWork(captureId)
            dispatch { listener.onCaptureStarted(captureId) }

            val request = device.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
                addTarget(jpegSurface)
                applyAutomaticControls(this, route)
                // 不设置 JPEG_ORIENTATION，保留 HAL 返回的原始 JPEG 字节。
            }.build()

            session.capture(request, stillCaptureCallback, cameraHandler)
        }
    }

    fun close() {
        postCamera { closeInternal(notify = true) }
    }

    fun release() {
        if (released) return
        released = true
        cameraHandler.post { closeInternal(notify = false) }
        cameraThread.quitSafely()
    }

    private val cameraStateCallback = object : CameraDevice.StateCallback() {
        override fun onOpened(camera: CameraDevice) {
            cameraDevice = camera
            runCatching { createCaptureSession(camera) }
                .onFailure { fail("创建摄像头会话失败", it) }
        }

        override fun onDisconnected(camera: CameraDevice) {
            camera.close()
            if (cameraDevice === camera) cameraDevice = null
            fail("摄像头已断开")
        }

        override fun onError(camera: CameraDevice, error: Int) {
            camera.close()
            if (cameraDevice === camera) cameraDevice = null
            fail("打开摄像头失败，Camera2 错误码 $error")
        }
    }

    private fun createCaptureSession(device: CameraDevice) {
        val route = currentRoute ?: return
        val preview = previewSurface ?: throw IllegalStateException("预览 Surface 不存在")
        val jpeg = imageReader?.surface ?: throw IllegalStateException("JPEG Surface 不存在")
        val physicalId = route.physicalCameraId

        val previewOutput = OutputConfiguration(preview).apply {
            if (physicalId != null) setPhysicalCameraId(physicalId)
        }
        val jpegOutput = OutputConfiguration(jpeg).apply {
            if (physicalId != null) setPhysicalCameraId(physicalId)
        }

        val sessionConfiguration = SessionConfiguration(
            SessionConfiguration.SESSION_REGULAR,
            listOf(previewOutput, jpegOutput),
            cameraExecutor,
            object : CameraCaptureSession.StateCallback() {
                override fun onConfigured(session: CameraCaptureSession) {
                    if (cameraDevice == null) {
                        session.close()
                        return
                    }

                    captureSession = session
                    previewRequestBuilder = device.createCaptureRequest(
                        CameraDevice.TEMPLATE_PREVIEW,
                    ).apply {
                        addTarget(preview)
                        applyAutomaticControls(this, route)
                    }

                    val request = previewRequestBuilder!!.build()
                    session.setRepeatingRequest(request, previewCaptureCallback, cameraHandler)

                    dispatch {
                        listener.onCameraReady(
                            route,
                            choosePreviewSize(route.previewSizes),
                            currentJpegSize!!,
                        )
                    }
                }

                override fun onConfigureFailed(session: CameraCaptureSession) {
                    fail(
                        "摄像头 ${route.routeId} 不接受预览 + 最大 JPEG 的物理镜头会话；" +
                            "请导出日志以便增加分辨率降级策略。",
                    )
                }
            },
        )

        device.createCaptureSession(sessionConfiguration)
    }

    private val previewCaptureCallback = object : CameraCaptureSession.CaptureCallback() {
        override fun onCaptureCompleted(
            session: CameraCaptureSession,
            request: CaptureRequest,
            result: TotalCaptureResult,
        ) {
            val activeId = activePhysicalCameraId(result)
            if (activeId != lastObservedPhysicalId) {
                lastObservedPhysicalId = activeId
                dispatch { listener.onActivePhysicalCameraObserved(activeId) }
            }
        }
    }

    private val stillCaptureCallback = object : CameraCaptureSession.CaptureCallback() {
        override fun onCaptureCompleted(
            session: CameraCaptureSession,
            request: CaptureRequest,
            result: TotalCaptureResult,
        ) {
            val work = captureWork ?: return
            work.captureResult = result
            writeMetadataIfReady(work)
        }

        override fun onCaptureFailed(
            session: CameraCaptureSession,
            request: CaptureRequest,
            failure: android.hardware.camera2.CaptureFailure,
        ) {
            captureWork = null
            fail("拍摄失败，原因码 ${failure.reason}")
        }
    }

    private fun onImageAvailable(reader: ImageReader) {
        val image = runCatching { reader.acquireLatestImage() }.getOrNull() ?: return
        image.use {
            val work = captureWork ?: return
            work.imageTimestampNs = it.timestamp
            val buffer = it.planes.firstOrNull()?.buffer
                ?: throw IllegalStateException("JPEG 图像没有可用平面")
            val bytes = ByteArray(buffer.remaining())
            buffer.get(bytes)

            runCatching { artifactWriter.writeJpeg(work.id, bytes) }
                .onSuccess {
                    work.jpegWritten = true
                    writeMetadataIfReady(work)
                    completeCaptureIfReady(work)
                }
                .onFailure { error ->
                    captureWork = null
                    fail("保存原始 JPEG 失败", error)
                }
        }
    }

    private fun writeMetadataIfReady(work: CaptureWork) {
        if (!work.jpegWritten || work.metadataWritten || captureWork !== work) return
        val result = work.captureResult ?: return
        val route = currentRoute ?: return
        val jpegSize = currentJpegSize ?: return
        val physicalResult = route.physicalCameraId?.let { physicalId ->
            physicalResults(result)[physicalId]
        } ?: result

        runCatching {
            artifactWriter.writeMetadata(
                CaptureMetadata(
                    captureId = work.id,
                    capturedAtUtc = artifactWriter.currentUtcTimestamp(),
                    route = route,
                    activePhysicalCameraId = activePhysicalCameraId(result),
                    sensorTimestampNs = physicalResult.get(CaptureResult.SENSOR_TIMESTAMP),
                    iso = physicalResult.get(CaptureResult.SENSOR_SENSITIVITY),
                    exposureTimeNs = physicalResult.get(CaptureResult.SENSOR_EXPOSURE_TIME),
                    frameDurationNs = physicalResult.get(CaptureResult.SENSOR_FRAME_DURATION),
                    focalLengthMm = physicalResult.get(CaptureResult.LENS_FOCAL_LENGTH),
                    aperture = physicalResult.get(CaptureResult.LENS_APERTURE),
                    focusDistanceDiopters = physicalResult.get(CaptureResult.LENS_FOCUS_DISTANCE),
                    afState = physicalResult.get(CaptureResult.CONTROL_AF_STATE),
                    aeState = physicalResult.get(CaptureResult.CONTROL_AE_STATE),
                    awbState = physicalResult.get(CaptureResult.CONTROL_AWB_STATE),
                    lensState = physicalResult.get(CaptureResult.LENS_STATE),
                    jpegWidth = jpegSize.width,
                    jpegHeight = jpegSize.height,
                    imageTimestampNs = work.imageTimestampNs,
                ),
            )
        }.onSuccess {
            work.metadataWritten = true
            completeCaptureIfReady(work)
        }.onFailure {
            captureWork = null
            fail("保存 CaptureResult 元数据失败", it)
        }
    }

    private fun completeCaptureIfReady(work: CaptureWork) {
        if (!work.jpegWritten || !work.metadataWritten || captureWork !== work) return
        captureWork = null
        val files = artifactWriter.filesFor(work.id)
        dispatch {
            listener.onCaptureSaved(work.id, files.jpegFile, files.metadataFile)
        }
    }

    private fun applyAutomaticControls(
        builder: CaptureRequest.Builder,
        route: CameraRoute,
    ) {
        builder.set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO)
        builder.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON)
        builder.set(CaptureRequest.CONTROL_AWB_MODE, CaptureRequest.CONTROL_AWB_MODE_AUTO)

        val characteristics = targetCharacteristics(route)
        val afModes = characteristics.get(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES)
            ?: intArrayOf()
        when {
            afModes.contains(CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE) ->
                builder.set(
                    CaptureRequest.CONTROL_AF_MODE,
                    CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE,
                )
            afModes.contains(CaptureRequest.CONTROL_AF_MODE_AUTO) ->
                builder.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_AUTO)
        }
    }

    private fun activePhysicalCameraId(result: TotalCaptureResult): String? {
        val reportedId = if (Build.VERSION.SDK_INT >= 29) {
            result.get(CaptureResult.LOGICAL_MULTI_CAMERA_ACTIVE_PHYSICAL_ID)
        } else {
            null
        }
        return reportedId
            ?: currentRoute?.physicalCameraId?.takeIf { physicalResults(result).containsKey(it) }
    }

    private fun physicalResults(result: TotalCaptureResult): Map<String, CaptureResult> {
        if (Build.VERSION.SDK_INT >= 31) {
            return result.physicalCameraTotalResults
        }

        @Suppress("DEPRECATION")
        return result.physicalCameraResults
    }

    private fun targetCharacteristics(route: CameraRoute): CameraCharacteristics =
        cameraManager.getCameraCharacteristics(route.physicalCameraId ?: route.logicalCameraId)

    private fun choosePreviewSize(sizes: List<Size>): Size {
        if (sizes.isEmpty()) throw IllegalStateException("摄像头不支持 SurfaceTexture 预览")
        val bounded = sizes.filter { it.width <= 1920 && it.height <= 1080 }
        return (bounded.ifEmpty { sizes }).maxBy { it.width.toLong() * it.height.toLong() }
    }

    private fun closeInternal(notify: Boolean) {
        captureWork = null
        runCatching { captureSession?.stopRepeating() }
        captureSession?.close()
        captureSession = null
        cameraDevice?.close()
        cameraDevice = null
        imageReader?.close()
        imageReader = null
        previewSurface?.release()
        previewSurface = null
        previewRequestBuilder = null
        currentRoute = null
        currentJpegSize = null
        lastObservedPhysicalId = null
        if (notify) dispatch { listener.onCameraClosed() }
    }

    private fun postCamera(block: () -> Unit) {
        if (released) return
        cameraHandler.post {
            runCatching(block).onFailure { fail(it.message ?: "摄像头操作失败", it) }
        }
    }

    private fun fail(message: String, throwable: Throwable? = null) {
        dispatch { listener.onError(message, throwable) }
    }

    private fun dispatch(block: () -> Unit) {
        mainHandler.post(block)
    }

    companion object {
        private const val TELECONVERTER_ROTATION_DEGREES = 180
    }
}

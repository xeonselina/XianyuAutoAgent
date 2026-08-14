package com.xianyu.cameraquality

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.SurfaceTexture
import android.os.Build
import android.os.Bundle
import android.util.Size
import android.view.TextureView
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import com.xianyu.cameraquality.camera.Camera2ProbeController
import com.xianyu.cameraquality.camera.CameraInventory
import com.xianyu.cameraquality.capture.CaptureArtifactWriter
import com.xianyu.cameraquality.model.CameraRoute
import com.xianyu.cameraquality.ui.AutoFitTextureView
import java.io.File

class MainActivity : Activity(), Camera2ProbeController.Listener {
    private lateinit var preview: AutoFitTextureView
    private lateinit var statusText: TextView
    private lateinit var capabilityText: TextView
    private lateinit var scanButton: Button
    private lateinit var openButton: Button
    private lateinit var captureButton: Button
    private lateinit var inventory: CameraInventory
    private lateinit var controller: Camera2ProbeController

    private var selectedRoute: CameraRoute? = null
    private var openRequested = false
    private var cameraReady = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        preview = findViewById(R.id.preview)
        statusText = findViewById(R.id.statusText)
        capabilityText = findViewById(R.id.capabilityText)
        scanButton = findViewById(R.id.scanButton)
        openButton = findViewById(R.id.openButton)
        captureButton = findViewById(R.id.captureButton)

        inventory = CameraInventory(this)
        controller = Camera2ProbeController(this, CaptureArtifactWriter(this), this)

        preview.surfaceTextureListener = surfaceTextureListener
        scanButton.setOnClickListener { ensurePermissionThenScan() }
        openButton.setOnClickListener {
            openRequested = true
            openSelectedCameraWhenReady()
        }
        captureButton.setOnClickListener {
            captureButton.isEnabled = false
            controller.capture()
        }

        ensurePermissionThenScan()
    }

    override fun onPause() {
        openRequested = false
        cameraReady = false
        captureButton.isEnabled = false
        controller.close()
        super.onPause()
    }

    override fun onDestroy() {
        controller.release()
        super.onDestroy()
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != CAMERA_PERMISSION_REQUEST) return

        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
            scanCameras()
        } else {
            setStatus(getString(R.string.permission_needed), isError = true)
        }
    }

    private fun ensurePermissionThenScan() {
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            scanCameras()
        } else {
            requestPermissions(arrayOf(Manifest.permission.CAMERA), CAMERA_PERMISSION_REQUEST)
        }
    }

    private fun scanCameras() {
        controller.close()
        openRequested = false
        cameraReady = false
        openButton.isEnabled = false
        captureButton.isEnabled = false
        setStatus("正在读取 Camera2 能力…")

        runCatching { inventory.scan() }
            .onSuccess { result ->
                selectedRoute = result.selectedRoute
                capabilityText.text = buildString {
                    append(result.report)
                    if (!isExpectedVivoModel()) {
                        appendLine()
                        appendLine("⚠ 当前设备不在首批目标型号名单中，结果仅供调试。")
                    }
                }
                openButton.isEnabled = result.selectedRoute != null
                if (result.selectedRoute == null) {
                    setStatus("未找到可用的 85mm 候选镜头", isError = true)
                } else {
                    setStatus("能力扫描完成，等待启动推荐长焦路由 ${result.selectedRoute.routeId}")
                }
            }
            .onFailure {
                setStatus("扫描失败：${it.message}", isError = true)
            }
    }

    private fun openSelectedCameraWhenReady() {
        val route = selectedRoute ?: return
        if (!preview.isAvailable) {
            setStatus("等待预览画布就绪…")
            return
        }

        cameraReady = false
        openButton.isEnabled = false
        captureButton.isEnabled = false
        controller.open(route, preview)
    }

    override fun onCameraOpening(route: CameraRoute) {
        setStatus("正在打开长焦路由 ${route.routeId}…")
    }

    override fun onCameraReady(route: CameraRoute, previewSize: Size, jpegSize: Size) {
        cameraReady = true
        openButton.isEnabled = true
        captureButton.isEnabled = true
        setStatus(
            "长焦已就绪 · 预览 ${previewSize.width}×${previewSize.height} · " +
                "JPEG ${jpegSize.width}×${jpegSize.height}",
        )
    }

    override fun onActivePhysicalCameraObserved(cameraId: String?) {
        val expectedId = selectedRoute?.physicalCameraId
        val message = when {
            expectedId == null -> "当前路由没有可验证的物理摄像头 ID"
            cameraId == expectedId -> "物理镜头已验证：$cameraId"
            cameraId == null -> "HAL 未上报活动物理 ID；拍照 JSON 将继续检查"
            else -> "警告：请求物理镜头 $expectedId，实际活动镜头 $cameraId"
        }
        setStatus(message, isError = cameraId != null && expectedId != null && cameraId != expectedId)
    }

    override fun onCaptureStarted(captureId: String) {
        setStatus("正在拍摄并保存 $captureId…")
    }

    override fun onCaptureSaved(captureId: String, jpegFile: File, metadataFile: File) {
        captureButton.isEnabled = cameraReady
        setStatus("样张已保存：${jpegFile.name} + ${metadataFile.name}")
        Toast.makeText(this, "样张与元数据保存成功", Toast.LENGTH_SHORT).show()
        capabilityText.append(
            "\n最近保存\n  JPEG: ${jpegFile.absolutePath}\n  JSON: ${metadataFile.absolutePath}\n",
        )
    }

    override fun onCameraClosed() {
        cameraReady = false
        captureButton.isEnabled = false
    }

    override fun onError(message: String, throwable: Throwable?) {
        cameraReady = false
        openButton.isEnabled = selectedRoute != null
        captureButton.isEnabled = false
        setStatus(message, isError = true)
        capabilityText.append("\n错误\n  $message\n")
        throwable?.let { capabilityText.append("  ${it.javaClass.simpleName}: ${it.message}\n") }
    }

    private fun setStatus(message: String, isError: Boolean = false) {
        statusText.text = message
        statusText.setTextColor(
            getColor(if (isError) R.color.danger else R.color.text_secondary),
        )
    }

    private fun isExpectedVivoModel(): Boolean {
        if (!Build.MANUFACTURER.contains("vivo", ignoreCase = true)) return false
        val normalized = Build.MODEL.replace(" ", "").lowercase()
        return EXPECTED_MODELS.any { normalized.contains(it) }
    }

    private val surfaceTextureListener = object : TextureView.SurfaceTextureListener {
        override fun onSurfaceTextureAvailable(surface: SurfaceTexture, width: Int, height: Int) {
            if (openRequested) openSelectedCameraWhenReady()
        }

        override fun onSurfaceTextureSizeChanged(surface: SurfaceTexture, width: Int, height: Int) = Unit

        override fun onSurfaceTextureDestroyed(surface: SurfaceTexture): Boolean {
            cameraReady = false
            captureButton.isEnabled = false
            controller.close()
            return true
        }

        override fun onSurfaceTextureUpdated(surface: SurfaceTexture) = Unit
    }

    companion object {
        private const val CAMERA_PERMISSION_REQUEST = 1001
        private val EXPECTED_MODELS = listOf("x200ultra", "x300pro", "x300ultra")
    }
}

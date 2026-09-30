package com.motionarcade.vision

import android.annotation.SuppressLint
import android.content.Context
import android.hardware.camera2.CaptureRequest
import android.hardware.display.DisplayManager
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.util.Size
import android.view.Display
import androidx.camera.camera2.interop.Camera2CameraControl
import androidx.camera.camera2.interop.Camera2Interop
import androidx.camera.camera2.interop.CaptureRequestOptions
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * CameraX 相机管理。
 *
 * 几个刻意的取舍：
 * 1. **只用 ImageAnalysis，不绑定 Preview**。游戏画面是 Canvas 自绘的，
 *    摄像头画面只在左下角预览面板里出现 —— 与其让 CameraX 再渲染一次预览
 *    （多一次 GPU 合成开销），不如把帧直接交给分析器，预览面板用最近一帧的
 *    缩略图来画。
 * 2. **输出格式 RGBA_8888**。YUV_420_888 更省带宽，但 MediaPipe 的
 *    MPImage 直接吃 Bitmap/ARGB，省掉的转换开销与引入的 I420→RGB 转换
 *    开销相比并不划算，而且 RGBA 让"预览帧复用"变得零成本。
 * 3. **STRATEGY_KEEP_ONLY_LATEST**：体感游戏要的是"最新姿态"，
 *    积压旧帧只会让操作延迟感变重。
 * 4. **镜头可切换**：手机当屏幕玩 → 前置（镜像交互，玩家能自检"有没有被识别"）；
 *    手机当主机接电视/大屏（检测到外接显示）→ 自动切后置（传感器更好、
 *    视场更广，也更接近最终板卡 + USB 摄像头的形态）。切换即时重绑定。
 * 5. **锁定相机自动调节**（对标游戏机摄像头"固定曝光固定焦距"的稳定性）：
 *    · AWB 从第一帧就锁 —— 白平衡泵是画面"忽冷忽热"的主要来源，锁定无害；
 *    · 后置镜头把 AF 关掉、对焦固定在无穷远 —— 2m 外的人脸在超焦距景深内，
 *      换来的是不会"拉风箱"（前置本来就是定焦，无需处理）；
 *    · AE 延迟 2.5 秒再锁 —— 启动瞬间就锁会把室内欠曝定死，等自动曝光收敛后
 *      锁定，兼顾亮度正确与"曝光泵"消除。
 */
class CameraManager(
    private val context: Context,
    private val lifecycleOwner: LifecycleOwner,
    private val onFrame: (ImageProxy) -> Unit,
) {
    companion object {
        private const val TAG = "CameraManager"
        /** 与 Python 端 CAM_W/CAM_H 一致；够用且省算力。 */
        private val ANALYSIS_SIZE = Size(640, 480)
        private const val AE_LOCK_DELAY_MS = 2500L
    }

    private val cameraExecutor = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())
    private var provider: ProcessCameraProvider? = null
    private var camera: Camera? = null
    private val bound = AtomicBoolean(false)
    private val aeLockRunnable = Runnable { lockAe() }

    /** 当前镜头：true=前置。镜像逻辑（预览/手感方向）都依赖它。 */
    @Volatile
    var lensFront: Boolean = true
        private set

    /** 当前帧画面是否镜像（前置=是）。 */
    val mirrored: Boolean get() = lensFront

    // ---- 预览缩略图：双缓冲 ----
    //
    // 踩过的坑：最初是每帧 createScaledBitmap 一张新的、并把上一张 recycle() 掉，
    // 结果渲染线程正拿着旧 Bitmap 绘制时相机线程把它回收了 —— 直接崩
    // "Canvas: trying to use a recycled bitmap"。
    // 所以改成两块固定 Bitmap 轮换：相机写其中一块、渲染读另一块，切换靠 Volatile 索引。
    // 既不分配也不回收，最坏情况只是某一帧预览轻微撕裂（预览面板而已，可接受）。
    private val thumbW = 300
    private val thumbH = 240
    private val thumbBuf = arrayOf(
        android.graphics.Bitmap.createBitmap(thumbW, thumbH, android.graphics.Bitmap.Config.ARGB_8888),
        android.graphics.Bitmap.createBitmap(thumbW, thumbH, android.graphics.Bitmap.Config.ARGB_8888)
    )
    private val thumbCanvas = arrayOf(
        android.graphics.Canvas(thumbBuf[0]),
        android.graphics.Canvas(thumbBuf[1])
    )
    private val thumbDst = android.graphics.RectF(0f, 0f, thumbW.toFloat(), thumbH.toFloat())
    @Volatile
    private var thumbRead = 0

    /** 最近一帧缩略图（HUD 预览面板用；前置已按"照镜子"镜像）。 */
    val lastFrame: android.graphics.Bitmap get() = thumbBuf[thumbRead]

    fun updateLastFrame(src: android.graphics.Bitmap) {
        val w = 1 - thumbRead
        val c = thumbCanvas[w]
        c.save()
        if (mirrored) c.scale(-1f, 1f, thumbW / 2f, thumbH / 2f)
        c.drawBitmap(src, null, thumbDst, null)
        c.restore()
        thumbRead = w
    }

    /** 切换镜头；运行中会即时重绑定。 */
    fun setLens(front: Boolean) {
        if (lensFront == front) return
        lensFront = front
        if (bound.get()) {
            Log.i(TAG, "lens -> ${if (front) "front" else "back"} (rebind)")
            rebind()
        }
    }

    /** 外接显示（HDMI / 无线投屏 / 板卡）存在 → 该用"主机形态"的后置镜头。 */
    private fun hasExternalDisplay(): Boolean = try {
        val dm = context.getSystemService(Context.DISPLAY_SERVICE) as DisplayManager
        dm.displays.any { it.displayId != Display.DEFAULT_DISPLAY }
    } catch (e: Exception) {
        Log.w(TAG, "display probe failed", e)
        false
    }

    @SuppressLint("UnsafeOptInUsageError")
    fun start() {
        if (bound.getAndSet(true)) return
        // 只在首次启动时自动选择；之后以显式 setLens 为准
        lensFront = !hasExternalDisplay()
        bind()
    }

    @SuppressLint("UnsafeOptInUsageError")
    private fun rebind() {
        mainHandler.removeCallbacks(aeLockRunnable)
        provider?.unbindAll()
        bind()
    }

    @SuppressLint("UnsafeOptInUsageError")
    private fun bind() {
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            try {
                val cameraProvider = future.get()
                provider = cameraProvider

                val analysis = ImageAnalysis.Builder()
                    .setResolutionSelector(
                        ResolutionSelector.Builder()
                            .setResolutionStrategy(
                                ResolutionStrategy(
                                    ANALYSIS_SIZE,
                                    ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER
                                )
                            )
                            .build()
                    )
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                    .also { b ->
                        // ---- 相机自动调节锁定（见类注释第 5 点）----
                        val ext = Camera2Interop.Extender(b)
                        ext.setCaptureRequestOption(CaptureRequest.CONTROL_AWB_LOCK, true)
                        if (!lensFront) {
                            ext.setCaptureRequestOption(
                                CaptureRequest.CONTROL_AF_MODE,
                                CaptureRequest.CONTROL_AF_MODE_OFF
                            )
                            ext.setCaptureRequestOption(CaptureRequest.LENS_FOCUS_DISTANCE, 0f)
                        }
                    }
                    .build()
                    .also {
                        it.setAnalyzer(cameraExecutor) { proxy -> onFrame(proxy) }
                    }

                cameraProvider.unbindAll()
                camera = cameraProvider.bindToLifecycle(
                    lifecycleOwner,
                    if (lensFront) CameraSelector.DEFAULT_FRONT_CAMERA
                    else CameraSelector.DEFAULT_BACK_CAMERA,
                    analysis,
                )
                // AE 已收敛后锁定（消除持续微调的"曝光泵"）
                mainHandler.removeCallbacks(aeLockRunnable)
                mainHandler.postDelayed(aeLockRunnable, AE_LOCK_DELAY_MS)
                Log.i(TAG, "camera bound (${if (lensFront) "front" else "back"}, $ANALYSIS_SIZE)")
            } catch (e: Exception) {
                Log.e(TAG, "bind failed", e)
                bound.set(false)
            }
        }, ContextCompat.getMainExecutor(context))
    }

    @SuppressLint("UnsafeOptInUsageError")
    private fun lockAe() {
        try {
            camera?.let {
                val opts = CaptureRequestOptions.Builder()
                    .setCaptureRequestOption(CaptureRequest.CONTROL_AE_LOCK, true)
                    .build()
                Camera2CameraControl.from(it.cameraControl).setCaptureRequestOptions(opts)
                Log.i(TAG, "AE locked")
            }
        } catch (e: Exception) {
            Log.w(TAG, "AE lock unsupported", e)
        }
    }

    fun stop() {
        try {
            bound.set(false)
            provider?.unbindAll()
            camera = null
        } catch (e: Exception) {
            Log.w(TAG, "stop failed", e)
        }
    }

    fun shutdown() {
        stop()
        cameraExecutor.shutdown()
    }
}

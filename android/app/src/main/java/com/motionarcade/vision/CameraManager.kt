package com.motionarcade.vision

import android.annotation.SuppressLint
import android.content.Context
import android.util.Log
import android.util.Size
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
 * 4. **前置摄像头**：玩家看着屏幕玩，必须能看到自己的脸/手。
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
    }

    private val cameraExecutor = Executors.newSingleThreadExecutor()
    private var provider: ProcessCameraProvider? = null
    private val bound = AtomicBoolean(false)

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

    /** 最近一帧缩略图（HUD 预览面板用）。 */
    val lastFrame: android.graphics.Bitmap get() = thumbBuf[thumbRead]

    fun updateLastFrame(src: android.graphics.Bitmap) {
        val w = 1 - thumbRead
        thumbCanvas[w].drawBitmap(src, null, thumbDst, null)
        thumbRead = w
    }

    @SuppressLint("UnsafeOptInUsageError")
    fun start() {
        if (bound.getAndSet(true)) return
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
                    .build()
                    .also {
                        it.setAnalyzer(cameraExecutor) { proxy -> onFrame(proxy) }
                    }

                cameraProvider.unbindAll()
                cameraProvider.bindToLifecycle(
                    lifecycleOwner,
                    CameraSelector.DEFAULT_FRONT_CAMERA,
                    analysis,
                )
                Log.i(TAG, "camera bound (front, ${ANALYSIS_SIZE})")
            } catch (e: Exception) {
                Log.e(TAG, "bind failed", e)
                bound.set(false)
            }
        }, ContextCompat.getMainExecutor(context))
    }

    fun stop() {
        try {
            provider?.unbindAll()
        } catch (e: Exception) {
            Log.w(TAG, "unbind failed", e)
        }
        bound.set(false)
    }

    fun shutdown() {
        stop()
        cameraExecutor.shutdown()
    }
}

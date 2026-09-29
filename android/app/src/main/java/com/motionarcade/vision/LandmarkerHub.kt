package com.motionarcade.vision

import android.content.Context
import android.graphics.Bitmap
import android.os.Build
import android.util.Log
import com.google.mediapipe.framework.image.BitmapImageBuilder
import com.google.mediapipe.framework.image.MPImage
import com.google.mediapipe.tasks.components.containers.NormalizedLandmark
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.core.Delegate
import com.google.mediapipe.tasks.vision.core.ImageProcessingOptions
import com.google.mediapipe.tasks.vision.core.RunningMode
import com.google.mediapipe.tasks.vision.facelandmarker.FaceLandmarker
import com.google.mediapipe.tasks.vision.facelandmarker.FaceLandmarkerResult
import com.google.mediapipe.tasks.vision.handlandmarker.HandLandmarker
import com.google.mediapipe.tasks.vision.handlandmarker.HandLandmarkerResult
import com.google.mediapipe.tasks.vision.poselandmarker.PoseLandmarker
import com.google.mediapipe.tasks.vision.poselandmarker.PoseLandmarkerResult
import java.util.concurrent.atomic.AtomicBoolean

/**
 * MediaPipe Tasks Vision 的封装：姿态(33) / 手(21) / 脸(468)。
 *
 * 设计要点
 * --------
 * 1. **按需创建、用完即释放**。三个模型同时常驻会吃掉大量内存与算力，
 *    而每个游戏只用到其中一部分（头控游戏不需要手/姿态，手控游戏不需要姿态）。
 * 2. **GPU 优先，失败自动退 CPU —— 而且是运行时降级**。
 *    这一点踩过坑：GPU delegate 在**创建时**可能成功，但**推理时**才炸
 *    （例如模拟器的软件 GL 缺少 `glGetBufferParameteri64v`，报 GL_INVALID_ENUM）。
 *    只在创建时 try/catch 兜不住这种情况，必须在 errorListener 里标记失败，
 *    再于下一次 detectAsync（相机线程）重建为 CPU —— 重建必须和推理同一线程，
 *    否则 MediaPipe 会直接崩。
 * 3. **LIVE_STREAM + 单调时间戳**：MediaPipe 要求 timestampMs 严格递增，
 *    调用方必须在同一线程顺序提交（本项目的 CameraX 用单线程 executor，天然满足）。
 */
class LandmarkerHub(private val context: Context) {

    companion object {
        private const val TAG = "LandmarkerHub"

        private const val POSE_MODEL = "models/pose_landmarker_lite.task"
        private const val HAND_MODEL = "models/hand_landmarker.task"
        private const val FACE_MODEL = "models/face_landmarker.task"

        /** 归一化坐标理论上 ∈[0,1]；超过这个阈值说明拿到的是像素坐标，需要换算。 */
        private const val NORMALIZED_MAX = 1.5f
    }

    // ---- 回调：由 VisionPipeline 注入 ----
    var onPose: ((PoseFrame?, Long) -> Unit)? = null
    var onHands: ((List<HandState>, Long) -> Unit)? = null
    var onFace: ((List<Joint>, Long) -> Unit)? = null

    private var pose: PoseLandmarker? = null
    private var hand: HandLandmarker? = null
    private var face: FaceLandmarker? = null

    private val poseFailed = AtomicBoolean(false)
    private val handFailed = AtomicBoolean(false)
    private val faceFailed = AtomicBoolean(false)

    /** GPU 推理失败 → 置位，下次 detectAsync 前整体重建为 CPU。 */
    private val gpuBroken = AtomicBoolean(false)
    /** 当前实际使用的 delegate（降级后为 true）。 */
    @Volatile
    private var usingCpu = false

    /** 当前是否在用 CPU（供诊断显示）。 */
    val cpuMode: Boolean get() = usingCpu

    init {
        // 模拟器的 GPU 基本不可靠（swiftshader 缺少 glGetBufferParameteri64v 等，
        // 会让 GPU delegate 在推理阶段每帧报 GL_INVALID_ENUM）。
        // 而且这种失败**既不抛异常、也不走 errorListener**，只在内部线程打日志，
        // 从调用侧根本探测不到 —— 所以模拟器直接走 CPU，别去赌它的 GL。
        if (isEmulator()) {
            usingCpu = true
            Log.i(TAG, "emulator detected → 直接使用 CPU delegate")
        }
    }

    private fun isEmulator(): Boolean =
        Build.FINGERPRINT.startsWith("generic") ||
            Build.FINGERPRINT.startsWith("unknown") ||
            Build.MODEL.contains("google_sdk") ||
            Build.MODEL.contains("Emulator") ||
            Build.MODEL.contains("Android SDK built for") ||
            Build.MANUFACTURER.contains("Genymotion") ||
            Build.BRAND.startsWith("generic") && Build.DEVICE.startsWith("generic") ||
            Build.PRODUCT == "google_sdk" ||
            Build.PRODUCT.contains("sdk_gphone") ||
            System.getProperty("ro.kernel.qemu") == "1" ||
            Build.HARDWARE.contains("goldfish") ||
            Build.HARDWARE.contains("ranchu")

    // ------------------------------------------------------------------ 生命周期

    fun ensure(channels: Set<InputChannel>) {
        if (InputChannel.BODY in channels || InputChannel.HEAD in channels) ensurePose()
        if (InputChannel.HAND in channels) ensureHand()
        if (InputChannel.HEAD in channels) ensureFace()
    }

    fun release(channels: Set<InputChannel>) {
        if (InputChannel.BODY !in channels && InputChannel.HEAD !in channels) releasePose()
        if (InputChannel.HAND !in channels) releaseHand()
        if (InputChannel.HEAD !in channels) releaseFace()
    }

    fun releaseAll() {
        releasePose(); releaseHand(); releaseFace()
    }

    private fun onTaskError(which: String, e: Exception) {
        val msg = e.message.orEmpty()
        // GPU delegate 在部分设备/模拟器上会在推理阶段才失败（GL_INVALID_ENUM 等）
        if (!usingCpu && (msg.contains("GL_", true) || msg.contains("gpu", true) ||
                msg.contains("delegate", true))
        ) {
            Log.w(TAG, "$which: GPU 推理失败，将降级为 CPU —— $msg")
            gpuBroken.set(true)
        } else {
            Log.e(TAG, "$which error", e)
        }
    }

    private fun ensurePose() {
        if (pose != null || poseFailed.get()) return
        pose = try {
            val opts = PoseLandmarker.PoseLandmarkerOptions.builder()
                .setBaseOptions(baseOptions(POSE_MODEL))
                .setRunningMode(RunningMode.LIVE_STREAM)
                .setNumPoses(1)
                .setMinPoseDetectionConfidence(0.5f)
                .setMinPosePresenceConfidence(0.5f)
                .setMinTrackingConfidence(0.5f)
                .setResultListener { result: PoseLandmarkerResult, _: MPImage ->
                    onPose?.invoke(toPoseFrame(result), System.currentTimeMillis())
                }
                .setErrorListener { e -> onTaskError("pose", e) }
                .build()
            PoseLandmarker.createFromOptions(context, opts).also {
                Log.i(TAG, "pose landmarker ready (${if (usingCpu) "CPU" else "GPU"})")
            }
        } catch (e: Exception) {
            // 创建阶段就失败：直接退 CPU 再试一次
            if (!usingCpu) {
                Log.w(TAG, "pose init failed on GPU, retry CPU", e)
                usingCpu = true
                ensurePose()
                null
            } else {
                poseFailed.set(true)
                Log.e(TAG, "pose unavailable", e)
                null
            }
        }
    }

    private fun ensureHand() {
        if (hand != null || handFailed.get()) return
        hand = try {
            val opts = HandLandmarker.HandLandmarkerOptions.builder()
                .setBaseOptions(baseOptions(HAND_MODEL))
                .setRunningMode(RunningMode.LIVE_STREAM)
                .setNumHands(2)
                .setMinHandDetectionConfidence(0.5f)
                .setMinHandPresenceConfidence(0.5f)
                .setMinTrackingConfidence(0.5f)
                .setResultListener { result: HandLandmarkerResult, _: MPImage ->
                    onHands?.invoke(toHandStates(result), System.currentTimeMillis())
                }
                .setErrorListener { e -> onTaskError("hand", e) }
                .build()
            HandLandmarker.createFromOptions(context, opts).also {
                Log.i(TAG, "hand landmarker ready (${if (usingCpu) "CPU" else "GPU"})")
            }
        } catch (e: Exception) {
            if (!usingCpu) {
                Log.w(TAG, "hand init failed on GPU, retry CPU", e)
                usingCpu = true
                ensureHand()
                null
            } else {
                handFailed.set(true)
                Log.e(TAG, "hand unavailable", e)
                null
            }
        }
    }

    private fun ensureFace() {
        if (face != null || faceFailed.get()) return
        face = try {
            val opts = FaceLandmarker.FaceLandmarkerOptions.builder()
                .setBaseOptions(baseOptions(FACE_MODEL))
                .setRunningMode(RunningMode.LIVE_STREAM)
                .setNumFaces(1)
                .setMinFaceDetectionConfidence(0.5f)
                .setMinFacePresenceConfidence(0.5f)
                .setMinTrackingConfidence(0.5f)
                .setResultListener { result: FaceLandmarkerResult, _: MPImage ->
                    onFace?.invoke(toFaceJoints(result), System.currentTimeMillis())
                }
                .setErrorListener { e -> onTaskError("face", e) }
                .build()
            FaceLandmarker.createFromOptions(context, opts).also {
                Log.i(TAG, "face landmarker ready (${if (usingCpu) "CPU" else "GPU"})")
            }
        } catch (e: Exception) {
            if (!usingCpu) {
                Log.w(TAG, "face init failed on GPU, retry CPU", e)
                usingCpu = true
                ensureFace()
                null
            } else {
                faceFailed.set(true)
                Log.e(TAG, "face unavailable", e)
                null
            }
        }
    }

    private fun baseOptions(model: String): BaseOptions =
        BaseOptions.builder()
            .setModelAssetPath(model)
            .setDelegate(if (usingCpu) Delegate.CPU else Delegate.GPU)
            .build()

    private fun releasePose() { pose?.close(); pose = null }
    private fun releaseHand() { hand?.close(); hand = null }
    private fun releaseFace() { face?.close(); face = null }

    /**
     * GPU 推理失败后的整体重建（必须在推理线程调用）。
     * 复位失败标志，让 ensure* 能重新创建。
     */
    private fun rebuildWithCpu(channels: Set<InputChannel>) {
        Log.w(TAG, "rebuilding all landmarkers on CPU")
        releaseAll()
        poseFailed.set(false); handFailed.set(false); faceFailed.set(false)
        usingCpu = true
        gpuBroken.set(false)
        ensure(channels)
    }

    // ------------------------------------------------------------------ 推理

    /** 提交一帧；只跑当前已装载的检测器。 */
    fun detectAsync(channels: Set<InputChannel>, bitmap: Bitmap,
                    rotationDegrees: Int, timestampMs: Long) {
        // GPU 挂了就在这里（推理线程）重建为 CPU —— 不能在其他线程直接重建
        if (gpuBroken.get() && !usingCpu) {
            rebuildWithCpu(channels)
            return                       // 本帧丢弃，重建后再开始推理
        }
        if (gpuBroken.get()) gpuBroken.set(false)

        val mp = BitmapImageBuilder(bitmap).build()
        val opts = ImageProcessingOptions.builder()
            .setRotationDegrees(rotationDegrees)
            .build()
        try {
            pose?.detectAsync(mp, opts, timestampMs)
            hand?.detectAsync(mp, opts, timestampMs)
            face?.detectAsync(mp, opts, timestampMs)
        } catch (e: Exception) {
            // 注意：GPU delegate 的失败很多时候是**同步抛出**的（Graph has errors /
            // GL_INVALID_ENUM），不会走 errorListener，所以必须在这里兜住。
            val msg = e.message.orEmpty()
            if (!usingCpu && (msg.contains("GL_", true) || msg.contains("gpu", true) ||
                    msg.contains("Graph has errors", true))
            ) {
                Log.w(TAG, "GPU 推理异常，下一帧降级为 CPU: ${msg.take(120)}")
                gpuBroken.set(true)
            } else {
                Log.w(TAG, "detect failed", e)
            }
        }
    }

    // ------------------------------------------------------------------ 结果转换

    /**
     * 把 MediaPipe landmark 转成 [Joint]。
     * 防御性处理：如果拿到的是像素坐标（>1.5），按最大绝对值归一，
     * 避免不同后端/版本坐标语义不一致导致整个控制链路量纲错乱。
     */
    private fun norm(list: List<NormalizedLandmark>): List<Joint> {
        if (list.isEmpty()) return emptyList()
        val maxAbs = list.maxOf { kotlin.math.abs(it.x()).coerceAtLeast(kotlin.math.abs(it.y())) }
        val k = if (maxAbs > NORMALIZED_MAX) 1f / maxAbs * NORMALIZED_MAX else 1f
        return list.map {
            Joint(it.x() * k, it.y() * k, it.visibility().orElse(1f))
        }
    }

    private fun toPoseFrame(result: PoseLandmarkerResult): PoseFrame? {
        val lm = result.landmarks()
        if (lm.isEmpty()) return null
        val joints = norm(lm[0])
        val map = mutableMapOf<String, Joint>()
        MP_POSE_TO_COCO.forEach { (name, idx) ->
            if (idx < joints.size) map[name] = joints[idx]
        }
        return PoseFrame(map)
    }

    private fun toHandStates(result: HandLandmarkerResult): List<HandState> {
        val lms = result.landmarks()
        val handed = result.handedness()
        val out = ArrayList<HandState>(lms.size)
        for (i in lms.indices) {
            val joints = norm(lms[i])
            if (joints.size < HAND_JOINTS.size) continue
            val map = HAND_JOINTS.mapIndexedNotNull { idx, name ->
                if (idx < joints.size) name to joints[idx] else null
            }.toMap()
            // MediaPipe 的 handedness 是**镜像后**的左右手（前置摄像头已镜像）
            val isLeft = handed.getOrNull(i)
                ?.firstOrNull()
                ?.categoryName()
                ?.equals("Left", ignoreCase = true) ?: false
            out.add(HandState(map, isLeft))
        }
        // 按 x 排序，保证"左手在前"的稳定顺序（与 Python 端一致）
        out.sortBy { it.center.x }
        return out
    }

    private fun toFaceJoints(result: FaceLandmarkerResult): List<Joint> {
        val lm = result.faceLandmarks()
        if (lm.isEmpty()) return emptyList()
        return norm(lm[0])
    }
}

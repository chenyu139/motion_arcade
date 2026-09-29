package com.motionarcade.vision

import android.content.Context
import android.graphics.Bitmap
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

/**
 * MediaPipe Tasks Vision 的封装：姿态(33) / 手(21) / 脸(468)。
 *
 * 设计要点
 * --------
 * 1. **按需创建、用完即释放**。三个模型同时常驻会吃掉大量内存与算力，
 *    而每个游戏只用到其中一部分（头控游戏不需要手/姿态，手控游戏不需要姿态）。
 *    [ensure] / [release] 让管线按游戏声明的通道动态装卸。
 * 2. **GPU 优先、CPU 兜底**。GPU delegate 在部分设备上初始化会失败
 *    （驱动/上下文问题），失败就退到 CPU，保证功能可用而不是直接崩。
 * 3. **LIVE_STREAM + 单调时间戳**。这是流式推理模式，MediaPipe 要求
 *    timestampMs 严格递增；调用方必须在**同一个线程**里顺序提交（本项目
 *    用 CameraX 的单线程 analyzer executor，天然满足）。
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

    private val poseFailed = java.util.concurrent.atomic.AtomicBoolean(false)
    private val handFailed = java.util.concurrent.atomic.AtomicBoolean(false)
    private val faceFailed = java.util.concurrent.atomic.AtomicBoolean(false)

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
                .setErrorListener { e -> Log.e(TAG, "pose error", e) }
                .build()
            PoseLandmarker.createFromOptions(context, opts).also {
                Log.i(TAG, "pose landmarker ready")
            }
        } catch (e: Exception) {
            Log.w(TAG, "pose init failed, falling back to CPU", e)
            try {
                val opts = PoseLandmarker.PoseLandmarkerOptions.builder()
                    .setBaseOptions(baseOptions(POSE_MODEL, gpu = false))
                    .setRunningMode(RunningMode.LIVE_STREAM)
                    .setNumPoses(1)
                    .setResultListener { result: PoseLandmarkerResult, _: MPImage ->
                        onPose?.invoke(toPoseFrame(result), System.currentTimeMillis())
                    }
                    .build()
                PoseLandmarker.createFromOptions(context, opts)
            } catch (e2: Exception) {
                poseFailed.set(true)
                Log.e(TAG, "pose unavailable", e2)
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
                .setErrorListener { e -> Log.e(TAG, "hand error", e) }
                .build()
            HandLandmarker.createFromOptions(context, opts).also {
                Log.i(TAG, "hand landmarker ready")
            }
        } catch (e: Exception) {
            Log.w(TAG, "hand init failed", e)
            handFailed.set(true)
            null
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
                .setErrorListener { e -> Log.e(TAG, "face error", e) }
                .build()
            FaceLandmarker.createFromOptions(context, opts).also {
                Log.i(TAG, "face landmarker ready")
            }
        } catch (e: Exception) {
            Log.w(TAG, "face init failed", e)
            faceFailed.set(true)
            null
        }
    }

    private fun baseOptions(model: String, gpu: Boolean = true): BaseOptions =
        BaseOptions.builder()
            .setModelAssetPath(model)
            .setDelegate(if (gpu) Delegate.GPU else Delegate.CPU)
            .build()

    private fun releasePose() { pose?.close(); pose = null }
    private fun releaseHand() { hand?.close(); hand = null }
    private fun releaseFace() { face?.close(); face = null }

    // ------------------------------------------------------------------ 推理

    /** 提交一帧；只跑当前已装载的检测器。 */
    fun detectAsync(bitmap: Bitmap, rotationDegrees: Int, timestampMs: Long) {
        val mp = BitmapImageBuilder(bitmap).build()
        val opts = ImageProcessingOptions.builder()
            .setRotationDegrees(rotationDegrees)
            .build()
        pose?.detectAsync(mp, opts, timestampMs)
        hand?.detectAsync(mp, opts, timestampMs)
        face?.detectAsync(mp, opts, timestampMs)
    }

    // ------------------------------------------------------------------ 结果转换

    /**
     * 把 MediaPipe landmark 转成 [Joint]。
     * 防御性处理：如果拿到的是像素坐标（>1.5），按图像宽高归一化，
     * 避免不同后端/版本坐标语义不一致导致整个控制链路量纲错乱。
     */
    private fun norm(list: List<NormalizedLandmark>): List<Joint> {
        if (list.isEmpty()) return emptyList()
        val maxAbs = list.maxOf { kotlin.math.abs(it.x()).coerceAtLeast(kotlin.math.abs(it.y())) }
        val k = if (maxAbs > NORMALIZED_MAX) {
            // 像素坐标：用第一个点所在图像尺寸换算不可靠，这里用经验上限归一
            1f / maxAbs * NORMALIZED_MAX
        } else 1f
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

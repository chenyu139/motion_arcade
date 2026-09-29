package com.motionarcade.vision

import android.content.Context
import android.os.SystemClock
import android.util.Log
import androidx.camera.core.ImageProxy
import androidx.lifecycle.LifecycleOwner
import kotlin.math.abs
import kotlin.math.hypot

/**
 * 视觉管线：相机帧 → MediaPipe 关键点 → [GameInput]。
 *
 * 这是整个体感操控的"手感"所在，几个关键设计：
 *
 * 1. **中性位校准**。正脸对着镜头时的读数并不等于 0（各人脸型/坐姿不同），
 *    所以进游戏先采样若干帧记下中性位，之后所有控制量都是"相对中性位"的偏移。
 *    没有这一步，玩家必须把头摆成某个奇怪角度才能保持不动。
 * 2. **尺度归一**。位移量一律除以眼距/肩宽，这样"离镜头远近不同的人"
 *    得到相同的控制量 —— 否则坐得远的人怎么动都没反应。
 * 3. **One Euro 滤波**。静止时压抖动、快速动时保持跟手（见 [OneEuroFilter]）。
 * 4. **边沿量不丢帧**。捏合/张开是"边沿事件"，但检测约 20~30fps、渲染 60fps，
 *    若直接在回调里置位、渲染帧里清零，会有帧读不到。这里用 pending 标志过渡，
 *    保证每个边沿**恰好被消费一次**。
 * 5. **按需启停**。按游戏声明的通道装卸模型，避免三个模型常驻烧算力。
 */
class VisionPipeline(
    private val context: Context,
    private val lifecycleOwner: LifecycleOwner,
) {
    companion object {
        private const val TAG = "VisionPipeline"

        // MediaPipe FaceMesh 常用索引
        private const val IDX_NOSE = 1
        private const val IDX_EYE_L = 33
        private const val IDX_EYE_R = 263
        private const val IDX_LIP_TOP = 13
        private const val IDX_LIP_BOT = 14

        // 校准
        private const val CALIB_FRAMES = 24
        private const val AXIS_RANGE = 0.55f     // 横向偏移多少算"打满"
        private const val PITCH_RANGE = 0.45f    // 纵向偏移多少算"打满"
        private const val JUMP_UP = 0.42f        // 抬头超过它就算跳
        private const val MOUTH_OPEN = 0.30f     // 张嘴阈值（唇距/眼距）

        // 捏合
        private const val PINCH_ON = 0.42f       // 小于它算捏住
        private const val PINCH_OFF = 0.62f      // 大于它算张开（迟滞，避免抖动误触发）
        private const val PINCH_FRAMES = 2       // 连续几帧确认，防止单点跳变
    }

    /** 游戏每帧读它。同一个对象复用，避免 60fps 下产生垃圾。 */
    val input = GameInput()

    private val hub = LandmarkerHub(context)
    private var camera: CameraManager? = null
    private var channels: Set<InputChannel> = emptySet()
    private var lastTs = 0L

    // ---- 中性位校准 ----
    private var calibrating = true
    private var calibCount = 0
    private var neutralX = 0.5f
    private var neutralY = 0.5f
    private var neutralYaw = 0f
    private var neutralPitch = 0f
    private var neutralEyeDist = 0.1f

    // ---- 滤波 ----
    private val axisFilter = OneEuroFilter(minCutoff = 1.1f, beta = 0.006f)
    private val pitchFilter = OneEuroFilter(minCutoff = 1.1f, beta = 0.006f)
    private val yawFilter = OneEuroFilter(minCutoff = 1.3f, beta = 0.008f)
    private val handXFilter = OneEuroFilter(minCutoff = 1.6f, beta = 0.010f)
    private val handYFilter = OneEuroFilter(minCutoff = 1.6f, beta = 0.010f)
    private val openFilter = OneEuroFilter(minCutoff = 1.2f, beta = 0.008f)

    // ---- 原始量（最近一次检测结果）----
    private var rawX = 0.5f
    private var rawY = 0.5f
    private var rawYaw = 0f
    private var rawPitch = 0f
    private var rawMouth = 0f
    private var faceSeen = false
    private var lastFaceMs = 0L

    private var bodySeen = false
    private var rawBodyX = 0f
    private var rawCrouch = 0f
    private var rawArmL = 0f
    private var rawArmR = 0f
    private var rawArmLExt = 0f
    private var rawArmRExt = 0f

    // ---- 手部 ----
    private var rawHandX = 0.5f
    private var rawHandY = 0.5f
    private var rawOpen = 0f
    private var rawFingers = 0
    private var latestHands: List<HandState> = emptyList()
    private var closedFrames = 0
    private var pinchArmed = true
    private var pendingPinch = false
    private var pendingRelease = false
    private var handSeen = false
    private var lastHandMs = 0L

    init {
        hub.onPose = { frame, _ -> frame?.let { onPoseFrame(it) } }
        hub.onHands = { hands, _ -> onHandStates(hands) }
        hub.onFace = { joints, _ -> onFaceJoints(joints) }
    }

    // ------------------------------------------------------------------ 生命周期

    fun start(required: Set<InputChannel>) {
        channels = required
        hub.ensure(required)
        hub.release(required)
        reset()
        if (camera == null) {
            camera = CameraManager(context, lifecycleOwner) { proxy -> onCameraFrame(proxy) }
        }
        camera?.start()
        Log.i(TAG, "start channels=$required")
    }

    fun stop() {
        camera?.stop()
        hub.releaseAll()
    }

    fun shutdown() {
        stop()
        camera?.shutdown()
        camera = null
    }

    fun reset() {
        calibrating = true
        calibCount = 0
        input.reset()
        axisFilter.reset(); pitchFilter.reset(); yawFilter.reset()
        handXFilter.reset(); handYFilter.reset(); openFilter.reset()
        closedFrames = 0
        pinchArmed = true
        pendingPinch = false
        pendingRelease = false
    }

    /** 换游戏时调用：只装卸有变化的通道，避免重复创建模型。 */
    fun retune(required: Set<InputChannel>) {
        if (required == channels) return
        hub.release(channels - required)
        hub.ensure(required)
        channels = required
    }

    // ------------------------------------------------------------------ 相机帧

    private fun onCameraFrame(proxy: ImageProxy) {
        try {
            val ts = SystemClock.uptimeMillis().coerceAtLeast(lastTs + 1)
            lastTs = ts
            val bitmap = proxy.toBitmap()
            hub.detectAsync(bitmap, proxy.imageInfo.rotationDegrees, ts)
        } catch (e: Exception) {
            Log.w(TAG, "frame failed", e)
        } finally {
            proxy.close()
        }
    }

    // ------------------------------------------------------------------ 回调

    private fun onFaceJoints(joints: List<Joint>) {
        if (joints.size <= IDX_LIP_BOT) {
            faceSeen = false
            return
        }
        val nose = joints[IDX_NOSE]
        val eyeL = joints[IDX_EYE_L]
        val eyeR = joints[IDX_EYE_R]
        val lipT = joints[IDX_LIP_TOP]
        val lipB = joints[IDX_LIP_BOT]

        val eyeDist = hypot(eyeL.x - eyeR.x, eyeL.y - eyeR.y).coerceAtLeast(1e-4f)
        val ex = (eyeL.x + eyeR.x) * 0.5f
        val ey = (eyeL.y + eyeR.y) * 0.5f

        // yaw：鼻尖相对双眼中点的水平偏移 ÷ 半眼距（尺度无关）
        rawYaw = ((nose.x - ex) / (eyeDist * 0.5f)).coerceIn(-1f, 1f)
        // pitch：鼻尖相对眼线的纵向偏移（画面 y 向下为正，取负让"抬头"为正）
        rawPitch = (-(nose.y - ey) / eyeDist).coerceIn(-1f, 1f)
        // mouth：唇距 ÷ 眼距
        rawMouth = (hypot(lipT.x - lipB.x, lipT.y - lipB.y) / eyeDist).coerceIn(0f, 1.5f)
        rawX = nose.x
        rawY = nose.y
        neutralEyeDist = eyeDist
        faceSeen = true
        lastFaceMs = SystemClock.uptimeMillis()
    }

    private fun onPoseFrame(frame: PoseFrame) {
        bodySeen = true
        // body_x：肩中点相对画面中心的横向偏移 ÷ 身体尺度
        val s = frame.shoulderMid
        rawBodyX = ((s.x - 0.5f) / (frame.scale * 1.6f)).coerceIn(-1f, 1f)
        rawCrouch = frame.crouch
        rawArmL = frame.armRaised("left")
        rawArmR = frame.armRaised("right")
        rawArmLExt = frame.armExtended("left")
        rawArmRExt = frame.armExtended("right")
    }

    private fun onHandStates(hands: List<HandState>) {
        if (hands.isEmpty()) {
            handSeen = false
            return
        }
        latestHands = hands
        val main = hands.first()
        rawHandX = main.center.x
        rawHandY = main.center.y
        rawOpen = main.openness
        rawFingers = main.fingers
        handSeen = true
        lastHandMs = SystemClock.uptimeMillis()

        // 捏合边沿（带迟滞 + 连续帧确认）
        val d = main.pinchDist
        when {
            d < PINCH_ON -> {
                if (++closedFrames >= PINCH_FRAMES && pinchArmed) {
                    pendingPinch = true
                    pinchArmed = false
                }
            }
            d > PINCH_OFF -> {
                if (!pinchArmed) pendingRelease = true
                closedFrames = 0
                pinchArmed = true
            }
        }
    }

    // ------------------------------------------------------------------ 每帧更新

    /**
     * 渲染线程每帧调用：把检测到的原始量平滑后写进 [input]。
     * dt 用于帧率无关平滑与 One Euro。
     */
    fun update(dt: Float) {
        input.beginFrame()

        val now = SystemClock.uptimeMillis()
        // 超过 800ms 没见到目标 ⇒ 判定丢失，控制量归零（不要停在陈旧值上）
        val faceAlive = faceSeen && (now - lastFaceMs) < 800
        val handAlive = handSeen && (now - lastHandMs) < 800

        // ---- 校准 ----
        if (calibrating) {
            if (faceAlive || handAlive) {
                neutralX += (rawX - neutralX) * 0.25f
                neutralY += (rawY - neutralY) * 0.25f
                neutralYaw += (rawYaw - neutralYaw) * 0.25f
                neutralPitch += (rawPitch - neutralPitch) * 0.25f
                if (++calibCount >= CALIB_FRAMES) calibrating = false
            }
            input.hint = "正在校准，请正对镜头保持不动"
            input.quality = GameInput.QUALITY_POOR
            return
        }

        // ---- 头部 ----
        input.found = faceAlive
        if (faceAlive) {
            val dx = (rawX - neutralX) / AXIS_RANGE
            val dy = -(rawY - neutralY) / PITCH_RANGE          // 抬头为正
            val yawRel = rawYaw - neutralYaw
            val pitchRel = rawPitch - neutralPitch

            // axis：位移与转头取"较大者"，转头不灵敏的人也能靠移动控制
            val axisRaw = if (abs(dx) >= abs(yawRel)) dx else yawRel
            input.axis = axisFilter.filter(axisRaw.coerceIn(-1f, 1f), dt)
            input.yaw = yawFilter.filter(yawRel.coerceIn(-1f, 1f), dt)
            input.headY = pitchFilter.filter(dy.coerceIn(-1f, 1f), dt)
            input.up = input.headY.coerceIn(0f, 1f)
            input.mouth = rawMouth
            input.jump = input.headY > JUMP_UP || rawMouth > MOUTH_OPEN
            input.confidence = 1f
            input.quality = GameInput.QUALITY_GOOD
        } else {
            input.axis = 0f; input.up = 0f; input.headY = 0f
            input.yaw = 0f; input.jump = false; input.mouth = 0f
            input.quality = GameInput.QUALITY_LOST
            input.hint = "没看到你，请正对镜头"
        }

        // ---- 身体 ----
        input.bodyFound = bodySeen
        if (bodySeen) {
            val k = smoothK(3f, dt)
            input.bodyX += (rawBodyX - input.bodyX) * k
            input.crouch += (rawCrouch - input.crouch) * k
            input.armL += (rawArmL - input.armL) * k
            input.armR += (rawArmR - input.armR) * k
            input.armLExt += (rawArmLExt - input.armLExt) * k
            input.armRExt += (rawArmRExt - input.armRExt) * k
        }

        // ---- 手 ----
        input.handFound = handAlive
        input.hands = latestHands
        if (handAlive) {
            // 前置摄像头镜像：玩家抬左手，屏幕光标应在左边
            input.hx = handXFilter.filter(1f - rawHandX, dt).coerceIn(0f, 1f)
            input.hy = handYFilter.filter(rawHandY, dt).coerceIn(0f, 1f)
            input.handOpen = openFilter.filter(rawOpen, dt).coerceIn(0f, 1f)
            input.fingers = rawFingers
            input.grabHold = rawOpen < 0.35f
            input.handL = latestHands.firstOrNull { it.isLeft }
            input.handR = latestHands.firstOrNull { !it.isLeft }
        } else {
            input.hx = 0.5f; input.hy = 0.5f
            input.handOpen = 0f; input.fingers = 0
            input.grabHold = false
        }

        // 边沿量：pending → input，消费一次即清（保证不丢也不重复）
        if (pendingPinch) { input.pinch = true; pendingPinch = false }
        if (pendingRelease) { input.release = true; pendingRelease = false }
    }
}

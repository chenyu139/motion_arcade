package com.motionarcade.vision

import android.content.Context
import android.os.Build
import android.os.PowerManager
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
 * 1. **中性位连续校准（无感）**。正脸读数并不为 0（脸型/坐姿各异），所以控制量
 *    都是相对中性位的偏移。校准不再"站好别动等 0.4 秒"：重新捕获到脸时瞬时
 *    对齐一次，之后以极慢的速率持续跟随——且**只在控制量接近中性时**才跟随，
 *    避免玩家保持某个偏移姿态十几秒后被"吸"回中心。
 * 2. **尺度归一**。位移量一律除以眼距/肩宽，远近手感一致。
 * 3. **One Euro 滤波**。静止压抖、快动跟手。
 * 4. **边沿量不丢帧**。捏合/点头/横扫都是边沿事件，用 pending 标志过渡，
 *    保证恰好被消费一次。
 * 5. **手势词表**。头部只产"瞄准"连续量 + 低频"点头"边沿；"挥/砸/推/倾"等
 *    动词由手部速度通道派生（见 [GameInput] 的手势区），游戏按语义取用。
 * 6. **按需启停 + 自适应降档**。按游戏声明装卸模型；推理吞吐不足或热节流时
 *    自动跳帧（[perfTier]），渲染侧同步降帧率，预览缩略图不受影响。
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
        private const val AXIS_RANGE = 0.55f     // 横向偏移多少算"打满"
        private const val PITCH_RANGE = 0.45f    // 纵向偏移多少算"打满"
        private const val MOUTH_OPEN = 0.30f     // 张嘴阈值（唇距/眼距）

        // 中性位连续跟随：只在控制量接近中性时生效，速率极慢
        private const val NEUTRAL_FOLLOW_K = 0.10f    // /秒
        private const val NEUTRAL_FOLLOW_GATE = 0.35f // |axis| 低于它才允许跟随
        private const val FACE_REGRAB_MS = 1500L      // 丢脸超过它，重捕获时瞬时对齐

        // 点头（快速低头再回正 → 一次边沿）
        private const val NOD_V = 3.0f            // 低头角速度阈值（headY/秒）
        private const val NOD_REARM = -0.10f      // 头回到它之上才允许下一次
        private const val NOD_REFRACT = 0.45f

        // 低头（钻/下筷的持续状态，带迟滞）
        private const val DUCK_ON = -0.42f
        private const val DUCK_OFF = -0.22f

        // 手势
        private const val SWING_V = 2.0f          // 横扫速度阈值（屏幕宽/秒）
        private const val SWING_REARM = 0.8f      // 速度回落到它以下才允许再扫
        private const val SWING_REFRACT = 0.40f
        private const val HANDZ_RANGE = 0.60f     // 手掌 apparent size 比基线大 60% → handZ=1
        private const val STRIKE_V = 1.6f         // 击鼓：拳向下速度阈值

        // 捏合
        private const val PINCH_ON = 0.42f       // 小于它算捏住
        private const val PINCH_OFF = 0.62f      // 大于它算张开（迟滞，避免抖动误触发）
        private const val PINCH_FRAMES = 2       // 连续几帧确认，防止单点跳变

        // 光线：画面中心平均亮度低于它 → 提示开灯（0~255）
        private const val DARK_LUMA = 40f
    }

    /** 游戏每帧读它。同一个对象复用，避免 60fps 下产生垃圾。 */
    val input = GameInput()

    /** 最近一帧缩略图（HUD 预览面板用）；相机未启动时为 null。 */
    val lastFrame: android.graphics.Bitmap? get() = camera?.lastFrame

    /** 当前帧画面是否镜像（前置=是）。后置镜头的手感方向依赖它。 */
    val mirrored: Boolean get() = camera?.mirrored ?: true

    /**
     * 性能档位（渲染侧读取）：0=全速 60fps；1=省档（分析跳 1 帧 + 渲染 30fps）；
     * 2=深度省档（跳 2 帧）。由热状态与推理吞吐自动决定。
     */
    @Volatile
    var perfTier: Int = 0
        private set

    private val hub = LandmarkerHub(context)
    private var camera: CameraManager? = null
    private var channels: Set<InputChannel> = emptySet()
    private var lastTs = 0L

    // ---- 中性位（连续校准）----
    private var needSnap = true
    private var lastFaceSeenAt = 0L
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
    private val tiltFilter = OneEuroFilter(minCutoff = 1.4f, beta = 0.010f)

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
    private var rawHandX = 0.5f                 // 已按镜头镜像
    private var rawHandY = 0.5f
    private var rawHandTilt = 0f                // 已按镜头镜像
    private var rawPalmW = 0.12f
    private var rawOpen = 0f
    private var rawFingers = 0
    private var latestHands: List<HandState> = emptyList()
    private var closedFrames = 0
    private var pinchArmed = true
    private var pendingPinch = false
    private var pendingRelease = false
    private var handSeen = false
    private var lastHandMs = 0L

    // ---- 手势检测状态（渲染线程）----
    private var lastHeadY = 0f
    private var nodArmed = true
    private var nodRefract = 0f
    private var duckOn = false
    private var mouthArmed = true
    private var hadFace = false
    private var hadHand = false
    private var prevFx = 0.5f
    private var prevFy = 0.5f
    private var vxSmooth = 0f
    private var vySmooth = 0f
    private var swingArmed = true
    private var swingRefract = 0f
    private var palmBaseline = 0.12f
    private var prevCyL = 0f
    private var prevCyR = 0f
    private var hadHandL = false
    private var hadHandR = false

    // ---- 光线采样 ----
    private var lumaFrames = 0
    private var frameLuma = 255f

    // ---- 自适应降档（相机线程计数）----
    private var framesSubmitted = 0
    private var resultsGot = 0
    private var tierCheckAt = 0L
    private var tierTarget = 0

    init {
        hub.onPose = { frame, _ -> frame?.let { onPoseFrame(it) }; resultsGot++ }
        hub.onHands = { hands, _ -> onHandStates(hands); resultsGot++ }
        hub.onFace = { joints, _ -> onFaceJoints(joints); resultsGot++ }
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

    /**
     * 重置控制状态。与旧版不同：**不再阻塞式校准**——中性位在下一帧捕获到
     * 目标时瞬时对齐（[needSnap]），随后连续跟随。
     */
    fun reset() {
        needSnap = true
        input.reset()
        axisFilter.reset(); pitchFilter.reset(); yawFilter.reset()
        handXFilter.reset(); handYFilter.reset(); openFilter.reset(); tiltFilter.reset()
        closedFrames = 0
        pinchArmed = true
        pendingPinch = false
        pendingRelease = false
        nodArmed = true; nodRefract = 0f; duckOn = false; mouthArmed = true
        hadFace = false; hadHand = false
        swingArmed = true; swingRefract = 0f
        hadHandL = false; hadHandR = false
        palmBaseline = 0.12f
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
            camera?.updateLastFrame(bitmap)
            sampleLuma(bitmap)

            // 自适应跳帧：预览与光线采样照常，只省推理
            if (perfTier > 0 && framesSubmitted % (perfTier + 1) != 0) return
            framesSubmitted++
            hub.detectAsync(channels, bitmap, proxy.imageInfo.rotationDegrees, ts)
        } catch (e: Exception) {
            Log.w(TAG, "frame failed", e)
        } finally {
            proxy.close()
        }
    }

    /** 每 30 帧采一次画面中心亮度（16×12 网格），用于"光线偏暗"提示。 */
    private fun sampleLuma(bitmap: android.graphics.Bitmap) {
        if (++lumaFrames % 30 != 0) return
        try {
            val w = bitmap.width
            val h = bitmap.height
            var sum = 0L
            var n = 0
            for (gy in 0 until 12) {
                val y = (h * (2 + gy * 8) / 100).coerceIn(0, h - 1)
                for (gx in 0 until 16) {
                    val x = (w * (2 + gx * 6) / 100).coerceIn(0, w - 1)
                    val p = bitmap.getPixel(x, y)
                    sum += (299 * (p shr 16 and 0xFF) + 587 * (p shr 8 and 0xFF) +
                        114 * (p and 0xFF)) / 1000
                    n++
                }
            }
            if (n > 0) frameLuma = sum / n.toFloat()
        } catch (_: Exception) {
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
        val mirror = camera?.mirrored ?: true
        // 镜像在源头做：前置镜头把 x/倾斜翻过来，下游（滤波、速度、游戏）统一按
        // "屏幕方向"理解。y 与镜头无关。
        rawHandX = if (mirror) 1f - main.center.x else main.center.x
        rawHandY = main.center.y
        val w = main.pts["wrist"]
        val m = main.pts["middle_mcp"]
        if (w != null && m != null) {
            val dx = m.x - w.x
            val len = hypot(dx, m.y - w.y)
            if (len > 1e-5f) {
                val t = dx / len
                rawHandTilt = if (mirror) -t else t
            }
        }
        rawPalmW = main.palmWidth
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

        // ---- 中性位连续校准（无感）----
        if (faceAlive) {
            val regab = needSnap ||
                (!hadFace && now - lastFaceSeenAt > FACE_REGRAB_MS)
            if (regab) {
                neutralX = rawX; neutralY = rawY
                neutralYaw = rawYaw; neutralPitch = rawPitch
                needSnap = false
            } else if (abs(rawX - neutralX) / AXIS_RANGE < NEUTRAL_FOLLOW_GATE &&
                abs(rawYaw - neutralYaw) < NEUTRAL_FOLLOW_GATE
            ) {
                // 只在玩家基本处于中性位时缓慢跟随，防止"偏移姿态被吸回中心"
                val k = (NEUTRAL_FOLLOW_K * dt).coerceIn(0f, 1f)
                neutralX += (rawX - neutralX) * k
                neutralY += (rawY - neutralY) * k
                neutralYaw += (rawYaw - neutralYaw) * k
                neutralPitch += (rawPitch - neutralPitch) * k
            }
        }
        if (faceAlive) lastFaceSeenAt = now
        hadFace = faceAlive

        // ---- 头部 ----
        input.found = faceAlive
        if (faceAlive) {
            val dx = (rawX - neutralX) / AXIS_RANGE
            val dy = -(rawY - neutralY) / PITCH_RANGE          // 抬头为正
            val yawRel = rawYaw - neutralYaw
            val pitchRel = rawPitch - neutralPitch

            // axis：位移与转头取"较大者"，转头不灵敏的人也能靠移动控制
            val axisRaw = if (abs(dx) >= abs(yawRel)) dx else yawRel
            val newAxis = axisFilter.filter(axisRaw.coerceIn(-1f, 1f), dt)
            input.axis = newAxis
            input.yaw = yawFilter.filter(yawRel.coerceIn(-1f, 1f), dt)
            val newHeadY = pitchFilter.filter(dy.coerceIn(-1f, 1f), dt)
            input.headY = newHeadY
            input.up = input.headY.coerceIn(0f, 1f)
            input.mouth = rawMouth

            // ---- 点头边沿：低头角速度超阈值，回正后才再触发 ----
            nodRefract = maxOf(0f, nodRefract - dt)
            val pitchV = if (hadFace) (newHeadY - lastHeadY) / dt else 0f
            if (pitchV < -NOD_V && nodArmed && nodRefract <= 0f) {
                pendingNod = true
                nodArmed = false
                nodRefract = NOD_REFRACT
            } else if (newHeadY > NOD_REARM) {
                nodArmed = true
            }
            // ---- 低头状态（迟滞）----
            duckOn = if (duckOn) newHeadY > DUCK_OFF else newHeadY < DUCK_ON
            input.duck = duckOn
            // ---- 张嘴边沿（替代旧的"持续张嘴=jump"）----
            if (rawMouth > MOUTH_OPEN) {
                if (mouthArmed) { pendingNod = true; mouthArmed = false }
            } else if (rawMouth < MOUTH_OPEN * 0.7f) {
                mouthArmed = true
            }

            input.confidence = 1f
            input.quality = GameInput.QUALITY_GOOD
        } else {
            input.axis = 0f; input.up = 0f; input.headY = 0f
            input.yaw = 0f; input.mouth = 0f
            input.duck = false
            input.quality = GameInput.QUALITY_LOST
            input.hint = "没看到你，请正对镜头"
            lastHeadY = 0f
        }
        lastHeadY = if (faceAlive) input.headY else 0f

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
            val fx = handXFilter.filter(rawHandX, dt).coerceIn(0f, 1f)
            val fy = handYFilter.filter(rawHandY, dt).coerceIn(0f, 1f)
            // 速度：滤波位置差分 + EMA；重捕获帧不计（避免瞬移误判成挥/砸）
            if (hadHand) {
                vxSmooth += ((fx - prevFx) / dt - vxSmooth) * (1f - kotlin.math.exp(-16f * dt))
                vySmooth += ((fy - prevFy) / dt - vySmooth) * (1f - kotlin.math.exp(-16f * dt))
            } else {
                vxSmooth = 0f; vySmooth = 0f
            }
            prevFx = fx; prevFy = fy
            input.hx = fx
            input.hy = fy
            input.handVx = vxSmooth
            input.handVy = vySmooth

            // 横扫边沿（变脸/挥拍）：速度冲过阈值，回落 + 冷却后才允许下一次
            swingRefract = maxOf(0f, swingRefract - dt)
            if (abs(vxSmooth) > SWING_V && swingArmed && swingRefract <= 0f) {
                pendingSwing = if (vxSmooth > 0f) 1 else -1
                swingArmed = false
                swingRefract = SWING_REFRACT
            } else if (abs(vxSmooth) < SWING_REARM) {
                swingArmed = true
            }

            // 手掌 pseudo-depth：apparent size 相对个人基线（慢速跟随）
            if (rawPalmW in 0.03f..0.5f) {
                palmBaseline += (rawPalmW - palmBaseline) * (0.35f * dt).coerceIn(0f, 1f)
            }
            val ratio = rawPalmW / palmBaseline.coerceAtLeast(1e-3f)
            input.handZ = ((ratio - 1f) / HANDZ_RANGE).coerceIn(0f, 1f)

            input.handTilt = tiltFilter.filter(rawHandTilt, dt).coerceIn(-1f, 1f)

            input.handOpen = openFilter.filter(rawOpen, dt).coerceIn(0f, 1f)
            input.fingers = rawFingers
            input.grabHold = rawOpen < 0.35f
            input.handL = latestHands.firstOrNull { it.isLeft }
            input.handR = latestHands.firstOrNull { !it.isLeft }

            // ---- 左右拳各自的"下砸"速度（击鼓）：瞬时值不平滑，要的就是爆发 ----
            input.handDipL = trackDip(input.handL, hadHandL, prevCyL, dt)
                .also { prevCyL = it.second; hadHandL = it.third }.first
            input.handDipR = trackDip(input.handR, hadHandR, prevCyR, dt)
                .also { prevCyR = it.second; hadHandR = it.third }.first
        } else {
            input.hx = 0.5f; input.hy = 0.5f
            input.handOpen = 0f; input.fingers = 0
            input.grabHold = false
            input.handVx = 0f; input.handVy = 0f
            input.handDipL = 0f; input.handDipR = 0f
            input.handZ = 0f; input.handTilt = 0f
            input.swing = 0
            input.handL = null; input.handR = null
            hadHand = false; hadHandL = false; hadHandR = false
        }
        hadHand = handAlive

        // ---- 光线提示 ----
        if (faceAlive && frameLuma < DARK_LUMA) {
            input.quality = GameInput.QUALITY_POOR
            input.hint = "光线偏暗 · 请开灯或别背对光源"
        }

        // 边沿量：pending → input，消费一次即清（保证不丢也不重复）
        if (pendingPinch) { input.pinch = true; pendingPinch = false }
        if (pendingRelease) { input.release = true; pendingRelease = false }
        if (pendingNod) { input.nod = true; input.jump = true; pendingNod = false }
        if (pendingSwing != 0) { input.swing = pendingSwing; pendingSwing = 0 }

        // ---- 自适应降档（每 2 秒评估一次）----
        evaluateTier(now)
    }

    /**
     * 单只手的向下速度（击鼓用瞬时值，不做平滑——要的就是爆发）。
     * 返回 (向下速度/秒, 最新 y, 是否有效跟踪)；刚重新出现的那帧不计速度
     * （同横扫的防瞬移逻辑）。
     */
    private fun trackDip(
        hand: HandState?,
        had: Boolean,
        prevY: Float,
        dt: Float,
    ): Triple<Float, Float, Boolean> {
        if (hand == null) return Triple(0f, prevY, false)
        val cy = hand.center.y
        if (!had) return Triple(0f, cy, true)
        val v = ((cy - prevY) / dt).coerceIn(-6f, 6f)
        return Triple(v, cy, true)
    }

    /** 吞吐 + 热状态 → 性能档位。 */
    private fun evaluateTier(now: Long) {
        if (now - tierCheckAt < 2000L) return
        tierCheckAt = now
        var target = 0
        // 1) 热节流（最硬的约束）
        try {
            if (Build.VERSION.SDK_INT >= 29) {
                val st = powerManager.currentThermalStatus
                if (st >= PowerManager.THERMAL_STATUS_SEVERE) target = 2
                else if (st >= PowerManager.THERMAL_STATUS_MODERATE) target = 1
            }
        } catch (_: Exception) {
        }
        // 2) 推理吞吐：三个检测器本应每帧各回一次结果，回得少 = 跟不上
        val expected = framesSubmitted * 3
        val ratio = if (expected > 0) resultsGot.toFloat() / expected else 1f
        if (framesSubmitted > 10) {
            if (ratio < 0.35f) target = maxOf(target, 2)
            else if (ratio < 0.6f) target = maxOf(target, 1)
        }
        framesSubmitted = 0
        resultsGot = 0
        // 档位阶梯移动，避免抖动
        perfTier = when {
            perfTier < target -> perfTier + 1
            perfTier > target -> perfTier - 1
            else -> perfTier
        }
        if (target > 0) Log.i(TAG, "perfTier=$perfTier (target=$target, ratio=$ratio)")
    }

    private val powerManager =
        context.getSystemService(Context.POWER_SERVICE) as PowerManager

    // ---- 边沿 pending ----
    private var pendingNod = false
    private var pendingSwing = 0
}

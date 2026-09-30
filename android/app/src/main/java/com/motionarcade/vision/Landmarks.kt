package com.motionarcade.vision

import kotlin.math.hypot

/**
 * 关键点基元。
 *
 * 坐标一律是**归一化**的：x、y ∈ [0,1]（相对画面宽高），与 Python 端
 * `core.vision.types.Joint` 的语义完全一致，这样两边的阈值/公式可以互相抄。
 */
data class Joint(
    val x: Float,
    val y: Float,
    val conf: Float = 1f,
) {
    val ok: Boolean get() = conf > 0f
}

/** MediaPipe Hand Landmarker 的 21 点命名（索引即模型输出顺序）。 */
val HAND_JOINTS: List<String> = listOf(
    "wrist",
    "thumb_cmc", "thumb_mcp", "thumb_ip", "thumb_tip",
    "index_mcp", "index_pip", "index_dip", "index_tip",
    "middle_mcp", "middle_pip", "middle_dip", "middle_tip",
    "ring_mcp", "ring_pip", "ring_dip", "ring_tip",
    "little_mcp", "little_pip", "little_dip", "little_tip",
)

/** 五指：(指尖名, 近端关节名)，用来算"这根手指伸直了吗"。 */
val FINGERS: List<Pair<String, String>> = listOf(
    "index_tip" to "index_pip",
    "middle_tip" to "middle_pip",
    "ring_tip" to "ring_pip",
    "little_tip" to "little_pip",
)

/**
 * 单只手的状态。
 *
 * 与 Python 端 `HandState` 对齐：
 *  - [palmWidth]：手掌尺度参考（食指掌指关节 → 小指掌指关节的距离），
 *    所有"多远算张开"的判断都除以它，保证远近不同手感一致；
 *  - [openness]：张开度 0~1（伸直手指数 / 5）；
 *  - [fingers]：伸直手指数；
 *  - [pinchStrength]：拇指尖与食指尖距离（除以掌宽），用于捏合判定。
 */
class HandState(
    val pts: Map<String, Joint>,
    val isLeft: Boolean,
    val conf: Float = 1f,
) {
    /** 手掌宽度（尺度参考）。 */
    val palmWidth: Float
        get() {
            val a = pts["index_mcp"] ?: return 0.12f
            val b = pts["little_mcp"] ?: return 0.12f
            val d = hypot(a.x - b.x, a.y - b.y)
            return if (d > 1e-4f) d else 0.12f
        }

    /** 掌心（腕与中指掌指关节的中点）——比单用 wrist 更贴合"手的中心"。 */
    val center: Joint
        get() {
            val w = pts["wrist"]
            val m = pts["middle_mcp"]
            return when {
                w != null && m != null -> Joint((w.x + m.x) * 0.5f, (w.y + m.y) * 0.5f, conf)
                w != null -> w
                m != null -> m
                else -> Joint(0.5f, 0.5f, 0f)
            }
        }

    /** 单指是否伸直：指尖到腕的距离 / 掌宽 超过阈值。 */
    private fun fingerExtended(tipName: String, pipName: String): Boolean {
        val tip = pts[tipName] ?: return false
        val pip = pts[pipName] ?: return false
        val w = pts["wrist"] ?: return false
        val dTip = hypot(tip.x - w.x, tip.y - w.y)
        val dPip = hypot(pip.x - w.x, pip.y - w.y)
        // 指尖明显比中节离腕更远 ⇒ 伸直
        return dTip > dPip * 1.12f
    }

    val extendedCount: Int get() = FINGERS.count { (tip, pip) -> fingerExtended(tip, pip) }

    val thumbExtended: Boolean
        get() {
            val t = pts["thumb_tip"] ?: return false
            val i = pts["index_mcp"] ?: return false
            return hypot(t.x - i.x, t.y - i.y) / palmWidth > 1.05f
        }

    /** 张开度 0~1：握拳≈0，五指全伸≈1。 */
    val openness: Float
        get() {
            val n = extendedCount + (if (thumbExtended) 1 else 0)
            return (n / 5f).coerceIn(0f, 1f)
        }

    val fingers: Int get() = extendedCount

    /** 捏合强度：0=捏住，越大=张开（除以掌宽做尺度归一）。 */
    val pinchDist: Float
        get() {
            val t = pts["thumb_tip"] ?: return 1f
            val i = pts["index_tip"] ?: return 1f
            return hypot(t.x - i.x, t.y - i.y) / palmWidth
        }

    /** 食指指向（腕→食指尖的单位向量），用于"指哪打哪"。 */
    val pointDirection: Pair<Float, Float>
        get() {
            val t = pts["index_tip"] ?: return 0f to 0f
            val w = pts["wrist"] ?: return 0f to 0f
            val dx = t.x - w.x
            val dy = t.y - w.y
            val d = hypot(dx, dy)
            return if (d < 1e-6f) 0f to 0f else (dx / d) to (dy / d)
        }
}

/**
 * MediaPipe Pose Landmarker 的 33 点中，本项目需要的 17 点（COCO 拓扑）。
 * key = COCO 名称，value = MediaPipe 索引。
 */
val MP_POSE_TO_COCO: Map<String, Int> = mapOf(
    "nose" to 0,
    "left_eye" to 2,
    "right_eye" to 5,
    "left_ear" to 7,
    "right_ear" to 8,
    "left_shoulder" to 11,
    "right_shoulder" to 12,
    "left_elbow" to 13,
    "right_elbow" to 14,
    "left_wrist" to 15,
    "right_wrist" to 16,
    "left_hip" to 23,
    "right_hip" to 24,
    "left_knee" to 25,
    "right_knee" to 26,
    "left_ankle" to 27,
    "right_ankle" to 28,
)

/**
 * 身体姿态帧（COCO-17）。等价于 Python 端 `PoseFrame`。
 *
 * 所有派生量都**除以身体尺度** [scale]，这样高矮胖瘦、离镜头远近不同的人
 * 得到的控制量是一致的——这是"手感一致"的关键，不能省。
 */
class PoseFrame(private val pts: Map<String, Joint>) {

    fun get(name: String): Joint = pts[name] ?: Joint(0f, 0f, 0f)

    private fun mid(a: Joint, b: Joint) = Joint((a.x + b.x) * 0.5f, (a.y + b.y) * 0.5f, minOf(a.conf, b.conf))

    val shoulderMid: Joint
        get() {
            val a = get("left_shoulder")
            val b = get("right_shoulder")
            return if (a.ok && b.ok) mid(a, b) else (if (a.ok) a else b)
        }

    val hipMid: Joint
        get() {
            val a = get("left_hip")
            val b = get("right_hip")
            return if (a.ok && b.ok) mid(a, b) else (if (a.ok) a else b)
        }

    /**
     * 身体尺度参考：肩宽优先，其次肩→髋距离。
     * 所有"位移多少算大动作"的判断都要除以它。
     */
    val scale: Float
        get() {
            val ls = get("left_shoulder")
            val rs = get("right_shoulder")
            if (ls.ok && rs.ok) {
                val d = hypot(ls.x - rs.x, ls.y - rs.y)
                if (d > 0.02f) return d
            }
            val s = shoulderMid
            val h = hipMid
            if (s.ok && h.ok) {
                val d = hypot(s.x - h.x, s.y - h.y)
                if (d > 0.02f) return d
            }
            return 0.22f
        }

    /** 头部左右转 -1~1：鼻尖相对双眼中点的水平偏移（除以半眼距）。 */
    val headYaw: Float
        get() {
            val n = get("nose")
            val le = get("left_eye")
            val re = get("right_eye")
            if (!(n.ok && le.ok && re.ok)) return 0f
            val ex = (le.x + re.x) * 0.5f
            val half = hypot(le.x - re.x, le.y - re.y) * 0.5f
            if (half < 1e-5f) return 0f
            return ((n.x - ex) / half).coerceIn(-1f, 1f)
        }

    /** 下蹲 0~1：髋到膝/踝的纵向距离相对站立时收缩了多少。 */
    val crouch: Float
        get() {
            val h = hipMid
            val k = get("left_knee")
            val k2 = get("right_knee")
            val knee = if (k.ok && k2.ok) mid(k, k2) else (if (k.ok) k else k2)
            if (!(h.ok && knee.ok)) return 0f
            // 站直时髋膝距离 ≈ 0.25×身高；这里用肩髋距当作身高代理做归一
            val leg = hypot(h.x - knee.x, h.y - knee.y)
            val ref = scale * 1.05f
            val ratio = (leg / ref).coerceIn(0f, 1.2f)
            return (1f - ratio / 0.95f).coerceIn(0f, 1f)
        }

    /** 手臂举起 0~1：腕高出肩的相对量（除以身体尺度）。 */
    fun armRaised(side: String): Float {
        val s = get("${side}_shoulder")
        val w = get("${side}_wrist")
        if (!(s.ok && w.ok)) return 0f
        return ((s.y - w.y) / scale).coerceIn(0f, 1f)
    }

    /** 手臂伸展 0~1：腕到肩距离 / (上臂+前臂) 长度，越接近 1 越直。 */
    fun armExtended(side: String): Float {
        val s = get("${side}_shoulder")
        val e = get("${side}_elbow")
        val w = get("${side}_wrist")
        if (!(s.ok && e.ok && w.ok)) return 0f
        val upper = hypot(s.x - e.x, s.y - e.y)
        val fore = hypot(e.x - w.x, e.y - w.y)
        val total = upper + fore
        if (total < 1e-5f) return 0f
        return (hypot(s.x - w.x, s.y - w.y) / total).coerceIn(0f, 1f)
    }
}

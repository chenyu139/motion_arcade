package com.motionarcade.vision

/**
 * 所有游戏统一接收的输入结构 —— **与 Python 端 `core.inputs.GameInput` 一一对应**。
 *
 * 之所以复用同一个对象而不是每帧 new 一个 data class：
 * 这是 60fps 的实时链路，每帧产生垃圾会直接换来 GC 卡顿（体感游戏里表现为
 * 动作"顿一下"）。所以这里是可变对象 + [beginFrame] 复位边沿量。
 *
 * 坐标系约定
 * ----------
 * · 归一化坐标一律 ∈ [0,1]，原点在左上角；
 * · [axis]/[yaw]/[headY] 是有符号量，0 = 中性位（已减去校准中性值）；
 * · [hx]/[hy] 是**主手**掌心在画面中的归一化位置，游戏里再映射到屏幕光标。
 */
class GameInput {

    // ── 头部 ────────────────────────────────────────────────────────────
    /** 是否检测到头部/人脸。 */
    var found: Boolean = false

    /** 头部水平控制量 -1 ~ +1（以校准中性位为原点）。 */
    var axis: Float = 0f

    /** 抬头幅度 0~1。 */
    var up: Float = 0f

    /** 头部纵向连续量 -1(低头) ~ +1(抬头)。 */
    var headY: Float = 0f

    /** 头部左右转 -1 ~ +1（可以只转头不移动）。 */
    var yaw: Float = 0f

    /**
     * 动作键（边沿）：快速点头 或 张嘴那刻为 true，保持不会连发。
     *
     * 语义约定（交互重构后）：**头部负责瞄准/转向，"点头"只做低频的发力/确认**——
     * 持续仰头不再是任何游戏的主触发（那是疲劳最快、精度最差的头部动作）。
     */
    var jump: Boolean = false

    /** 快速点头边沿（同 [jump] 里的点头分量，想区分"点头 vs 张嘴"的游戏用这个）。 */
    var nod: Boolean = false

    /** 持续低头状态（带迟滞）：钻行/下筷这类"低着头做事"的连续动作。 */
    var duck: Boolean = false

    /** 张嘴程度 0~1。 */
    var mouth: Float = 0f

    // ── 识别质量（供 UI 提示与降级；游戏逻辑一般不必关心）──────────────
    var confidence: Float = 1f
    var quality: String = QUALITY_GOOD          // good / far / poor / angle / lost
    var hint: String = ""

    // ── 手部 ────────────────────────────────────────────────────────────
    var handFound: Boolean = false
    var hx: Float = 0.5f
    var hy: Float = 0.5f
    var handOpen: Float = 0f                    // 0=握拳 1=张开
    var fingers: Int = 0
    var hands: List<HandState> = emptyList()
    var handL: HandState? = null
    var handR: HandState? = null
    var pinch: Boolean = false                  // 捏合边沿（仅触发帧为 true）
    var release: Boolean = false                // 张开边沿（握拳→张开那一刻）
    var grabHold: Boolean = false               // "保持收拢"连续状态

    // ── 手势词表（文化动词的通用检测，游戏按语义取用）───────────────────
    /** 横扫边沿：0=无 / +1=手掌向右快速扫 / -1=向左（变脸、挥拍这类"挥"的动词）。 */
    var swing: Int = 0

    /** 手掌横向速度（镜像后屏幕坐标/秒），供游戏自定义速度判定。 */
    var handVx: Float = 0f

    /** 手掌纵向速度（/秒，向下为正——击鼓的"下砸"用它）。 */
    var handVy: Float = 0f

    /** 左手向下速度（/秒，两只手分开给——击鼓要分清左右拳）。 */
    var handDipL: Float = 0f

    /** 右手向下速度（/秒）。 */
    var handDipR: Float = 0f

    /** 手掌 pseudo-depth 0~1：越 1 手越靠近镜头（推/递这类"向前"的动词近似）。 */
    var handZ: Float = 0f

    /** 手腕倾斜 -1 ~ +1（+ = 向右倒）：茶艺注水这类"倾"的动词。 */
    var handTilt: Float = 0f

    // ── 全身（需要身体入镜）─────────────────────────────────────────────
    var bodyFound: Boolean = false
    var bodyX: Float = 0f                       // 身体横向偏移 -1 ~ +1
    var crouch: Float = 0f                      // 下蹲 0(站直) ~ 1(蹲到底)
    var armL: Float = 0f                        // 左臂举起 0~1
    var armR: Float = 0f
    var armLExt: Float = 0f                     // 左臂伸展 0(弯曲) ~ 1(伸直)
    var armRExt: Float = 0f

    companion object {
        const val QUALITY_GOOD = "good"
        const val QUALITY_FAR = "far"
        const val QUALITY_POOR = "poor"
        const val QUALITY_ANGLE = "angle"
        const val QUALITY_LOST = "lost"
    }

    /**
     * 每帧开头调用：只清**边沿量**（pinch/release/nod/swing/jump），连续量保留，
     * 这样即使这一帧检测器没出结果，控制量也不会突然归零把角色甩回去。
     */
    fun beginFrame() {
        pinch = false
        release = false
        nod = false
        swing = 0
        jump = false
    }

    /** 彻底复位（换游戏/重新校准时用）。 */
    fun reset() {
        found = false
        axis = 0f
        up = 0f
        headY = 0f
        yaw = 0f
        jump = false
        nod = false
        duck = false
        mouth = 0f
        confidence = 1f
        quality = QUALITY_GOOD
        hint = ""
        handFound = false
        hx = 0.5f
        hy = 0.5f
        handOpen = 0f
        fingers = 0
        hands = emptyList()
        handL = null
        handR = null
        pinch = false
        release = false
        grabHold = false
        bodyFound = false
        bodyX = 0f
        crouch = 0f
        armL = 0f
        armR = 0f
        armLExt = 0f
        armRExt = 0f
        swing = 0
        handVx = 0f
        handVy = 0f
        handDipL = 0f
        handDipR = 0f
        handZ = 0f
        handTilt = 0f
    }
}

/** 游戏声明自己需要哪些输入通道，用来**按需启停检测器**省算力。 */
enum class InputChannel { HEAD, HAND, BODY }
